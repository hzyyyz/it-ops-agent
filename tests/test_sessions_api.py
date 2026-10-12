from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def session_api(tmp_path):
    from backend.database import Base, get_db
    from backend.main import app
    from backend.api.chat import get_agent_service
    from backend.services.agent_service import AgentService
    from backend.models import Conversation, Message

    engine = create_engine(f"sqlite:///{tmp_path / 'sessions.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    calls = []

    def database():
        with factory() as db:
            yield db

    class FakeAgent:
        def execute_stream(self, query, history=None):
            calls.append((query, history))
            yield "回答：" + query

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_agent_service] = lambda: AgentService(FakeAgent)
    with TestClient(app) as client:
        yield client, calls, factory
    app.dependency_overrides.clear()
    engine.dispose()


def test_chat_creates_persisted_session_and_continues(session_api):
    client, calls, factory = session_api
    response = client.post("/api/chat", json={"message": "设备故障"})
    assert response.status_code == 200
    sid = response.json()["session_id"]
    assert response.json()["answer"] == "回答：设备故障"
    assert calls == [("设备故障", [])]
    response = client.post("/api/chat", json={"message": "继续", "session_id": sid})
    assert response.status_code == 200
    assert response.json()["session_id"] == sid
    assert calls[-1][1] == [
        {"role": "user", "content": "设备故障"},
        {"role": "assistant", "content": "回答：设备故障"},
    ]
    from backend.models import Message
    from sqlalchemy import select
    # A separate connection sees committed data.
    with factory() as db:
        assert len(db.scalars(select(Message)).all()) == 4
    detail = client.get(f"/api/sessions/{sid}").json()
    assert detail["title"] == "设备故障"
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant", "user", "assistant"]
    assert detail["created_at"].endswith("Z")


def test_list_pagination_and_delete(session_api):
    client, *_ = session_api
    ids = [client.post("/api/chat", json={"message": text}).json()["session_id"] for text in ["first", "second"]]
    response = client.get("/api/sessions?limit=1")
    assert response.status_code == 200
    assert [s["id"] for s in response.json()] == [ids[1]]
    assert client.get("/api/sessions?limit=1&offset=1").json()[0]["id"] == ids[0]
    assert client.delete(f"/api/sessions/{ids[0]}").status_code == 204
    assert client.get(f"/api/sessions/{ids[0]}").status_code == 404
    from backend.models import Message
    from sqlalchemy import select
    with session_api[2]() as db:
        assert db.scalars(select(Message).where(Message.session_id == ids[0])).all() == []


def test_unknown_session_does_not_invoke_agent(session_api):
    client, calls, _ = session_api
    sid = str(uuid4())
    assert client.get(f"/api/sessions/{sid}").status_code == 404
    assert client.delete(f"/api/sessions/{sid}").status_code == 404
    assert client.post("/api/chat", json={"message": "hi", "session_id": sid}).status_code == 404
    assert calls == []


@pytest.mark.parametrize("payload", [
    {"message": "hi", "history": []}, {"message": "hi", "session_id": "bad"},
    {"message": " "}, {"message": 123}, {"message": "x" * 10001}, {},
])
def test_invalid_chat(session_api, payload):
    assert session_api[0].post("/api/chat", json=payload).status_code == 422
    assert session_api[1] == []


def test_failed_agent_does_not_save_partial_turn(session_api):
    from backend.api.chat import get_agent_service
    from backend.main import app
    from backend.services.agent_service import AgentService

    client, *_ = session_api
    sid = client.post("/api/chat", json={"message": "first"}).json()["session_id"]

    class BrokenAgent:
        def execute_stream(self, *args):
            raise RuntimeError("private")

    app.dependency_overrides[get_agent_service] = lambda: AgentService(BrokenAgent)
    for payload in [{"message": "fail"}, {"message": "fail", "session_id": sid}]:
        response = client.post("/api/chat", json=payload)
        assert response.status_code == 502
        assert "private" not in response.text
    assert len(client.get("/api/sessions").json()) == 1
    assert len(client.get(f"/api/sessions/{sid}").json()["messages"]) == 2


