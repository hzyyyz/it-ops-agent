from typing import Callable, Any
from time import perf_counter
from langchain.agents import AgentState
from langchain.agents.middleware import wrap_tool_call, wrap_model_call, before_model, after_model, dynamic_prompt, ModelRequest, ModelResponse
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.runtime import Runtime
from langgraph.types import Command
from utils.logger_handler import logger
from utils.prompt_loader import load_system_prompt, load_report_prompts
from observability.tracing import record, span


@wrap_tool_call
def monitor_tool(
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command]
) -> ToolMessage | Command:
    name = request.tool_call["name"]
    logger.info("Tool started: %s", name)
    with span("tool", tool_name=name):
        result = handler(request)
        content = getattr(result, "content", None)
        record("tool.result", tool_name=name, result_type=type(result).__name__,
               result_chars=len(content) if isinstance(content, str) else 0)
        if name == "prepare_report_context":
            request.runtime.context["report"] = True
        return result


@wrap_model_call
def trace_model_call(request: ModelRequest,
                     handler: Callable[[ModelRequest], ModelResponse]) -> ModelResponse:
    started = perf_counter()
    message_count = len(request.state.get("messages", []))
    record("model.start", message_count=message_count)
    try:
        response = handler(request)
    except Exception as exc:
        record("model.end", status="error", error_type=type(exc).__name__,
               duration_ms=round((perf_counter() - started) * 1000, 3))
        raise
    input_tokens = output_tokens = 0
    for message in response.result:
        usage = getattr(message, "usage_metadata", None) or {}
        input_tokens += usage.get("input_tokens", 0)
        output_tokens += usage.get("output_tokens", 0)
    record("model.end", status="ok", input_tokens=input_tokens, output_tokens=output_tokens,
           duration_ms=round((perf_counter() - started) * 1000, 3))
    return response


@before_model
def log_before_model(state:AgentState, runtime: Runtime) -> dict[str, Any] | None:
    logger.info("Model request with %d messages", len(state["messages"]))
    return None

@after_model
def log_after_model(state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
    message = state['messages'][-1]
    if getattr(message, 'tool_calls', None):
        logger.info("Model selected tools: %s", [tc["name"] for tc in message.tool_calls])
    else:
        logger.info("Model response received")
    return None


@dynamic_prompt
def report_prompt_switch(request: ModelRequest) -> str:
    is_report = request.runtime.context.get("report", False)
    if is_report:
        return load_report_prompts()

    return load_system_prompt()


