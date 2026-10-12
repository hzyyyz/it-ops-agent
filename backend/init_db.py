"""Initialize tables and additively migrate an existing single-user MySQL database."""
from backend.database import Base, get_engine
from backend import models  # Register model metadata.
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session


def _existing_knowledge_documents() -> list[dict]:
    from pathlib import Path
    from backend.services.knowledge_service import KnowledgeService
    from utils.config_handler import chroma_conf
    from utils.path_tool import get_abs_path

    return KnowledgeService(Path(get_abs_path(chroma_conf["data_path"])), lambda: {}).list_documents()


def main():
    engine = get_engine()
    try:
        Base.metadata.create_all(engine)
        if "user_id" not in {column["name"] for column in inspect(engine).get_columns("sessions")}:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE sessions ADD COLUMN user_id VARCHAR(36) NULL"))
        if "ix_sessions_user_id" not in {index["name"] for index in inspect(engine).get_indexes("sessions")}:
            with engine.begin() as connection:
                connection.execute(text("CREATE INDEX ix_sessions_user_id ON sessions (user_id)"))
        with Session(engine) as db:
            if db.get(models.User, "local-admin") is None:
                db.add(models.User(id="local-admin", username="admin", role="admin"))
            for document in _existing_knowledge_documents():
                if db.get(models.DocumentRecord, document["name"]) is None:
                    from datetime import datetime, timezone
                    updated = datetime.fromisoformat(document["updated_at"])
                    if updated.tzinfo:
                        updated = updated.astimezone(timezone.utc).replace(tzinfo=None)
                    db.add(models.DocumentRecord(name=document["name"], size_bytes=document["size_bytes"],
                                                 updated_at=updated, index_status="pending"))
            db.execute(text("UPDATE sessions SET user_id = 'local-admin' WHERE user_id IS NULL"))
            db.commit()
        print("Database tables initialized: users, sessions, messages, documents, evaluation_results")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
