"""Semantic deduper (U4) — cosine match, cache reuse, fail-closed propagation."""

from __future__ import annotations

import pytest

from wgmesh_pipeline.forge.dedup import SemanticDeduper
from wgmesh_pipeline.forge.embeddings import EmbeddingError


class FakeEmbedder:
    """Maps text -> vector; counts embed calls. Raises for text == 'BOOM'."""

    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self.vectors = vectors
        self.calls: list[str] = []

    def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        if text == "BOOM":
            raise EmbeddingError("boom")
        return self.vectors[text]


class FakeCache(dict):
    def get_post_embedding(self, post_id, model):
        return self.get((post_id, model))

    def put_post_embedding(self, post_id, model, vector):
        self[(post_id, model)] = list(vector)


def _deduper(embedder, cache, threshold=0.9):
    return SemanticDeduper(embedder, cache, model="m", threshold=threshold)


def test_similar_candidate_matches_post() -> None:
    emb = FakeEmbedder(
        {
            "lead capture form": [1.0, 0.0],
            "add email lead-capture\nbody": [0.99, 0.01],  # candidate
        }
    )
    posts = [{"id": "p1", "title": "lead capture form", "content": ""}]
    match = _deduper(emb, FakeCache()).find_duplicate("add email lead-capture\nbody", posts)
    assert match is not None and match["id"] == "p1"


def test_distinct_candidate_no_match() -> None:
    emb = FakeEmbedder(
        {"android vpn": [0.0, 1.0], "pricing decision\nbody": [1.0, 0.0]}
    )
    posts = [{"id": "p1", "title": "android vpn", "content": ""}]
    assert _deduper(emb, FakeCache()).find_duplicate("pricing decision\nbody", posts) is None


def test_cache_hit_skips_re_embedding_the_post() -> None:
    emb = FakeEmbedder({"cand": [1.0, 0.0]})
    cache = FakeCache()
    cache.put_post_embedding("p1", "m", [1.0, 0.0])  # pre-cached
    posts = [{"id": "p1", "title": "x", "content": ""}]

    match = _deduper(emb, cache).find_duplicate("cand", posts)

    assert match["id"] == "p1"
    assert emb.calls == ["cand"]  # only the candidate embedded, not the post


def test_cache_miss_embeds_and_stores_post() -> None:
    emb = FakeEmbedder({"cand": [1.0, 0.0], "post1 title\npost body": [1.0, 0.0]})
    cache = FakeCache()
    posts = [{"id": "p1", "title": "post1 title", "content": "post body"}]

    _deduper(emb, cache).find_duplicate("cand", posts)

    assert cache.get_post_embedding("p1", "m") == [1.0, 0.0]


def test_embeddings_failure_propagates() -> None:
    emb = FakeEmbedder({})
    with pytest.raises(EmbeddingError):
        _deduper(emb, FakeCache()).find_duplicate("BOOM", [{"id": "p1"}])


def test_picks_highest_similarity_above_threshold() -> None:
    emb = FakeEmbedder(
        {
            "cand": [1.0, 0.0],
            "near": [0.95, 0.31],   # ~0.95 cosine
            "nearer": [0.99, 0.14], # ~0.99 cosine
        }
    )
    posts = [
        {"id": "near", "title": "near", "content": ""},
        {"id": "nearer", "title": "nearer", "content": ""},
    ]
    match = _deduper(emb, FakeCache(), threshold=0.9).find_duplicate("cand", posts)
    assert match["id"] == "nearer"
