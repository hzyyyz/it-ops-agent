"""Opt-in MySQL verification. Initialize the dedicated application DB first.

Set RUN_MYSQL_INTEGRATION=1 and the MYSQL_* variables explicitly. This test
creates and deletes only its own session, never drops tables or clears history.
The Agent is simulated; no LLM credentials or outbound model call is needed.
"""
import os
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient


@pytest.mark.skipif(os.getenv("RUN_MYSQL_INTEGRATION") != "1", reason="MySQL integration is explicitly opt-in")
def test_mysql_persistence_across_process_and_delete():
    from backend.api.chat import get_agent_service
    from backend.main import app
    from backend.services.agent_service import AgentService

    calls = []

    class FakeAgent:
        def execute_stream(self, query, history=None):
            calls.append(history)
            yield "MySQL 验证回答 ✅"

    app.dependency_overrides[get_agent_service] = lambda: AgentService(FakeAgent)
    sid = None
    try:
        with TestClient(app) as client:
            response = client.post("/api/chat", json={"message": "MySQL 持久化验证 ✅"})
            assert response.status_code == 200, response.text
            sid = response.json()["session_id"]
            # A fresh Python process and fresh pool must see the committed pair.
            code = (
                "import sys; from sqlalchemy.orm import Session; "
                "from backend.database import get_engine; "
                "from backend.services.session_service import SessionService; "
                "db=Session(get_engine()); detail=SessionService(db).detail(sys.argv[1]); "
                "assert len(detail.messages)==2; db.close()"
            )
            result = subprocess.run([sys.executable, "-c", code, sid], capture_output=True, timeout=30)
            assert result.returncode == 0, "Separate process could not restore MySQL session"
            response = client.post("/api/chat", json={"message": "继续", "session_id": sid})
            assert response.status_code == 200, response.text
            assert len(calls[-1]) == 2
            detail = client.get(f"/api/sessions/{sid}")
            assert len(detail.json()["messages"]) == 4
            assert client.delete(f"/api/sessions/{sid}").status_code == 204
            assert client.get(f"/api/sessions/{sid}").status_code == 404
            sid = None
    finally:
        if sid:
            with TestClient(app) as cleanup:
                result = cleanup.delete(f"/api/sessions/{sid}")
                assert result.status_code in (204, 404), "Could not clean up integration test session"
        app.dependency_overrides.clear()
