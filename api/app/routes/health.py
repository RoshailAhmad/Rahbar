"""Liveness and readiness (section 4.3). They answer different questions.

/healthz  is the process alive?           Touches nothing. Liveness probe.
/readyz   can this pod take traffic now?  Checks Chroma, the index and Redis. Readiness probe.

/readyz is also where the embedding pin is enforced (section 4.4): the indexer writes
`embed_model` into the collection metadata, and a pod whose EMBED_MODEL disagrees with
it refuses to become ready and logs both values, instead of silently serving garbage.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, Request, Response

router = APIRouter()
log = logging.getLogger("rahbar.api.health")


@router.get("/healthz")
def healthz() -> dict[str, str]:
    """Is the process alive? Must never touch Chroma, Redis or the LLM."""
    return {"status": "alive"}


def _collection(settings: Any) -> Any:
    """The index collection, read-only. Raises if Chroma or the collection is missing."""
    import chromadb
    from chromadb.config import Settings as ChromaSettings

    client = chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port,
                                 settings=ChromaSettings(anonymized_telemetry=False))
    return client.get_collection(settings.collection)


def _check_redis() -> tuple[str, str | None]:
    try:
        import redis

        client = redis.Redis(host=os.environ.get("REDIS_HOST", "redis"),
                             port=int(os.environ.get("REDIS_PORT", 6379)),
                             socket_connect_timeout=1, socket_timeout=1)
        client.ping()
    except Exception as exc:
        return "fail", f"redis: {type(exc).__name__}: {exc}"
    return "ok", None


@router.get("/readyz")
def readyz(request: Request, response: Response) -> dict[str, object]:
    """200 only if Chroma is reachable, the collection is non-empty, its embedding model
    matches EMBED_MODEL, and Redis is reachable. Otherwise 503 naming what failed."""
    settings = request.app.state.settings
    failures: list[str] = []
    checks: dict[str, str] = {}

    try:
        collection = _collection(settings)
        chunks = collection.count()
        metadata = collection.metadata or {}
    except Exception as exc:  # Chroma unreachable, or the indexer has not run yet
        failures.append(f"chroma: {type(exc).__name__}: {exc}")
        checks["index"] = "fail"
    else:
        indexed_model = metadata.get("embed_model")
        if chunks == 0:
            failures.append(f"chroma: collection '{settings.collection}' is empty")
        if indexed_model != settings.embed_model:
            log.error(
                "embedding model mismatch: refusing to become ready",
                extra={"index_embed_model": indexed_model,
                       "api_embed_model": settings.embed_model,
                       "index_dimension": metadata.get("dimension"),
                       "collection": settings.collection},
            )
            failures.append(f"embedding model mismatch: index built with {indexed_model!r}, "
                            f"api EMBED_MODEL={settings.embed_model!r}")
        checks["index"] = f"{chunks} chunks, embed_model={indexed_model}"

    redis_status, redis_failure = _check_redis()
    checks["redis"] = redis_status
    if redis_failure:
        failures.append(redis_failure)

    if failures:
        response.status_code = 503
        return {"status": "not ready", "failed": failures, "checks": checks}
    return {"status": "ready", "checks": checks}
