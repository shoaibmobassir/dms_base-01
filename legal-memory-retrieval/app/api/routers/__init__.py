"""Section routers — one prefix per sidebar view."""

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

__all__ = [
    "activity",
    "answers",
    "clients",
    "documents_router",
    "home",
    "knowledge",
    "matters",
    "people",
    "projects",
    "retrieval",
    "search",
    "system",
    "tasks",
    "teams",
]
