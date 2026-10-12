"""Request-local JSONL tracing with an explicit metadata allowlist."""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
from threading import Lock
from time import perf_counter


_current: ContextVar[dict | None] = ContextVar("agent_trace", default=None)
_write_lock = Lock()
_allowed = frozenset({
    "method", "route", "http_status", "status", "duration_ms", "error_type",
    "tool_name", "result_type", "result_chars", "model_name", "message_count", "input_tokens", "output_tokens",
    "candidate_count", "vector_count", "lexical_count", "doc_count", "sources",
    "mode", "rewrite_failed", "rerank_failed", "reranked", "answer_chars",
    "chunk_count", "query_chars",
})


@contextmanager
def trace_scope(trace_id: str, session_id: str | None = None):
    token = _current.set({"trace_id": trace_id, "session_id": session_id})
    try:
        yield
    finally:
        _current.reset(token)


def current_trace_id() -> str | None:
    context = _current.get()
    return context["trace_id"] if context else None


def set_session_id(session_id: str | None) -> None:
    context = _current.get()
    if context is not None:
        context["session_id"] = session_id


def _safe_source(source: str) -> str:
    normalized = str(source).replace("\\", "/")
    if normalized.startswith("data/"):
        return normalized
    if "/data/" in normalized:
        return "data/" + normalized.rsplit("/data/", 1)[1]
    return normalized.rsplit("/", 1)[-1]


def record(event: str, **metadata) -> None:
    context = _current.get()
    if context is None:
        return
    try:
        row = {"timestamp": datetime.now(timezone.utc).isoformat(),
               "trace_id": context["trace_id"], "session_id": context["session_id"],
               "event": event}
        for key, value in metadata.items():
            if key in _allowed and value is not None:
                row[key] = [_safe_source(source) for source in value] if key == "sources" else value
        line = json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
        path = Path(os.getenv("AGENT_TRACE_FILE", "logs/traces.jsonl"))
        with _write_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as stream:
                stream.write(line)
    except (OSError, TypeError, ValueError) as exc:
        logging.getLogger(__name__).warning("Trace write failed (%s)", type(exc).__name__)


@contextmanager
def span(name: str, **metadata):
    start = perf_counter()
    record(f"{name}.start", **metadata)
    try:
        yield
    except Exception as exc:
        record(f"{name}.end", **metadata, status="error",
               error_type=type(exc).__name__, duration_ms=round((perf_counter() - start) * 1000, 3))
        raise
    else:
        record(f"{name}.end", **metadata, status="ok",
               duration_ms=round((perf_counter() - start) * 1000, 3))
