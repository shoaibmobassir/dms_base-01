"""Tabular reviews (plan 22, W4): durable, shared by the workspace's access, filled by leased background workers.

Mounted at /api/tabular. Services live in ``app/tabular``.
"""
from __future__ import annotations

from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from app import tabular as svc
from app.auth.deps import resolve_member
from app.db.connection import connect
from app.firm import FirmError
from app.tabular import runner

router = APIRouter(tags=["Tabular Reviews"])


def _run(fn, *args, **kwargs):
    with connect() as conn:
        try:
            return jsonable_encoder(fn(conn, *args, **kwargs))
        except FirmError as exc:
            conn.rollback()
            raise HTTPException(status_code=exc.status, detail=jsonable_encoder({"message": exc.detail, **exc.extra})) from exc


class ColumnIn(BaseModel):
    label: str | None = Field(default=None, max_length=120)
    question: str | None = Field(default=None, max_length=2000)
    answer_format: Literal["text", "date", "yes_no", "number", "money", "list", "choice"] | None = None
    choices: list[str] = Field(default_factory=list, max_length=20)
    preset: str | None = None


class ReviewCreate(BaseModel):
    title: str = Field(max_length=200)
    kind: Literal["matter", "project", "library"]
    id: str
    columns: list[ColumnIn] = Field(default_factory=list, max_length=svc.MAX_COLUMNS)
    document_ids: list[str] = Field(default_factory=list, max_length=svc.MAX_ROWS)
    folders: list[str] = Field(default_factory=list, max_length=200)
    group_by: Literal["document", "folder"] = "document"
    model: str | None = None
    playbook_id: str | None = None
    run: bool = True


class ReviewPatch(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    row_version: int | None = None


class ColumnPatch(BaseModel):
    label: str | None = Field(default=None, max_length=120)
    question: str | None = Field(default=None, max_length=2000)
    answer_format: Literal["text", "date", "yes_no", "number", "money", "list", "choice"] | None = None
    choices: list[str] | None = Field(default=None, max_length=20)
    position: int | None = Field(default=None, ge=0)


class RowsIn(BaseModel):
    document_ids: list[str] = Field(default_factory=list, max_length=svc.MAX_ROWS)
    folders: list[str] = Field(default_factory=list, max_length=200)
    run: bool = True


class RunIn(BaseModel):
    scope: Literal["open", "all", "column", "row", "cell"] = "open"
    column_id: str | None = None
    row_id: str | None = None


class SaveAsPlaybook(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class CellIn(BaseModel):
    answer: str | None = Field(default=None, max_length=4000)


def _kick(review_id: str) -> None:
    runner.start(review_id)


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "tabular_reviews"}


@router.get("/presets")
def presets() -> dict:
    return {"presets": [{"key": k, **v} for k, v in svc.PRESETS.items()]}


@router.post("/reviews", status_code=201)
def create_review(body: ReviewCreate, member_id: str | None = Depends(resolve_member)) -> dict:
    data = body.model_dump()
    if data["kind"] == "library" and data["id"] == "me":
        data["id"] = member_id
    out = _run(svc.create_review, member_id, data)
    if body.run and out["rows"]:
        _run(svc.mark_for_run, member_id, out["review_id"], "open")
        _kick(out["review_id"])
    return out


@router.get("/reviews")
def list_reviews(kind: Literal["matter", "project", "library"], id: str,
                 member_id: str | None = Depends(resolve_member)) -> dict:
    cid = member_id if kind == "library" and id == "me" else id
    return {"items": _run(svc.list_reviews, member_id, kind, cid)}


@router.get("/reviews/{review_id}")
def get_review(review_id: str, member_id: str | None = Depends(resolve_member)) -> dict:
    out = _run(svc.get_review, member_id, review_id)
    with connect() as conn:
        if runner.needs_workers(conn, review_id):  # a run interrupted by a restart carries on
            _kick(review_id)
    return out


@router.patch("/reviews/{review_id}")
def update_review(review_id: str, body: ReviewPatch, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(svc.update_review, member_id, review_id, body.title, body.row_version)


@router.delete("/reviews/{review_id}")
def archive_review(review_id: str, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(svc.archive_review, member_id, review_id)


@router.post("/reviews/{review_id}/columns")
def add_columns(review_id: str, columns: list[ColumnIn], run: bool = True,
                member_id: str | None = Depends(resolve_member)) -> dict:
    out = _run(svc.add_columns, member_id, review_id, [c.model_dump() for c in columns])
    if run:
        _run(svc.mark_for_run, member_id, review_id, "open")
        _kick(review_id)
    return out


@router.patch("/reviews/{review_id}/columns/{column_id}")
def update_column(review_id: str, column_id: str, body: ColumnPatch, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(svc.update_column, member_id, review_id, column_id, body.model_dump(exclude_none=True))


@router.delete("/reviews/{review_id}/columns/{column_id}")
def delete_column(review_id: str, column_id: str, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(svc.delete_column, member_id, review_id, column_id)


@router.post("/reviews/{review_id}/rows")
def add_rows(review_id: str, body: RowsIn, member_id: str | None = Depends(resolve_member)) -> dict:
    out = _run(svc.add_rows, member_id, review_id, body.document_ids, body.folders)
    if body.run and out.get("added"):
        _run(svc.mark_for_run, member_id, review_id, "open")
        _kick(review_id)
    return out


@router.delete("/reviews/{review_id}/rows/{row_id}")
def delete_row(review_id: str, row_id: str, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(svc.delete_row, member_id, review_id, row_id)


@router.post("/reviews/{review_id}/run")
def run_review(review_id: str, body: RunIn, member_id: str | None = Depends(resolve_member)) -> dict:
    _run(svc.mark_for_run, member_id, review_id, body.scope, body.column_id, body.row_id)
    _kick(review_id)
    return _run(svc.get_review, member_id, review_id)


@router.post("/reviews/{review_id}/stop")
def stop_review(review_id: str, member_id: str | None = Depends(resolve_member)) -> dict:
    _run(svc.stop_run, member_id, review_id)
    return _run(svc.get_review, member_id, review_id)


@router.patch("/reviews/{review_id}/cells/{row_id}/{column_id}")
def override_cell(review_id: str, row_id: str, column_id: str, body: CellIn,
                  member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(svc.override_cell, member_id, review_id, row_id, column_id, body.answer)


@router.get("/reviews/{review_id}/export.xlsx")
def export_xlsx(review_id: str, member_id: str | None = Depends(resolve_member)) -> Response:
    from app.audit import events as audit
    from app.tabular.export import workbook

    view = _run(svc.get_review, member_id, review_id)
    audit.record("tabular.export", member_id=member_id, object_type="tab_review", object_id=review_id)
    name = f"{view['title']}.xlsx"
    return Response(content=workbook(view),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})


@router.get("/reviews/{review_id}/cells")
def cells_for_assistant(review_id: str, rows: list[str] | None = Query(default=None),
                        columns: list[str] | None = Query(default=None),
                        member_id: str | None = Depends(resolve_member)) -> dict:
    """The filled table, compact, for the Assistant's ``read_review_cells`` tool (redacted like the page)."""
    return _run(runner.cells_for_assistant, member_id, review_id, rows, columns)


@router.post("/reviews/{review_id}/save-as-playbook", status_code=201)
def save_as_playbook(review_id: str, body: SaveAsPlaybook, member_id: str | None = Depends(resolve_member)) -> dict:
    """Keep this review's questions as a playbook to start the next review with."""
    return _run(svc.save_as_playbook, member_id, review_id, body.title)
