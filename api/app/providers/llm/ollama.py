"""Ollama provider: ollama-host or ollama-incluster (section 3.5)."""

from __future__ import annotations

import httpx

from ...config import Settings
from ...schemas import Answer, Passage
from .prompt import build_messages


class OllamaProvider:
    name = "ollama"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings   # ollama_url, llm_model, temperature
        self.client = httpx.Client(timeout=settings.llm_timeout_seconds)
        self.last_usage: tuple[int, int] = (0, 0)   # (tokens in, tokens out), for metrics

    def generate(self, question: str, passages: list[Passage]) -> Answer:
        """One call. Raises httpx.HTTPError or pydantic.ValidationError on failure; the
        retry and the fallback live in services/answer.py."""
        response = self.client.post(
            f"{self.settings.ollama_url}/api/chat",
            json={
                "model": self.settings.llm_model,
                "messages": build_messages(question, passages),
                "stream": False,
                # Constrained decoding: Ollama only emits JSON matching this schema.
                "format": Answer.model_json_schema(),
                # 4096 fits instructions + TOP_K=3 chunks; a bigger window costs RAM and,
                # on a small laptop, swapping. Raise LLM_NUM_CTX if TOP_K goes up.
                "options": {"temperature": self.settings.temperature,
                            "num_ctx": self.settings.llm_num_ctx},
            },
        )
        response.raise_for_status()
        body = response.json()
        self.last_usage = (int(body.get("prompt_eval_count", 0)), int(body.get("eval_count", 0)))
        # Structure is enforced above; we still validate, because truth is not.
        return Answer.model_validate_json(body["message"]["content"])
