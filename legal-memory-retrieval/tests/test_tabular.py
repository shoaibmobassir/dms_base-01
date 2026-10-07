"""Durable tabular reviews (plan 22, W4) through the HTTP API and the real database, with a fake model.

The model is replaced so answers are deterministic: it answers every question with the first words of the first
passage, which the engine must then find again in that passage (a verified citation).
"""
from __future__ import annotations

import io
import json
import re
import threading
import uuid
from datetime import timedelta

import openpyxl
import pytest

from app.db.connection import connect
from app.tabular import runner
from tests.conftest import as_member
from tests.test_workspaces import _ok, _project, _upload, cast, made  # noqa: F401  (fixtures)


class FakeModel:
    def __init__(self):
        self.calls = 0
        self.lock = threading.Lock()

    def __call__(self, model):
        def call(messages):
            with self.lock:
                self.calls += 1
            prompt = messages[-1]["content"]
            questions = re.findall(r"^(\d+)\. ", prompt.split("PASSAGES:")[0], re.M)
            first = re.search(r"^\[1\](?: \(page \d+\))? (.+)$", prompt, re.M)
            words = " ".join(first.group(1).split()[:8]) if first else ""
            answers = [{"q": int(q), "answer": f"answer to {q}: {words}", "quote": words, "passage": 1, "not_found": not words}
                       for q in questions]
            return json.dumps({"answers": answers})
        return call


@pytest.fixture
def model(monkeypatch):
    fake = FakeModel()
    monkeypatch.setattr(runner, "llm_factory", fake)
    # Runs happen in the request thread so tests see the result at once.
    monkeypatch.setattr(runner, "start", lambda review_id, workers=None: runner.run_now(review_id))
    return fake


@pytest.fixture
def reviews():
    made_ids: list[str] = []
    yield made_ids
    with connect() as conn:
        conn.execute("DELETE FROM tab_reviews WHERE review_id = ANY(%s)", (made_ids,))
        conn.commit()


def _review(client, member, reviews, **body):
    r = client.post("/api/tabular/reviews", json=body, headers=as_member(member))
    out = _ok(r, 201)
    reviews.append(out["review_id"])
    return out


def _cells(view):
    return {(c["row_id"], c["column_id"]): c for c in view["cells"]}


def test_a_review_fills_every_cell_with_a_verified_citation(client, cast, made, model, reviews):
    pid = _project(client, cast["outsider"], made)["project_id"]
    a, _, _ = _upload(client, cast["outsider"], made, kind="project", cid=pid, body=b"E2E-TMP The notice period is ninety days from the date of notice.")
    b, _, _ = _upload(client, cast["outsider"], made, kind="project", cid=pid, body=b"E2E-TMP Liability is capped at the fees paid in the prior year.")
    view = _review(client, cast["outsider"], reviews, title="DD", kind="project", id=pid, document_ids=[a, b],
                   columns=[{"preset": "notice_period"}, {"label": "Cap", "question": "Is liability capped?", "answer_format": "yes_no"}])
    view = _ok(client.get(f"/api/tabular/reviews/{view['review_id']}", headers=as_member(cast["outsider"])))
    assert [r["document_id"] for r in view["rows"]] == [a, b]
    assert model.calls == 2  # one call per row, for all its columns
    for c in view["cells"]:
        assert c["status"] == "done" and c["answer"].startswith("answer to")
        cit = c["citations"][0]
        assert cit["verified"] and cit["document_id"] in (a, b) and cit["chunk_id"]
    # running again with nothing open does not call the model
    _ok(client.post(f"/api/tabular/reviews/{view['review_id']}/run", json={"scope": "open"}, headers=as_member(cast["outsider"])))
    assert model.calls == 2


