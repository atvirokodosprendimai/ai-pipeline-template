"""z.ai text-embeddings client for semantic dedup (U1).

OpenAI-compatible embeddings shape (``POST {base}/embeddings`` with
``{model, input}`` → ``{data: [{embedding: [...]}]}``), reusing the box's
existing z.ai credential. The model id / base URL are config (``EMBEDDINGS_MODEL``
/ ``EMBEDDINGS_BASE_URL``) so the operator confirms them at deploy — VERIFY the
exact model + dimension against the live z.ai account before enabling semantic
dedup (``DEDUP_SEMANTIC_ENABLED``).

Fail-closed-loud: a non-2xx or malformed response raises ``EmbeddingError``; the
client never returns a zero/empty vector silently (the dedup caller degrades to
exact-title on the raise, so a swallowed failure would corrupt dedup instead).
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from wgmesh_pipeline.config import Config

USER_AGENT = "wgmesh-pipeline-embeddings/1"


class EmbeddingError(RuntimeError):
    """An embeddings request failed or returned a malformed body."""


@dataclass
class HttpResponse:
    status: int
    text: str


HttpCaller = Callable[[str, str, Mapping[str, str], bytes | None], HttpResponse]


def _default_http_caller(
    method: str, url: str, headers: Mapping[str, str], body: bytes | None
) -> HttpResponse:
    req = urllib.request.Request(url, data=body, method=method)
    for key, value in headers.items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return HttpResponse(resp.status, resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:  # type: ignore[attr-defined]
        return HttpResponse(exc.code, exc.read().decode("utf-8", "replace"))


class EmbeddingsClient:
    """Turns text into a vector via the z.ai embeddings endpoint."""

    def __init__(self, config: Config, *, http_caller: HttpCaller | None = None):
        self._key = config.zai_api_key
        if not self._key:
            raise EmbeddingError("ZAI_API_KEY is required for semantic dedup embeddings")
        self._base = config.embeddings_base_url.rstrip("/")
        self._model = config.embeddings_model
        self._http = http_caller or _default_http_caller

    def embed(self, text: str) -> list[float]:
        if not text or not text.strip():
            raise EmbeddingError("cannot embed empty text")
        body = json.dumps({"model": self._model, "input": text}).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }
        resp = self._http("POST", f"{self._base}/embeddings", headers, body)
        if not 200 <= resp.status < 300:
            raise EmbeddingError(
                f"embeddings {self._model} returned {resp.status}: {(resp.text or '')[:200]}"
            )
        return _vector_from(resp.text)


def _vector_from(text: str) -> list[float]:
    try:
        parsed: Any = json.loads(text)
    except ValueError as exc:
        raise EmbeddingError("embeddings response was not JSON") from exc
    data = parsed.get("data") if isinstance(parsed, dict) else None
    if not isinstance(data, list) or not data:
        raise EmbeddingError("embeddings response missing 'data' array")
    vector = data[0].get("embedding") if isinstance(data[0], dict) else None
    if not isinstance(vector, list) or not vector:
        raise EmbeddingError("embeddings response missing 'embedding' vector")
    try:
        return [float(x) for x in vector]
    except (TypeError, ValueError) as exc:
        raise EmbeddingError("embedding vector held a non-numeric value") from exc
