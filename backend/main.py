import logging
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError

from backend.api.chat import router
from backend.api.sessions import router as sessions_router
from backend.api.knowledge import router as knowledge_router
from backend.api.traces import router as traces_router
from backend.api.health import router as health_router
from backend.auth import require_admin
from backend.database import DatabaseConfigurationError
from backend.services.session_service import SessionConflictError, SessionNotFoundError
from backend.services.agent_service import AgentExecutionError, AgentUnavailableError
from observability.tracing import record, trace_scope


logger = logging.getLogger(__name__)
app = FastAPI(title="IT 运维 Agent API", version="2.0.0")
app.include_router(router, dependencies=[Depends(require_admin)])
app.include_router(sessions_router, dependencies=[Depends(require_admin)])
app.include_router(knowledge_router, dependencies=[Depends(require_admin)])
app.include_router(traces_router, dependencies=[Depends(require_admin)])
app.include_router(health_router)
app.mount("/ui", StaticFiles(directory=Path(__file__).resolve().parents[1] / "web", html=True), name="ui")


@app.middleware("http")
async def trace_request(request: Request, call_next):
    trace_id = uuid4().hex
    request.state.trace_id = trace_id
    with trace_scope(trace_id):
        started = perf_counter()
        record("request.start", method=request.method)
        try:
            response = await call_next(request)
        except Exception as exc:
            record("request.end", status="error", error_type=type(exc).__name__,
                   http_status=500,
                   duration_ms=round((perf_counter() - started) * 1000, 3))
            logger.error("Unhandled request failure (%s)", type(exc).__name__)
            return JSONResponse(status_code=500,
                                content={"detail": "服务处理失败，请稍后重试。"},
                                headers={"X-Trace-Id": trace_id})
        route = getattr(request.scope.get("route"), "path", "unmatched")
        record("request.response", route=route, http_status=response.status_code)
        record("request.end", status="error" if response.status_code >= 400 else "ok",
               http_status=response.status_code,
               duration_ms=round((perf_counter() - started) * 1000, 3))
        response.headers["X-Trace-Id"] = trace_id
        return response


@app.exception_handler(SessionNotFoundError)
async def session_not_found(request: Request, exc: SessionNotFoundError):
    return JSONResponse(status_code=404, content={"detail": "会话不存在或已删除。"})


@app.exception_handler(SessionConflictError)
async def session_conflict(request: Request, exc: SessionConflictError):
    return JSONResponse(status_code=409, content={"detail": "会话已被其他请求更新，请刷新会话后重试。"})


@app.exception_handler(DatabaseConfigurationError)
@app.exception_handler(SQLAlchemyError)
async def database_unavailable(request: Request, exc: Exception):
    logger.error("Database unavailable (%s)", type(exc).__name__)
    return JSONResponse(status_code=503, content={"detail": "数据库不可用，请检查 MySQL 配置、连接和表初始化。"})


@app.exception_handler(AgentUnavailableError)
async def agent_unavailable(request: Request, exc: AgentUnavailableError) -> JSONResponse:
    logger.error("Agent initialization failed (%s)", type(exc.__cause__ or exc).__name__)
    return JSONResponse(status_code=503, content={"detail": "Agent 初始化失败，请检查后端模型配置和日志。"})


@app.exception_handler(AgentExecutionError)
async def agent_execution_failed(request: Request, exc: AgentExecutionError) -> JSONResponse:
    logger.error("Agent execution failed (%s)", type(exc.__cause__ or exc).__name__)
    return JSONResponse(status_code=502, content={"detail": "Agent 暂时无法完成请求，请稍后重试。"})
