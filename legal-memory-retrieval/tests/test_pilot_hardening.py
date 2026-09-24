"""Regression tests for production plan 08 (pilot readiness), steps A1–A3.

A1 generated-file download needs the owner · A2 upload ACL, ownership, limits,
content checks, quarantine · A3 no HTML injection in the Word pane, legacy UI not
served, security headers. Runs against the seeded demo database.
"""
from __future__ import annotations

import io
import uuid
from pathlib import Path

import pytest

from app.config import settings
from conftest import Wall, as_member

ROOT = Path(__file__).resolve().parents[1]
DOCX_MAGIC = b"PK\x03\x04" + b"\x00" * 64
PDF_MAGIC = b"%PDF-1.7\n%fake\n"


# ── A1: generated files ───────────────────────────────────────────────────────


@pytest.fixture
def artifact(seeded):
    from app.chat.tools.generation_tools import generate_docx

    return generate_docx("../../../tmp/evil title", [{"heading": "H", "content": "body"}], owner_member_id="MEM-00001")


def test_generated_file_only_for_owner(client, artifact):
    url = f"/api/documents/{artifact['document_id']}/download"
    assert client.get(url, headers=as_member("MEM-00001")).status_code == 200
    assert client.get(url, headers=as_member("MEM-00002")).status_code == 404
    assert client.get(url).status_code == 404  # anonymous dev caller


def test_generated_filename_cannot_escape(artifact):
    from app.chat.tools.generation_tools import generated_dir
    from app.db.connection import connect

    assert "/" not in artifact["filename"] and not artifact["filename"].startswith(".")
    with connect() as conn:
        row = conn.execute(
            "SELECT storage_path FROM generated_artifacts WHERE artifact_id = %s", (artifact["document_id"],)
        ).fetchone()
    assert Path(row["storage_path"]).resolve().is_relative_to(generated_dir())


def test_generated_id_prefix_no_longer_matches(client, artifact):
    # The old code served any file whose name *started with* the requested id.
    prefix = artifact["document_id"][:8]
    assert client.get(f"/api/documents/{prefix}/download", headers=as_member("MEM-00001")).status_code == 404


def test_object_store_confined_to_root(tmp_path):
    from app.storage.object_store import LocalObjectStore

    store = LocalObjectStore(tmp_path / "store")
    for uri in ("file:///etc/passwd", "../../etc/passwd", f"file://{ROOT}/.env"):
        with pytest.raises(FileNotFoundError):
            store.get(uri)
        assert store.exists(uri) is False


def test_original_download_respects_wall(client, walls: list[Wall]):
    w = walls[0]
    assert client.get(f"/api/documents/{w.document_id}/download", headers=as_member(w.outsider)).status_code == 404


# ── A2: uploads ───────────────────────────────────────────────────────────────


@pytest.fixture(scope="module", autouse=True)
def _remove_test_uploads():
    """Delete the batches (rows + stored files) this module creates; the dev DB is shared."""
    from app.db.connection import connect
    from app.storage.object_store import get_object_store

    with connect() as conn:
        started = conn.execute("SELECT now() AS t").fetchone()["t"]
    yield
    store = get_object_store()
    with connect() as conn, conn.transaction():
        batches = conn.execute(
            "SELECT batch_id, ingest_job_id FROM upload_batches WHERE created_at >= %s", (started,)
        ).fetchall()
        ids = [b["batch_id"] for b in batches]
        for f in conn.execute("SELECT storage_uri FROM upload_batch_files WHERE batch_id = ANY(%s)", (ids,)).fetchall():
            try:
                store.delete(f["storage_uri"])
            except FileNotFoundError:
                pass
        conn.execute("DELETE FROM upload_batch_files WHERE batch_id = ANY(%s)", (ids,))
        conn.execute("DELETE FROM upload_batches WHERE batch_id = ANY(%s)", (ids,))
        jobs = [b["ingest_job_id"] for b in batches if b["ingest_job_id"]]
        conn.execute("DELETE FROM ingest_items WHERE job_id = ANY(%s)", (jobs,))
        conn.execute("DELETE FROM ingest_jobs WHERE job_id = ANY(%s)", (jobs,))
        conn.execute("DELETE FROM generated_artifacts WHERE created_at >= %s", (started,))


def _upload(client, matter_id, member, files):
    return client.post(
        "/api/uploads/batches",
        data={"matter_id": matter_id},
        files=[("files", (name, io.BytesIO(data), "application/octet-stream")) for name, data in files],
        headers=as_member(member),
    )


def test_upload_into_restricted_matter_denied(client, walls: list[Wall]):
    w = walls[0]
    resp = _upload(client, w.matter_id, w.outsider, [("memo.txt", b"hello")])
    assert resp.status_code == 404


