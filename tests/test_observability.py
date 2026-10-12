import json
import asyncio
from pathlib import Path
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from tests.test_chat_api import api  # noqa: F401 - fixture


def read_events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_trace_recorder_correlates_events_and_drops_content(monkeypatch, tmp_path):
    from observability.tracing import record, trace_scope

    path = tmp_path / "traces.jsonl"
    monkeypatch.setenv("AGENT_TRACE_FILE", str(path))
    with trace_scope("trace-123", "session-456"):
        record("tool.end", tool_name="get_cpu_usage", duration_ms=12.5,
               status="ok", args="secret argument", result="secret result")
    row, = read_events(path)
    assert row["trace_id"] == "trace-123"
    assert row["session_id"] == "session-456"
    assert row["event"] == "tool.end"
    assert row["tool_name"] == "get_cpu_usage"
    assert row["duration_ms"] == 12.5
    assert "secret" not in json.dumps(row)


def test_chat_and_stream_expose_trace_id_and_write_correlated_events(monkeypatch, tmp_path, api):
    path = tmp_path / "traces.jsonl"
    monkeypatch.setenv("AGENT_TRACE_FILE", str(path))
    client, _, _, _ = api
    response = client.post("/api/chat", json={"message": "secret question"})
    trace_id = response.headers["x-trace-id"]
    assert response.json()["trace_id"] == trace_id
    assert response.json()["session_id"]
    rows = [row for row in read_events(path) if row["trace_id"] == trace_id]
    assert {row["event"] for row in rows} >= {"request.start", "agent.end", "request.end"}
    assert "secret question" not in path.read_text(encoding="utf-8")

    stream = client.post("/api/chat/stream", json={"message": "stream secret"})
    stream_id = stream.headers["x-trace-id"]
    assert f'"trace_id": "{stream_id}"' in stream.text
    stream_rows = [row for row in read_events(path) if row["trace_id"] == stream_id]
    assert {row["event"] for row in stream_rows} >= {"request.start", "agent.end", "request.end"}
    assert "stream secret" not in path.read_text(encoding="utf-8")


def test_http_error_marks_request_trace_as_error(monkeypatch, tmp_path, api):
    path = tmp_path / "traces.jsonl"
    monkeypatch.setenv("AGENT_TRACE_FILE", str(path))
    client, _, _, _ = api
    response = client.get("/api/missing")
    assert response.status_code == 404
    rows = [row for row in read_events(path) if row["trace_id"] == response.headers["x-trace-id"]]
    end = next(row for row in rows if row["event"] == "request.end")
    assert end["status"] == "error"
    assert end["http_status"] == 404


def test_unhandled_http_error_still_returns_trace_id(monkeypatch, tmp_path):
    from fastapi import Request
    from backend.main import trace_request

    path = tmp_path / "traces.jsonl"
    monkeypatch.setenv("AGENT_TRACE_FILE", str(path))
    request = Request({"type": "http", "method": "GET", "path": "/api/failure", "headers": []})

    async def fail(_request):
        raise RuntimeError("private failure text")

    response = asyncio.run(trace_request(request, fail))
    assert response.status_code == 500
    assert response.headers["x-trace-id"]
    assert "private failure text" not in path.read_text(encoding="utf-8")
    rows = read_events(path)
    assert rows[-1]["event"] == "request.end"
    assert rows[-1]["status"] == "error"


def test_trace_span_records_error_type_without_message(monkeypatch, tmp_path):
    from observability.tracing import span, trace_scope

    path = tmp_path / "traces.jsonl"
    monkeypatch.setenv("AGENT_TRACE_FILE", str(path))
    try:
        with trace_scope("trace-err"):
            with span("rag.search", mode="advanced"):
                raise ValueError("secret internal content")
    except ValueError:
        pass
    rows = read_events(path)
    assert rows[-1]["event"] == "rag.search.end"
    assert rows[-1]["status"] == "error"
    assert rows[-1]["error_type"] == "ValueError"
    assert "secret internal content" not in path.read_text(encoding="utf-8")


def test_tool_and_model_middleware_emit_metadata_only(monkeypatch, tmp_path):
    from agent.tools.middleware import monitor_tool, trace_model_call
    from langchain_core.messages import AIMessage, ToolMessage
    from observability.tracing import trace_scope

    path = tmp_path / "traces.jsonl"
    monkeypatch.setenv("AGENT_TRACE_FILE", str(path))
    tool_request = SimpleNamespace(tool_call={"name": "get_cpu_usage", "args": {"token": "private-value"}},
                                   runtime=SimpleNamespace(context={}))
    model_response = SimpleNamespace(result=[AIMessage(content="private answer",
        usage_metadata={"input_tokens": 11, "output_tokens": 7, "total_tokens": 18})])
    with trace_scope("trace-middleware"):
        monitor_tool.wrap_tool_call(tool_request, lambda _: ToolMessage(content="private result", tool_call_id="1"))
        trace_model_call.wrap_model_call(SimpleNamespace(state={"messages": [1, 2]}),
                                         lambda _: model_response)
    rows = read_events(path)
    assert {row["event"] for row in rows} >= {"tool.end", "tool.result", "model.end"}
    assert next(row for row in rows if row["event"] == "tool.result")["result_chars"] == len("private result")
    assert next(row for row in rows if row["event"] == "model.end")["input_tokens"] == 11
    assert "private" not in path.read_text(encoding="utf-8")


