"""Knowledge retrieval port + an in-memory hybrid retriever.

``KnowledgeRetriever`` is the OS Core port. ``InMemoryKnowledgeRetriever`` pins the
v1 retrieval *semantics* (AR-20260607) with no DB: structured filters on projected
fields, hybrid vector + lexical scoring fused by Reciprocal Rank Fusion, plus
outcome/recency boosts — and every result carries an explainable ``score_breakdown``.
The SQL (pgvector + FTS) adapter implements the same port over the projected columns.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from agent_os_contracts import KnowledgeAsset, KnowledgeQuery, RetrievalResult

from .. import embedding
from ..embedding import Embedder

__all__ = ["KnowledgeRetriever", "InMemoryKnowledgeRetriever"]


class KnowledgeRetriever(ABC):
    """Search the KnowledgeAsset memory, returning ranked, explainable results."""

    @abstractmethod
    def search(self, query: KnowledgeQuery) -> tuple[RetrievalResult, ...]: ...


@dataclass
class _Entry:
    asset: KnowledgeAsset
    embedding: tuple[float, ...]
    tokens: frozenset[str]
    seq: int
    metric_name: str | None
    risk_level: str | None
    outcome: str | None
    outcome_score: float


class InMemoryKnowledgeRetriever(KnowledgeRetriever):
    """Dependency-free hybrid retriever; pins v1 retrieval semantics for tests/dev.

    Structured fields not carried by ``KnowledgeAsset`` (metric_name, risk_level,
    outcome, outcome_score) are supplied at ``index`` time — mirroring the projected
    columns the persistence layer denormalizes in the write path. ``owner`` and
    ``lifecycle_state`` come from the asset itself.
    """

    def __init__(
        self,
        embedder: Embedder,
        *,
        vector_weight: float = 1.0,
        lexical_weight: float = 1.0,
        outcome_weight: float = 0.25,
        recency_weight: float = 0.05,
        rrf_k: int = 60,
    ) -> None:
        self._embedder = embedder
        self._vw = vector_weight
        self._lw = lexical_weight
        self._ow = outcome_weight
        self._rw = recency_weight
        self._rrf_k = rrf_k
        self._entries: list[_Entry] = []
        self._seq = 0

    def index(
        self,
        asset: KnowledgeAsset,
        *,
        text: str | None = None,
        metric_name: str | None = None,
        risk_level: str | None = None,
        outcome: str | None = None,
        outcome_score: float = 0.0,
    ) -> None:
        """Add/refresh an asset in the index (re-indexing the same asset_id replaces it)."""
        content = text if text is not None else asset.title
        self._entries = [e for e in self._entries if e.asset.asset_id != asset.asset_id]
        self._seq += 1
        self._entries.append(
            _Entry(
                asset=asset,
                embedding=self._embedder.embed(content),
                tokens=frozenset(embedding.tokenize(content)),
                seq=self._seq,
                metric_name=metric_name,
                risk_level=risk_level,
                outcome=outcome,
                outcome_score=outcome_score,
            )
        )

    def search(self, query: KnowledgeQuery) -> tuple[RetrievalResult, ...]:
        candidates = [e for e in self._entries if self._matches(e, query)]
        if not candidates:
            return ()

        query_vec = self._embedder.embed(query.text)
        query_tokens = frozenset(embedding.tokenize(query.text))
        vector = {id(e): _cosine(query_vec, e.embedding) for e in candidates}
        lexical = {id(e): _jaccard(query_tokens, e.tokens) for e in candidates}

        vector_rank = _ranks(candidates, vector)
        lexical_rank = _ranks(candidates, lexical)
        max_seq = max(e.seq for e in candidates)

        # Reciprocal Rank Fusion of vector + lexical, then min-max normalized to
        # [0,1] so relevance dominates and the outcome/recency boosts act as
        # calibrated tiebreakers (raw RRF gaps are otherwise tiny).
        rrf = {
            id(e): self._vw / (self._rrf_k + vector_rank[id(e)])
            + self._lw / (self._rrf_k + lexical_rank[id(e)])
            for e in candidates
        }
        lo, hi = min(rrf.values()), max(rrf.values())
        spread = hi - lo

        results: list[RetrievalResult] = []
        for e in candidates:
            rrf_norm = 1.0 if spread == 0 else (rrf[id(e)] - lo) / spread
            outcome_boost = self._ow * e.outcome_score
            recency_boost = self._rw * (e.seq / max_seq)
            total = rrf_norm + outcome_boost + recency_boost
            results.append(
                RetrievalResult(
                    asset=e.asset,
                    score=total,
                    score_breakdown={
                        "vector": vector[id(e)],
                        "lexical": lexical[id(e)],
                        "rrf": rrf[id(e)],
                        "rrf_normalized": rrf_norm,
                        "outcome_boost": outcome_boost,
                        "recency_boost": recency_boost,
                        "total": total,
                    },
                )
            )

        results.sort(key=lambda r: r.score, reverse=True)
        return tuple(results[: query.k])

    @staticmethod
    def _matches(entry: _Entry, query: KnowledgeQuery) -> bool:
        if query.metric_name is not None and entry.metric_name != query.metric_name:
            return False
        if query.owner is not None and entry.asset.owner != query.owner:
            return False
        if query.risk_level is not None and entry.risk_level != query.risk_level:
            return False
        if query.lifecycle_state is not None and entry.asset.state != query.lifecycle_state:
            return False
        if query.outcome is not None and entry.outcome != query.outcome:
            return False
        return True


def _cosine(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    # Embedder returns L2-normalized vectors, so cosine == dot product.
    return sum(x * y for x, y in zip(a, b))


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a and not b:
        return 0.0
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def _ranks(candidates: list[_Entry], scores: dict[int, float]) -> dict[int, int]:
    """1-based competition rank by score desc; equal scores share a rank (1,2,2,4...).

    Sharing a rank on ties matters: otherwise identical candidates get artificial
    rank gaps that min-max normalization amplifies, drowning the boosts.
    """
    order = sorted(candidates, key=lambda e: scores[id(e)], reverse=True)
    ranks: dict[int, int] = {}
    prev_score: float | None = None
    prev_rank = 0
    for position, e in enumerate(order, start=1):
        score = scores[id(e)]
        if prev_score is not None and score == prev_score:
            ranks[id(e)] = prev_rank
        else:
            ranks[id(e)] = position
            prev_rank = position
            prev_score = score
    return ranks
