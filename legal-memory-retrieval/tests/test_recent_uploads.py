"""The caller's own recent upload batches."""
from __future__ import annotations

from tests.conftest import as_member


def test_lists_only_my_batches(client, seeded):
    mine = client.get("/api/uploads/batches", headers=as_member("MEM-00001"))
    assert mine.status_code == 200, mine.text
    for b in mine.json()["batches"]:
        assert {"batch_id", "matter_title", "indexed", "duplicates", "failed", "retryable", "files"} <= set(b)
