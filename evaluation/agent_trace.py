"""Capture only public outputs, tool names, usage and timing from one Agent run."""

from time import perf_counter


def trace_agent(graph, question: str) -> dict:
    start = perf_counter()
    first_token_ms = None
    final_messages = []
    for mode, payload in graph.stream(
            {"messages": [{"role": "user", "content": question}]},
            stream_mode=["messages", "values"], context={"report": False}):
        if mode == "messages":
            chunk, metadata = payload
            if (first_token_ms is None and metadata.get("langgraph_node") == "model"
                    and getattr(chunk, "type", "") == "AIMessageChunk"
                    and isinstance(chunk.content, str) and chunk.content
                    and not getattr(chunk, "tool_call_chunks", None)):
                first_token_ms = (perf_counter() - start) * 1000
        elif mode == "values":
            final_messages = payload["messages"]
    tools = []
    input_tokens = output_tokens = 0
    answer = ""
    for message in final_messages:
        if getattr(message, "type", "") != "ai":
            continue
        tools.extend(call["name"] for call in getattr(message, "tool_calls", []) or [])
        usage = getattr(message, "usage_metadata", None) or {}
        input_tokens += usage.get("input_tokens", 0)
        output_tokens += usage.get("output_tokens", 0)
        if not getattr(message, "tool_calls", None) and isinstance(message.content, str):
            answer = message.content
    return {"answer": answer, "observed_tools": tools,
            "first_token_ms": first_token_ms, "total_ms": (perf_counter() - start) * 1000,
            "input_tokens": input_tokens, "output_tokens": output_tokens}


def trace_report(workflow, question: str) -> dict:
    """Evaluate the same report graph used by chat without retaining its records."""
    start = perf_counter()
    first_token_ms = None
    chunks = []
    tools = []
    input_tokens = output_tokens = 0
    report_generated = False
    for mode, payload in workflow.graph.stream({"message": question}, stream_mode=["custom", "updates"]):
        if mode == "custom" and payload.get("type") == "report_delta":
            if first_token_ms is None:
                first_token_ms = (perf_counter() - start) * 1000
            chunks.append(payload["text"])
        elif mode == "updates":
            if "resolve_identity" in payload and payload["resolve_identity"].get("demo_employee"):
                tools.append("get_employee_id")
            if "resolve_month" in payload and payload["resolve_month"].get("default_month"):
                tools.append("get_current_month")
            if "lookup_asset" in payload:
                tools.append("query_asset_record")
            if "generate_report" in payload:
                generated = payload["generate_report"]
                report_generated = generated.get("report_generated", False)
                input_tokens = generated.get("input_tokens", 0)
                output_tokens = generated.get("output_tokens", 0)
    return {"answer": "".join(chunks).strip(), "observed_tools": tools,
            "report_generated": report_generated,
            "first_token_ms": first_token_ms, "total_ms": (perf_counter() - start) * 1000,
            "input_tokens": input_tokens, "output_tokens": output_tokens}
