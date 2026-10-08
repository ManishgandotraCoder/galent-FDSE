"""Redis cache for finished model extractions.

Tests and callers can pass MemoryCache instead. If Redis is down, reads and
writes are skipped and the pipeline still runs.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

import redis

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_cache: RedisCache | None = None


class MemoryCache:
    """Process-local stand-in used by tests and when a caller injects a cache."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    @property
    def available(self) -> bool:
        return True

    def get_json(self, key: str) -> Any | None:
        raw = self._values.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    def set_json(self, key: str, value: Any, ttl: int) -> None:
        del ttl
        self._values[key] = json.dumps(value)


class RedisCache:
    def __init__(self, url: str, client: Any | None = None) -> None:
        self._url = url
        self._client = client
        self._ok: bool | None = True if client is not None else None
        parsed = urlparse(url)
        host = parsed.hostname or "redis"
        port = parsed.port or 6379
        self._target = f"{host}:{port}"

    def _note_down(self) -> None:
        if self._ok is not False:
            logger.warning("redis unavailable; continuing without a cache target=%s", self._target)
        self._ok = False

    @property
    def available(self) -> bool:
        return self._connect() is not None

    def get_json(self, key: str) -> Any | None:
        client = self._connect()
        if client is None:
            return None
        try:
            raw = client.get(key)
        except redis.RedisError:
            self._note_down()
            return None
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def set_json(self, key: str, value: Any, ttl: int) -> None:
        client = self._connect()
        if client is None:
            return
        payload = json.dumps(value)
        try:
            if ttl > 0:
                client.set(key, payload, ex=ttl)
            else:
                client.set(key, payload)
        except redis.RedisError:
            self._note_down()

    def _connect(self) -> Any | None:
        if self._ok is False:
            return None
        if self._client is not None:
            return self._client
        try:
            client = redis.Redis.from_url(
                self._url,
                decode_responses=True,
                socket_connect_timeout=1,
                socket_timeout=2,
            )
            client.ping()
        except redis.RedisError:
            self._note_down()
            self._client = None
            return None
        self._client = client
        self._ok = True
        return client


def get_cache() -> RedisCache:
    global _cache
    if _cache is None or _cache.available is False:
        _cache = RedisCache(get_settings().redis_url)
    return _cache


def reset_cache() -> None:
    global _cache
    _cache = None
