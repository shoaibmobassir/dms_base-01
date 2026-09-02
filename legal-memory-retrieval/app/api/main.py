from contextlib import asynccontextmanager
import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.api.routers import (
    activity,
    answers,
    clients,
    documents_router,
    home,
    knowledge,
    matters,
    people,
    projects,
    retrieval,
    search,
    system,
    tasks,
    teams,
)
from app.db.pool import close_pool, init_pool
from app.observability.tracing import setup_tracing
from app.sprint import CURRENT_SPRINT

logger = logging.getLogger(__name__)

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
}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    setup_tracing()
    # Initialize async connection pool for parallel retrieval engine
    try:
        await init_pool()
        logger.info("Async connection pool initialized")
    except Exception as exc:
        logger.warning("Async pool init failed (v1 engine will still work): %s", exc)
    yield
    # Cleanup
    await close_pool()
    logger.info("Async connection pool closed")


app = FastAPI(
    title="LEXOS — Legal DMS & AI Institutional Memory API",
    version="1.0.0",
    description="Production-grade Legal Document Management & Institutional Memory Intelligence Engine",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(system.router, prefix="/api/system")
app.include_router(home.router, prefix="/api/home")
app.include_router(retrieval.router, prefix="/api/retrieval")
app.include_router(answers.router, prefix="/api/answers")
app.include_router(matters.router, prefix="/api/matters")
app.include_router(documents_router.router, prefix="/api/documents")
app.include_router(projects.router, prefix="/api/projects")
app.include_router(clients.router, prefix="/api/clients")
app.include_router(people.router, prefix="/api/people")
app.include_router(search.router, prefix="/api/search")
app.include_router(teams.router, prefix="/api/teams")
app.include_router(knowledge.router, prefix="/api/knowledge")
app.include_router(activity.router, prefix="/api/activity")
app.include_router(tasks.router, prefix="/api/tasks")

_static_dir = os.path.join(os.path.dirname(__file__), "..", "..", "static")


def _spa_index() -> FileResponse:
    return FileResponse(os.path.join(_static_dir, "index.html"))


if os.path.isdir(_static_dir):

    @app.get("/ui")
    @app.get("/ui/{rest:path}")
    def spa_ui(rest: str = "") -> FileResponse:
        """Serve static assets; all other /ui/* paths fall back to the SPA shell."""
        if rest:
            asset = os.path.join(_static_dir, rest)
            if os.path.isfile(asset):
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