def test_advanced_rag_trace_records_stages_and_sources_without_queries(monkeypatch, tmp_path):
    from langchain_core.documents import Document
    from observability.tracing import trace_scope
    from rag.retrieval import RetrievalPipeline

    path = tmp_path / "traces.jsonl"
    monkeypatch.setenv("AGENT_TRACE_FILE", str(path))
    doc = Document(page_content="private document", metadata={"source": "data/故障排除.txt"})

    class Store:
        def similarity_search(self, query, k):
            return [doc]

        def get(self, **kwargs):
            return {"documents": [doc.page_content], "metadatas": [doc.metadata]}

    class Reranker:
        def predict(self, pairs):
            return [1.0] * len(pairs)

    with trace_scope("trace-rag"):
        docs = RetrievalPipeline(Store(), rewriter=lambda q: q, reranker=Reranker()).retrieve("private query")
    rows = read_events(path)
    assert docs == [doc]
    assert {row["event"] for row in rows} >= {
        "rag.rewrite.end", "rag.vector_search.end", "rag.keyword_search.end",
        "rag.rerank.end", "rag.retrieval.end",
    }
    assert next(row for row in rows if row["event"] == "rag.retrieval.end")["sources"] == ["data/故障排除.txt"]
    content = path.read_text(encoding="utf-8")
    assert "private query" not in content
    assert "private document" not in content


def test_trace_write_failure_does_not_break_the_request(monkeypatch, tmp_path):
    from observability.tracing import record, trace_scope

    monkeypatch.setenv("AGENT_TRACE_FILE", str(tmp_path))  # directory, not a file
    with trace_scope("trace-write-error"):
        record("request.start", method="POST")


def test_trace_serialization_failure_does_not_break_the_request(monkeypatch, tmp_path):
    from observability.tracing import record, trace_scope

    monkeypatch.setenv("AGENT_TRACE_FILE", str(tmp_path / "traces.jsonl"))
    with trace_scope("trace-serialization-error"):
        record("model.end", input_tokens=object())


def test_trace_sources_hide_absolute_parent_directories(monkeypatch, tmp_path):
    from observability.tracing import record, trace_scope

    path = tmp_path / "traces.jsonl"
    monkeypatch.setenv("AGENT_TRACE_FILE", str(path))
    with trace_scope("trace-sources"):
        record("rag.retrieval.end", sources=[r"F:\private\data\故障排除.txt", r"F:\secret\notes.txt"])
    row, = read_events(path)
    assert row["sources"] == ["data/故障排除.txt", "notes.txt"]
    assert "private" not in path.read_text(encoding="utf-8")


def test_rag_answer_records_nested_model_tokens(monkeypatch, tmp_path):
    from langchain_core.messages import AIMessage
    from observability.tracing import trace_scope
    import rag.rag_service as module

    path = tmp_path / "traces.jsonl"
    monkeypatch.setenv("AGENT_TRACE_FILE", str(path))

    class Store:
        vector_store = SimpleNamespace()

        def get_retriever(self):
            return None

    class Chain:
        def invoke(self, value):
            return AIMessage(content="private answer", usage_metadata={
                "input_tokens": 13, "output_tokens": 5, "total_tokens": 18})

    monkeypatch.setattr(module, "VectorStoreService", Store)
    monkeypatch.setattr(module.RagSummarizeService, "_init_chain", lambda self: Chain())
    rag = module.RagSummarizeService(mode="baseline")
    monkeypatch.setattr(rag, "retriever_docs", lambda query: [])
    with trace_scope("trace-rag-answer"):
        assert rag.rag_summarize("private question") == "private answer"
    rows = read_events(path)
    assert next(row for row in rows if row["event"] == "rag.answer.usage")["input_tokens"] == 13
    assert "private answer" not in path.read_text(encoding="utf-8")


def test_concurrent_retrieval_events_keep_their_own_counts(monkeypatch, tmp_path):
    from langchain_core.documents import Document
    from observability.tracing import trace_scope
    from rag.retrieval import RetrievalPipeline

    path = tmp_path / "traces.jsonl"
    monkeypatch.setenv("AGENT_TRACE_FILE", str(path))

    class Store:
        def similarity_search(self, query, k):
            return [Document(page_content=f"{query}-{index}", metadata={"source": f"data/{query}.txt"})
                    for index in range(1 if query == "one" else 2)]

    pipeline = RetrievalPipeline(Store(), mode="baseline")
    original = pipeline._retrieve
    barrier = Barrier(2)
    readback = Barrier(2)

    def synchronized_retrieve(query):
        result = original(query)
        barrier.wait(timeout=5)
        return result

    monkeypatch.setattr(pipeline, "_retrieve", synchronized_retrieve)

    def run(query):
        with trace_scope(query):
            pipeline.retrieve(query)
            readback.wait(timeout=5)
            return pipeline.last_trace["candidate_count"]

    with ThreadPoolExecutor(max_workers=2) as executor:
        counts = list(executor.map(run, ("one", "two")))
    assert counts == [1, 2]
    rows = {row["trace_id"]: row for row in read_events(path) if row["event"] == "rag.retrieval.end"}
    assert rows["one"]["candidate_count"] == 1
    assert rows["two"]["candidate_count"] == 2
