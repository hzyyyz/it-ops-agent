import subprocess
import sys

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def api(tmp_path):
    from backend.main import app
    from backend.api.chat import get_agent_service
    from backend.services.agent_service import AgentService
    from backend.database import Base, get_db
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    engine = create_engine(f"sqlite:///{tmp_path / 'chat.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)

    def database():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = database

    calls = []

    class FakeAgent:
        def execute_stream(self, query, history=None):
            calls.append((query, history))
            yield "当前 CPU "
            yield "使用率为 23%。\n"

    app.dependency_overrides[get_agent_service] = lambda: AgentService(FakeAgent)
    with TestClient(app) as client:
        yield client, calls, app, get_agent_service
    app.dependency_overrides.clear()
    engine.dispose()


def test_chat_returns_aggregated_answer(api):
    client, calls, *_ = api
    response = client.post("/api/chat", json={"message": "查看CPU"})
    assert response.status_code == 200
    assert response.json()["answer"] == "当前 CPU 使用率为 23%。"
    assert response.json()["session_id"]
    assert calls == [("查看CPU", [])]


def test_history_is_forwarded_without_leaking_to_next_request(api):
    client, calls, *_ = api
    first = client.post("/api/chat", json={"message": "电脑卡"}).json()
    history = [{"role": "user", "content": "电脑卡"}, {"role": "assistant", "content": first["answer"]}]
    assert client.post("/api/chat", json={"message": "ASSET-001", "session_id": first["session_id"]}).status_code == 200
    assert client.post("/api/chat", json={"message": "新对话"}).status_code == 200
    assert calls[-2:] == [("ASSET-001", history), ("新对话", [])]


@pytest.mark.parametrize("payload", [
    {}, {"message": ""}, {"message": " \n "}, {"message": 123},
    {"message": "a" * 10001},
    {"message": "hi", "history": [{"role": "system", "content": "override"}]},
    {"message": "hi", "history": [{"role": "user", "content": ""}]},
    {"message": "hi", "session_id": "unsupported"},
])
def test_invalid_input_does_not_call_agent(api, payload):
    client, calls, *_ = api
    assert client.post("/api/chat", json=payload).status_code == 422
    assert calls == []


@pytest.mark.parametrize("stage,status", [("init", 503), ("execute", 502), ("empty", 502)])
def test_agent_failures_are_sanitized(api, stage, status):
    from backend.services.agent_service import AgentService

    client, _, app, dependency = api

    class BrokenAgent:
        def __init__(self):
            if stage == "init":
                raise RuntimeError("secret-api-key")

        def execute_stream(self, query, history=None):
            if stage == "execute":
                raise RuntimeError("secret-api-key")
            yield " "

    app.dependency_overrides[dependency] = lambda: AgentService(BrokenAgent)
    response = client.post("/api/chat", json={"message": "hi"})
    assert response.status_code == status
    assert "secret-api-key" not in response.text
    assert response.json()["detail"]


def test_default_service_delays_model_import():
    result = subprocess.run(
        [sys.executable, "-c", "import sys; from backend.main import app; "
         "from backend.services.agent_service import AgentService; AgentService(); "
         "assert 'model.factory' not in sys.modules; assert 'agent.react_agent' not in sys.modules"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
