"""Spreadsheet import: check first (nothing saved), then apply; row-level reasons; admin only."""
from __future__ import annotations

import uuid

import pytest

from app.db.connection import connect
from tests.conftest import as_member

ADMIN = "MEM-00011"


def _post(client, entity, text, member=ADMIN, dry=True):
    return client.post(f"/api/imports/{entity}", data={"dry_run": "true" if dry else "false"},
                       files={"file": ("x.csv", text.encode(), "text/csv")}, headers=as_member(member))


@pytest.fixture
def tag():
    t = uuid.uuid4().hex[:8]
    yield t
    with connect() as conn:
        conn.execute("DELETE FROM matters WHERE title LIKE %s", (f"E2E-TMP %{t}%",))
        conn.execute("DELETE FROM member_roles WHERE member_id IN (SELECT member_id FROM members WHERE email LIKE %s)", (f"e2e-tmp-{t}%",))
        conn.execute("DELETE FROM members WHERE email LIKE %s", (f"e2e-tmp-{t}%",))
        conn.execute("DELETE FROM clients WHERE name LIKE %s", (f"E2E-TMP %{t}%",))
        conn.commit()


def test_template_download(client, seeded):
    r = client.get("/api/imports/clients/template", headers=as_member(ADMIN))
    assert r.status_code == 200 and r.text.startswith("name,")
    assert client.get("/api/imports/nope/template", headers=as_member(ADMIN)).status_code == 404


def test_people_preview_saves_nothing_then_apply(client, seeded, tag):
    csv_text = ("name,title,email,roles\n"
                f"E2E-TMP Ada {tag},Associate,e2e-tmp-{tag}-a@example.com,fee_earner\n"
                f"E2E-TMP Bad {tag},Associate,not-an-email,fee_earner\n"
                f"E2E-TMP Role {tag},Associate,e2e-tmp-{tag}-r@example.com,wizard\n")
    prev = _post(client, "people", csv_text)
    assert prev.status_code == 200, prev.text
    body = prev.json()
    assert (body["total"], body["ok"], body["errors"], body["created"]) == (3, 1, 2, 0)
    with connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM members WHERE email LIKE %s", (f"e2e-tmp-{tag}%",)).fetchone()["n"] == 0
    done = _post(client, "people", csv_text, dry=False).json()
    assert done["created"] == 1
    assert _post(client, "people", csv_text).json()["errors"] == 3  # the first row is now a duplicate


def test_clients_then_matters(client, seeded, tag):
    name = f"E2E-TMP Client {tag}"
    out = _post(client, "clients", f"name,industry\n{name},Energy\n{name},Energy\n", dry=False).json()
    assert out["created"] == 1 and out["errors"] == 1
    csv_m = ("title,client,practice_area\n"
             f"E2E-TMP Matter {tag},{name},Corporate\n"
             f"E2E-TMP Orphan {tag},No Such Client {tag},Corporate\n")
    res = _post(client, "matters", csv_m, dry=False).json()
    assert res["created"] == 1 and res["errors"] == 1
    assert "No client named" in [r for r in res["rows"] if r["status"] == "error"][0]["message"]


def test_missing_column_and_permission(client, seeded):
    assert _post(client, "clients", "industry\nEnergy\n").status_code == 422
    with connect() as conn:
        other = conn.execute("SELECT member_id FROM members m WHERE active AND NOT EXISTS "
                             "(SELECT 1 FROM member_roles r WHERE r.member_id = m.member_id AND r.role_key = 'firm_admin') LIMIT 1").fetchone()
    assert _post(client, "people", "name\nX\n", member=other["member_id"]).status_code == 403