def test_concurrent_update_rejects_stale_answer(session_api):
    from backend.api.chat import get_agent_service
    from backend.main import app
    from backend.models import Conversation
    from backend.services.agent_service import AgentService
    from sqlalchemy import update

    client, _, factory = session_api
    sid = client.post("/api/chat", json={"message": "first"}).json()["session_id"]

    class RacingAgent:
        def execute_stream(self, *args):
            with factory() as other:
                other.execute(update(Conversation).where(Conversation.id == sid).values(version=Conversation.version + 1))
                other.commit()
            yield "stale answer"

    app.dependency_overrides[get_agent_service] = lambda: AgentService(RacingAgent)
    assert client.post("/api/chat", json={"message": "race", "session_id": sid}).status_code == 409
    assert len(client.get(f"/api/sessions/{sid}").json()["messages"]) == 2


def test_database_failure_before_generation_does_not_call_agent(session_api):
    from backend.database import get_db
    from backend.main import app
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import Session

    class OfflineDatabase(Session):
        def execute(self, *args, **kwargs):
            raise OperationalError("private SQL", {}, Exception("private password"))

    def offline_db():
        with OfflineDatabase(session_api[2].kw["bind"]) as db:
            yield db

    app.dependency_overrides[get_db] = offline_db
    response = session_api[0].post("/api/chat", json={"message": "hi"})
    assert response.status_code == 503
    assert "private" not in response.text
    assert session_api[1] == []


def test_database_failure_rolls_back_both_messages(session_api):
    from backend.database import get_db
    from backend.main import app
    from sqlalchemy.orm import Session
    from sqlalchemy.exc import OperationalError

    client, _, factory = session_api
    sid = client.post("/api/chat", json={"message": "first"}).json()["session_id"]

    class FailingCommitSession(Session):
        def commit(self):
            self.flush()
            raise OperationalError("commit", {}, Exception("storage failure"))

    def failing_db():
        with FailingCommitSession(factory.kw["bind"]) as db:
            yield db

    app.dependency_overrides[get_db] = failing_db
    assert client.post("/api/chat", json={"message": "second", "session_id": sid}).status_code == 503
    assert len(client.get(f"/api/sessions/{sid}").json()["messages"]) == 2


def test_deleted_during_generation_returns_404(session_api):
    from backend.main import app
    from backend.api.chat import get_agent_service
    from backend.models import Conversation
    from backend.services.agent_service import AgentService

    client, _, factory = session_api
    sid = client.post("/api/chat", json={"message": "first"}).json()["session_id"]

    class DeletingAgent:
        def execute_stream(self, *args):
            with factory() as other:
                other.delete(other.get(Conversation, sid))
                other.commit()
            yield "answer"

    app.dependency_overrides[get_agent_service] = lambda: AgentService(DeletingAgent)
    assert client.post("/api/chat", json={"message": "race", "session_id": sid}).status_code == 404
    assert client.get("/api/sessions").json() == []


def test_recent_context_limit_preserves_full_history(session_api):
    from backend.models import Conversation, Message

    client, calls, factory = session_api
    with factory() as db:
        conversation = Conversation(title="long conversation")
        db.add(conversation)
        db.flush()
        sid = conversation.id
        for index in range(102):
            db.add(Message(session_id=sid, role="user" if index % 2 == 0 else "assistant", content=str(index)))
        db.commit()
    assert client.post("/api/chat", json={"message": "next", "session_id": sid}).status_code == 200
    assert len(calls[-1][1]) == 100
    assert calls[-1][1][0] == {"role": "user", "content": "2"}
    assert calls[-1][1][-1] == {"role": "assistant", "content": "101"}
    assert len(client.get(f"/api/sessions/{sid}").json()["messages"]) == 104
