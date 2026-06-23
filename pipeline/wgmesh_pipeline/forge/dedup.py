"""Semantic Build-Suggestion deduper (U4).

Decides whether a candidate post duplicates any existing board post by cosine
similarity of their embeddings, not exact-title equality. Each post's vector is
cached (by post id + model) so a dedup pass embeds only the candidate plus any
posts missing a cached vector. An embeddings failure propagates ``EmbeddingError``
so the forge can degrade to exact-title — this class never swallows it.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol, Sequence

from wgmesh_pipeline.forge.similarity import cosine


class _Embedder(Protocol):
    def embed(self, text: str) -> list[float]: ...


class _Cache(Protocol):
    def get_post_embedding(self, post_id: str, model: str) -> list[float] | None: ...
    def put_post_embedding(
        self, post_id: str, model: str, vector: list[float]
    ) -> None: ...


def post_text(post: Mapping[str, Any]) -> str:
    """The text embedded for a post — title plus body (the brief carries the
    intent a title abbreviates)."""
    title = str(post.get("title") or "")
    body = str(post.get("content") or "")
    return f"{title}\n{body}".strip()


class SemanticDeduper:
    def __init__(
        self,
        embedder: _Embedder,
        cache: _Cache,
        *,
        model: str,
        threshold: float,
    ) -> None:
        self._embedder = embedder
        self._cache = cache
        self._model = model
        self._threshold = threshold

    def find_duplicate(
        self, candidate_text: str, posts: Sequence[Mapping[str, Any]]
    ) -> Mapping[str, Any] | None:
        """The existing post most similar to ``candidate_text`` at or above the
        threshold, or None. Raises ``EmbeddingError`` (from the embedder) on an
        embeddings failure — the caller degrades to exact-title."""
        candidate = self._embedder.embed(candidate_text)
        best: Mapping[str, Any] | None = None
        best_sim = -1.0
        for post in posts:
            post_id = str(post.get("id") or "")
            if not post_id:
                continue
            vector = self._cache.get_post_embedding(post_id, self._model)
            if vector is None:
                vector = self._embedder.embed(post_text(post))
                self._cache.put_post_embedding(post_id, self._model, vector)
            sim = cosine(candidate, vector)
            if sim >= self._threshold and sim > best_sim:
                best, best_sim = post, sim
        return best
