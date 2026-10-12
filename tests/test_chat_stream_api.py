import json

from backend.api.chat import get_agent_service
from backend.main import app
from backend.services.agent_service import AgentService
from tests.test_sessions_api import session_api  # noqa: F401 - fixture


def events(response):
    return [(name, json.loads(data)) for name, data in (
        (block.split("\n")[0][7:], block.split("\n")[1][6:])
        for block in response.text.strip().split("\n\n")
    )]


def test_stream_emits_deltas_then_committed_session(session_api):
    client, calls, _ = session_api
    response = client.post("/api/chat/stream", json={"message": "检查设备"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    received = events(response)
    assert received[0] == ("delta", {"text": "回答：检查设备"})
    assert received[-1][0] == "done"
    assert received[-1][1]["answer"] == "回答：检查设备"
    sid = received[-1][1]["session_id"]
    assert client.get(f"/api/sessions/{sid}").json()["messages"][-1]["content"] == "回答：检查设备"
    assert calls == [("检查设备", [])]


def test_stream_failure_sends_safe_error_without_saving(session_api):
    client, _, _ = session_api

    class BrokenAgent:
        def execute_stream(self, query, history=None):
            yield "partial"
            raise RuntimeError("private-key")

    app.dependency_overrides[get_agent_service] = lambda: AgentService(BrokenAgent)
    received = events(client.post("/api/chat/stream", json={"message": "hi"}))
    assert received[0] == ("delta", {"text": "partial"})
    assert received[-1][0] == "error"
    assert "private-key" not in str(received)
    assert client.get("/api/sessions").json() == []


def test_stream_invalid_session_is_404_before_start(session_api):
    from uuid import uuid4

    client, calls, _ = session_api
    response = client.post("/api/chat/stream", json={"message": "hi", "session_id": str(uuid4())})
    assert response.status_code == 404
    assert calls == []


def test_stream_save_exception_is_sanitized(monkeypatch, session_api):
    from backend.services.session_service import SessionService

    def broken_save(self, *args):
        raise RuntimeError("private-database-detail")

    monkeypatch.setattr(SessionService, "save_chat", broken_save)
    client, _, _ = session_api
    received = events(client.post("/api/chat/stream", json={"message": "hi"}))
    assert received[-1][0] == "error"
    assert "private-database-detail" not in str(received)
