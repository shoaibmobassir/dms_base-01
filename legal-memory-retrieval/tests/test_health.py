from fastapi.testclient import TestClient

from app.api.main import SERVICE_CATALOG, app
from app.sprint import CURRENT_SPRINT


def test_health_sprint_property() -> None:
    client = TestClient(app)
    body = client.get("/api/system/health").json()
    assert body["sprint"] == CURRENT_SPRINT
    assert body["sprint"] == 9
    assert body["status"] == "ok"
    assert body["llm"] is True
    assert body["query_understanding"] is True
    assert body["graph"] is True
    assert body["engine_v2"] is True
    assert body["gateway"] == "lexos"
    root = client.get("/").json()
    assert root["sprint"] == 9
    assert "services" in root
    assert root["services"]["answers"]["prefix"] == "/api/answers"
    assert root["services"]["retrieval"]["prefix"] == "/api/retrieval"
    assert root["services"]["matters"]["prefix"] == "/api/matters"
    assert root["services"]["documents"]["prefix"] == "/api/documents"


def test_service_health_endpoints() -> None:
    client = TestClient(app)
    for name, meta in SERVICE_CATALOG.items():
        resp = client.get(meta["health"])
        assert resp.status_code == 200, f"{name} health failed"
        body = resp.json()
        assert body.get("status") == "ok" or body.get("service") == name


def test_architecture_and_info() -> None:
    client = TestClient(app)
    info = client.get("/api/system/info").json()
    assert info["use_engine_v2"] is True
    assert info["retrieval_engine"] == "v2"
    assert "retrieve_debug" in info["endpoints"]
    arch = client.get("/api/system/architecture")
    assert arch.status_code == 200
    assert "Parallel" in arch.text or "retrieval" in arch.text.lower()
