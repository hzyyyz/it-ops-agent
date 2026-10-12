"""The small web UI uses safe same-origin APIs."""

import json

from fastapi.testclient import TestClient


def test_knowledge_api_upload_list_delete_and_sync(monkeypatch, tmp_path):
    from backend.main import app
    from backend.api.knowledge import get_knowledge_service
    from backend.services.knowledge_service import KnowledgeService

    calls = []
    service = KnowledgeService(tmp_path, sync=lambda: calls.append("sync") or {
        "added": 1, "kept": 0, "deleted": 0, "failed": 0})
    app.dependency_overrides[get_knowledge_service] = lambda: service
    try:
        with TestClient(app) as client:
            response = client.put("/api/knowledge/故障指南.txt", content="Redis OOM".encode(),
                                  headers={"content-type": "application/octet-stream"})
            assert response.status_code == 200
            assert response.json()["name"] == "故障指南.txt"
            listed = client.get("/api/knowledge").json()
            assert [item["name"] for item in listed] == ["故障指南.txt"]
            assert listed[0]["size_bytes"] == len("Redis OOM".encode())
            assert listed[0]["updated_at"]
            assert client.post("/api/knowledge/sync").json()["added"] == 1
            assert client.delete("/api/knowledge/故障指南.txt").status_code == 204
            assert client.get("/api/knowledge").json() == []
            assert calls == ["sync", "sync", "sync"]
    finally:
        app.dependency_overrides.clear()


def test_original_multipart_upload_endpoint_uses_same_knowledge_service(tmp_path):
    from backend.main import app
    from backend.api.knowledge import get_knowledge_service
    from backend.services.knowledge_service import KnowledgeService

    app.dependency_overrides[get_knowledge_service] = lambda: KnowledgeService(
        tmp_path, lambda: {"added": 1, "kept": 0, "deleted": 0, "failed": 0})
    try:
        with TestClient(app) as client:
            result = client.post("/api/knowledge/upload", files={
                "file": ("new.txt", b"hello", "text/plain")})
            assert result.status_code == 200
            assert result.json()["name"] == "new.txt"
            assert (tmp_path / "new.txt").read_bytes() == b"hello"
    finally:
        app.dependency_overrides.clear()


def test_knowledge_api_rejects_invalid_names_and_large_content(monkeypatch, tmp_path):
    from backend.main import app
    from backend.api.knowledge import get_knowledge_service
    from backend.services.knowledge_service import KnowledgeService

    service = KnowledgeService(tmp_path, sync=lambda: {}, max_bytes=4)
    app.dependency_overrides[get_knowledge_service] = lambda: service
    try:
        with TestClient(app) as client:
            assert client.put("/api/knowledge/file.md", content=b"abc").status_code == 400
            assert client.put("/api/knowledge/%5Csecret.txt", content=b"abc").status_code == 400
            assert client.put("/api/knowledge/CON.txt", content=b"abc").status_code == 400
            assert client.put("/api/knowledge/bad%3Aname.txt", content=b"abc").status_code == 400
            assert client.put("/api/knowledge/.hidden.txt", content=b"abc").status_code == 400
            assert client.put("/api/knowledge/file.txt", content=b"12345").status_code == 413
            assert client.put("/api/knowledge/file.txt", content=b"").status_code == 400
            assert list(tmp_path.iterdir()) == []
    finally:
        app.dependency_overrides.clear()


def test_knowledge_api_reports_sync_failure_and_keeps_file_for_retry(tmp_path):
    from backend.main import app
    from backend.api.knowledge import get_knowledge_service
    from backend.services.knowledge_service import KnowledgeService

    outcomes = iter([{"failed": 1}, {"added": 1, "kept": 0, "deleted": 0, "failed": 0}])
    service = KnowledgeService(tmp_path, sync=lambda: next(outcomes))
    app.dependency_overrides[get_knowledge_service] = lambda: service
    try:
        with TestClient(app) as client:
            response = client.put("/api/knowledge/retry.txt", content=b"retry me")
            assert response.status_code == 503
            assert (tmp_path / "retry.txt").read_bytes() == b"retry me"
            assert client.post("/api/knowledge/sync").status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_trace_api_exposes_only_metadata(monkeypatch, tmp_path):
    from backend.main import app

    trace_id = "a" * 32
    trace_file = tmp_path / "traces.jsonl"
    trace_file.write_text(json.dumps({"trace_id": trace_id, "event": "tool.end",
                                      "tool_name": "get_cpu_usage", "duration_ms": 12,
                                      "private_answer": "secret", "timestamp": "2026-10-11T00:00:00Z"}) + "\n",
                          encoding="utf-8")
    monkeypatch.setenv("AGENT_TRACE_FILE", str(trace_file))
    with TestClient(app) as client:
        response = client.get(f"/api/traces/{trace_id}")
        assert response.status_code == 200
        assert response.json()["events"][0]["tool_name"] == "get_cpu_usage"
        assert "secret" not in response.text
        assert client.get("/api/traces/not-valid").status_code == 422


def test_web_ui_is_served_by_fastapi():
    from backend.main import app

    with TestClient(app) as client:
        page = client.get("/ui/")
        assert page.status_code == 200
        assert "IT 运维助手" in page.text
        assert 'id="auth-form"' in page.text
        assert client.get("/ui/app.js").status_code == 200
        assert client.get("/ui/styles.css").status_code == 200
