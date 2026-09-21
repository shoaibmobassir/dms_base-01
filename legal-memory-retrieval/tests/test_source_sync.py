"""Phase 0 universal source sync — unit + DB integration tests."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.sources.connectors.fake import FakeConnector
from app.sources.crypto import decrypt_token, encrypt_token, reset_crypto_for_tests
from app.sources.factory import (
    clear_fake_registry,
    get_connector,
    register_fake_connector,
)
from app.sources.models import ChangeType, ConnectionRecord, Permission, Scope
from app.sources.permissions import matter_trust_allows, principal_intersects
from app.sources.queue import (
    QUEUE_DOWNLOAD,
    SourceJob,
    backoff_seconds,
    clear_inline_queues,
    dequeue,
    enqueue,
)


class TestCrypto:
    def test_roundtrip(self, monkeypatch):
        reset_crypto_for_tests()
        from app.config import settings

        monkeypatch.setattr(
            settings, "sources_token_encryption_secret", "test-secret-for-sources-crypto"
        )
        reset_crypto_for_tests()
        enc = encrypt_token("access-token-abc")
        assert enc != "access-token-abc"
        assert decrypt_token(enc) == "access-token-abc"
        reset_crypto_for_tests()


class TestFakeConnector:
    def test_incremental_cursor_advances(self):
        c = FakeConnector(page_size=10)
        c.seed_file("f1", "a.txt", b"hello")
        c.seed_file("f2", "b.txt", b"world")
        page1 = c.get_changes(None, Scope())
        assert page1.done
        assert len(page1.items) == 2
        assert page1.next_cursor == "2"

        page2 = c.get_changes(page1.next_cursor, Scope())
        assert page2.items == []
        assert page2.done

        c.mutate_file("f1", b"hello!")
        page3 = c.get_changes(page1.next_cursor, Scope())
        assert len(page3.items) == 1
        assert page3.items[0].change_type == ChangeType.modified
        assert page3.next_cursor == "3"

    def test_delete_emits_tombstone_change(self):
        c = FakeConnector()
        c.seed_file("f1", "a.txt", b"x")
        c.delete_file("f1")
        page = c.get_changes("1", Scope())  # after seed
        assert any(i.change_type == ChangeType.deleted for i in page.items)

    def test_download_bytes(self):
        c = FakeConnector()
        c.seed_file("f1", "a.txt", b"payload")
        assert b"".join(c.download_file("f1")) == b"payload"


class TestQueueBackoff:
    def test_enqueue_dequeue_inline(self, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "sources_queue_inline", True)
        clear_inline_queues()
        enqueue(
            SourceJob(
                job_type=QUEUE_DOWNLOAD,
                connection_id="SRC-1",
                payload={"provider_file_id": "f1"},
            )
        )
        job = dequeue(QUEUE_DOWNLOAD)
        assert job is not None
        assert job.payload["provider_file_id"] == "f1"
        assert dequeue(QUEUE_DOWNLOAD) is None

    def test_backoff_grows(self, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "sources_sync_backoff_base_seconds", 1.0)
        assert backoff_seconds(0) == 1.0
        assert backoff_seconds(1) == 2.0
        assert backoff_seconds(2) == 4.0
        assert backoff_seconds(10) == 60.0


class TestPermissionsHelpers:
    def test_matter_trust(self):
        assert matter_trust_allows(matter_acl_ok=True) is True
        assert matter_trust_allows(matter_acl_ok=False) is False

    def test_principal_intersects(self):
        perms = [
            Permission(principal_type="user", principal_id="g-user-1"),
            Permission(principal_type="anyone", principal_id="*"),
        ]
        assert principal_intersects(
            perms, member_id="M1", mapped_provider_ids={"g-user-1"}
        )
        assert principal_intersects(
            [Permission(principal_type="user", principal_id="other")],
            member_id="M1",
            mapped_provider_ids=set(),
        ) is False


class TestFactory:
    def test_fake_registry(self):
        clear_fake_registry()
        conn = ConnectionRecord(
            connection_id="SRC-TEST",
            organization_id="harbour",
            provider="fake",
            provider_account_id="a1",
            display_name="Fake",
            status="active",
            config={"matter_id": "MTR-1"},
        )
        fake = FakeConnector()
        register_fake_connector("SRC-TEST", fake)
        assert get_connector(conn) is fake
        clear_fake_registry()


def _ensure_source_tables() -> bool:
    """Apply Phase 0 migration if DB reachable. Return False if unavailable."""
    try:
        from app.db.connection import connect

        migration = (
            Path(__file__).resolve().parents[1]
            / "app"
            / "db"
            / "migrations"
            / "20260919_source_sync_phase0.sql"
        )
        sql = migration.read_text(encoding="utf-8")
        with connect() as conn:
            conn.execute("SELECT 1 FROM matters LIMIT 1")
            for stmt in _split_sql(sql):
                conn.execute(stmt)
            conn.commit()
        return True
    except Exception:
        return False


def _split_sql(sql: str) -> list[str]:
    stmts: list[str] = []
    buf: list[str] = []
    for line in sql.splitlines():
        if line.strip().startswith("--"):
            continue
        buf.append(line)
        if line.rstrip().endswith(";"):
            stmts.append("\n".join(buf))
            buf = []
    if buf:
        stmts.append("\n".join(buf))
    return [s for s in stmts if s.strip()]


@pytest.fixture
def sources_db(object_store_env, monkeypatch):
    from app.config import settings

    if not _ensure_source_tables():
        pytest.skip("database unavailable or empty")
    monkeypatch.setattr(settings, "sources_sync_enabled", True)
    monkeypatch.setattr(settings, "sources_queue_inline", True)
    clear_fake_registry()
    clear_inline_queues()
    yield
    clear_fake_registry()
    clear_inline_queues()


@pytest.fixture
def object_store_env(tmp_path: Path, monkeypatch):
    from app.storage.object_store import reset_object_store_for_tests
    from app.config import settings

    reset_object_store_for_tests()
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_root", str(tmp_path / "objects"))
    yield tmp_path / "objects"
    reset_object_store_for_tests()


class TestSyncEngineDB:
    def test_sync_index_skip_delete(self, sources_db):
        from app.db.connection import connect
        from app.sources import store
        from app.sources.sync_engine import run_sync

        with connect() as conn:
            row = conn.execute(
                "SELECT matter_id FROM matters LIMIT 1"
            ).fetchone()
        if not row:
            pytest.skip("no matters")
        matter_id = row["matter_id"]

        uniq = os.urandom(3).hex()
        connection = store.create_connection(
            organization_id="harbour",
            provider="fake",
            matter_id=matter_id,
            provider_account_id="fake-1",
            display_name="Fake",
        )
        fake = FakeConnector()
        fake.seed_file(
            f"fid-{uniq}",
            f"policy_{uniq}.txt",
            f"Maternity leave is 26 weeks {uniq}.\n".encode(),
            path=f"HR/policy_{uniq}.txt",
        )
        register_fake_connector(connection.connection_id, fake)

        r1 = run_sync(connection.connection_id, process_inline=True)
        assert r1["status"] == "ok"
        assert r1["change_count"] >= 1
        actions1 = {a["action"] for a in r1["actions"]}
        assert "downloaded" in actions1 or "enqueued_download" in actions1

        files = store.list_source_files(connection.connection_id)
        indexed = [f for f in files if f["status"] == "indexed"]
        assert len(indexed) == 1
        doc_id = indexed[0]["document_id"]
        assert doc_id

        # Unchanged re-emit → skip
        fake.reemit_unchanged(f"fid-{uniq}")
        r2 = run_sync(connection.connection_id, process_inline=True)
        assert r2["status"] == "ok"
        assert any(a["action"] == "skipped_unchanged" for a in r2["actions"])

        # Delete → tombstone
        fake.delete_file(f"fid-{uniq}")
        r3 = run_sync(connection.connection_id, process_inline=True)
        assert r3["status"] == "ok"
        assert any(a["action"] == "deleted" for a in r3["actions"])

        with connect() as conn:
            doc = conn.execute(
                "SELECT status, body FROM documents WHERE document_id = %s",
                (doc_id,),
            ).fetchone()
            chunks = conn.execute(
                "SELECT count(*) AS n FROM chunks WHERE document_id = %s",
                (doc_id,),
            ).fetchone()
        assert doc["status"] == "Deleted"
        assert chunks["n"] == 0

        sf = store.get_source_file_by_provider(connection.connection_id, f"fid-{uniq}")
        assert sf["status"] == "deleted"
        assert sf["deleted_at"] is not None
