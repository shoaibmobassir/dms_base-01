"""Document editor, file versions, locks and compare (plan 16, E1–E2). Mounted at /api/editor.

The same lock + version calls serve the browser editor now and a Word add-in or a
Collabora (WOPI) connector later.
"""
from __future__ import annotations

from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from app.auth.deps import resolve_member
from app.db.connection import connect
from app.documents import comments, editing, privacy, review

router = APIRouter(tags=["editor"])


def _run(fn, *args, **kwargs):
    with connect() as conn:
        try:
            return fn(conn, *args, **kwargs)
        except editing.EditError as exc:
            raise HTTPException(status_code=exc.status,
                                detail=jsonable_encoder({"message": exc.detail, **exc.extra})) from exc


class EditRun(BaseModel):
    text: str = Field(max_length=editing.MAX_OP_TEXT)
    bold: bool = False
    italic: bool = False
    underline: bool = False


class EditOp(BaseModel):
    op: Literal["replace", "delete", "insert_after", "format"]
    pid: int = Field(ge=0)
    text: str | None = Field(default=None, max_length=editing.MAX_OP_TEXT)
    style: str | None = Field(default=None, max_length=64)
    runs: list[EditRun] | None = Field(default=None, max_length=2000)


class DraftBody(BaseModel):
    base_version_id: str
    ops: list[EditOp] = Field(default_factory=list, max_length=editing.MAX_OPS)


class SaveBody(DraftBody):
    note: str = Field(default="", max_length=1000)
    mode: Literal["tracked", "clean"] = "tracked"


@router.get("/health")
def editor_health() -> dict:
    return {"service": "editor", "status": "ok"}


