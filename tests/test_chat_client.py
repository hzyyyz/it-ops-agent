import json

import httpx
import pytest


def test_client_sends_message_and_history(monkeypatch):
    from frontend.chat_client import request_chat

    monkeypatch.setenv("AGENT_API_URL", "http://backend:8000/")
    sid = "2f37f9c7-233b-4f09-a46f-000000000001"

    def handler(request):
        assert str(request.url) == "http://backend:8000/api/chat"
        assert json.loads(request.content) == {"message": "hi", "session_id": sid}
        return httpx.Response(200, json={"answer": "你好", "session_id": sid})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert request_chat("hi", sid, client=client) == {"answer": "你好", "session_id": sid}


def test_client_sends_admin_token_for_json_and_stream(monkeypatch):
    from frontend.chat_client import request_chat, request_chat_stream

    monkeypatch.setenv("AGENT_ADMIN_TOKEN", "local-admin-secret")
    sid = "2f37f9c7-233b-4f09-a46f-000000000001"

    def handler(request):
        assert request.headers["authorization"] == "Bearer local-admin-secret"
        if request.url.path.endswith("/stream"):
            return httpx.Response(200, text=(
                'event: delta\ndata: {"text":"好"}\n\n'
                f'event: done\ndata: {{"answer":"好","session_id":"{sid}"}}\n\n'),
                headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json={"answer": "好", "session_id": sid})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert request_chat("hi", client=client)["answer"] == "好"
        assert list(request_chat_stream("hi", client=client)) == ["好"]


@pytest.mark.parametrize("failure", ["timeout", "connect", "status", "json", "missing", "empty"])
def test_client_reports_safe_actionable_errors(failure):
    from frontend.chat_client import ChatAPIError, request_chat

    def handler(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("secret", request=request)
        if failure == "connect":
            raise httpx.ConnectError("secret", request=request)
        if failure == "status":
            return httpx.Response(503, text="secret")
        if failure == "json":
            return httpx.Response(200, text="not-json")
        return httpx.Response(200, json={} if failure == "missing" else {"answer": " "})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ChatAPIError) as exc:
            request_chat("hi", client=client)
    assert str(exc.value)
    assert "secret" not in str(exc.value)


def test_invalid_backend_url_reports_configuration_error(monkeypatch):
    from frontend.chat_client import ChatAPIError, request_chat

    monkeypatch.setenv("AGENT_API_URL", "http://localhost:bad")
    with pytest.raises(ChatAPIError, match="AGENT_API_URL"):
        request_chat("hi")


def test_session_client_operations():
    from frontend.chat_client import list_sessions, get_session, delete_session

    sid = "2f37f9c7-233b-4f09-a46f-000000000001"
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path))
        if request.method == "DELETE":
            return httpx.Response(204)
        if request.url.path.endswith(sid):
            return httpx.Response(200, json={"id": sid, "title": "对话", "messages": [{"role": "user", "content": "hi"}]})
        assert request.url.params["offset"] == "20"
        return httpx.Response(200, json=[{"id": sid, "title": "对话"}])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert list_sessions(offset=20, client=client)[0]["id"] == sid
        assert get_session(sid, client=client)["messages"][0]["content"] == "hi"
        assert delete_session(sid, client=client) is None
    assert seen == [("GET", "/api/sessions"), ("GET", f"/api/sessions/{sid}"), ("DELETE", f"/api/sessions/{sid}")]


def test_stream_client_yields_deltas_and_session_id():
    from frontend.chat_client import request_chat_stream

    sid = "2f37f9c7-233b-4f09-a46f-000000000001"
    body = (f'event: delta\ndata: {{"text":"你"}}\n\n'
            f'event: delta\ndata: {{"text":"好"}}\n\n'
            f'event: done\ndata: {{"answer":"你好","session_id":"{sid}"}}\n\n')

    def handler(request):
        assert request.url.path == "/api/chat/stream"
        assert request.headers["accept"] == "text/event-stream"
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        stream = request_chat_stream("hi", client=client)
        assert list(stream) == ["你", "好"]
        assert stream.session_id == sid


@pytest.mark.parametrize("body", [
    'event: delta\ndata: {"text":"partial"}\n\n',
    'event: error\ndata: {"code":"agent_error","message":"请重试"}\n\n',
])
def test_stream_client_rejects_incomplete_or_error(body):
    from frontend.chat_client import ChatAPIError, request_chat_stream

    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(
            200, text=body, headers={"content-type": "text/event-stream"}))) as client:
        with pytest.raises(ChatAPIError):
            list(request_chat_stream("hi", client=client))
