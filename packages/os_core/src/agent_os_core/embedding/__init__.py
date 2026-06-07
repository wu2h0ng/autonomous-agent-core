"""Embedding port + a dependency-free default embedder.

``Embedder`` is the pure contract OS Core depends on. Real ML embedders are
adapters wired via the Model Gateway (outside Core); ``HashingEmbedder`` is a
deterministic, dependency-free bag-of-words vectorizer (NOT a stub) so retrieval
is exercisable in dev/tests without a model — analogous to ``StaticQueryExecutor``.

Per AR-20260607: OS Core never invokes an embedder on the write path. Re-embedding
is a persistence-layer concern (``EmbeddingKnowledgeStore`` decorator).
"""

from __future__ import annotations

import hashlib
import math
import re
from abc import ABC, abstractmethod

__all__ = ["Embedder", "HashingEmbedder", "tokenize"]

_TOKEN = re.compile(r"[a-z0-9_]+")


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric/underscore tokenization (shared by embed + lexical)."""
    return _TOKEN.findall(text.lower())


class Embedder(ABC):
    """Maps text to a fixed-dimension vector. Pure contract; no model bound here."""

    @property
    @abstractmethod
    def model_id(self) -> str: ...

    @property
    @abstractmethod
    def dimensions(self) -> int: ...

    @abstractmethod
    def embed(self, text: str) -> tuple[float, ...]:
        """Return an L2-normalized embedding of ``text``."""
        ...


class HashingEmbedder(Embedder):
    """Deterministic hashing bag-of-words embedder (no external dependency).

    Tokens are hashed into ``dimensions`` buckets (counts), then L2-normalized so
    cosine similarity is meaningful. Deterministic: identical text -> identical
    vector. Suitable for dev/tests and as a real default; swap in an ML embedder
    adapter for production semantic quality.
    """

    def __init__(self, dimensions: int = 64) -> None:
        if dimensions <= 0:
            raise ValueError("dimensions must be positive")
        self._dimensions = dimensions

    @property
    def model_id(self) -> str:
        return f"hashing-bow-{self._dimensions}"

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def embed(self, text: str) -> tuple[float, ...]:
        vec = [0.0] * self._dimensions
        for token in tokenize(text):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % self._dimensions
            vec[bucket] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0.0:
            vec = [v / norm for v in vec]
        return tuple(vec)
