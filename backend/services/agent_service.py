"""Adapt the existing Agent without importing models during API startup."""

from collections.abc import Callable, Iterable
from time import perf_counter
from typing import Protocol

from observability.tracing import record


class Agent(Protocol):
    def execute_stream(self, query: str, history: list[dict[str, str]] | None = None) -> Iterable[str]: ...


def create_agent() -> Agent:
    from agent.react_agent import ReactAgent

    return ReactAgent()


class AgentUnavailableError(Exception):
    """Model or Agent initialization failed."""


class AgentExecutionError(Exception):
    """Agent failed to produce a usable answer."""


class AgentService:
    def __init__(self, agent_factory: Callable[[], Agent] = create_agent):
        self._agent_factory = agent_factory

    def chat(self, message: str, history: list[dict[str, str]]) -> str:
        return "".join(self.stream(message, history)).strip()

    def stream(self, message: str, history: list[dict[str, str]]) -> Iterable[str]:
        # Each request gets its own graph and report context. No shared history.
        started = perf_counter()
        record("agent.start", message_count=len(history) + 1)
        try:
            agent = self._agent_factory()
        except Exception as exc:
            record("agent.end", status="error", error_type=type(exc).__name__,
                   duration_ms=round((perf_counter() - started) * 1000, 3))
            raise AgentUnavailableError from exc

        try:
            has_text = False
            first_text = True
            answer_chars = 0
            for chunk in agent.execute_stream(message, history):
                if chunk and chunk.strip():
                    has_text = True
                    if first_text:
                        first_text = False
                        record("agent.first_token", duration_ms=round((perf_counter() - started) * 1000, 3))
                if chunk:
                    answer_chars += len(chunk)
                    yield chunk
            if not has_text:
                raise ValueError("Agent returned an empty answer")
        except Exception as exc:
            record("agent.end", status="error", error_type=type(exc).__name__,
                   duration_ms=round((perf_counter() - started) * 1000, 3))
            raise AgentExecutionError from exc
        record("agent.end", status="ok", answer_chars=answer_chars,
               duration_ms=round((perf_counter() - started) * 1000, 3))
