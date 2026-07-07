"""Knowledge retrieval port + a shared hybrid scorer + an in-memory retriever.

``KnowledgeRetriever`` is the OS Core port. ``HybridScorer`` holds the v1 retrieval
*semantics* (AR-20260607): hybrid vector + lexical fused by Reciprocal Rank Fusion
(min-max normalized so relevance dominates), plus outcome/recency boosts as calibrated
tiebreakers, with an explainable ``score_breakdown`` per result. Both the in-memory
retriever and the SQL adapter feed the SAME scorer over already-filtered candidates,
so semantics are identical regardless of backend (the SQL adapter just applies the
structured filters in SQL and may push vector search into pgvector for performance).
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from agent_os_contracts import KnowledgeAsset, KnowledgeQuery, LifecycleState, RetrievalResult

from .. import embedding
from ..embedding import Embedder
from ..knowledge_memory import KnowledgeStorePort

__all__ = [
    "Candidate",
    "HybridScorer",
    "IndexingKnowledgeStore",
    "InMemoryKnowledgeRetriever",
    "KnowledgeRetriever",
    "outcome_to_score",
    "project_asset",
    "tokenize_content",
]


def tokenize_content(text: str) -> frozenset[str]:
    """Token set for lexical matching (shared by indexers and retrievers)."""
    return frozenset(embedding.tokenize(text))


# --- Shared asset->index projection (one source of truth for ALL backends) ---
#
# The KnowledgeAssetBuilder titles assets "[metric] question"; the projection parses
# the metric back out, uses the title as the searchable content, and folds the
# feedback-derived outcome into a [0,1] ranking weight. The persistence layer's
# default_projector delegates here so SQL and in-memory indexing stay semantically
# identical (AR-20260611).

_TITLE_METRIC = re.compile(r"^\[(?P<metric>[^\]]+)\]")

# Unknown outcomes are neutral; no outcome yet -> 0 (not adopted).
_OUTCOME_SCORES = {"adopted": 1.0, "rejected": 0.0}


def outcome_to_score(outcome: str | None) -> float:
    if outcome is None:
        return 0.0
    return _OUTCOME_SCORES.get(outcome, 0.5)


def project_asset(asset: KnowledgeAsset) -> dict[str, Any]:
    match = _TITLE_METRIC.match(asset.title)
    return {
        "metric_name": match.group("metric") if match else None,
        "content": asset.title,
        "outcome": asset.outcome,
        "outcome_score": outcome_to_score(asset.outcome),
    }


@dataclass(frozen=True)
class Candidate:
    """A pre-filtered candidate fed to the scorer (backend-agnostic).

    ``recency`` is any monotonic value (insertion seq or timestamp); the scorer
    normalizes it across the candidate set. ``outcome_score`` is the denormalized
    feedback weight projected at index time.
    """

    asset: KnowledgeAsset
    embedding: tuple[float, ...]
    tokens: frozenset[str]
    recency: float
    outcome_score: float


class HybridScorer:
    """Backend-agnostic hybrid scorer. Owns the v1 retrieval semantics."""

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
        self.embedder = embedder
        self._vw = vector_weight
        self._lw = lexical_weight
        self._ow = outcome_weight
        self._rw = recency_weight
        self._rrf_k = rrf_k

    def score(
        self, query: KnowledgeQuery, candidates: list[Candidate]
    ) -> tuple[RetrievalResult, ...]:
        if not candidates:
            return ()

        query_vec = self.embedder.embed(query.text)
        query_tokens = frozenset(embedding.tokenize(query.text))
        idx = list(range(len(candidates)))
        vector = {i: _cosine(query_vec, candidates[i].embedding) for i in idx}
        lexical = {i: _jaccard(query_tokens, candidates[i].tokens) for i in idx}

        vector_rank = _ranks(idx, vector)
        lexical_rank = _ranks(idx, lexical)
        rrf = {
            i: self._vw / (self._rrf_k + vector_rank[i])
            + self._lw / (self._rrf_k + lexical_rank[i])
            for i in idx
        }
        lo, hi = min(rrf.values()), max(rrf.values())
        spread = hi - lo
        max_recency = max(c.recency for c in candidates) or 1.0

        results: list[RetrievalResult] = []
        for i in idx:
            c = candidates[i]
            rrf_norm = 1.0 if spread == 0 else (rrf[i] - lo) / spread
            outcome_boost = self._ow * c.outcome_score
            recency_boost = self._rw * (c.recency / max_recency)
            total = rrf_norm + outcome_boost + recency_boost
            results.append(
                RetrievalResult(
                    asset=c.asset,
                    score=total,
                    score_breakdown={
                        "vector": vector[i],
                        "lexical": lexical[i],
                        "rrf": rrf[i],
                        "rrf_normalized": rrf_norm,
                        "outcome_boost": outcome_boost,
                        "recency_boost": recency_boost,
                        "total": total,
                    },
                )
            )

        results.sort(key=lambda r: r.score, reverse=True)
        return tuple(results[: query.k])


class KnowledgeRetriever(ABC):
    """Search the KnowledgeAsset memory, returning ranked, explainable results."""

    @abstractmethod
    def search(
        self, query: KnowledgeQuery, *, tenant_id: str = "default"
    ) -> tuple[RetrievalResult, ...]: ...


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
    tenant_id: str


class InMemoryKnowledgeRetriever(KnowledgeRetriever):
    """Dependency-free hybrid retriever over the shared scorer; pins v1 semantics.

    Structured fields not carried by ``KnowledgeAsset`` (metric_name, risk_level,
    outcome, outcome_score) are supplied at ``index`` time — mirroring the projected
    columns the persistence layer denormalizes. ``owner`` / ``lifecycle_state`` come
    from the asset.
    """

    def __init__(self, embedder: Embedder, **scorer_kwargs: float) -> None:
        self._scorer = HybridScorer(embedder, **scorer_kwargs)
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
        tenant_id: str = "default",
    ) -> None:
        content = text if text is not None else asset.title
        # One current entry per asset AND per trace: a version bump (new asset id,
        # same source_trace_id) replaces its predecessor — mirroring the SQL
        # knowledge_index, which keys on source_trace_id.
        self._entries = [
            e
            for e in self._entries
            if e.tenant_id != tenant_id
            or (
                e.asset.asset_id != asset.asset_id
                and not (
                    asset.source_trace_id is not None
                    and e.asset.source_trace_id == asset.source_trace_id
                )
            )
        ]
        self._seq += 1
        self._entries.append(
            _Entry(
                asset=asset,
                embedding=self._scorer.embedder.embed(content),
                tokens=tokenize_content(content),
                seq=self._seq,
                metric_name=metric_name,
                risk_level=risk_level,
                outcome=outcome,
                outcome_score=outcome_score,
                tenant_id=tenant_id,
            )
        )

    def search(
        self, query: KnowledgeQuery, *, tenant_id: str = "default"
    ) -> tuple[RetrievalResult, ...]:
        candidates = [
            Candidate(
                asset=e.asset,
                embedding=e.embedding,
                tokens=e.tokens,
                recency=float(e.seq),
                outcome_score=e.outcome_score,
            )
            for e in self._entries
            if e.tenant_id == tenant_id and self._matches(e, query)
        ]
        return self._scorer.score(query, candidates)

    @staticmethod
    def _matches(entry: _Entry, query: KnowledgeQuery) -> bool:
        if query.metric_name is not None and entry.metric_name != query.metric_name:
            return False
        if query.owner is not None and entry.asset.owner != query.owner:
            return False
        if query.risk_level is not None and entry.risk_level != query.risk_level:
            return False
        if query.lifecycle_state is not None:
            if entry.asset.state != query.lifecycle_state:
                return False
        elif (
            entry.asset.state
            not in {
                LifecycleState.ACTIVE,
                LifecycleState.PUBLISHED,
            }
            and entry.outcome != "adopted"
        ):
            return False
        if query.outcome is not None and entry.outcome != query.outcome:
            return False
        return True


class IndexingKnowledgeStore(KnowledgeStorePort):
    """KnowledgeStorePort decorator that indexes writes into an in-memory retriever.

    The dependency-free counterpart of the persistence layer's EmbeddingKnowledgeStore:
    register/register_version delegate to the wrapped store, then (re)index the stored
    asset via the shared projection, so the memory backend's runtime writes are
    immediately recallable/searchable. Assets without a trace are not retrievable
    memory and are skipped.
    """

    def __init__(self, base: KnowledgeStorePort, retriever: InMemoryKnowledgeRetriever) -> None:
        self._base = base
        self._retriever = retriever

    def register(self, asset: KnowledgeAsset, *, tenant_id: str = "default") -> KnowledgeAsset:
        stored = self._base.register(asset, tenant_id=tenant_id)
        self._index(stored, tenant_id=tenant_id)
        return stored

    def register_version(
        self, asset: KnowledgeAsset, *, tenant_id: str = "default"
    ) -> KnowledgeAsset:
        stored = self._base.register_version(asset, tenant_id=tenant_id)
        self._index(stored, tenant_id=tenant_id)
        return stored

    def get_by_trace(self, trace_id: str, *, tenant_id: str = "default") -> KnowledgeAsset | None:
        return self._base.get_by_trace(trace_id, tenant_id=tenant_id)

    def version_of(self, trace_id: str, *, tenant_id: str = "default") -> int:
        return self._base.version_of(trace_id, tenant_id=tenant_id)

    def all_assets(self, *, tenant_id: str = "default") -> tuple[KnowledgeAsset, ...]:
        return self._base.all_assets(tenant_id=tenant_id)

    def _index(self, asset: KnowledgeAsset, *, tenant_id: str = "default") -> None:
        if asset.source_trace_id is None:
            return
        proj = project_asset(asset)
        self._retriever.index(
            asset,
            text=proj["content"],
            metric_name=proj["metric_name"],
            outcome=proj["outcome"],
            outcome_score=proj["outcome_score"],
            tenant_id=tenant_id,
        )


def _cosine(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    # Embedder returns L2-normalized vectors, so cosine == dot product.
    return sum(x * y for x, y in zip(a, b))


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def _ranks(idx: list[int], scores: dict[int, float]) -> dict[int, int]:
    """1-based competition rank by score desc; equal scores share a rank (1,2,2,4...).

    Sharing a rank on ties matters: otherwise identical candidates get artificial
    rank gaps that min-max normalization amplifies, drowning the boosts.
    """
    order = sorted(idx, key=lambda i: scores[i], reverse=True)
    ranks: dict[int, int] = {}
    prev_score: float | None = None
    prev_rank = 0
    for position, i in enumerate(order, start=1):
        score = scores[i]
        if prev_score is not None and score == prev_score:
            ranks[i] = prev_rank
        else:
            ranks[i] = position
            prev_rank = position
            prev_score = score
    return ranks
