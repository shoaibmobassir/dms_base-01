from fastapi.testclient import TestClient

from app.api.main import app

HEADERS = {"X-Member-Id": "MEM-00001"}


def test_people_list() -> None:
    client = TestClient(app)
    resp = client.get("/api/people", headers=HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "people"
    assert len(body["items"]) > 0


def test_matters_acl() -> None:
    client = TestClient(app)
    resp = client.get("/api/matters?limit=5", headers=HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "matters"
    assert "items" in body
    assert "total" in body


def test_home_stats() -> None:
    client = TestClient(app)
    resp = client.get("/api/home/stats", headers=HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "home"
    assert body["counts"]["matters"] > 0


def test_documents_list() -> None:
    client = TestClient(app)
    resp = client.get("/api/documents?limit=5", headers=HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "documents"
    assert "items" in body


def test_document_detail_route() -> None:
    client = TestClient(app)
    resp = client.get("/api/documents/DOC-00001", headers=HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "documents"
    assert body["document_id"] == "DOC-00001"


def test_clients_list() -> None:
    client = TestClient(app)
    resp = client.get("/api/clients?limit=5", headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json()["service"] == "clients"


def test_projects_list() -> None:
    client = TestClient(app)
    resp = client.get("/api/projects?limit=5", headers=HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "projects"
    assert "items" in body


def test_teams_list() -> None:
    client = TestClient(app)
    resp = client.get("/api/teams", headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json()["service"] == "teams"


def test_knowledge_arguments() -> None:
    client = TestClient(app)
    resp = client.get("/api/knowledge/arguments?limit=5", headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json()["service"] == "knowledge"


def test_activity_feed() -> None:
    client = TestClient(app)
    resp = client.get("/api/activity?limit=5", headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json()["service"] == "activity"


def test_tasks_list() -> None:
    client = TestClient(app)
    resp = client.get("/api/tasks?limit=5", headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json()["service"] == "tasks"


def test_search() -> None:
    client = TestClient(app)
    resp = client.get("/api/search?q=indemnity&limit=5", headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json()["service"] == "search"


def test_answers_abstains_on_empty_query() -> None:
    client = TestClient(app)
    resp = client.post(
        "/api/answers",
        json={"query": "   ", "k": 5},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "answers"
    assert body["abstained"] is True


def test_answers_returns_dms_fields() -> None:
    client = TestClient(app)
    resp = client.post(
        "/api/answers",
        json={"query": "What indemnity cap clauses do we negotiate in M&A?", "k": 5},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "answers"
    assert "key_finding" in body
    assert "structured_citations" in body
    assert "sources" in body
    assert "matchedMatters" in body
    assert "tags" in body


def test_retrieval_returns_hits_envelope() -> None:
    client = TestClient(app)
    resp = client.post(
        "/api/retrieval",
        json={"query": "indemnity cap M&A", "k": 5},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "retrieval"
    assert "hits" in body
    assert "understanding" in body
    assert "total_hits" in body
