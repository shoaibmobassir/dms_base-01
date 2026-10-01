"""Firm sign-in: OIDC login/callback, session, sign-out, administrator revocation.

Mounted without the router-wide ``resolve_member`` dependency (these endpoints
create identity); the revocation endpoint resolves the caller itself.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse

from app.audit import events as audit
from app.auth import oidc, sessions
from app.auth.deps import resolve_member
from app.config import settings
from app.db.connection import connect
from app.observability.request_id import current_client_ip

log = logging.getLogger(__name__)
router = APIRouter(tags=["auth"])


@router.get("/config")
def auth_config() -> dict:
    """What the sign-in screen should offer."""
    return {
        "auth_enabled": settings.auth_enabled,
        "oidc_enabled": settings.oidc_enabled,
        "api_key_login": settings.auth_enabled and settings.allow_api_key_browser_login,
    }


@router.get("/login")
def login(next: str | None = Query(default=None)) -> RedirectResponse:
    if not settings.oidc_enabled:
        raise HTTPException(status_code=404, detail="Firm sign-in is not configured")
    return RedirectResponse(oidc.begin_login(next), status_code=302)


@router.get("/callback")
def callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
    if error or not code or not state:
        audit.record("auth.sign_in", member_id=None, outcome="denied", detail={"reason": error or "missing code/state"})
        return RedirectResponse("/ui/?signin=failed", status_code=302)
    try:
        who = oidc.complete_login(code, state)
    except oidc.OIDCError as exc:
        log.warning("sign-in failed: %s", exc)
        audit.record("auth.sign_in", member_id=None, outcome="denied", detail={"reason": str(exc)})
        return RedirectResponse("/ui/?signin=failed", status_code=302)
    response = RedirectResponse(who.next_path, status_code=302)
    sessions.create(response, who.member_id, subject=who.subject, ip=current_client_ip() or None,
                    user_agent=request.headers.get("user-agent"))
    audit.record("auth.sign_in", member_id=who.member_id, detail={"method": "oidc", "email": who.email})
    return response


@router.get("/session")
def session(request: Request) -> dict:
    """The signed-in member for the current browser session (401 if none)."""
    current = sessions.load(request.cookies.get(sessions.SESSION_COOKIE))
    if current is None:
        raise HTTPException(status_code=401, detail="Not signed in")
    with connect() as conn:
        person = conn.execute(
            "SELECT member_id, name, role, practice_areas, specializations, office, joined_year, is_lawyer "
            "FROM members WHERE member_id = %s",
            (current.member_id,),
        ).fetchone()
    return {"person": person}


@router.post("/logout", status_code=204)
def logout(request: Request) -> Response:
    token = request.cookies.get(sessions.SESSION_COOKIE)
    current = sessions.load(token)
    # Sign-out is state-changing: require the CSRF token so a third-party page can't log users out.
    if current is not None and not sessions.csrf_ok(current, request.headers.get("x-csrf-token")):
        raise HTTPException(status_code=403, detail="CSRF token missing or invalid")
    member = sessions.revoke(token)
    response = Response(status_code=204)
    sessions.clear_cookies(response)
    if member:
        audit.record("auth.sign_out", member_id=member)
    return response


@router.post("/members/{target}/revoke-sessions")
def revoke_member_sessions(target: str, member_id: str | None = Depends(resolve_member)) -> dict:
    """Administrator: end every session of a member (leaver, lost device, deprovisioning)."""
    if not audit.is_admin(member_id):
        audit.record("admin.revoke_sessions", member_id=member_id, outcome="denied", object_type="member", object_id=target)
        raise HTTPException(status_code=403, detail="Administrator access required")
    n = sessions.revoke_all(target)
    audit.record("admin.revoke_sessions", member_id=member_id, object_type="member", object_id=target, detail={"sessions": n})
    return {"revoked": n}
