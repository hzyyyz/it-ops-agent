import json
import logging
from time import perf_counter
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.schemas.chat import ChatRequest, ChatResponse
from backend.services.agent_service import AgentService, AgentExecutionError, AgentUnavailableError
from backend.services.session_service import SessionService, SessionConflictError, SessionNotFoundError
from observability.tracing import record, set_session_id, span, trace_scope

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api", tags=["chat"])


def get_agent_service() -> AgentService:
    return AgentService()


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest, service: Annotated[AgentService, Depends(get_agent_service)],
         db: Annotated[Session, Depends(get_db)], http_request: Request) -> ChatResponse:
    # Sync endpoint: blocking model/tool work runs in FastAPI's thread pool.
    set_session_id(str(request.session_id) if request.session_id else None)
    with span("chat"):
        answer, session_id = SessionService(db).chat(
            request.message, str(request.session_id) if request.session_id else None, service)
    set_session_id(session_id)
    record("chat.saved", answer_chars=len(answer))
    return ChatResponse(answer=answer, session_id=session_id, trace_id=http_request.state.trace_id)


def _event(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/chat/stream")
def chat_stream(request: ChatRequest, service: Annotated[AgentService, Depends(get_agent_service)],
                db: Annotated[Session, Depends(get_db)], http_request: Request) -> StreamingResponse:
    session = SessionService(db)
    sid = str(request.session_id) if request.session_id else None
    history, version = session.prepare_chat(sid)
    bind = db.get_bind()
    trace_id = http_request.state.trace_id

    def generate():
        current_sid = sid
        started = perf_counter()
        status = "ok"

        def observe(event, **metadata):
            with trace_scope(trace_id, current_sid):
                record(event, **metadata)

        def traced_chunks():
            iterator = iter(service.stream(request.message, history))
            while True:
                # Starlette can advance each chunk in a different thread context.
                with trace_scope(trace_id, current_sid):
                    try:
                        chunk = next(iterator)
                    except StopIteration:
                        return
                yield chunk

        observe("chat.stream.start")
        chunks = []
        try:
            for chunk in traced_chunks():
                chunks.append(chunk)
                yield _event("delta", {"text": chunk})
            answer = "".join(chunks).strip()
            if not answer:
                raise AgentExecutionError
            # Streaming runs in a worker thread. Own its Session in that thread.
            with trace_scope(trace_id, current_sid):
                with Session(bind, expire_on_commit=False) as stream_db:
                    _, saved_id = SessionService(stream_db).save_chat(request.message, sid, version, answer)
            current_sid = saved_id
            observe("chat.saved", answer_chars=len(answer), chunk_count=len(chunks))
            yield _event("done", {"answer": answer, "session_id": saved_id, "trace_id": trace_id})
        except GeneratorExit:
            status = "cancelled"
            raise
        except (SessionNotFoundError, SessionConflictError):
            status = "error"
            observe("chat.error", error_type="SessionConflictError")
            yield _event("error", {"code": "session_conflict", "message": "会话已变化，请刷新后重试。", "trace_id": trace_id})
        except (SQLAlchemyError,) as exc:
            status = "error"
            logger.error("Streaming chat database failure (%s)", type(exc).__name__)
            observe("chat.error", error_type=type(exc).__name__)
            yield _event("error", {"code": "database_unavailable", "message": "数据库不可用，请稍后重试。", "trace_id": trace_id})
        except (AgentUnavailableError, AgentExecutionError) as exc:
            status = "error"
            logger.error("Streaming chat agent failure (%s)", type(exc).__name__)
            observe("chat.error", error_type=type(exc).__name__)
            yield _event("error", {"code": "agent_error", "message": "Agent 暂时无法完成请求，请稍后重试。", "trace_id": trace_id})
        except Exception as exc:
            status = "error"
            logger.error("Unexpected streaming chat failure (%s)", type(exc).__name__)
            observe("chat.error", error_type=type(exc).__name__)
            yield _event("error", {"code": "server_error", "message": "服务处理失败，请稍后重试。", "trace_id": trace_id})
        finally:
            observe("chat.stream.end", status=status,
                    duration_ms=round((perf_counter() - started) * 1000, 3))

    return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
