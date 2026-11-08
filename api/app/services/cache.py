"""Semantic cache in Redis (section 3.3; the choice is defended in docs/adr/0003).

- A hit is cosine similarity >= CACHE_THRESHOLD between the new question's embedding
  and a cached question's embedding.
- Entries live under a key that includes the index_version the indexer wrote, so a
  re-index invalidates the whole cache at once: new questions look under the new key,
  and the old key simply expires (TTL).
- The never-cache rules live in answer.py (follow-ups, abstentions, fallbacks,
  anything that failed validation).
- Fail open: if Redis is down the service keeps answering, just without a cache.
"""

from __future__ import annotations

import json
import logging
import math
import time
from collections.abc import Sequence
from typing import Any

from ..config import Settings

log = logging.getLogger("rahbar.cache")
MAX_ENTRIES = 500          # per index_version; a linear scan of 500 vectors is ~1 ms
RETRY_AFTER_SECONDS = 30   # after a Redis failure, skip the cache for this long


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class SemanticCache:
    def __init__(self, settings: Settings, client: Any = None) -> None:
        self.threshold = settings.cache_threshold
        self.ttl = settings.cache_ttl_seconds
        self._settings = settings
        self._client = client
        self._down_until = 0.0

    def _redis(self) -> Any:
        if self._client is None:
            import redis

            self._client = redis.Redis(host=self._settings.redis_host,
                                       port=self._settings.redis_port,
                                       socket_connect_timeout=0.5, socket_timeout=0.5)
        return self._client

    @staticmethod
    def key(index_version: str) -> str:
        return f"rahbar:cache:{index_version}"

    def _available(self) -> bool:
        return time.monotonic() >= self._down_until

    def _failed(self, exc: Exception) -> None:
        self._down_until = time.monotonic() + RETRY_AFTER_SECONDS
        log.warning("cache unavailable, answering without it", extra={"error": str(exc)})

    def lookup(self, index_version: str, vector: Sequence[float]) -> tuple[dict[str, Any], float] | None:
        """The best cached response at or above the threshold, with its similarity."""
        if not self._available():
            return None
        try:
            raw = self._redis().lrange(self.key(index_version), 0, MAX_ENTRIES - 1)
        except Exception as exc:
            self._failed(exc)
            return None
        best: tuple[dict[str, Any], float] | None = None
        for item in raw:
            entry = json.loads(item)
            score = cosine(vector, entry["vector"])
            if score >= self.threshold and (best is None or score > best[1]):
                best = (entry["response"], score)
        return best

    def store(self, index_version: str, vector: Sequence[float], question: str,
              response: dict[str, Any]) -> None:
        if not self._available():
            return
        entry = json.dumps({"question": question, "vector": list(vector), "response": response})
        try:
            pipe = self._redis().pipeline()
            key = self.key(index_version)
            pipe.lpush(key, entry)
            pipe.ltrim(key, 0, MAX_ENTRIES - 1)
            pipe.expire(key, self.ttl)
            pipe.execute()
        except Exception as exc:
            self._failed(exc)
