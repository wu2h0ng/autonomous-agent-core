"""Write-side embedding decorator + SQL hybrid retriever (persistence layer).

Per AR-20260607 the re-embed cascade lives HERE, not in OS Core: `EmbeddingKnowledgeStore`
wraps any `KnowledgeStorePort`, and after a write computes the embedding (via the OS Core
`Embedder` adapter) and maintains the `knowledge_index` projection row. `SqlKnowledgeRetriever`
applies structured filters in SQL (indexed projected columns, never JSON scans) and ranks the
filtered candidates with the SAME `HybridScorer` the in-memory retriever uses — so semantics are
identical across backends. (pgvector `<=>` + HNSW can later push vector search into the DB for
performance without changing semantics.)
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from agent_os_contracts import KnowledgeAsset, KnowledgeQuery, RetrievalResult
from agent_os_core import (
    Candidate,
    Embedder,
    HybridScorer,
    KnowledgeRetriever,
    KnowledgeStorePort,
    tokenize_content,
)
from sqlalchemy import Connection, Engine, select

from . import mappers, schema


@contextmanager
def _write(bind: Engine | Connection) -> Iterator[Connection]:
    """Yield a connection for writes: reuse a caller-owned Connection (unit of work)
    or open a short transaction on an Engine."""
    if isinstance(bind, Connection):
        yield bind
    else:
        with bind.begin() as conn:
            yield conn


# Projection: derive index columns from an asset. Default parses the metric from the
# KnowledgeAssetBuilder title convention "[metric] question"; owner/lifecycle come from
# the asset; outcome comes from the asset's feedback-folded `outcome` field.
Projector = Callable[[KnowledgeAsset], dict[str, Any]]

_TITLE_METRIC = re.compile(r"^\[(?P<metric>[^\]]+)\]")

# Maps a feedback outcome to a [0,1] weight used by HybridScorer.outcome_boost.
# Unknown outcomes are treated as neutral; no outcome yet -> 0 (not adopted).
_OUTCOME_SCORES = {"adopted": 1.0, "rejected": 0.0}


def outcome_to_score(outcome: str | None) -> float:
    if outcome is None:
        return 0.0
    return _OUTCOME_SCORES.get(outcome, 0.5)


def default_projector(asset: KnowledgeAsset) -> dict[str, Any]:
    match = _TITLE_METRIC.match(asset.title)
    return {
        "metric_name": match.group("metric") if match else None,
        "content": asset.title,
        "outcome": asset.outcome,
        "outcome_score": outcome_to_score(asset.outcome),
    }


class EmbeddingKnowledgeStore(KnowledgeStorePort):
    """KnowledgeStorePort decorator that maintains the knowledge_index on writes."""

    def __init__(
        self,
        base: KnowledgeStorePort,
        embedder: Embedder,
        bind: Engine | Connection,
        *,
        projector: Projector = default_projector,
    ) -> None:
        self._base = base
        self._embedder = embedder
        self._bind = bind
        self._projector = projector

    # --- KnowledgeStorePort: storage delegates to base, then (re)index ---

    def register(self, asset: KnowledgeAsset) -> KnowledgeAsset:
        stored = self._base.register(asset)
        # Index the asset now associated with the trace (dedup may return an existing one).
        self._reindex(stored)
        return stored

    def register_version(self, asset: KnowledgeAsset) -> KnowledgeAsset:
        stored = self._base.register_version(asset)
        self._reindex(stored)
        return stored

    def get_by_trace(self, trace_id: str) -> KnowledgeAsset | None:
        return self._base.get_by_trace(trace_id)

    def version_of(self, trace_id: str) -> int:
        return self._base.version_of(trace_id)

    def all_assets(self) -> tuple[KnowledgeAsset, ...]:
        return self._base.all_assets()

    # --- indexing ---

    def _reindex(self, asset: KnowledgeAsset) -> None:
        # Index is keyed by source_trace_id (one current row per trace). Assets without
        # a trace are not retrievable memory and are skipped.
        if asset.source_trace_id is None:
            return
        proj = self._projector(asset)
        content = proj.get("content") or asset.title
        table = schema.knowledge_index
        values = {
            "source_trace_id": asset.source_trace_id,
            "asset_id": asset.asset_id,
            "metric_name": proj.get("metric_name"),
            "owner": asset.owner,
            "risk_level": proj.get("risk_level"),
            "lifecycle_state": asset.state.value,
            "outcome": proj.get("outcome"),
            "outcome_score": float(proj.get("outcome_score") or 0.0),
            "content": content,
            "embedding": list(self._embedder.embed(content)),
            "asset_payload": mappers.knowledge_to_payload(asset),
        }
        with _write(self._bind) as conn:
            conn.execute(table.delete().where(table.c.source_trace_id == asset.source_trace_id))
            conn.execute(table.insert().values(**values))


class SqlKnowledgeRetriever(KnowledgeRetriever):
    """Hybrid retriever: structured filters in SQL, ranking via the shared scorer."""

    def __init__(self, engine: Engine, scorer: HybridScorer) -> None:
        self._engine = engine
        self._scorer = scorer

    def search(self, query: KnowledgeQuery) -> tuple[RetrievalResult, ...]:
        t = schema.knowledge_index
        stmt = select(t.c.id, t.c.asset_payload, t.c.content, t.c.embedding, t.c.outcome_score)
        # Structured filters resolve to indexed-column predicates (never JSON scans).
        if query.metric_name is not None:
            stmt = stmt.where(t.c.metric_name == query.metric_name)
        if query.owner is not None:
            stmt = stmt.where(t.c.owner == query.owner)
        if query.risk_level is not None:
            stmt = stmt.where(t.c.risk_level == query.risk_level)
        if query.lifecycle_state is not None:
            stmt = stmt.where(t.c.lifecycle_state == query.lifecycle_state.value)
        if query.outcome is not None:
            stmt = stmt.where(t.c.outcome == query.outcome)

        with self._engine.connect() as conn:
            rows = conn.execute(stmt).fetchall()

        candidates = [
            Candidate(
                asset=mappers.knowledge_from_payload(row.asset_payload),
                embedding=tuple(row.embedding),
                tokens=tokenize_content(row.content),
                recency=float(row.id),
                outcome_score=float(row.outcome_score),
            )
            for row in rows
        ]
        return self._scorer.score(query, candidates)
