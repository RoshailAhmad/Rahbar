"""Prometheus metrics at /metrics (section 4.8).

Request count and latency are wired up already. Add your own the same way:
retrieval latency, generation latency, cache hits, abstentions, fallbacks, tokens.
"""

from __future__ import annotations

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

router = APIRouter()

REQUESTS = Counter("rahbar_requests_total", "HTTP requests", ["path", "status"])
LATENCY = Histogram(
    "rahbar_request_seconds",
    "HTTP request latency",
    ["path"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
)


@router.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

# Query pipeline metrics (section 4.8).
RETRIEVAL = Histogram("rahbar_retrieval_seconds", "Retrieval latency (embed + Chroma query)",
                      buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5))
GENERATION = Histogram("rahbar_generation_seconds", "LLM generation latency",
                       buckets=(0.5, 1, 2, 5, 10, 20, 30, 60, 120))
CACHE_HITS = Counter("rahbar_cache_hits_total", "Semantic cache hits")
CACHE_MISSES = Counter("rahbar_cache_misses_total", "Semantic cache misses")
ABSTENTIONS = Counter("rahbar_abstentions_total", "Answers declined: corpus does not cover it")
FALLBACKS = Counter("rahbar_fallbacks_total", "Canned responses after a failed retry")
TOKENS_IN = Counter("rahbar_tokens_in_total", "Prompt tokens sent to the LLM")
TOKENS_OUT = Counter("rahbar_tokens_out_total", "Completion tokens received from the LLM")
