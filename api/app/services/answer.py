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
from ..providers.llm.prompt import build_messages
from .guards import abstention, declines_in_text, fallback, is_followup, valid_citations
from .trace import Trace, injection_pattern

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
        except Exception as exc:  # anything else: still never a 500
            log.exception("generation crashed", extra={"attempt": attempt,
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
                                page=p.page, score=p.score, text=p.text) for p in passages],
        provider=provider.name,
        cached=cached,
    )


def _chunk_ref(p: Passage) -> dict:
    return {"chunk_id": p.chunk_id, "doc_id": p.doc_id or p.source.rsplit(".", 1)[0],
            "source": p.source, "section": p.section, "page": p.page,
            "doc_version": p.doc_version, "score": round(p.score, 4)}


def answer_question(
    question: str, retriever: Retriever, provider: LLMProvider, settings: Settings
) -> AskResponse:
    """The query pipeline. Writes one trace record per call (Part D1), whatever the outcome."""
    tr = Trace(request_id_var.get(), question)
    tr.set(embedding={"model": settings.embed_model, "dimension": None},
           collection={"name": settings.collection, "index_version": None},
           model={"provider": provider.name, "name": settings.llm_model,
                  "temperature": settings.temperature, "seed": settings.llm_seed,
                  "num_ctx": settings.llm_num_ctx})
    try:
        response = _answer(question, retriever, provider, settings, tr)
    except Exception as exc:  # never lose the trace, never a 500 from here
        log.exception("pipeline crashed", extra={"error": f"{type(exc).__name__}: {exc}"})
        metrics.FALLBACKS.inc()
        tr.guardrail("output", "fallback", reason=f"{type(exc).__name__}")
        response = _response(fallback(), [], provider)
    tr.set(response={"answer": response.answer, "answered_from_context": response.answered_from_context,
                     "confidence": response.confidence, "cached": response.cached,
                     "citations": [c.model_dump() for c in response.citations],
                     "fallback": any(g["action"] == "fallback" for g in tr.record["guardrails"])})
    for stage, ms in tr.record["latency_ms"].items():
        metrics.STAGE.labels(stage=stage).observe(ms / 1000)
    tr.finish()
    return response


def _answer(question: str, retriever: Retriever, provider: LLMProvider, settings: Settings,
            tr: Trace) -> AskResponse:
    followup = is_followup(question)
    cache = get_cache(settings)
    embed: Any = getattr(retriever, "embed_query", None)   # only the real retriever has one
    vector: tuple[float, ...] | None = None
    index_version = ""

    # Input rail (D4): flag instructions hidden in the question. The question is still
    # answered: the prompt treats it as data and the output is schema-constrained.
    pattern = injection_pattern(question)
    if pattern:
        metrics.INJECTIONS.labels(rail="input").inc()
        tr.guardrail("input", "flagged", pattern=pattern)

    # 2. Semantic cache (never for follow-ups).
    if embed is not None and not followup:
        try:
            with tr.stage("embed"):
                vector = embed(question)
            index_version = retriever.index_version()  # type: ignore[attr-defined]
            tr.record["embedding"]["dimension"] = len(vector) if vector else None
            tr.record["collection"]["index_version"] = index_version
        except Exception as exc:
            log.warning("cache key unavailable", extra={"error": str(exc)})
        if vector is not None:
            with tr.stage("cache"):
                hit = cache.lookup(index_version, vector)
            if hit is not None:
                metrics.CACHE_HITS.inc()
                tr.set(cache={"hit": True, "similarity": round(hit[1], 4)})
                response = AskResponse(**{**hit[0], "request_id": request_id_var.get(),
                                          "cached": True})
                log.info("answered", extra={"cached": True, "similarity": round(hit[1], 4),
                                            "index_version": index_version})
                return response
            metrics.CACHE_MISSES.inc()
    tr.set(cache={"hit": False, "skipped": followup or vector is None})

    # 3-4. Retrieve.
    try:
        with metrics.RETRIEVAL.time(), tr.stage("retrieve"):
            passages = retriever.retrieve(question, k=settings.top_k)
    except Exception as exc:  # Chroma or the embedding call failed: answer safely
        log.exception("retrieval failed", extra={"error": f"{type(exc).__name__}: {exc}"})
        metrics.FALLBACKS.inc()
        tr.guardrail("output", "fallback", reason="retrieval failed")
        return _response(fallback(), [], provider)
    if passages:
        metrics.TOP1_SIMILARITY.observe(passages[0].score)

    # Retrieval rail (D4): a retrieved chunk that tries to instruct the model is kept out
    # of the prompt, and the action is written into the trace.
    clean: list[Passage] = []
    for p in passages:
        hit_pattern = injection_pattern(p.text)
        if hit_pattern:
            metrics.INJECTIONS.labels(rail="retrieval").inc()
            tr.guardrail("retrieval", "excluded_from_prompt", chunk_id=p.chunk_id,
                         doc_id=p.doc_id or p.source, pattern=hit_pattern)
        else:
            clean.append(p)
    # TOP_K passages are retrieved (and reported, so recall@5 can be measured), but only
    # the best LLM_PASSAGES that clear the relevance floor go to the model: a small model
    # on a CPU reads ~18 tokens/s, so every extra passage costs seconds.
    evidence = [p for p in clean if p.score >= settings.relevance_floor]
    evidence = evidence[:settings.llm_passages]
    tr.set(retrieval={"top_k": settings.top_k, "filter": getattr(retriever, "last_filter", None),
                      "relevance_floor": settings.relevance_floor, "reranker": None,
                      "chunks": [_chunk_ref(p) for p in passages],
                      "reranked_order": [p.chunk_id for p in passages],  # no reranker: retrieval order
                      "evidence_ids": [p.chunk_id for p in evidence]})

    # Relevance floor: abstain honestly instead of letting the model guess.
    used_fallback = False
    if not evidence:
        tr.guardrail("retrieval", "abstain_below_relevance_floor",
                     top_score=round(passages[0].score, 4) if passages else None)
        answer = abstention()
    else:
        tr.prompt(build_messages(question, evidence))
        with tr.stage("generate"):
            answer, used_fallback = _generate_with_retry(provider, question, evidence)
        usage = getattr(provider, "last_usage", None)
        if usage:
            tr.set(tokens={"in": usage[0], "out": usage[1]})
        if used_fallback:
            tr.guardrail("output", "fallback", reason="validation failed twice")
        kept, dropped = valid_citations(answer, evidence)
        if dropped:
            log.warning("dropped citations that match no retrieved passage",
                        extra={"dropped": dropped})
            tr.guardrail("output", "dropped_citations", count=dropped)
        answer = answer.model_copy(update={"citations": kept})
        # Grounding guards: an answer that admits the evidence does not cover the
        # question, or that cites nothing we retrieved, is not an answer from context.
        if answer.answered_from_context and (declines_in_text(answer.answer) or not kept):
            log.warning("ungrounded answer converted to an abstention",
                        extra={"self_declined": declines_in_text(answer.answer),
                               "valid_citations": len(kept)})
            tr.guardrail("output", "converted_to_abstention",
                         self_declined=declines_in_text(answer.answer), valid_citations=len(kept))
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
