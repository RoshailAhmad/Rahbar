"""Turns a question into an AskResponse: the query pipeline (section 3.2).

1. validate (FastAPI + AskRequest: 3 to 500 characters)
2. cache check (skipped for follow-ups)
3-4. embed + retrieve (in the retriever; superseded documents filtered there)
   relevance floor: nothing relevant -> honest abstention, no model call
5-6. augment + generate (the provider; schema-constrained, low temperature)
7. validate: one retry, then a safe fallback - never a 500
   citation check: drop any citation that does not match a retrieved passage
8. cache the turn if it is safe to cache
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from pydantic import ValidationError

from ..config import Settings
from ..logjson import request_id_var
from ..providers.llm.base import LLMProvider
from ..retrieval.base import Retriever
from ..routes import metrics
from ..schemas import Answer, AskResponse, Passage, RetrievedRef
from .cache import SemanticCache
from .guards import abstention, declines_in_text, fallback, is_followup, valid_citations

log = logging.getLogger("rahbar.answer")
_cache: SemanticCache | None = None


def get_cache(settings: Settings) -> SemanticCache:
    global _cache
    if _cache is None:
        _cache = SemanticCache(settings)
    return _cache


def _generate_with_retry(provider: LLMProvider, question: str,
                         passages: list[Passage]) -> tuple[Answer, bool]:
    """(answer, used_fallback). Retry once on a malformed or failed reply."""
    for attempt in (1, 2):
        try:
            with metrics.GENERATION.time():
                answer = provider.generate(question, passages)
            usage = getattr(provider, "last_usage", (0, 0))
            metrics.TOKENS_IN.inc(usage[0])
            metrics.TOKENS_OUT.inc(usage[1])
            return answer, False
        except (ValidationError, ValueError, KeyError, httpx.HTTPError) as exc:
            log.warning("generation failed", extra={"attempt": attempt,
                                                    "error": f"{type(exc).__name__}: {exc}"})
    metrics.FALLBACKS.inc()
    return fallback(), True


def _response(answer: Answer, passages: list[Passage], provider: LLMProvider,
              cached: bool = False) -> AskResponse:
    return AskResponse(
        request_id=request_id_var.get(),
        answer=answer.answer,                  # `reasoning` is never sent to the user
        citations=answer.citations,
        answered_from_context=answer.answered_from_context,
        confidence=answer.confidence,
        retrieved=[RetrievedRef(chunk_id=p.chunk_id, source=p.source, section=p.section,
                                page=p.page, score=p.score) for p in passages],
        provider=provider.name,
        cached=cached,
    )


def answer_question(
    question: str, retriever: Retriever, provider: LLMProvider, settings: Settings
) -> AskResponse:
    followup = is_followup(question)
    cache = get_cache(settings)
    embed: Any = getattr(retriever, "embed_query", None)   # only the real retriever has one
    vector: tuple[float, ...] | None = None
    index_version = ""

    # 2. Semantic cache (never for follow-ups).
    if embed is not None and not followup:
        try:
            vector = embed(question)
            index_version = retriever.index_version()  # type: ignore[attr-defined]
        except Exception as exc:
            log.warning("cache key unavailable", extra={"error": str(exc)})
        if vector is not None:
            hit = cache.lookup(index_version, vector)
            if hit is not None:
                metrics.CACHE_HITS.inc()
                response = AskResponse(**{**hit[0], "request_id": request_id_var.get(),
                                          "cached": True})
                log.info("answered", extra={"cached": True, "similarity": round(hit[1], 4),
                                            "index_version": index_version})
                return response
            metrics.CACHE_MISSES.inc()

    # 3-4. Retrieve.
    with metrics.RETRIEVAL.time():
        passages = retriever.retrieve(question, k=settings.top_k)
    evidence = [p for p in passages if p.score >= settings.relevance_floor]

    # Relevance floor: abstain honestly instead of letting the model guess.
    used_fallback = False
    if not evidence:
        answer = abstention()
    else:
        answer, used_fallback = _generate_with_retry(provider, question, evidence)
        kept, dropped = valid_citations(answer, evidence)
        if dropped:
            log.warning("dropped citations that match no retrieved passage",
                        extra={"dropped": dropped})
        answer = answer.model_copy(update={"citations": kept})
        # Grounding guards: an answer that admits the evidence does not cover the
        # question, or that cites nothing we retrieved, is not an answer from context.
        if answer.answered_from_context and (declines_in_text(answer.answer) or not kept):
            log.warning("ungrounded answer converted to an abstention",
                        extra={"self_declined": declines_in_text(answer.answer),
                               "valid_citations": len(kept)})
            answer = abstention()
        if not answer.answered_from_context:
            # A decline cites nothing and is never "high confidence".
            answer = answer.model_copy(update={"citations": [], "confidence": "low"})

    abstained = not answer.answered_from_context and not used_fallback
    if abstained:
        metrics.ABSTENTIONS.inc()

    response = _response(answer, passages, provider)

    # 8. Cache only validated, grounded, standalone answers. Never abstentions,
    # fallbacks, follow-ups or anything that failed validation: a cached mistake is
    # served to everyone.
    safe_to_cache = (vector is not None and not followup and not used_fallback
                     and answer.answered_from_context and bool(answer.citations))
    if safe_to_cache and vector is not None:
        cache.store(index_version, vector, question,
                    response.model_dump(exclude={"request_id", "cached"}))

    log.info(
        "answered",
        extra={
            "retriever": retriever.name, "provider": provider.name, "top_k": settings.top_k,
            "chunk_ids": [p.chunk_id for p in passages],
            "scores": [round(p.score, 4) for p in passages],
            "answered_from_context": answer.answered_from_context,
            "abstained": abstained, "fallback": used_fallback, "cached": False,
            "followup": followup, "citations": len(answer.citations),
        },
    )
    return response
