"""Read bounded, metadata-only trace events for the current request."""

import json
import os
from pathlib import Path
import re

from fastapi import APIRouter, HTTPException


router = APIRouter(prefix="/api/traces", tags=["traces"])
_TRACE_ID = re.compile(r"[0-9a-f]{32}")
_PUBLIC_FIELDS = frozenset({
    "timestamp", "event", "session_id", "method", "route", "http_status", "status",
    "duration_ms", "error_type", "tool_name", "result_type", "result_chars",
    "model_name", "message_count", "input_tokens", "output_tokens", "candidate_count",
    "vector_count", "lexical_count", "doc_count", "sources", "mode", "rewrite_failed",
    "rerank_failed", "reranked", "answer_chars", "chunk_count", "query_chars",
})


@router.get("/{trace_id}")
def get_trace(trace_id: str):
    if not _TRACE_ID.fullmatch(trace_id):
        raise HTTPException(status_code=422, detail="无效的 Trace ID。")
    path = Path(os.getenv("AGENT_TRACE_FILE", "logs/traces.jsonl"))
    events = []
    try:
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                try:
                    row = json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    continue
                if isinstance(row, dict) and row.get("trace_id") == trace_id:
                    events.append({key: value for key, value in row.items() if key in _PUBLIC_FIELDS})
                    if len(events) >= 200:
                        break
    except FileNotFoundError:
        pass
    return {"trace_id": trace_id, "events": events}
