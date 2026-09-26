from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.api.routers import (
    activity,
    answers,
    chat_router,
    clients,
    documents_router,
    home,
    knowledge,
    matters,
    people,
    projects,
    retrieval,
    search,
    sources,
    system,
    tasks,
    teams,
    reviews,
    uploads,
    tabular,
    workflows_router,
    drafting_router,
    word_router,
    caselaw_router,
    audit_router,
    auth_router,
)
from app.api.limits import BodySizeLimitMiddleware
from app.api.security_headers import SecurityHeadersMiddleware
from app.auth.deps import resolve_member
from app.config import settings
from app.db.connection import close_sync_pool, init_sync_pool
from app.db.pool import close_pool, init_pool
from app.observability.request_id import RequestIDMiddleware
from app.observability.tracing import setup_tracing
from app.sprint import CURRENT_SPRINT

logger = logging.getLogger(__name__)

from app.observability import redaction  # noqa: E402

redaction.install()

if settings.env == "production" and (_problems := settings.production_problems()):
    raise RuntimeError("Refusing to start with unsafe production settings:\n  - " + "\n  - ".join(_problems))

SERVICE_CATALOG = {
    "system": {"prefix": "/api/system", "health": "/api/system/health"},
    "home": {"prefix": "/api/home", "health": "/api/home/health"},
    "retrieval": {"prefix": "/api/retrieval", "health": "/api/retrieval/health"},
    "answers": {"prefix": "/api/answers", "health": "/api/answers/health"},
    "matters": {"prefix": "/api/matters", "health": "/api/matters/health"},
    "documents": {"prefix": "/api/documents", "health": "/api/documents/health"},
    "projects": {"prefix": "/api/projects", "health": "/api/projects/health"},
    "clients": {"prefix": "/api/clients", "health": "/api/clients/health"},
    "people": {"prefix": "/api/people", "health": "/api/people/health"},
    "search": {"prefix": "/api/search", "health": "/api/search/health"},
    "teams": {"prefix": "/api/teams", "health": "/api/teams/health"},
    "knowledge": {"prefix": "/api/knowledge", "health": "/api/knowledge/health"},
    "activity": {"prefix": "/api/activity", "health": "/api/activity/health"},
    "tasks": {"prefix": "/api/tasks", "health": "/api/tasks/health"},
    "reviews": {"prefix": "/api/reviews", "health": "/api/reviews/health"},
    "uploads": {"prefix": "/api/uploads", "health": "/api/uploads/health"},
    "tabular": {"prefix": "/api/tabular", "health": "/api/tabular/health"},
    "workflows": {"prefix": "/api/workflows", "health": "/api/workflows/health"},
    "drafting": {"prefix": "/api/drafting", "health": "/api/drafting/health"},
    "word": {"prefix": "/api/word", "health": "/api/word/health"},
    "caselaw": {"prefix": "/api/caselaw", "health": "/api/caselaw/health"},
    "audit": {"prefix": "/api/audit", "health": "/api/audit/health"},
    "chat": {"prefix": "/api/chat", "health": "/api/chat/health"},
    "sources": {"prefix": "/api/sources", "health": "/api/sources/health"},
}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    setup_tracing()
    try:
        init_sync_pool()
    except Exception as exc:
        logger.warning("Sync pool init failed (lazy connect will retry): %s", exc)
    try:
        await init_pool()
        logger.info("Async connection pool initialized")
    except Exception as exc:
        logger.warning("Async pool init failed (v1 engine will still work): %s", exc)
    yield
    await close_pool()
    close_sync_pool()
    logger.info("Connection pools closed")


app = FastAPI(
    title="LEXOS — Legal DMS & AI Institutional Memory API",
    version="1.0.0",
    description="Production-grade Legal Document Management & Institutional Memory Intelligence Engine",
    lifespan=lifespan,
    # Interactive docs expose the whole API surface and load scripts from a CDN.
    docs_url=None if settings.env == "production" else "/docs",
    redoc_url=None if settings.env == "production" else "/redoc",
    openapi_url=None if settings.env == "production" else "/openapi.json",
)

_cors_origins = settings.cors_origin_list
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    # Credentials may only be combined with an explicit origin allow-list.
    allow_credentials="*" not in _cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)
app.add_middleware(BodySizeLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
# Added last so it is outermost and still echoes the id on streamed responses.
app.add_middleware(RequestIDMiddleware)

# System (health, info, firm branding) is public so probes and the sign-in screen work.
app.include_router(system.router, prefix="/api/system")
# Sign-in endpoints create identity, so they can't require it (revocation checks the caller itself).
app.include_router(auth_router.router, prefix="/api/auth")

# Everything else requires an identity: with AUTH_ENABLED=true that means a valid API
# key, even on routers whose handlers don't read the member themselves.
_AUTHED_ROUTERS = [
    (home, "home"),
    (retrieval, "retrieval"),
    (answers, "answers"),
    (matters, "matters"),
    (documents_router, "documents"),
    (clients, "clients"),
    (people, "people"),
    (search, "search"),
    (teams, "teams"),
    (knowledge, "knowledge"),
    (tasks, "tasks"),
    (reviews, "reviews"),
    (uploads, "uploads"),
    (tabular, "tabular"),
    (workflows_router, "workflows"),
    (drafting_router, "drafting"),
    (word_router, "word"),
    (caselaw_router, "caselaw"),
    (audit_router, "audit"),
    (chat_router, "chat"),
    (sources, "sources"),
]
if settings.enable_legacy_projects:
    _AUTHED_ROUTERS += [(projects, "projects"), (activity, "activity")]
else:
    SERVICE_CATALOG.pop("projects", None)
    SERVICE_CATALOG.pop("activity", None)

for _module, _name in _AUTHED_ROUTERS:
    app.include_router(_module.router, prefix=f"/api/{_name}", dependencies=[Depends(resolve_member)])


_static_dir = Path(__file__).resolve().parents[2] / "static"


def _spa_index() -> FileResponse:
    return FileResponse(_static_dir / "index.html")


def _static_asset(rest: str) -> Path | None:
    """Return the file for ``rest`` only if it resolves inside ``static/``."""
    asset = (_static_dir / rest).resolve()
    if asset.is_relative_to(_static_dir) and asset.is_file():
        return asset
    return None


if _static_dir.is_dir():

    @app.get("/ui")
    @app.get("/ui/{rest:path}")
    def spa_ui(rest: str = "") -> FileResponse:
        """Serve static assets; all other /ui/* paths fall back to the SPA shell."""
        if rest:
            asset = _static_asset(rest)
            if asset is not None:
                return FileResponse(asset)
        return _spa_index()


@app.get("/")
def root() -> dict:
    return {
        "service": "LEXOS Legal DMS",
        "version": "1.0.0",
        "sprint": CURRENT_SPRINT,
        "ui": "/ui",
        "docs": "/docs",
        "services": SERVICE_CATALOG,
    }
