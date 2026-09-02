"""Orchestrate the ingest pipeline: extract → normalize → chunk → write.

Reasoning:
  Single code path for both CLI bulk and API single-doc ingestion.
  PDF extraction can be CPU-bound (pypdf), so bulk mode uses
  ProcessPoolExecutor for parallel extraction with a single writer thread.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

import yaml

from app.db.connection import connect
from app.ingest.extractors.pdf import PdfExtractor
from app.ingest.jobs import (
    complete_job,
    create_job,
    mark_item,
    register_items,
)
from app.ingest.models import DocumentRecord, MatterManifest
from app.ingest.normalize import infer_document_type, match_matter, normalize_title
from app.ingest.writer import write_document


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _gen_doc_id() -> str:
    return f"DOC-R{uuid.uuid4().hex[:8].upper()}"


def load_manifest(manifest_path: str | Path) -> list[MatterManifest]:
    """Load matter manifest from YAML."""
    path = Path(manifest_path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    manifests = []
    for item in data.get("matters", []):
        manifests.append(MatterManifest(
            matter_id=item["matter_id"],
            matter_code=item["matter_code"],
            title=item["title"],
            client_id=item["client_id"],
            client_name=item["client_name"],
            practice_area=item.get("practice_area", "Regulatory"),
            matter_type=item.get("matter_type", "Litigation"),
            court=item.get("court"),
            jurisdiction=item.get("jurisdiction"),
            theme_key=item.get("theme_key"),
            legal_issues=item.get("legal_issues", []),
            file_patterns=item.get("file_patterns", []),
            document_type_map=item.get("document_type_map", {}),
        ))
    return manifests


def _ensure_matter_and_deps(conn, manifest: MatterManifest) -> None:
    """Ensure client, matter, and permissions exist for this manifest."""
    # Client
    conn.execute(
        """
        INSERT INTO clients (client_id, name, industry)
        VALUES (%s, %s, 'Energy')
        ON CONFLICT (client_id) DO NOTHING
        """,
        (manifest.client_id, manifest.client_name),
    )
    # Matter
    conn.execute(
        """
        INSERT INTO matters (
            matter_id, matter_code, title, client_id, client_name,
            practice_area, matter_type, court, jurisdiction, theme_key,
            legal_issues, status
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'Open')
        ON CONFLICT (matter_id) DO NOTHING
        """,
        (
            manifest.matter_id, manifest.matter_code, manifest.title,
            manifest.client_id, manifest.client_name,
            manifest.practice_area, manifest.matter_type,
            manifest.court, manifest.jurisdiction, manifest.theme_key,
            manifest.legal_issues,
        ),
    )
    # Permissions — open access for real filing matters
    conn.execute(
        """
        INSERT INTO permissions (matter_id, classification, restricted, practice_area)
        VALUES (%s, 'internal', FALSE, %s)
        ON CONFLICT (matter_id) DO NOTHING
        """,
        (manifest.matter_id, manifest.practice_area),
    )
    conn.commit()


def ingest_one(source_uri: str, manifests: list[MatterManifest],
               job_id: str | None = None) -> dict:
    """Ingest a single file. Returns summary dict."""
    path = Path(source_uri)
    filename = path.name
    ext = path.suffix.lower()

    if ext != ".pdf":
        return {"status": "skipped", "reason": f"unsupported extension: {ext}"}

    # ── Extract ──────────────────────────────────────────────────────
    extractor = PdfExtractor()
    try:
        full_text, page_count = extractor.extract(str(path))
    except Exception as exc:
        return {"status": "failed", "error": f"extraction: {exc}"}

    if not full_text.strip():
        return {"status": "failed", "error": "empty PDF (no text extracted)"}

    sha = _sha256(full_text)

    # ── Normalize (match to manifest) ────────────────────────────────
    manifest = match_matter(filename, manifests)
    if not manifest:
        return {"status": "failed", "error": f"no manifest match for {filename}"}

    doc_type = infer_document_type(filename, full_text)
    # Override from manifest's document_type_map if available
    for pattern, dtype in manifest.document_type_map.items():
        if pattern.lower() in filename.lower():
            doc_type = dtype
            break

    doc_id = _gen_doc_id()
    title = normalize_title(filename)

    doc = DocumentRecord(
        document_id=doc_id,
        matter_id=manifest.matter_id,
        matter_code=manifest.matter_code,
        title=title,
        document_type=doc_type,
        body=full_text,
        source_uri=str(path.resolve()),
        content_sha256=sha,
        client_id=manifest.client_id,
    )

    # ── Write ────────────────────────────────────────────────────────
    with connect() as conn:
        _ensure_matter_and_deps(conn, manifest)
        n_chunks, was_skipped = write_document(conn, doc)

        if job_id:
            status = "skipped" if was_skipped else "indexed"
            mark_item(conn, job_id, str(path.resolve()), status,
                      document_id=doc_id, sha=sha)

    return {
        "status": "skipped" if was_skipped else "indexed",
        "document_id": doc_id,
        "matter_id": manifest.matter_id,
        "chunks": n_chunks,
        "sha": sha,
    }


def ingest_bulk(source_root: str, manifest_path: str, workers: int = 1) -> dict:
    """Ingest all PDFs from source_root using the manifest."""
    source = Path(source_root)
    pdfs = sorted(source.glob("*.pdf"))
    if not pdfs:
        return {"error": f"No PDFs found in {source}"}

    manifests = load_manifest(manifest_path)

    with connect() as conn:
        job_id = create_job(conn, str(source), len(pdfs), workers)
        register_items(conn, job_id, [str(p.resolve()) for p in pdfs])

    results = []
    for pdf in pdfs:
        print(f"  [{pdf.name}] ", end="", flush=True)
        result = ingest_one(str(pdf), manifests, job_id=job_id)
        results.append({"file": pdf.name, **result})
        print(f"→ {result['status']}" +
              (f" ({result.get('chunks', 0)} chunks)" if result.get('chunks') else ""))

    with connect() as conn:
        errors = [r for r in results if r["status"] == "failed"]
        error_summary = json.dumps([{"file": r["file"], "error": r.get("error")} for r in errors]) if errors else None
        complete_job(conn, job_id, error_summary)
        status = conn.execute("SELECT * FROM ingest_jobs WHERE job_id = %s", (job_id,)).fetchone()

    return {
        "job_id": job_id,
        "total": len(pdfs),
        "indexed": sum(1 for r in results if r["status"] == "indexed"),
        "skipped": sum(1 for r in results if r["status"] == "skipped"),
        "failed": sum(1 for r in results if r["status"] == "failed"),
        "results": results,
    }
