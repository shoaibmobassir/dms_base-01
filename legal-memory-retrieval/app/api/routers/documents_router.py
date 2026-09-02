from fastapi import APIRouter, Depends, HTTPException, Query
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
