"""Cosine similarity matcher (U3) — the dedup precision gate."""

from __future__ import annotations

from wgmesh_pipeline.forge.similarity import cosine, is_similar


def test_identical_vectors_are_cosine_one() -> None:
    v = [1.0, 2.0, 3.0]
    assert cosine(v, list(v)) == 1.0
    assert is_similar(v, list(v), 0.99) is True


def test_orthogonal_vectors_are_zero() -> None:
    assert cosine([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert is_similar([1.0, 0.0], [0.0, 1.0], 0.5) is False


def test_threshold_flips_is_similar() -> None:
    a = [1.0, 0.0]
    b = [1.0, 1.0]  # cosine = 1/sqrt(2) ≈ 0.707
    assert is_similar(a, b, 0.70) is True
    assert is_similar(a, b, 0.71) is False


def test_zero_vector_is_dissimilar_not_crash() -> None:
    assert cosine([0.0, 0.0], [1.0, 2.0]) == 0.0
    assert is_similar([0.0, 0.0], [1.0, 2.0], 0.0) is True  # 0.0 >= 0.0


def test_mismatched_length_is_zero() -> None:
    assert cosine([1.0, 2.0], [1.0]) == 0.0


def test_empty_vectors_are_zero() -> None:
    assert cosine([], []) == 0.0
