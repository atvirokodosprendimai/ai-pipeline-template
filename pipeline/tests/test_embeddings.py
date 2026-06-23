"""z.ai embeddings client (U1) — fail-closed against the OpenAI-compatible shape."""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from wgmesh_pipeline.forge.embeddings import (
    EmbeddingError,
    EmbeddingsClient,
    HttpResponse,
)


@dataclass
class _Config:
    zai_api_key: str | None = "zai_key"
    embeddings_base_url: str = "https://api.z.ai/api/paas/v4"
    embeddings_model: str = "embedding-3"


def _client(response: HttpResponse):
    calls: list[dict] = []

    def caller(method, url, headers, body):
        calls.append(
            {"method": method, "url": url, "body": json.loads(body) if body else None}
        )
        return response

    return EmbeddingsClient(_Config(), http_caller=caller), calls


def test_embed_returns_vector_and_posts_model_input() -> None:
    body = json.dumps({"data": [{"embedding": [0.1, 0.2, 0.3]}]})
    client, calls = _client(HttpResponse(200, body))

    vec = client.embed("hello world")

    assert vec == [0.1, 0.2, 0.3]
    assert calls[0]["url"].endswith("/embeddings")
    assert calls[0]["body"] == {"model": "embedding-3", "input": "hello world"}


def test_missing_key_raises_at_construction() -> None:
    with pytest.raises(EmbeddingError, match="ZAI_API_KEY"):
        EmbeddingsClient(_Config(zai_api_key=None), http_caller=lambda *a: None)


def test_empty_text_raises() -> None:
    client, _ = _client(HttpResponse(200, json.dumps({"data": [{"embedding": [1.0]}]})))
    with pytest.raises(EmbeddingError, match="empty text"):
        client.embed("   ")


def test_non_2xx_raises() -> None:
    client, _ = _client(HttpResponse(429, "rate limited"))
    with pytest.raises(EmbeddingError, match="429"):
        client.embed("x")


def test_malformed_no_data_raises() -> None:
    client, _ = _client(HttpResponse(200, json.dumps({"ok": 1})))
    with pytest.raises(EmbeddingError, match="missing 'data'"):
        client.embed("x")


def test_malformed_no_vector_raises() -> None:
    client, _ = _client(HttpResponse(200, json.dumps({"data": [{"id": "x"}]})))
    with pytest.raises(EmbeddingError, match="missing 'embedding'"):
        client.embed("x")


def test_non_numeric_vector_raises() -> None:
    client, _ = _client(
        HttpResponse(200, json.dumps({"data": [{"embedding": ["a", "b"]}]}))
    )
    with pytest.raises(EmbeddingError, match="non-numeric"):
        client.embed("x")
