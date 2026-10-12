"""Cheap dependency readiness check; never loads the Agent or a model."""

from pathlib import Path
from typing import Annotated, Callable

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text

from backend.cache import get_recent_history_cache
from backend.database import get_engine
from utils.config_handler import chroma_conf
from utils.path_tool import get_abs_path


router = APIRouter(prefix="/api", tags=["health"])


def _mysql_ready() -> bool:
    with get_engine().connect() as connection:
        connection.execute(text("SELECT id FROM sessions LIMIT 1"))
        connection.execute(text("SELECT name FROM documents LIMIT 1"))
        connection.execute(text("SELECT id FROM evaluation_results LIMIT 1"))
    return True


def _redis_ready() -> bool | None:
    cache = get_recent_history_cache()
    return None if cache is None else bool(cache.client.ping())


def _knowledge_ready() -> bool:
    return Path(get_abs_path(chroma_conf["data_path"])).is_dir()


def get_health_checks() -> dict[str, Callable[[], bool | None]]:
    return {"mysql": _mysql_ready, "redis": _redis_ready, "knowledge": _knowledge_ready}


@router.get("/health")
def health(checks: Annotated[dict[str, Callable[[], bool | None]], Depends(get_health_checks)]):
    states = {}
    for name, check in checks.items():
        try:
            result = check()
            states[name] = "disabled" if result is None else "ok" if result else "error"
        except Exception:
            states[name] = "error"
    ready = states.get("mysql") == "ok" and states.get("knowledge") == "ok"
    healthy = ready and states.get("redis") != "error"
    return JSONResponse({"status": "ok" if healthy else "degraded", "checks": states},
                        status_code=200 if ready else 503)
