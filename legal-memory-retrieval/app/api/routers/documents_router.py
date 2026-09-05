from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from psycopg.rows import dict_row

from app.api.acl import ACL_CLAUSE
from app.api.documents import (
    document_detail_enriched,
    document_diff,
    document_versions,
    ingest_document,
)
from app.api.ingest_jobs import (
    create_ingest_job,
    get_ingest_job,
    retry_ingest_job,
    run_ingest_job,
)
from app.api.schemas import IngestDocumentRequest, IngestJobRequest, VersionCreate, DevelopingVersionRequest
from app.auth.deps import resolve_member
from app.db.connection import connect
from app.documents import (
    create_version,
    create_developing_version,
    list_versions as list_doc_versions,
    get_version,
    diff_versions,
)
from app.documents.anchor import AnchorTarget, resolve_anchor
from app.documents.canonical import (
    get_version_blocks,
    parse_canonical_blocks,
    save_canonical_blocks,
)

router = APIRouter(tags=["documents"])

SERVICE = "documents"


@router.get("/health")
def documents_health() -> dict:
    return {"service": SERVICE, "status": "ok"}


@router.get("")
def documents_list(
    q: str | None = Query(default=None),
    matter_id: str | None = Query(default=None),
    client_id: str | None = Query(default=None),
    doc_type: str | None = Query(default=None),
    author: str | None = Query(default=None),
    member_id: str | None = Depends(resolve_member),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    params: dict = {"member_id": member_id, "limit": limit, "offset": offset}
    wheres = [ACL_CLAUSE]
    if q:
        wheres.append(
            "(d.title ILIKE %(q_like)s"
            " OR d.document_id ILIKE %(q_like)s"
            " OR d.author_name ILIKE %(q_like)s"
            " OR d.body ILIKE %(q_like)s)"
        )
        params["q_like"] = f"%{q}%"
    if matter_id:
        wheres.append("d.matter_id = %(matter_id)s")
        params["matter_id"] = matter_id
    if client_id:
        wheres.append("d.client_id = %(client_id)s")
        params["client_id"] = client_id
    if doc_type:
        wheres.append("d.document_type ILIKE %(doc_type_like)s")
        params["doc_type_like"] = f"%{doc_type}%"
    if author:
        wheres.append("d.author_name ILIKE %(author_like)s")
        params["author_like"] = f"%{author}%"
    where = " AND ".join(wheres)
    sql = f"""
        SELECT d.document_id, d.matter_id, d.matter_code, d.title,
               d.document_type, d.author_name, d.doc_date, d.status, d.version
        FROM documents d
        LEFT JOIN permissions p ON p.matter_id = d.matter_id
        WHERE {where}
        ORDER BY d.doc_date DESC NULLS LAST
        LIMIT %(limit)s OFFSET %(offset)s
    """
    count_sql = f"""
        SELECT COUNT(*) AS n FROM documents d
        LEFT JOIN permissions p ON p.matter_id = d.matter_id
        WHERE {where}
    """
    count_params = {k: v for k, v in params.items() if k not in ("limit", "offset")}
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            items = list(cur.fetchall())
            cur.execute(count_sql, count_params)
            total = cur.fetchone()["n"]
    return {"service": SERVICE, "total": total, "items": items}


@router.post("/ingest")
def ingest_document_endpoint(
    req: IngestDocumentRequest,
    member_id: str | None = Depends(resolve_member),
) -> dict:
    result = ingest_document(req, member_id)
    result["service"] = SERVICE
    return result


@router.post("/ingest/jobs")
def ingest_job_create(
    req: IngestJobRequest,
    member_id: str | None = Depends(resolve_member),
) -> dict:
    result = create_ingest_job(req.source_root, req.manifest, req.workers)
    if req.run_immediately:
        run_result = run_ingest_job(result["job_id"], req.manifest)
        result.update(run_result)
    result["service"] = SERVICE
    return result


@router.get("/ingest/jobs/{job_id}")
def ingest_job_status(
    job_id: str,
    member_id: str | None = Depends(resolve_member),
) -> dict:
    result = get_ingest_job(job_id)
    result["service"] = SERVICE
    return result


@router.post("/ingest/jobs/{job_id}/retry")
def ingest_job_retry(
    job_id: str,
    req: IngestJobRequest,
    member_id: str | None = Depends(resolve_member),
) -> dict:
    result = retry_ingest_job(job_id, req.manifest)
    result["service"] = SERVICE
    return result


@router.get("/{document_id}")
def document_detail(
    document_id: str,
    highlight_chunk: str | None = Query(default=None, description="chunk_id to highlight"),
    chunk_id: str | None = Query(default=None, description="alias for highlight_chunk"),
    q: str | None = Query(default=None),
    member_id: str | None = Depends(resolve_member),
) -> dict:
    chunk = highlight_chunk or chunk_id
    result = document_detail_enriched(
        document_id,
        member_id,
        highlight_chunk=chunk,
        q=q,
    )
    result["service"] = SERVICE
    return result


# ── Document Versioning ─────────────────────────────────────────────────────


def _check_doc_access(document_id: str, member_id: str | None) -> None:
    """Verify ACL allows access to the document."""
    doc_id = document_id.upper()
    params = {"doc_id": doc_id, "member_id": member_id}
    access_sql = f"""
        SELECT 1 FROM documents d
        LEFT JOIN permissions p ON p.matter_id = d.matter_id
        WHERE d.document_id = %(doc_id)s AND {ACL_CLAUSE}
    """
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(access_sql, params)
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Document not found or access denied")


@router.post("/{document_id}/versions")
def create_document_version(
    document_id: str,
    body: VersionCreate,
    member_id: str | None = Depends(resolve_member),
) -> dict:
    """Create a new immutable version of the document."""
    # ACL check
    _check_doc_access(document_id, member_id)
    version = create_version(
        document_id=document_id.upper(),
        body=body.body,
        title=body.title,
        author_name=body.author_name,
        source=body.source,
        version_status=body.version_status,
        version_label=body.version_label,
    )
    return {"service": SERVICE, "status": "created", "version": version}


@router.post("/{document_id}/versions/developing")
def create_developing_version_endpoint(
    document_id: str,
    body: DevelopingVersionRequest | None = None,
    member_id: str | None = Depends(resolve_member),
) -> dict:
    """Create a new developing/working version from the current document body."""
    _check_doc_access(document_id, member_id)
    req = body or DevelopingVersionRequest()
    version = create_developing_version(
        document_id=document_id.upper(),
        author_name=req.author_name,
    )
    return {"service": SERVICE, "status": "created", "version": version}


@router.get("/{document_id}/versions")
def document_versions_endpoint(
    document_id: str,
    member_id: str | None = Depends(resolve_member),
) -> dict:
    _check_doc_access(document_id, member_id)
    versions = list_doc_versions(document_id.upper())
    return {"service": SERVICE, "document_id": document_id, "versions": versions}


@router.get("/{document_id}/versions/{version_id}")
def document_version_detail(
    document_id: str,
    version_id: str,
    member_id: str | None = Depends(resolve_member),
) -> dict:
    _check_doc_access(document_id, member_id)
    version = get_version(document_id.upper(), version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")
    return {"service": SERVICE, "version": version}


@router.get("/{document_id}/versions/{version_id}/diff")
def document_version_diff(
    document_id: str,
    version_id: str,
    compare_with: str = Query(description="version_id to compare against"),
    member_id: str | None = Depends(resolve_member),
) -> dict:
    _check_doc_access(document_id, member_id)
    result = diff_versions(version_id, compare_with)
    result["service"] = SERVICE
    return result


@router.get("/{document_id}/diff")
def document_diff_endpoint(
    document_id: str,
    compare_with_id: str | None = Query(default=None),
    member_id: str | None = Depends(resolve_member),
) -> dict:
    result = document_diff(document_id, compare_with_id, member_id)
    result["service"] = SERVICE
    return result


@router.get("/{document_id}/chunks")
def document_chunks_endpoint(
    document_id: str,
    member_id: str | None = Depends(resolve_member),
) -> dict:
    doc_id = document_id.upper()
    params = {"doc_id": doc_id, "member_id": member_id}
    access_sql = f"""
        SELECT 1 FROM documents d
        LEFT JOIN permissions p ON p.matter_id = d.matter_id
        WHERE d.document_id = %(doc_id)s AND {ACL_CLAUSE}
    """
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(access_sql, params)
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Document not found or access denied")
            cur.execute(
                "SELECT chunk_id, chunk_index, text FROM chunks"
                " WHERE document_id = %(doc_id)s ORDER BY chunk_index",
                {"doc_id": doc_id},
            )
            return {"service": SERVICE, "document_id": doc_id, "chunks": list(cur.fetchall())}


@router.get("/{document_id}/versions/{version_id}/chunks")
def get_version_hierarchical_chunks(
    document_id: str,
    version_id: str,
    children_only: bool = Query(default=False),
    member_id: str | None = Depends(resolve_member),
) -> dict:
    """Version-scoped hierarchical chunks (parent section + child paragraph groups)."""
    _check_doc_access(document_id, member_id)
    from app.documents.hierarchical_chunks import get_version_chunks

    chunks = get_version_chunks(version_id, children_only=children_only)
    return {
        "service": SERVICE,
        "document_id": document_id,
        "version_id": version_id,
        "chunks": chunks,
        "count": len(chunks),
    }


@router.get("/chunks/{chunk_id}/context")
def get_chunk_context_envelope(
    chunk_id: str,
    member_id: str | None = Depends(resolve_member),
) -> dict:
    """Full context envelope for a chunk (client/matter/folder/doc/section/page)."""
    from app.documents.hierarchical_chunks import build_context_envelope_for_chunk

    envelope = build_context_envelope_for_chunk(chunk_id)
    if envelope is None:
        raise HTTPException(status_code=404, detail="Chunk not found")
    return {"service": SERVICE, "chunk_id": chunk_id, "context_envelope": envelope}


# ── Canonical AST Blocks & Intelligence ──────────────────────────────────────


@router.get("/{document_id}/versions/{version_id}/blocks")
def get_version_blocks_endpoint(
    document_id: str,
    version_id: str,
    member_id: str | None = Depends(resolve_member),
) -> dict:
    """Retrieve canonical AST blocks with deterministic offsets and SHA-256 hashes."""
    _check_doc_access(document_id, member_id)

    blocks = get_version_blocks(version_id)
    if not blocks:
        ver = get_version(document_id.upper(), version_id)
        if ver and ver.get("body"):
            parsed = parse_canonical_blocks(ver["body"], document_id.upper(), version_id)
            save_canonical_blocks(parsed)
            blocks = [b.to_dict() for b in parsed]

    return {
        "service": SERVICE,
        "document_id": document_id,
        "version_id": version_id,
        "blocks": blocks,
        "total_blocks": len(blocks),
    }


class ResolveAnchorRequest(BaseModel):
    quoted_text: str
    text_hash: str | None = None
    block_id: str | None = None
    page_number: int = 1
    start_offset: int = 0
    end_offset: int = 0


@router.post("/{document_id}/versions/{version_id}/resolve-anchor")
def resolve_anchor_endpoint(
    document_id: str,
    version_id: str,
    req: ResolveAnchorRequest,
    member_id: str | None = Depends(resolve_member),
) -> dict:
    """Resolve a content anchor (exact → fuzzy → semantic). PDF coords are not required."""
    _check_doc_access(document_id, member_id)
    target = AnchorTarget(
        version_id=version_id,
        quoted_text=req.quoted_text,
        text_hash=req.text_hash,
        block_id=req.block_id,
        page_number=req.page_number,
        start_offset=req.start_offset,
        end_offset=req.end_offset,
    )
    resolved = resolve_anchor(target)
    return {
        "service": SERVICE,
        "document_id": document_id,
        "version_id": version_id,
        "resolved": resolved.to_dict(),
    }


@router.get("/{document_id}/versions/{version_id}/findings")
def get_version_findings_endpoint(
    document_id: str,
    version_id: str,
    member_id: str | None = Depends(resolve_member),
) -> dict:
    """Retrieve all structured AI findings and durable evidence anchors for a document version."""
    _check_doc_access(document_id, member_id)
    from app.documents import list_version_findings

    findings = list_version_findings(document_id.upper(), version_id)
    return {
        "service": SERVICE,
        "document_id": document_id,
        "version_id": version_id,
        "findings": findings,
        "count": len(findings),
    }


@router.post("/{document_id}/versions/{version_id}/diff/{compare_with_id}")
def document_multilevel_diff_endpoint(
    document_id: str,
    version_id: str,
    compare_with_id: str,
    member_id: str | None = Depends(resolve_member),
) -> dict:
    """Compute complete dual-level diff: word-level redline + structured semantic legal delta."""
    _check_doc_access(document_id, member_id)
    from app.documents.diff import diff_document_versions

    result = diff_document_versions(version_id, compare_with_id)
    return {"service": SERVICE, "diff": result.to_dict()}


class AnnotationCreateRequest(BaseModel):
    quoted_text: str
    annotation_type: str = "user_highlight"
    block_id: str | None = None
    page_number: int = 1
    start_offset: int = 0
    end_offset: int = 0
    author_name: str | None = None
    finding_id: str | None = None
    content: str | None = None


@router.post("/{document_id}/versions/{version_id}/annotations")
def create_annotation_endpoint(
    document_id: str,
    version_id: str,
    req: AnnotationCreateRequest,
    member_id: str | None = Depends(resolve_member),
) -> dict:
    """Create a durable annotation attached to a canonical block."""
    _check_doc_access(document_id, member_id)
    from app.documents import create_annotation

    ann = create_annotation(
        document_id=document_id.upper(),
        version_id=version_id,
        quoted_text=req.quoted_text,
        annotation_type=req.annotation_type,
        block_id=req.block_id,
        page_number=req.page_number,
        start_offset=req.start_offset,
        end_offset=req.end_offset,
        author_id=member_id,
        author_name=req.author_name,
        finding_id=req.finding_id,
        content=req.content,
    )
    return {"service": SERVICE, "status": "created", "annotation": ann}


@router.get("/{document_id}/versions/{version_id}/annotations")
def list_annotations_endpoint(
    document_id: str,
    version_id: str,
    member_id: str | None = Depends(resolve_member),
) -> dict:
    """List all active annotations for a version."""
    _check_doc_access(document_id, member_id)
    from app.documents import list_annotations

    anns = list_annotations(document_id.upper(), version_id)
    return {
        "service": SERVICE,
        "document_id": document_id,
        "version_id": version_id,
        "annotations": anns,
        "count": len(anns),
    }

