"""Cosine similarity for semantic dedup (U3).

Pure vector math, no I/O — the precision/recall gate for the Build-Suggestion
dedup. A duplicate is a post whose embedding is at least ``threshold`` cosine to
the candidate's. Zero-norm vectors return 0.0 (never a divide error), so a bad
embedding degrades to "not similar" rather than crashing the dedup pass.
"""

from __future__ import annotations

import math
from typing import Sequence


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity of two equal-length vectors in [-1, 1]. Mismatched
    lengths or a zero-norm vector → 0.0 (treated as dissimilar, not an error)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def is_similar(
    a: Sequence[float], b: Sequence[float], threshold: float
) -> bool:
    """True iff ``cosine(a, b) >= threshold`` — the duplicate decision."""
    return cosine(a, b) >= threshold
