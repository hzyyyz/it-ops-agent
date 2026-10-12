"""Best-effort Redis cache for the recent context of a persisted session."""

from functools import lru_cache
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv


logger = logging.getLogger(__name__)
SESSION_CACHE_TTL_SECONDS = 1800


class RecentHistoryCache:
    def __init__(self, client, ttl_seconds: int = SESSION_CACHE_TTL_SECONDS):
        self.client = client
        self.ttl_seconds = ttl_seconds

    @staticmethod
    def _key(session_id: str) -> str:
        return f"session:{session_id}:messages"

    def get(self, session_id: str, version: int) -> list[dict[str, str]] | None:
        try:
            payload = self.client.get(self._key(session_id))
            if payload is None:
                return None
            entry = json.loads(payload)
            if type(entry) is not dict or type(entry.get("version")) is not int or entry["version"] != version:
                return None
            history = entry.get("messages")
            if type(history) is not list or any(
                type(row) is not dict or row.get("role") not in ("user", "assistant")
                or type(row.get("content")) is not str for row in history
            ):
                return None
            return history
        except Exception as exc:
            logger.warning("Redis cache read failed (%s)", type(exc).__name__)
            return None

    def set(self, session_id: str, version: int, history: list[dict[str, str]]) -> None:
        try:
            payload = json.dumps({"version": version, "messages": history}, ensure_ascii=False)
            self.client.setex(self._key(session_id), self.ttl_seconds, payload)
        except Exception as exc:
            logger.warning("Redis cache write failed (%s)", type(exc).__name__)

    def delete(self, session_id: str) -> None:
        try:
            self.client.delete(self._key(session_id))
        except Exception as exc:
            logger.warning("Redis cache delete failed (%s)", type(exc).__name__)


@lru_cache(maxsize=4)
def _cache_for_url(url: str) -> RecentHistoryCache:
    from redis import Redis

    return RecentHistoryCache(Redis.from_url(
        url, decode_responses=True, socket_connect_timeout=0.3, socket_timeout=0.3,
    ))


def get_recent_history_cache() -> RecentHistoryCache | None:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    url = os.getenv("REDIS_URL")
    if not url:
        return None
    try:
        return _cache_for_url(url)
    except Exception as exc:
        logger.warning("Redis cache unavailable (%s)", type(exc).__name__)
        return None
