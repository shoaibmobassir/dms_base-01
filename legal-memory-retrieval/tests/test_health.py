from fastapi.testclient import TestClient

from app.api.main import app
from app.sprint import CURRENT_SPRINT


def test_health_sprint_property() -> None:
    client = TestClient(app)
    body = client.get("/health").json()
    assert body["sprint"] == CURRENT_SPRINT
    assert body["sprint"] == 8
    assert body["status"] == "ok"
    assert body["llm"] is True
    assert body["query_understanding"] is True
    assert body["graph"] is True
    root = client.get("/").json()
    assert root["sprint"] == 8
    assert root["ask"] == "POST /ask"
