import os
import json
from collections.abc import Iterator
from uuid import UUID

import httpx


class ChatAPIError(Exception):
    """An actionable error safe to display in the frontend."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _request(method: str, path: str, *, client: httpx.Client | None = None, **kwargs):
    url = os.getenv("AGENT_API_URL", "http://127.0.0.1:8000").rstrip("/") + path
    headers = dict(kwargs.pop("headers", {}))
    if token := os.getenv("AGENT_ADMIN_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    timeout = httpx.Timeout(120.0, connect=5.0)
    try:
        if client is None:
            with httpx.Client() as owned_client:
                response = owned_client.request(method, url, timeout=timeout, headers=headers, **kwargs)
        else:
            response = client.request(method, url, timeout=timeout, headers=headers, **kwargs)
        response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise ChatAPIError("请求超时，请稍后重试；复杂报告可能需要更长时间。") from exc
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        detail = {
            422: "输入不符合要求，请检查问题长度和会话编号。",
            404: "会话不存在或已删除，请新建会话。",
            409: "会话已更新，请刷新会话后重试。",
            503: "服务不可用，请检查后端的模型或数据库配置。",
        }.get(status, "请检查后端日志后重试。")
        raise ChatAPIError(f"后端返回错误（HTTP {status}），{detail}", status) from exc
    except (httpx.RequestError, httpx.InvalidURL) as exc:
        raise ChatAPIError("无法连接后端，请确认 FastAPI 已启动且 AGENT_API_URL 配置正确。") from exc

    if response.status_code == 204:
        return None
    try:
        return response.json()
    except ValueError as exc:
        raise ChatAPIError("后端响应格式异常，请检查 API 服务版本。") from exc


def request_chat(message: str, session_id: str | None = None, *, client: httpx.Client | None = None) -> dict:
    data = _request("POST", "/api/chat", client=client, json={"message": message, "session_id": session_id})
    try:
        answer = data["answer"]
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("Invalid answer")
        UUID(data["session_id"])
        return {"answer": answer, "session_id": data["session_id"]}
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ChatAPIError("后端响应格式异常，请检查 API 服务版本。") from exc


class ChatStream:
    def __init__(self, message: str, session_id: str | None, client: httpx.Client | None):
        self.message = message
        self.requested_session_id = session_id
        self.client = client
        self.session_id: str | None = None

    def __iter__(self) -> Iterator[str]:
        url = os.getenv("AGENT_API_URL", "http://127.0.0.1:8000").rstrip("/") + "/api/chat/stream"
        owned = self.client is None
        client = self.client or httpx.Client()
        headers = {"Accept": "text/event-stream"}
        if token := os.getenv("AGENT_ADMIN_TOKEN"):
            headers["Authorization"] = f"Bearer {token}"
        pieces = []
        event_name = None
        data_lines = []
        completed = False
        try:
            with client.stream("POST", url, json={"message": self.message, "session_id": self.requested_session_id},
                               headers=headers, timeout=httpx.Timeout(120.0, connect=5.0)) as response:
                response.raise_for_status()
                if not response.headers.get("content-type", "").startswith("text/event-stream"):
                    raise ChatAPIError("后端响应格式异常，请检查 API 服务版本。")
                for raw_line in response.iter_lines():
                    line = raw_line.rstrip("\r")
                    if line.startswith("event:"):
                        event_name = line[6:].strip()
                    elif line.startswith("data:"):
                        data_lines.append(line[5:].lstrip())
                    elif not line and event_name:
                        try:
                            data = json.loads("\n".join(data_lines))
                            if event_name == "delta":
                                chunk = data["text"]
                                if not isinstance(chunk, str):
                                    raise ValueError
                                pieces.append(chunk)
                                yield chunk
                            elif event_name == "done":
                                UUID(data["session_id"])
                                if data["answer"] != "".join(pieces).strip():
                                    raise ValueError
                                self.session_id = data["session_id"]
                                completed = True
                            elif event_name == "error":
                                raise ChatAPIError({
                                    "session_conflict": "会话已变化，请刷新后重试。",
                                    "database_unavailable": "数据库不可用，请稍后重试。",
                                    "agent_error": "Agent 暂时无法完成请求，请稍后重试。",
                                }.get(data.get("code"), "后端处理失败，请稍后重试。"))
                        except (ValueError, KeyError, TypeError, AttributeError) as exc:
                            raise ChatAPIError("后端流式响应格式异常。") from exc
                        event_name, data_lines = None, []
                if not completed:
                    raise ChatAPIError("回答传输中断，请刷新会话核对是否保存。")
        except httpx.TimeoutException as exc:
            raise ChatAPIError("请求超时，请稍后重试；复杂报告可能需要更长时间。") from exc
        except httpx.HTTPStatusError as exc:
            raise ChatAPIError(f"后端返回错误（HTTP {exc.response.status_code}）。", exc.response.status_code) from exc
        except (httpx.RequestError, httpx.InvalidURL) as exc:
            raise ChatAPIError("无法连接后端，请确认 FastAPI 已启动且 AGENT_API_URL 配置正确。") from exc
        finally:
            if owned:
                client.close()


def request_chat_stream(message: str, session_id: str | None = None,
                        *, client: httpx.Client | None = None) -> ChatStream:
    return ChatStream(message, session_id, client)


def _validate_summary(data):
    UUID(data["id"])
    if not isinstance(data["title"], str):
        raise ValueError("Invalid title")


def list_sessions(*, limit: int = 20, offset: int = 0, client: httpx.Client | None = None) -> list[dict]:
    data = _request("GET", "/api/sessions", client=client, params={"limit": limit, "offset": offset})
    try:
        if not isinstance(data, list):
            raise ValueError("Invalid sessions")
        for item in data:
            _validate_summary(item)
        return data
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ChatAPIError("后端会话列表格式异常。") from exc


def get_session(session_id: str, *, client: httpx.Client | None = None) -> dict:
    data = _request("GET", f"/api/sessions/{session_id}", client=client)
    try:
        _validate_summary(data)
        if data["id"] != session_id or not isinstance(data["messages"], list):
            raise ValueError("Invalid session")
        for message in data["messages"]:
            if message["role"] not in ("user", "assistant") or not isinstance(message["content"], str):
                raise ValueError("Invalid message")
        return data
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ChatAPIError("后端会话详情格式异常。") from exc


def delete_session(session_id: str, *, client: httpx.Client | None = None) -> None:
    _request("DELETE", f"/api/sessions/{session_id}", client=client)
