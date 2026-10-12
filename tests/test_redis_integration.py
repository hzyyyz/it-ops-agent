"""Opt-in check against the Redis service configured for the API container."""

import os
from uuid import uuid4

import pytest


@pytest.mark.skipif(os.getenv("RUN_REDIS_INTEGRATION") != "1", reason="Redis integration is explicitly opt-in")
def test_real_redis_recent_context_ttl_and_delete():
    from redis import Redis
    from backend.cache import RecentHistoryCache

    url = os.getenv("REDIS_URL")
    if not url:
        pytest.skip("REDIS_URL is not configured")
    client = Redis.from_url(url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2)
    cache = RecentHistoryCache(client)
    session_id = str(uuid4())
    key = f"session:{session_id}:messages"
    try:
        cache.set(session_id, 7, [{"role": "user", "content": "cache probe"}])
        assert cache.get(session_id, 7) == [{"role": "user", "content": "cache probe"}]
        assert 0 < client.ttl(key) <= 1800
        cache.delete(session_id)
        assert client.exists(key) == 0
    finally:
        client.delete(key)
