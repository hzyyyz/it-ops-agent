from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session


def test_init_db_upgrades_old_sessions_without_erasing_messages(monkeypatch, tmp_path):
    from backend import init_db
    from backend.models import Conversation, DocumentRecord, EvaluationResult, User

    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE sessions (id VARCHAR(36) PRIMARY KEY, title VARCHAR(100), created_at DATETIME, updated_at DATETIME, version INTEGER)"))
        connection.execute(text("CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id VARCHAR(36), role VARCHAR(16), content TEXT, created_at DATETIME)"))
        connection.execute(text("INSERT INTO sessions (id,title,version) VALUES ('old','existing',0)"))
        connection.execute(text("INSERT INTO messages (id,session_id,role,content) VALUES (1,'old','user','keep me')"))
    monkeypatch.setattr(init_db, "get_engine", lambda: engine)
    monkeypatch.setattr(init_db, "_existing_knowledge_documents", lambda: [
        {"name": "existing.txt", "size_bytes": 7, "updated_at": "2026-01-01T00:00:00+00:00"}])

    init_db.main()
    init_db.main()

    tables = set(inspect(engine).get_table_names())
    assert {User.__tablename__, DocumentRecord.__tablename__, EvaluationResult.__tablename__} <= tables
    assert "user_id" in {column["name"] for column in inspect(engine).get_columns("sessions")}
    with Session(engine) as db:
        assert db.get(User, "local-admin").username == "admin"
        assert db.get(DocumentRecord, "existing.txt").index_status == "pending"
        assert db.execute(text("SELECT COUNT(*) FROM documents")).scalar_one() == 1
        assert db.get(Conversation, "old").user_id == "local-admin"
        assert db.execute(text("SELECT content FROM messages WHERE id=1")).scalar_one() == "keep me"