@pytest.mark.parametrize(
    "name,data,reason",
    [
        ("contract.pdf", DOCX_MAGIC, "does not match"),  # renamed zip
        ("payload.exe", b"MZ\x90\x00", "not accepted"),
        ("macro.docm", DOCX_MAGIC, "not accepted"),
        ("notes.txt", b"text\x00with nul", "binary"),
        ("empty.pdf", b"", "empty"),
    ],
)
def test_upload_content_policy(client, walls: list[Wall], name, data, reason):
    w = walls[0]
    resp = _upload(client, w.matter_id, w.insider, [(name, data)])
    assert resp.status_code == 400, resp.text
    assert reason in resp.json()["detail"]


def test_upload_path_traversal_rejected(client, walls: list[Wall]):
    w = walls[0]
    resp = client.post(
        "/api/uploads/batches",
        data={"matter_id": w.matter_id, "relative_paths": ["../../escape.txt"]},
        files=[("files", ("escape.txt", io.BytesIO(b"x"), "text/plain"))],
        headers=as_member(w.insider),
    )
    assert resp.status_code == 400


def test_upload_file_size_cap(client, walls: list[Wall], monkeypatch):
    w = walls[0]
    monkeypatch.setattr(settings, "max_upload_file_mb", 1)
    resp = _upload(client, w.matter_id, w.insider, [("big.txt", b"a" * (1024 * 1024 + 10))])
    assert resp.status_code == 413


def test_request_body_cap_before_parsing(client, walls: list[Wall], monkeypatch):
    w = walls[0]
    monkeypatch.setattr(settings, "max_upload_batch_mb", 1)
    resp = _upload(client, w.matter_id, w.insider, [("a.txt", b"a" * (3 * 1024 * 1024))])
    assert resp.status_code == 413
    assert "Request body larger" in resp.json()["detail"]


def test_non_upload_requests_capped(client, seeded):
    resp = client.post("/api/answers", content=b"x" * (11 * 1024 * 1024), headers={"content-type": "application/json"})
    assert resp.status_code == 413


def test_batch_owner_only(client, walls: list[Wall]):
    w = walls[0]
    created = _upload(client, w.matter_id, w.insider, [("owner-check.txt", b"owner only " * 3)])
    assert created.status_code == 200, created.text
    bid = created.json()["batch_id"]
    other = next(m for m in ("MEM-00012", "MEM-00014", "MEM-00015", "MEM-00016") if m != w.insider)
    assert client.get(f"/api/uploads/batches/{bid}", headers=as_member(w.insider)).status_code == 200
    assert client.get(f"/api/uploads/batches/{bid}", headers=as_member(other)).status_code == 404
    assert client.post(f"/api/uploads/batches/{bid}/run", headers=as_member(other)).status_code == 404


def test_infected_file_is_quarantined(client, walls: list[Wall], monkeypatch):
    import app.ingest.upload_batch as ub

    w = walls[0]
    created = _upload(client, w.matter_id, w.insider, [("eicar.txt", b"pretend-infected " + PDF_MAGIC)])
    assert created.status_code == 200
    monkeypatch.setattr(ub, "scan_for_malware", lambda data: "Eicar-Test-Signature")
    result = client.post(f"/api/uploads/batches/{created.json()['batch_id']}/run", headers=as_member(w.insider)).json()
    assert result["indexed"] == 0 and result["failed"] == 1
    statuses = {f["status"] for f in result["batch"]["files"]}
    assert statuses == {"quarantined"}


def test_scanner_outage_fails_closed(walls: list[Wall], monkeypatch):
    from app.ingest import upload_policy

    monkeypatch.setattr(settings, "malware_scanner", "clamd")
    monkeypatch.setattr(settings, "clamd_port", 1)  # nothing listens here
    with pytest.raises(OSError):
        upload_policy.scan_for_malware(b"data")


def test_production_requires_malware_scanner():
    from app.config import Settings

    assert any("MALWARE_SCANNER" in p for p in Settings(malware_scanner="off").production_problems())


# ── A3: HTML injection, legacy UI, headers ────────────────────────────────────


def test_word_taskpane_has_no_html_injection():
    html = (ROOT / "static" / "word-taskpane.html").read_text()
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "onclick="):
        assert sink not in html, sink


def test_legacy_ui_not_in_served_tree(client):
    assert not (ROOT / "static" / "_legacy").exists()
    resp = client.get("/ui/_legacy/app.js")
    assert "innerHTML" not in resp.text


@pytest.mark.parametrize("path", ["/ui/", "/ui/word-taskpane.html", "/api/system/health"])
def test_security_headers(client, path):
    resp = client.get(path)
    assert resp.headers["x-content-type-options"] == "nosniff"
    csp = resp.headers["content-security-policy"]
    assert "unsafe-eval" not in csp
    script_src = next((d for d in csp.split(";") if "script-src" in d), "")
    assert "'unsafe-inline'" not in script_src
    if path == "/ui/word-taskpane.html":
        assert "office.com" in csp
    else:
        assert "frame-ancestors 'none'" in csp


