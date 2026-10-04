"""Write layer routes (plan 17, P2). Services live in ``app/firm``; reads stay in their routers.

Mounted beside the read routers: /api/matters, /api/clients, /api/conflicts, /api/people,
/api/events, /api/home.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from app.auth.deps import resolve_member
from app.db.connection import connect
from app.firm import FirmError, clients as client_svc, feed, imports as import_svc, matters as matter_svc, people as people_svc

matters_router = APIRouter(tags=["matters (write)"])
clients_router = APIRouter(tags=["clients (write)"])
conflicts_router = APIRouter(tags=["conflicts"])
people_router = APIRouter(tags=["people (write)"])
events_router = APIRouter(tags=["events"])
home_router = APIRouter(tags=["home"])
imports_router = APIRouter(tags=["imports"])


def _run(fn, *args, **kwargs):
    with connect() as conn:
        try:
            return jsonable_encoder(fn(conn, *args, **kwargs))
        except FirmError as exc:
            conn.rollback()
            raise HTTPException(status_code=exc.status, detail=jsonable_encoder({"message": exc.detail, **exc.extra})) from exc


# ── matters ──────────────────────────────────────────────────────────────────

class TeamEntry(BaseModel):
    member_id: str
    role: str = "Associate"


class MatterCreate(BaseModel):
    title: str = Field(max_length=500)
    client_id: str
    practice_area: str = Field(max_length=200)
    matter_type: str | None = None
    matter_code: str | None = Field(default=None, max_length=40)
    opposing_party: str | None = None
    jurisdiction: str | None = None
    court: str | None = None
    office: str | None = None
    opened_date: date | None = None
    claim_amount: float | None = None
    legal_issues: list[str] = Field(default_factory=list, max_length=50)
    facts: list[str] = Field(default_factory=list, max_length=50)
    access_mode: Literal["open", "team", "restricted"] = "team"
    lead_member_id: str | None = None
    team: list[TeamEntry] = Field(default_factory=list, max_length=50)


class MatterPatch(BaseModel):
    changes: dict[str, Any]
    row_version: int | None = None


class StaffBody(BaseModel):
    role: str = "Associate"
    started_at: date | None = None
    ended_at: date | None = None


class EventBody(BaseModel):
    occurred_on: date | None = None
    title: str | None = Field(default=None, max_length=500)
    detail: str | None = Field(default=None, max_length=5000)
    kind: str | None = None
    source_document_id: str | None = None
    row_version: int | None = None


class ArgumentBody(BaseModel):
    issue: str | None = Field(default=None, max_length=500)
    position: str | None = Field(default=None, max_length=100)
    argument: str | None = Field(default=None, max_length=20000)
    outcome: str | None = Field(default=None, max_length=2000)
    supporting_documents: list[str] | None = Field(default=None, max_length=50)
    row_version: int | None = None


class LinkBody(BaseModel):
    related_matter_id: str
    relation: str = "related"
    note: str = Field(default="", max_length=1000)


def _set(body: BaseModel) -> dict:
    return {k: v for k, v in body.model_dump(exclude_unset=True).items() if k != "row_version"}


@matters_router.post("", status_code=201)
def create_matter(body: MatterCreate, member_id: str | None = Depends(resolve_member)) -> dict:
    data = body.model_dump()
    data["team"] = [t.model_dump() for t in body.team]
    if data.get("opened_date"):
        data["opened_date"] = data["opened_date"].isoformat()
    return _run(matter_svc.create_matter, member_id, data)


@matters_router.patch("/{matter_id}")
def update_matter(matter_id: str, body: MatterPatch, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(matter_svc.update_matter, member_id, matter_id, body.changes, body.row_version)


class CloseBody(BaseModel):
    outcome: str = Field(min_length=1, max_length=2000)
    closed_date: date | None = None
    resolve_deadlines: bool = False
    row_version: int | None = None


class ReopenBody(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


@matters_router.get("/{matter_id}/close-check")
def get_close_check(matter_id: str, member_id: str | None = Depends(resolve_member)) -> dict:
    return jsonable_encoder(_run(matter_svc.close_check, member_id, matter_id))


@matters_router.post("/{matter_id}/close")
def post_close(matter_id: str, body: CloseBody, member_id: str | None = Depends(resolve_member)) -> dict:
    return jsonable_encoder(_run(matter_svc.close_matter, member_id, matter_id, body.outcome,
                                 body.closed_date.isoformat() if body.closed_date else None, body.resolve_deadlines, body.row_version))


@matters_router.post("/{matter_id}/reopen")
def post_reopen(matter_id: str, body: ReopenBody, member_id: str | None = Depends(resolve_member)) -> dict:
    return jsonable_encoder(_run(matter_svc.reopen_matter, member_id, matter_id, body.reason))


@matters_router.get("/{matter_id}/team")
def get_team(matter_id: str, member_id: str | None = Depends(resolve_member)) -> dict:
    def fn(conn):
        matter_svc.require_level(conn, member_id, matter_id, "read")
        return {"matter_id": matter_id, "team": matter_svc.team(conn, matter_id)}
    return _run(matter_svc.guard(fn))


@matters_router.put("/{matter_id}/team/{person_id}")
def put_staff(matter_id: str, person_id: str, body: StaffBody, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(matter_svc.set_staff, member_id, matter_id, person_id, body.role,
                body.started_at.isoformat() if body.started_at else None, body.ended_at.isoformat() if body.ended_at else None)


@matters_router.delete("/{matter_id}/team/{person_id}")
def delete_staff(matter_id: str, person_id: str, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(matter_svc.remove_staff, member_id, matter_id, person_id)


@matters_router.post("/{matter_id}/events", status_code=201)
def post_event(matter_id: str, body: EventBody, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(matter_svc.add_event, member_id, matter_id, _set(body))


@matters_router.patch("/{matter_id}/events/{event_id}")
def patch_event(matter_id: str, event_id: str, body: EventBody, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(matter_svc.update_event, member_id, matter_id, event_id, _set(body), body.row_version)


@matters_router.delete("/{matter_id}/events/{event_id}", status_code=204)
def delete_event(matter_id: str, event_id: str, member_id: str | None = Depends(resolve_member)) -> None:
    _run(matter_svc.delete_event, member_id, matter_id, event_id)


@matters_router.post("/{matter_id}/arguments", status_code=201)
def post_argument(matter_id: str, body: ArgumentBody, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(matter_svc.add_argument, member_id, matter_id, _set(body))


@matters_router.patch("/{matter_id}/arguments/{argument_id}")
def patch_argument(matter_id: str, argument_id: str, body: ArgumentBody, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(matter_svc.update_argument, member_id, matter_id, argument_id, _set(body), body.row_version)


@matters_router.delete("/{matter_id}/arguments/{argument_id}", status_code=204)
def delete_argument(matter_id: str, argument_id: str, member_id: str | None = Depends(resolve_member)) -> None:
    _run(matter_svc.delete_argument, member_id, matter_id, argument_id)


@matters_router.post("/{matter_id}/related", status_code=201)
def post_link(matter_id: str, body: LinkBody, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(matter_svc.link_matters, member_id, matter_id, body.related_matter_id, body.relation, body.note)


@matters_router.delete("/{matter_id}/related/{related_id}", status_code=204)
def delete_link(matter_id: str, related_id: str, member_id: str | None = Depends(resolve_member)) -> None:
    _run(matter_svc.unlink_matters, member_id, matter_id, related_id)


# ── spreadsheet import ───────────────────────────────────────────────────────

@imports_router.get("/{entity}/template")
def get_import_template(entity: str) -> Response:
    try:
        text = import_svc.template_csv(entity)
    except FirmError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from exc
    return Response(content=text, media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{entity}-template.csv"'})


@imports_router.post("/{entity}")
async def post_import(entity: str, file: UploadFile = File(...), dry_run: bool = Form(default=True),
                      member_id: str | None = Depends(resolve_member)) -> dict:
    raw = await file.read(import_svc.MAX_BYTES + 1)
    fn = import_svc.preview if dry_run else import_svc.apply
    return _run(fn, member_id, entity, raw)


# ── clients and conflict checks ──────────────────────────────────────────────

class ClientCreate(BaseModel):
    name: str = Field(max_length=300)
    check_id: str
    industry: str | None = None
    size: str | None = None
    headquarters: str | None = None
    locations: list[str] = Field(default_factory=list, max_length=30)
    subsidiaries: list[str] = Field(default_factory=list, max_length=30)
    aliases: list[str] = Field(default_factory=list, max_length=30)


class CheckBody(BaseModel):
    names: list[str] = Field(min_length=1, max_length=client_svc.MAX_NAMES)
    purpose: str = Field(default="", max_length=500)


class DecisionBody(BaseModel):
    decision: Literal["clear", "conflict", "waived"]
    notes: str = Field(default="", max_length=2000)


@clients_router.post("", status_code=201)
def create_client(body: ClientCreate, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(client_svc.create_client, member_id, body.model_dump())


class ClientPatch(BaseModel):
    name: str | None = Field(default=None, max_length=300)
    industry: str | None = None
    size: str | None = None
    headquarters: str | None = None
    aliases: list[str] | None = Field(default=None, max_length=30)
    locations: list[str] | None = Field(default=None, max_length=30)
    subsidiaries: list[str] | None = Field(default=None, max_length=30)
    status: Literal["active", "on_hold", "inactive"] | None = None


class NoteBody(BaseModel):
    kind: Literal["prefers", "avoid", "terms"]
    text: str = Field(min_length=1, max_length=2000)
    source_matter_id: str | None = None


@clients_router.patch("/{client_id}")
def patch_client(client_id: str, body: ClientPatch, member_id: str | None = Depends(resolve_member)) -> dict:
    return jsonable_encoder(_run(client_svc.update_client, member_id, client_id, _set(body)))


@clients_router.post("/{client_id}/notes", status_code=201)
def post_client_note(client_id: str, body: NoteBody, member_id: str | None = Depends(resolve_member)) -> dict:
    return jsonable_encoder(_run(client_svc.add_client_note, member_id, client_id, body.kind, body.text, body.source_matter_id))


@clients_router.delete("/{client_id}/notes/{note_id}", status_code=204)
def delete_client_note(client_id: str, note_id: str, member_id: str | None = Depends(resolve_member)) -> None:
    _run(client_svc.delete_client_note, member_id, client_id, note_id)


@conflicts_router.post("/check", status_code=201)
def post_check(body: CheckBody, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(client_svc.run_check, member_id, body.names, body.purpose)


@conflicts_router.get("")
def get_checks(scope: Literal["mine", "to_decide"] = Query(default="mine"), member_id: str | None = Depends(resolve_member)) -> dict:
    return {"items": _run(client_svc.list_checks, member_id, scope)}


@conflicts_router.get("/{check_id}")
def get_check(check_id: str, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(client_svc.get_check, member_id, check_id)


@conflicts_router.post("/{check_id}/decision")
def post_decision(check_id: str, body: DecisionBody, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(client_svc.decide, member_id, check_id, body.decision, body.notes)


# ── people ───────────────────────────────────────────────────────────────────

class PersonBody(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    role: str | None = Field(default=None, max_length=200)
    office: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=200)
    is_lawyer: bool | None = None
    joined_year: int | None = None
    practice_areas: list[str] | None = Field(default=None, max_length=30)
    specializations: list[str] | None = Field(default=None, max_length=30)
    roles: list[str] | None = None


@people_router.patch("/me")
def patch_me(body: PersonBody, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(people_svc.update_me, member_id, body.model_dump(exclude_unset=True))


@people_router.post("", status_code=201)
def post_person(body: PersonBody, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(people_svc.create_person, member_id, body.model_dump(exclude_unset=True))


class DeactivateBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


@people_router.post("/{person_id}/deactivate")
def post_deactivate(person_id: str, body: DeactivateBody, member_id: str | None = Depends(resolve_member)) -> dict:
    return jsonable_encoder(_run(people_svc.deactivate_person, member_id, person_id, body.reason))


@people_router.post("/{person_id}/reactivate")
def post_reactivate(person_id: str, member_id: str | None = Depends(resolve_member)) -> dict:
    return jsonable_encoder(_run(people_svc.reactivate_person, member_id, person_id))


@people_router.patch("/{person_id}")
def patch_person(person_id: str, body: PersonBody, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(people_svc.update_person, member_id, person_id, body.model_dump(exclude_unset=True))


# ── live updates ─────────────────────────────────────────────────────────────

POLL_SECONDS = 1.5
STREAM_SECONDS = 300      # the client reconnects with the last id it saw
HEARTBEAT_SECONDS = 15


@events_router.get("")
def get_events(since: int | None = Query(default=None, ge=0), member_id: str | None = Depends(resolve_member)) -> dict:
    """Events after ``since`` that the member may see (``since`` omitted: just the current position)."""
    with connect() as conn:
        if since is None:
            return {"latest": feed.latest_seq(conn), "items": []}
        items = feed.events_since(conn, member_id, since)
        # The cursor moves past events the member may not see too, so it never stalls on them.
        return jsonable_encoder({"latest": _last_scanned(conn, since), "items": items})


def _last_scanned(conn, since: int) -> int:
    row = conn.execute("SELECT coalesce(max(seq), %s) AS n FROM (SELECT seq FROM domain_events WHERE seq > %s "
                       "ORDER BY seq LIMIT 200) x", (since, since)).fetchone()
    return int(row["n"])


@events_router.get("/stream")
async def stream_events(request: Request, since: int | None = Query(default=None, ge=0),
                        member_id: str | None = Depends(resolve_member)) -> StreamingResponse:
    """Server-sent events: one ``event: <topic>`` per domain event the member may see."""
    last_event_id = request.headers.get("last-event-id")
    cursor = int(last_event_id) if last_event_id and last_event_id.isdigit() else since

    def poll(c: int | None) -> tuple[int, list[dict]]:
        with connect() as conn:
            if c is None:
                return feed.latest_seq(conn), []
            items = feed.events_since(conn, member_id, c)
            return max(_last_scanned(conn, c), c), items

    async def gen():
        nonlocal cursor
        loop = asyncio.get_running_loop()
        started = loop.time()
        beat = started
        cursor, _ = await asyncio.to_thread(poll, cursor) if cursor is None else (cursor, [])
        yield f"retry: 3000\nevent: ready\ndata: {json.dumps({'latest': cursor})}\n\n"
        while loop.time() - started < STREAM_SECONDS:
            if await request.is_disconnected():
                return
            cursor, items = await asyncio.to_thread(poll, cursor)
            for e in items:
                payload = json.dumps(jsonable_encoder(e))
                yield f"id: {e['seq']}\nevent: {e['topic']}\ndata: {payload}\n\n"
            if loop.time() - beat > HEARTBEAT_SECONDS:
                beat = loop.time()
                yield ": keep-alive\n\n"
            await asyncio.sleep(POLL_SECONDS)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


# ── home ─────────────────────────────────────────────────────────────────────

@home_router.get("/my-work")
def get_my_work(member_id: str | None = Depends(resolve_member)) -> dict:
    with connect() as conn:
        return jsonable_encoder(feed.my_work(conn, member_id))


# ── calendar (plan 17, P3) ───────────────────────────────────────────────────

from app.firm import calendar as cal_svc  # noqa: E402

calendar_router = APIRouter(tags=["calendar"])
calendar_feed_router = APIRouter(tags=["calendar feed"])  # mounted WITHOUT the sign-in dependency


class CalEventBody(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    kind: str | None = None
    starts_at: str | None = None
    ends_at: str | None = None
    all_day: bool | None = None
    location: str | None = Field(default=None, max_length=300)
    detail: str | None = Field(default=None, max_length=5000)
    matter_id: str | None = None
    attendees: list[str] | None = Field(default=None, max_length=100)
    row_version: int | None = None


class DeadlineBody(BaseModel):
    matter_id: str | None = None
    title: str | None = Field(default=None, max_length=300)
    kind: str | None = None
    due_date: date | None = None
    court: str | None = Field(default=None, max_length=300)
    owner_member_id: str | None = None
    notes: str | None = Field(default=None, max_length=2000)
    status: Literal["open", "done"] | None = None
    row_version: int | None = None


class FeedBody(BaseModel):
    show_restricted: bool = False


@calendar_router.get("")
def get_calendar(from_: date = Query(alias="from"), to: date = Query(...),
                 scope: Literal["mine", "team", "matter", "firm"] = Query(default="mine"),
                 matter_id: str | None = Query(default=None), member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(cal_svc.list_items, member_id, from_, to, scope, matter_id)


@calendar_router.post("/events", status_code=201)
def post_cal_event(body: CalEventBody, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(cal_svc.create_event, member_id, _set(body))


@calendar_router.patch("/events/{event_id}")
def patch_cal_event(event_id: str, body: CalEventBody, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(cal_svc.update_event, member_id, event_id, _set(body), body.row_version)


@calendar_router.delete("/events/{event_id}", status_code=204)
def delete_cal_event(event_id: str, member_id: str | None = Depends(resolve_member)) -> None:
    _run(cal_svc.delete_event, member_id, event_id)


@calendar_router.post("/deadlines", status_code=201)
def post_deadline(body: DeadlineBody, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(cal_svc.create_deadline, member_id, _set(body))


@calendar_router.patch("/deadlines/{deadline_id}")
def patch_deadline(deadline_id: str, body: DeadlineBody, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(cal_svc.update_deadline, member_id, deadline_id, _set(body), body.row_version)


@calendar_router.post("/deadlines/{deadline_id}/confirm")
def post_confirm(deadline_id: str, member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(cal_svc.confirm_deadline, member_id, deadline_id)


@calendar_router.get("/feed")
def get_feed(member_id: str | None = Depends(resolve_member)) -> dict:
    return _run(cal_svc.feed_status, member_id)


@calendar_router.post("/feed", status_code=201)
def post_feed(body: FeedBody, request: Request, member_id: str | None = Depends(resolve_member)) -> dict:
    out = _run(cal_svc.create_feed, member_id, body.show_restricted)
    base = str(request.base_url).rstrip("/")
    return {**out, "url": f"{base}/api/calendar-feed/{out['token']}.ics"}


@calendar_router.delete("/feed", status_code=204)
def delete_feed(member_id: str | None = Depends(resolve_member)) -> None:
    _run(cal_svc.revoke_feed, member_id)


@calendar_feed_router.get("/{token}.ics")
def get_ics(token: str):
    """A member's private calendar feed; the unguessable token is the credential (revocable)."""
    from fastapi.responses import Response

    with connect() as conn:
        body = cal_svc.ics_for_token(conn, token)
    if body is None:
        raise HTTPException(status_code=404, detail="Unknown or revoked calendar feed")
    return Response(content=body, media_type="text/calendar; charset=utf-8",
                    headers={"Cache-Control": "private, max-age=300", "Content-Disposition": 'inline; filename="precentis.ics"'})
