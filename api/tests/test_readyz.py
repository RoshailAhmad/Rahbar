"""Readiness and the embedding-pin guardrail (sections 4.3, 4.4), with no cluster."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.routes import health


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("RETRIEVER", "stub")
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    monkeypatch.setenv("EMBED_MODEL", "nomic-embed-text")
    from app.main import app

    with TestClient(app) as c:
        yield c


class _FakeCollection:
    def __init__(self, count: int, model: str) -> None:
        self._count, self.metadata = count, {"embed_model": model, "dimension": 768}

    def count(self) -> int:
        return self._count


def _fake_chroma(monkeypatch: pytest.MonkeyPatch, count: int, model: str) -> None:
    import chromadb

    class FakeClient:
        def __init__(self, *a: object, **k: object) -> None: ...

        def get_collection(self, name: str) -> _FakeCollection:
            return _FakeCollection(count, model)

    monkeypatch.setattr(chromadb, "HttpClient", FakeClient)
    monkeypatch.setattr(health, "_check_redis", lambda: ("ok", None))


def test_ready_when_index_matches(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_chroma(monkeypatch, 10, "nomic-embed-text")
    r = client.get("/readyz")
    assert r.status_code == 200, r.json()


def test_not_ready_on_embedding_mismatch(client: TestClient,
                                         monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_chroma(monkeypatch, 10, "dummy-768")
    r = client.get("/readyz")
    assert r.status_code == 503
    assert "mismatch" in r.json()["failed"][0]


def test_not_ready_on_empty_collection(client: TestClient,
                                       monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_chroma(monkeypatch, 0, "nomic-embed-text")
    r = client.get("/readyz")
    assert r.status_code == 503
    assert "empty" in r.json()["failed"][0]


def test_liveness_never_checks_dependencies(client: TestClient,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_chroma(monkeypatch, 0, "wrong")
    assert client.get("/healthz").status_code == 200