def test_api_docs_disabled_in_production(tmp_path):
    import subprocess
    import sys

    code = (
        "from app.config import settings; settings.env='production';"
        "import importlib, app.api.main as m; importlib.reload(m);"
        "print(m.app.docs_url, m.app.openapi_url)"
    )
    env = {
        "PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "AUTH_ENABLED": "true",
        "CORS_ORIGINS": "https://dms.example", "SOURCES_TOKEN_ENCRYPTION_SECRET": "x" * 40,
        "INGEST_ALLOWED_ROOTS": "/srv", "DATABASE_URL": "postgresql://a:b@localhost:55432/legal_memory",
        "MALWARE_SCANNER": "clamd", "ENV": "production", "INGEST_MODE": "queue",
        "OIDC_ISSUER": "https://idp.example", "OIDC_CLIENT_ID": "x", "OIDC_REDIRECT_URI": "https://dms.example/api/auth/callback",
        "ALLOW_API_KEY_BROWSER_LOGIN": "false",
    }
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-500:]
    assert out.stdout.strip().endswith("None None")


# ── D: ingest off the request path ────────────────────────────────────────────


def _drain_queue_except(batch_id: str) -> None:
    """Park other queued batches (from other suites) so run_once picks ours."""
    from app.db.connection import connect

    with connect() as conn:
        conn.execute("UPDATE upload_batches SET status = 'pending' WHERE status = 'queued' AND batch_id <> %s", (batch_id,))
        conn.commit()


def test_queue_mode_enqueues_and_worker_processes(client, walls: list[Wall], monkeypatch):
    from app.workers import ingest as worker

    w = walls[0]
    monkeypatch.setattr(settings, "ingest_mode", "queue")
    unique = uuid.uuid4().hex.encode()  # dedup-by-hash must not match an earlier run
    created = _upload(client, w.matter_id, w.insider, [("queued-note.txt", b"a queued note about the cure period " + unique)])
    bid = created.json()["batch_id"]
    resp = client.post(f"/api/uploads/batches/{bid}/run", headers=as_member(w.insider))
    assert resp.status_code == 202 and resp.json()["status"] == "queued"
    assert client.get(f"/api/uploads/batches/{bid}", headers=as_member(w.insider)).json()["batch"]["status"] == "queued"

    _drain_queue_except(bid)
    assert worker.run_once() == bid
    batch = client.get(f"/api/uploads/batches/{bid}", headers=as_member(w.insider)).json()["batch"]
    assert batch["status"] == "completed" and batch["files"][0]["status"] == "indexed"
    _delete_documents(batch)


def test_worker_reclaims_stale_batch(client, walls: list[Wall]):
    from app.db.connection import connect
    from app.workers import ingest as worker

    w = walls[0]
    bid = _upload(client, w.matter_id, w.insider, [("stale.txt", b"stale batch text " + uuid.uuid4().hex.encode())]).json()["batch_id"]
    with connect() as conn:  # a worker died mid-batch an hour ago
        conn.execute("UPDATE upload_batches SET status = 'running', updated_at = now() - interval '1 hour' WHERE batch_id = %s", (bid,))
        conn.commit()
    _drain_queue_except(bid)
    assert worker.run_once() == bid
    batch = client.get(f"/api/uploads/batches/{bid}", headers=as_member(w.insider)).json()["batch"]
    assert batch["status"] == "completed"
    _delete_documents(batch)


def test_worker_leaves_live_batches_alone(client, walls: list[Wall]):
    from app.db.connection import connect
    from app.workers import ingest as worker

    w = walls[0]
    bid = _upload(client, w.matter_id, w.insider, [("live.txt", b"live batch")]).json()["batch_id"]
    with connect() as conn:
        conn.execute("UPDATE upload_batches SET status = 'running', updated_at = now() WHERE batch_id = %s", (bid,))
        conn.commit()
    _drain_queue_except(bid)
    assert worker.run_once() != bid


def test_production_requires_queue_mode():
    from app.config import Settings

    assert any("INGEST_MODE" in p for p in Settings(ingest_mode="inline").production_problems())


def _delete_documents(batch: dict) -> None:
    """Remove documents the worker created (the module fixture removes the batches)."""
    from app.db.connection import connect

    ids = [f["document_id"] for f in batch["files"] if f.get("document_id")]
    with connect() as conn, conn.transaction():
        conn.execute("DELETE FROM chunks WHERE document_id = ANY(%s)", (ids,))
        conn.execute("DELETE FROM document_blocks WHERE document_id = ANY(%s)", (ids,))
        conn.execute("UPDATE documents SET current_version_id = NULL WHERE document_id = ANY(%s)", (ids,))
        conn.execute("DELETE FROM document_versions WHERE document_id = ANY(%s)", (ids,))
        conn.execute("UPDATE upload_batch_files SET document_id = NULL, version_id = NULL WHERE document_id = ANY(%s)", (ids,))
        conn.execute("DELETE FROM ingest_items WHERE document_id = ANY(%s)", (ids,))
        conn.execute("DELETE FROM documents WHERE document_id = ANY(%s)", (ids,))
