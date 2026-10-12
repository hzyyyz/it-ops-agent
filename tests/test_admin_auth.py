from fastapi.testclient import TestClient


def test_admin_token_is_required_on_data_apis_and_health_is_public(monkeypatch):
    from backend.main import app
    from backend.auth import require_admin

    app.dependency_overrides.pop(require_admin, None)
    monkeypatch.setenv("AGENT_ADMIN_TOKEN", "a" * 40)
    try:
        with TestClient(app) as client:
            assert client.get("/api/health").status_code != 401
            for path in ("/api/sessions", "/api/knowledge", "/api/traces/" + "b" * 32):
                response = client.get(path)
                assert response.status_code == 401
                assert "a" * 40 not in response.text
            assert client.post("/api/chat", json={"message": "hi"}).status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_admin_token_allows_protected_api(monkeypatch, tmp_path):
    from backend.main import app
    from backend.auth import require_admin
    from backend.api.knowledge import get_knowledge_service
    from backend.services.knowledge_service import KnowledgeService

    app.dependency_overrides.pop(require_admin, None)
    app.dependency_overrides[get_knowledge_service] = lambda: KnowledgeService(tmp_path, lambda: {})
    monkeypatch.setenv("AGENT_ADMIN_TOKEN", "z" * 40)
    try:
        with TestClient(app) as client:
            assert client.get("/api/knowledge", headers={"Authorization": "Bearer " + "z" * 40}).json() == []
            assert client.get("/api/knowledge", headers={"Authorization": "Bearer wrong"}).status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_missing_admin_token_fails_closed(monkeypatch):
    from backend.main import app
    from backend.auth import require_admin

    app.dependency_overrides.pop(require_admin, None)
    monkeypatch.setenv("AGENT_ADMIN_TOKEN", "")
    try:
        with TestClient(app) as client:
            response = client.get("/api/knowledge")
            assert response.status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_example_placeholder_cannot_authorize_requests(monkeypatch):
    from backend.main import app
    from backend.auth import require_admin

    app.dependency_overrides.pop(require_admin, None)
    placeholder = "replace-with-at-least-32-random-characters"
    monkeypatch.setenv("AGENT_ADMIN_TOKEN", placeholder)
    try:
        with TestClient(app) as client:
            response = client.get("/api/knowledge", headers={"Authorization": "Bearer " + placeholder})
            assert response.status_code == 503
    finally:
        app.dependency_overrides.clear()
