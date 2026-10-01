"""Shared fixtures for tests that run against the seeded demo database.

Seed first:  python scripts/migrate.py && python scripts/seed_demo.py
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.db.connection import connect


@dataclass(frozen=True)
class Wall:
    """A restricted matter, one member inside its wall and one outside."""

    matter_id: str
    matter_code: str
    title: str
    client_id: str
    document_id: str
    insider: str
    outsider: str


@pytest.fixture(scope="session")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(scope="session")
def seeded() -> None:
    with connect() as conn:
        try:
            firm = conn.execute("SELECT 1 FROM firm_profile").fetchone()
        except Exception:
            firm = None
    if not firm:
        pytest.skip("demo data not seeded: run scripts/migrate.py && scripts/seed_demo.py")


@pytest.fixture(scope="session")
def walls(seeded) -> list[Wall]:
    """Every restricted matter that has at least one document."""
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT m.matter_id, m.matter_code, m.title, m.client_id, p.allowed_members,
                   (SELECT d.document_id FROM documents d WHERE d.matter_id = m.matter_id
                     ORDER BY d.document_id LIMIT 1) AS document_id
            FROM matters m JOIN permissions p ON p.matter_id = m.matter_id
            WHERE p.restricted
            ORDER BY m.matter_id
            """
        ).fetchall()
        members = [r["member_id"] for r in conn.execute("SELECT member_id FROM members ORDER BY member_id")]
    out = []
    for r in rows:
        outsiders = [m for m in members if m not in r["allowed_members"]]
        if r["document_id"] and outsiders and r["allowed_members"]:
            out.append(
                Wall(
                    matter_id=r["matter_id"],
                    matter_code=r["matter_code"],
                    title=r["title"],
                    client_id=r["client_id"],
                    document_id=r["document_id"],
                    insider=r["allowed_members"][0],
                    outsider=outsiders[0],
                )
            )
    if not out:
        pytest.skip("no restricted matters with documents — seed_demo.py restricts some")
    return out


def as_member(member_id: str) -> dict[str, str]:
    return {"X-Member-Id": member_id}


@pytest.fixture
def batch_cleanup():
    """Upload batches a test creates; their documents are deleted when the test ends."""
    from app.ingest.purge import purge_upload_batches

    batch_ids: list[str] = []
    yield batch_ids
    purge_upload_batches(batch_ids)


@pytest.fixture
def document_cleanup():
    """Document ids a test creates outside an upload batch; deleted when the test ends."""
    from app.ingest.purge import purge_documents

    ids: list[str] = []
    yield ids
    if ids:
        with connect() as conn, conn.transaction():
            purge_documents(conn, ids)


_GENERATED_TMP: str | None = None


def pytest_configure(config):
    """Files the Assistant generates during tests go to a temp folder, not data/object_store."""
    import tempfile

    from app.chat.tools import generation_tools

    global _GENERATED_TMP
    _GENERATED_TMP = str(Path(tempfile.mkdtemp(prefix="precentis-generated-")).resolve())
    generation_tools.generated_dir = lambda: Path(_GENERATED_TMP)


def pytest_unconfigure(config):
    if not _GENERATED_TMP:
        return
    import shutil

    try:
        with connect() as conn:
            conn.execute("DELETE FROM generated_artifacts WHERE storage_path LIKE %s", (f"{_GENERATED_TMP}%",))
            conn.commit()
    except Exception:
        pass  # no database in this run
    shutil.rmtree(_GENERATED_TMP, ignore_errors=True)