def test_two_workers_never_fill_the_same_row_and_a_stopped_run_resumes(client, cast, made, model, reviews):
    pid = _project(client, cast["outsider"], made)["project_id"]
    docs = [_upload(client, cast["outsider"], made, kind="project", cid=pid, body=f"E2E-TMP clause {i} {uuid.uuid4().hex}".encode())[0]
            for i in range(6)]
    view = _review(client, cast["outsider"], reviews, title="Lease", kind="project", id=pid, document_ids=docs,
                   columns=[{"preset": "parties"}], run=False)
    rid = view["review_id"]
    with connect() as conn:
        conn.execute("UPDATE tab_reviews SET run_by = %s WHERE review_id = %s", (cast["outsider"], rid))
        conn.execute("UPDATE tab_cells SET status = 'pending' FROM tab_rows r WHERE r.row_id = tab_cells.row_id AND r.review_id = %s", (rid,))
        conn.commit()
    threads = [threading.Thread(target=runner.run_now, args=(rid,)) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert model.calls == 6
    # a crash: one row left "running" under a lease that has lapsed
    row = view["rows"][0]["row_id"]
    with connect() as conn:
        conn.execute("UPDATE tab_cells SET status = 'running', answer = NULL WHERE row_id = %s", (row,))
        conn.execute("UPDATE tab_rows SET lease_owner = 'dead', lease_until = now() - interval '1 minute' WHERE row_id = %s", (row,))
        conn.commit()
        assert runner.needs_workers(conn, rid)
    runner.run_now(rid)
    view = _ok(client.get(f"/api/tabular/reviews/{rid}", headers=as_member(cast["outsider"])))
    assert all(c["status"] == "done" for c in view["cells"]) and model.calls == 7


def test_changing_a_question_makes_its_answers_stale_but_keeps_lawyer_answers(client, cast, made, model, reviews):
    pid = _project(client, cast["outsider"], made)["project_id"]
    doc, _, _ = _upload(client, cast["outsider"], made, kind="project", cid=pid)
    view = _review(client, cast["outsider"], reviews, title="Q", kind="project", id=pid, document_ids=[doc],
                   columns=[{"preset": "term"}, {"preset": "governing_law"}])
    rid = view["review_id"]
    h = as_member(cast["outsider"])
    term, law = view["columns"][0]["column_id"], view["columns"][1]["column_id"]
    row = view["rows"][0]["row_id"]
    _ok(client.patch(f"/api/tabular/reviews/{rid}/cells/{row}/{law}", json={"answer": "English law"}, headers=h))
    _ok(client.patch(f"/api/tabular/reviews/{rid}/columns/{law}", json={"question": "Which law and which courts?"}, headers=h))
    _ok(client.patch(f"/api/tabular/reviews/{rid}/columns/{term}", json={"label": "Duration"}, headers=h))  # a rename only
    view = _ok(client.get(f"/api/tabular/reviews/{rid}", headers=h))
    cells = _cells(view)
    assert cells[(row, law)]["answer"] == "English law" and cells[(row, law)]["edited"]
    assert cells[(row, term)]["status"] == "done"
    _ok(client.patch(f"/api/tabular/reviews/{rid}/columns/{term}", json={"question": "How long does it last?"}, headers=h))
    assert _cells(_ok(client.get(f"/api/tabular/reviews/{rid}", headers=h)))[(row, term)]["status"] == "stale"
    _ok(client.post(f"/api/tabular/reviews/{rid}/run", json={"scope": "open"}, headers=h))
    cells = _cells(_ok(client.get(f"/api/tabular/reviews/{rid}", headers=h)))
    assert cells[(row, term)]["status"] == "done" and cells[(row, law)]["answer"] == "English law"
    # clearing the lawyer's answer puts the model's back
    _ok(client.patch(f"/api/tabular/reviews/{rid}/cells/{row}/{law}", json={"answer": None}, headers=h))
    assert not _cells(_ok(client.get(f"/api/tabular/reviews/{rid}", headers=h)))[(row, law)]["edited"]


def test_viewers_never_see_answers_drawn_from_documents_they_cannot_read(client, cast, made, model, reviews):
    wall = cast["wall"]
    pid = _project(client, cast["insider"], made)["project_id"]
    _ok(client.put(f"/api/projects/{pid}/members", json={"principal_id": cast["outsider"], "role": "viewer"},
                   headers=as_member(cast["insider"])))
    _ok(client.post(f"/api/workspaces/documents/{wall.document_id}/links", json={"kind": "project", "id": pid},
                    headers=as_member(cast["insider"])), 201)
    own, _, _ = _upload(client, cast["insider"], made, kind="project", cid=pid)
    view = _review(client, cast["insider"], reviews, title="Mixed", kind="project", id=pid,
                   document_ids=[wall.document_id, own], columns=[{"preset": "parties"}])
    rid = view["review_id"]
    seen = _ok(client.get(f"/api/tabular/reviews/{rid}", headers=as_member(cast["outsider"])))
    walled = next(r for r in seen["rows"] if r["restricted"])
    assert walled["document_id"] is None and walled["title"] is None
    hidden = [c for c in seen["cells"] if c["row_id"] == walled["row_id"]]
    assert hidden and all(c["restricted"] and "answer" not in c for c in hidden)
    assert wall.title not in json.dumps(seen)
    compact = _ok(client.get(f"/api/tabular/reviews/{rid}/cells", headers=as_member(cast["outsider"])))
    assert all(c["document_id"] != wall.document_id for c in compact["cells"]) and len(compact["cells"]) == 1
    # a viewer cannot change the review
    assert client.post(f"/api/tabular/reviews/{rid}/run", json={"scope": "all"}, headers=as_member(cast["outsider"])).status_code == 403
    # the export is redacted the same way
    x = client.get(f"/api/tabular/reviews/{rid}/export.xlsx", headers=as_member(cast["outsider"]))
    wb = openpyxl.load_workbook(io.BytesIO(x.content))
    flat = json.dumps([[c.value for c in r] for ws in wb.worksheets for r in ws.iter_rows()], default=str)
    assert "Restricted document" in flat and wall.title not in flat and wall.document_id not in flat


def test_a_run_never_reads_what_its_runner_cannot(client, cast, made, model, reviews):
    """Started by someone who cannot read a linked walled document: that row fails, the model never sees it."""
    wall = cast["wall"]
    pid = _project(client, cast["insider"], made)["project_id"]
    _ok(client.put(f"/api/projects/{pid}/members", json={"principal_id": cast["outsider"], "role": "editor"},
                   headers=as_member(cast["insider"])))
    _ok(client.post(f"/api/workspaces/documents/{wall.document_id}/links", json={"kind": "project", "id": pid},
                    headers=as_member(cast["insider"])), 201)
    view = _review(client, cast["insider"], reviews, title="Insider's", kind="project", id=pid,
                   document_ids=[wall.document_id], columns=[{"preset": "parties"}], run=False)
    calls = model.calls
    _ok(client.post(f"/api/tabular/reviews/{view['review_id']}/run", json={"scope": "all"}, headers=as_member(cast["outsider"])))
    assert model.calls == calls
    with connect() as conn:
        cell = conn.execute("SELECT c.status, c.error FROM tab_cells c JOIN tab_rows r USING (row_id) WHERE r.review_id = %s",
                            (view["review_id"],)).fetchone()
    assert cell["status"] == "failed" and "cannot read" in cell["error"]


def test_folder_rows_answer_from_the_documents_in_the_folder(client, cast, made, model, reviews):
    pid = _project(client, cast["outsider"], made)["project_id"]
    d1, _, _ = _upload(client, cast["outsider"], made, kind="project", cid=pid, folder="Leases/Unit 4", body=b"E2E-TMP Unit four rent is due quarterly in advance.")
    _upload(client, cast["outsider"], made, kind="project", cid=pid, folder="Other", body=b"E2E-TMP unrelated memo text here.")
    view = _review(client, cast["outsider"], reviews, title="By folder", kind="project", id=pid, group_by="folder",
                   folders=["Leases"], columns=[{"label": "Rent", "question": "When is rent due?"}])
    view = _ok(client.get(f"/api/tabular/reviews/{view['review_id']}", headers=as_member(cast["outsider"])))
    assert view["rows"][0]["kind"] == "folder" and view["rows"][0]["folder_path"] == "Leases"
    cell = view["cells"][0]
    assert cell["status"] == "done" and cell["citations"][0]["document_id"] == d1


def test_reviews_follow_workspace_access_and_validate_input(client, cast, made, model, reviews):
    pid = _project(client, cast["outsider"], made)["project_id"]
    h = as_member(cast["outsider"])
    bad = client.post("/api/tabular/reviews", json={"title": "x", "kind": "project", "id": pid, "columns": []}, headers=h)
    assert bad.status_code == 422
    bad = client.post("/api/tabular/reviews", json={"title": "x", "kind": "project", "id": pid,
                                                    "columns": [{"label": "c", "question": "q", "answer_format": "choice", "choices": ["a"]}]}, headers=h)
    assert bad.status_code == 422
    view = _review(client, cast["outsider"], reviews, title="Mine", kind="project", id=pid, columns=[{"preset": "parties"}])
    assert client.get(f"/api/tabular/reviews/{view['review_id']}", headers=as_member(cast["stranger"])).status_code == 404
    listed = _ok(client.get("/api/tabular/reviews", params={"kind": "project", "id": pid}, headers=h))["items"]
    assert [x["review_id"] for x in listed] == [view["review_id"]]
    assert client.get("/api/tabular/reviews", params={"kind": "project", "id": pid}, headers=as_member(cast["stranger"])).status_code == 404
    _ok(client.delete(f"/api/tabular/reviews/{view['review_id']}", headers=h))
    assert _ok(client.get("/api/tabular/reviews", params={"kind": "project", "id": pid}, headers=h))["items"] == []
