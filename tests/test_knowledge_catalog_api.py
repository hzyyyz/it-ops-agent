from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def test_knowledge_upload_and_delete_update_document_table(tmp_path):
    from backend.database import Base, get_db
    from backend.main import app
    from backend.api.knowledge import get_knowledge_service, get_document_catalog
    from backend.models import DocumentRecord
    from backend.services.knowledge_service import KnowledgeService

    engine = create_engine(f"sqlite:///{tmp_path / 'meta.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)

    def database():
        with Session(engine) as db:
            yield db

    app.dependency_overrides.pop(get_document_catalog, None)
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_knowledge_service] = lambda: KnowledgeService(
        tmp_path / "data", lambda: {"added": 1, "kept": 0, "deleted": 0, "failed": 0})
    try:
        with TestClient(app) as client:
            assert client.put("/api/knowledge/guide.txt", content=b"hello").status_code == 200
            with Session(engine) as db:
                row = db.get(DocumentRecord, "guide.txt")
                assert (row.size_bytes, row.index_status) == (5, "ready")
            assert client.delete("/api/knowledge/guide.txt").status_code == 204
            with Session(engine) as db:
                assert db.get(DocumentRecord, "guide.txt") is None
    finally:
        app.dependency_overrides.clear()