@router.get("/documents/{document_id}")
def get_edit_model(document_id: str, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(editing.edit_model, document_id.upper(), member_id)


# Each editor window sends its lock token in this header (see editing.acquire_lock).
LockToken = Header(default=None, alias="X-Edit-Lock", max_length=64)


@router.post("/documents/{document_id}/lock")
def post_lock(document_id: str, takeover: bool = Query(default=False), token: str | None = LockToken,
              member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(editing.acquire_lock, document_id.upper(), member_id, token=token, takeover=takeover)


@router.post("/documents/{document_id}/lock/heartbeat")
def post_heartbeat(document_id: str, token: str | None = LockToken, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(editing.heartbeat, document_id.upper(), member_id, token)


@router.delete("/documents/{document_id}/lock", status_code=204)
def delete_lock(document_id: str, token: str | None = LockToken, member_id: str | None = Depends(resolve_member)) -> None:
    _run(editing.release_lock, document_id.upper(), member_id, token)


@router.put("/documents/{document_id}/draft")
def put_draft(document_id: str, body: DraftBody, token: str | None = LockToken,
              member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(editing.save_draft, document_id.upper(), member_id, body.base_version_id,
                [o.model_dump(exclude_none=True) for o in body.ops], token)


@router.delete("/documents/{document_id}/draft", status_code=204)
def delete_draft(document_id: str, member_id: str | None = Depends(resolve_member)) -> None:
    _run(editing.discard_draft, document_id.upper(), member_id)


@router.post("/documents/{document_id}/save", status_code=201)
def post_save(document_id: str, body: SaveBody, token: str | None = LockToken,
              member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(editing.save_edits, document_id.upper(), member_id, body.base_version_id,
                [o.model_dump(exclude_none=True) for o in body.ops], body.note, body.mode, token)


@router.post("/documents/{document_id}/versions", status_code=201)
async def post_version_upload(
    document_id: str,
    file: UploadFile = File(...),
    base_version_id: str | None = Form(default=None),
    note: str = Form(default="", max_length=1000),
    label: str | None = Form(default=None, max_length=80),
    token: str | None = LockToken,
    member_id: str | None = Depends(resolve_member),
) -> dict:
    from app.config import settings

    limit = settings.max_upload_file_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status_code=413, detail={"message": f"Files are limited to {settings.max_upload_file_mb} MB"})
    return _run(editing.upload_version, document_id.upper(), member_id, file.filename or "upload", data,
                base_version_id, note, label, token)


@router.get("/documents/{document_id}/compare")
def get_compare(document_id: str, from_: str = Query(alias="from"), to: str = Query(...),
                member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(editing.compare, document_id.upper(), member_id, from_, to)


@router.get("/documents/{document_id}/compare.docx")
def get_compare_docx(document_id: str, from_: str = Query(alias="from"), to: str = Query(...),
                     member_id: str | None = Depends(resolve_member)) -> Response:
    data, name = _run(editing.compare_docx, document_id.upper(), member_id, from_, to)
    return Response(content=data, media_type=editing.DOCX_MIME,
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})


@router.get("/documents/{document_id}/history")
def get_history(document_id: str, limit: int = Query(default=100, le=500),
                member_id: str | None = Depends(resolve_member)) -> JSONResponse:
    items = _run(editing.history, document_id.upper(), member_id, limit)
    return JSONResponse(jsonable_encoder({"items": items}), headers={"Cache-Control": "no-store"})


# ── comments on the exact view (E6) ──────────────────────────────────────────

class Rect(BaseModel):
    x0: float = Field(ge=0, le=1)
    y0: float = Field(ge=0, le=1)
    x1: float = Field(ge=0, le=1)
    y1: float = Field(ge=0, le=1)


class CommentBody(BaseModel):
    body: str = Field(max_length=comments.MAX_BODY)
    version_id: str | None = None
    page: int | None = Field(default=None, ge=1)
    rects: list[Rect] = Field(default_factory=list, max_length=comments.MAX_RECTS)
    quote: str = Field(default="", max_length=comments.MAX_QUOTE)
    parent_id: str | None = None


class CommentStatus(BaseModel):
    status: Literal["open", "resolved"]


@router.get("/documents/{document_id}/comments")
def get_comments(document_id: str, version_id: str | None = Query(default=None),
                 member_id: str | None = Depends(resolve_member)) -> JSONResponse:
    out = _run(comments.list_comments, document_id.upper(), member_id, version_id)
    return JSONResponse(jsonable_encoder(out), headers={"Cache-Control": "no-store"})


@router.post("/documents/{document_id}/comments", status_code=201)
def post_comment(document_id: str, body: CommentBody, member_id: str | None = Depends(resolve_member)) -> dict:
    return jsonable_encoder(_run(comments.add_comment, document_id.upper(), member_id, body=body.body,
                                 version_id=body.version_id, page=body.page,
                                 rects=[r.model_dump() for r in body.rects], quote=body.quote, parent_id=body.parent_id))


@router.patch("/documents/{document_id}/comments/{comment_id}")
def patch_comment(document_id: str, comment_id: str, body: CommentStatus,
                  member_id: str | None = Depends(resolve_member)) -> dict:
    return jsonable_encoder(_run(comments.set_status, document_id.upper(), member_id, comment_id, body.status))


@router.delete("/documents/{document_id}/comments/{comment_id}", status_code=204)
def delete_comment(document_id: str, comment_id: str, member_id: str | None = Depends(resolve_member)) -> None:
    _run(comments.delete_comment, document_id.upper(), member_id, comment_id)


# ── document privacy (plan 17, P1b) ──────────────────────────────────────────

class Share(BaseModel):
    principal_type: Literal["member", "team"]
    principal_id: str = Field(max_length=64)
    level: Literal["read", "edit"] = "read"


class PrivacyBody(BaseModel):
    visibility: Literal["matter", "private", "restricted"]
    shares: list[Share] = Field(default_factory=list, max_length=privacy.MAX_SHARES)
    row_version: int | None = None


@router.get("/documents/{document_id}/privacy")
def get_privacy(document_id: str, member_id: str | None = Depends(resolve_member)) -> JSONResponse:
    out = _run(privacy.get_privacy, document_id.upper(), member_id)
    return JSONResponse(jsonable_encoder(out), headers={"Cache-Control": "no-store"})


@router.put("/documents/{document_id}/privacy")
def put_privacy(document_id: str, body: PrivacyBody, member_id: str | None = Depends(resolve_member)) -> dict:
    return jsonable_encoder(_run(privacy.set_privacy, document_id.upper(), member_id, visibility=body.visibility,
                                 shares=[x.model_dump() for x in body.shares], row_version=body.row_version))


@router.get("/documents/{document_id}/share-targets")
def get_share_targets(document_id: str, member_id: str | None = Depends(resolve_member)) -> dict:
    return jsonable_encoder(_run(privacy.share_targets, document_id.upper(), member_id))


# ── Word review: who changed what, accept / reject (plan 18) ──────────────────

class ReviewBody(BaseModel):
    base_version_id: str
    action: Literal["accept", "reject"]
    keys: list[str] | None = Field(default=None, max_length=20000)
    authors: list[str] | None = Field(default=None, max_length=50)
    all: bool = False
    note: str = Field(default="", max_length=1000)


@router.get("/documents/{document_id}/review")
def get_review(document_id: str, version_id: str | None = Query(default=None),
               member_id: str | None = Depends(resolve_member)) -> JSONResponse:
    out = _run(review.get_review, document_id.upper(), member_id, version_id)
    return JSONResponse(jsonable_encoder(out), headers={"Cache-Control": "no-store"})


@router.post("/documents/{document_id}/review", status_code=201)
def post_review(document_id: str, body: ReviewBody, token: str | None = LockToken,
                member_id: str | None = Depends(resolve_member)) -> dict:
    return jsonable_encoder(_run(review.apply_review, document_id.upper(), member_id, base_version_id=body.base_version_id,
                                 action=body.action, keys=body.keys, authors=body.authors, everything=body.all,
                                 note=body.note, token=token))


@router.get("/documents/{document_id}/contributors")
def get_contributors(document_id: str, member_id: str | None = Depends(resolve_member)) -> JSONResponse:
    out = _run(review.contributors, document_id.upper(), member_id)
    return JSONResponse(jsonable_encoder(out), headers={"Cache-Control": "no-store"})


@router.get("/documents/{document_id}/download-with-comments")
def get_download_with_comments(document_id: str, version_id: str | None = Query(default=None),
                               member_id: str | None = Depends(resolve_member)) -> Response:
    """The Word file with every Precentis comment, reply and resolution written into it."""
    data, name = _run(review.download_with_comments, document_id.upper(), member_id, version_id)
    return Response(content=data, media_type=editing.DOCX_MIME,
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})
