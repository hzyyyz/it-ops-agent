"""Redis accelerates recent context; MySQL remains authoritative."""

from sqlalchemy import create_engine, event, update
from sqlalchemy.orm import Session
from tests.test_sessions_api import session_api  # noqa: F401 - shared API fixture


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.ttls = {}
        self.deleted = []
        self.get_calls = 0

    def get(self, key):
        self.get_calls += 1
        return self.values.get(key)

    def setex(self, key, ttl, value):
        self.values[key] = value
        self.ttls[key] = ttl

    def delete(self, key):
        self.deleted.append(key)
        self.values.pop(key, None)


def seed(engine):
    from backend.models import Conversation, Message

    with Session(engine) as db:
        conversation = Conversation(title="first")
        db.add(conversation)
        db.flush()
        db.add_all([Message(session_id=conversation.id, role="user", content="first"),
                    Message(session_id=conversation.id, role="assistant", content="reply")])
        db.commit()
        return conversation.id


def make_engine():
    from backend.database import Base
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return engine


def test_recent_history_cache_uses_30_minute_ttl_and_rejects_corrupt_entries():
    from backend.cache import RecentHistoryCache

    redis = FakeRedis()
    cache = RecentHistoryCache(redis)
    history = [{"role": "user", "content": "private"}]
    cache.set("session-id", 3, history)
    key = "session:session-id:messages"
    assert redis.ttls[key] == 1800
    assert cache.get("session-id", 3) == history
    assert cache.get("session-id", 4) is None
    redis.values[key] = "not-json"
    assert cache.get("session-id", 3) is None


def test_prepare_chat_uses_cache_after_first_mysql_read():
    from backend.cache import RecentHistoryCache
    from backend.services.session_service import SessionService

    engine = make_engine()
    sid = seed(engine)
    cache = RecentHistoryCache(FakeRedis())
    message_selects = []

    def count_query(conn, cursor, statement, parameters, context, executemany):
        if "FROM messages" in statement:
            message_selects.append(statement)

    event.listen(engine, "before_cursor_execute", count_query)
    try:
        with Session(engine) as db:
            service = SessionService(db, cache=cache)
            first = service.prepare_chat(sid)
            second = service.prepare_chat(sid)
        assert first == second == ([{"role": "user", "content": "first"},
                                    {"role": "assistant", "content": "reply"}], 0)
        assert len(message_selects) == 1
    finally:
        event.remove(engine, "before_cursor_execute", count_query)
        engine.dispose()


def test_cache_io_does_not_hold_mysql_read_transaction():
    from backend.services.session_service import SessionService

    engine = make_engine()
    sid = seed(engine)
    with Session(engine) as db:
        class CheckingCache:
            def get(self, session_id, version):
                assert not db.in_transaction()
                return None

            def set(self, session_id, version, history):
                assert not db.in_transaction()

        history, version = SessionService(db, cache=CheckingCache()).prepare_chat(sid)
    assert version == 0
    assert len(history) == 2
    engine.dispose()


def test_cache_miss_rechecks_mysql_version_before_loading_messages():
    from backend.models import Conversation, Message
    from backend.services.session_service import SessionService

    engine = make_engine()
    sid = seed(engine)
    with Session(engine) as db:
        class ChangingCache:
            def get(self, session_id, version):
                assert version == 0
                with Session(engine) as other:
                    other.execute(update(Conversation).where(Conversation.id == sid).values(version=1))
                    other.add_all([Message(session_id=sid, role="user", content="second"),
                                   Message(session_id=sid, role="assistant", content="new reply")])
                    other.commit()
                return None

            def set(self, session_id, version, history):
                assert version == 1

        history, version = SessionService(db, cache=ChangingCache()).prepare_chat(sid)
    assert version == 1
    assert history[-1]["content"] == "new reply"
    engine.dispose()


def test_mysql_version_change_forces_refresh_of_stale_cache():
    from backend.cache import RecentHistoryCache
    from backend.models import Conversation, Message
    from backend.services.session_service import SessionService

    engine = make_engine()
    sid = seed(engine)
    cache = RecentHistoryCache(FakeRedis())
    with Session(engine) as db:
        assert SessionService(db, cache=cache).prepare_chat(sid)[1] == 0
    with Session(engine) as db:
        db.execute(update(Conversation).where(Conversation.id == sid).values(version=1))
        db.add_all([Message(session_id=sid, role="user", content="second"),
                    Message(session_id=sid, role="assistant", content="new reply")])
        db.commit()
    with Session(engine) as db:
        history, version = SessionService(db, cache=cache).prepare_chat(sid)
    assert version == 1
    assert [row["content"] for row in history] == ["first", "reply", "second", "new reply"]
    engine.dispose()


def test_successful_save_and_delete_invalidate_cache():
    from backend.cache import RecentHistoryCache
    from backend.services.session_service import SessionService

    engine = make_engine()
    sid = seed(engine)
    redis = FakeRedis()
    cache = RecentHistoryCache(redis)
    with Session(engine) as db:
        service = SessionService(db, cache=cache)
        _, version = service.prepare_chat(sid)
        service.save_chat("second", sid, version, "new reply")
        assert redis.deleted == [f"session:{sid}:messages"]
        history, version = service.prepare_chat(sid)
        assert version == 1
        assert history[-1]["content"] == "new reply"
        service.delete(sid)
    assert redis.deleted == [f"session:{sid}:messages"] * 2
    assert cache.get(sid, 1) is None
    engine.dispose()


def test_redis_failure_does_not_prevent_mysql_chat_or_delete():
    from backend.cache import RecentHistoryCache
    from backend.services.session_service import SessionService

    class BrokenRedis:
        def get(self, key):
            raise OSError("secret redis host")

        def setex(self, key, ttl, value):
            raise OSError("secret redis host")

        def delete(self, key):
            raise OSError("secret redis host")

    engine = make_engine()
    sid = seed(engine)
    cache = RecentHistoryCache(BrokenRedis())
    with Session(engine) as db:
        service = SessionService(db, cache=cache)
        history, version = service.prepare_chat(sid)
        assert len(history) == 2
        service.save_chat("second", sid, version, "new reply")
        assert len(service.detail(sid).messages) == 4
        service.delete(sid)
    engine.dispose()


def test_http_and_sse_chat_share_recent_context_cache(monkeypatch, session_api):
    from backend.cache import RecentHistoryCache
    from backend.services import session_service

    redis = FakeRedis()
    cache = RecentHistoryCache(redis)
    monkeypatch.setattr(session_service, "get_recent_history_cache", lambda: cache)
    client, calls, _ = session_api
    first = client.post("/api/chat", json={"message": "first"}).json()
    sid = first["session_id"]
    stream = client.post("/api/chat/stream", json={"message": "second", "session_id": sid})
    assert stream.status_code == 200
    assert 'event: done' in stream.text
    assert len(calls[-1][1]) == 2
    assert redis.get_calls >= 1
    assert client.post("/api/chat", json={"message": "third", "session_id": sid}).status_code == 200
    assert len(calls[-1][1]) == 4
    assert client.get(f"/api/sessions/{sid}").status_code == 200
