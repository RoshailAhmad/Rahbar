"""Hosted free-tier provider (Groq, Google AI Studio, OpenRouter): OpenAI-compatible.

The key arrives as LLM_API_KEY from a Kubernetes Secret created on the command
line. It never appears in a file you commit, and never in a log line.
"""

from __future__ import annotations

import httpx

from ...config import Settings
from ...schemas import Answer, Passage
from .prompt import build_messages


class HostedProvider:
    name = "hosted"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings   # hosted_base_url, llm_model, llm_api_key, temperature
        self.client = httpx.Client(timeout=settings.llm_timeout_seconds)
        self.last_usage: tuple[int, int] = (0, 0)

    def generate(self, question: str, passages: list[Passage]) -> Answer:
        response = self.client.post(
            f"{self.settings.hosted_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {self.settings.llm_api_key}"},
            json={
                "model": self.settings.llm_model,
                "messages": build_messages(question, passages),
                "temperature": self.settings.temperature,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "Answer", "schema": Answer.model_json_schema()},
                },
            },
        )
        response.raise_for_status()
        body = response.json()
        usage = body.get("usage", {})
        self.last_usage = (int(usage.get("prompt_tokens", 0)),
                           int(usage.get("completion_tokens", 0)))
        return Answer.model_validate_json(body["choices"][0]["message"]["content"])
