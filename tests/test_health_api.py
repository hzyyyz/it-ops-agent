from fastapi.testclient import TestClient


def test_health_reports_readiness_without_loading_agent():
    from backend.main import app
    from backend.api.health import get_health_checks

    app.dependency_overrides[get_health_checks] = lambda: {
        "mysql": lambda: True,
        "redis": lambda: True,
        "knowledge": lambda: True,
    }
    try:
        with TestClient(app) as client:
            response = client.get("/api/health")
            assert response.status_code == 200
            assert response.json() == {"status": "ok", "checks": {
                "mysql": "ok", "redis": "ok", "knowledge": "ok"}}
    finally:
        app.dependency_overrides.clear()


def test_health_returns_503_for_required_dependency_failure():
    from backend.main import app
    from backend.api.health import get_health_checks

    def offline():
        raise RuntimeError("private database URL")

    app.dependency_overrides[get_health_checks] = lambda: {
        "mysql": offline,
        "redis": lambda: None,
        "knowledge": lambda: True,
    }
    try:
        with TestClient(app) as client:
            response = client.get("/api/health")
            assert response.status_code == 503
            assert response.json() == {"status": "degraded", "checks": {
                "mysql": "error", "redis": "disabled", "knowledge": "ok"}}
            assert "private" not in response.text
    finally:
        app.dependency_overrides.clear()


def test_redis_failure_is_reported_without_marking_api_unavailable():
    from backend.main import app
    from backend.api.health import get_health_checks

    def offline():
        raise RuntimeError("Redis offline")

    app.dependency_overrides[get_health_checks] = lambda: {
        "mysql": lambda: True, "redis": offline, "knowledge": lambda: True,
    }
    try:
        with TestClient(app) as client:
            response = client.get("/api/health")
            assert response.status_code == 200
            assert response.json()["status"] == "degraded"
            assert response.json()["checks"]["redis"] == "error"
    finally:
        app.dependency_overrides.clear()
