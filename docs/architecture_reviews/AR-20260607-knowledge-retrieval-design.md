# AR-20260607 Knowledge retrieval design (Phase 3)

> Status: **Proposed (design only — not implemented).** Sequels the persistent store
> (AR-20260606-persistent-store-design). Defines how the KnowledgeAsset corpus is searched/retrieved.
> Scope: retrieval over governed organizational decision memory. Out of scope (later/never): a
> standalone graph DB now, LLM graph-extraction pipelines, full agentic retrieval, opaque end-to-end
> neural retrieval.

## 1. Problem

`KnowledgeAsset` is not generic documents — it is **structured, governed, outcome-linked decision
memory**: business intent → evidence → action → feedback → outcome, with owner, version, risk level,
lifecycle state, and a `source_trace_id`. The retrieval need is "find prior decisions/lessons relevant
to THIS business situation, with their outcomes and governance context, that I can trust and reuse" —
not "find text similar to a query".

Pure vector similarity (bare pgvector ANN) is the floor, not the ceiling. In complex scenarios it:
- ignores **structure** (metric, owner, time window, risk, `outcome=adopted|rejected`, confidence);
- models **no relationships** (decision ↔ metric ↔ entity ↔ other decisions) → no multi-hop / "what
  changed since we last cut this budget?";
- has no **recency / trust / outcome weighting** (a stale failed lesson can outrank a fresh adopted one);
- is opaque — hard to explain *why* a result surfaced, which conflicts with our EvidenceChain ethos.

## 2. Guiding constraints

- **Explainability is a hard constraint.** Every retrieval result must carry *why it surfaced*
  (matched terms, filters, similarity, outcome/recency boosts, provenance). This argues FOR
  structured/hybrid/graph (traceable) and AGAINST end-to-end black-box neural retrieval.
- **OS Core stays infra-independent.** Core owns Port ABCs (Embedder, KnowledgeRetriever); concrete
  pgvector / FTS / graph adapters live in `packages/persistence/` (or a sibling), wired by the factory.
- **Sync-first** (consistent with the Phase 2 async reversal). Migrate to async only when the whole
  I/O path (model + query + store) goes async together.
- **Lean on the Contract Spine, don't bolt on heavyweight infra.** Our `SemanticObject /
  MetricContract / OperationTrace / KnowledgeAsset` already form a nascent ontology/graph (cf. 8.8 /
  the Palantir-aligned path). "GraphRAG for us" means making those relationships queryable, not
  importing Neo4j or LLM-extracting a graph we already have.
- **No premature optimization.** Most "complex scenario" wins come from hybrid + metadata, achievable
  in Postgres with no new infrastructure.

## 3. Design — a layered retriever, not a single silver bullet

### 3.1 Ports (OS Core)
- `Embedder` (ABC): `embed(text) -> vector`, `model_id` / `dimensions`. Concrete model lives behind
  the Model Gateway / an adapter; OS Core does not bind a model.
- `KnowledgeRetriever` (ABC): `search(query: KnowledgeQuery) -> tuple[RetrievalResult, ...]`, where
  `KnowledgeQuery` carries text + structured filters (metric, owner, time window, risk, outcome,
  lifecycle) + `k`, and `RetrievalResult` carries the asset + a **score breakdown** (the "why").
- `InMemoryKnowledgeRetriever` for tests; `SqlKnowledgeRetriever` (pgvector+FTS) and later a
  graph-aware retriever as adapters.

### 3.2 Layer 1 — Hybrid retrieval (the real v1, all in Postgres)
- **Vector** similarity (pgvector, **HNSW** index; consider `pgvectorscale` for filtered ANN at scale).
- **Lexical** full-text (Postgres `tsvector`/BM25-ish) — catches exact metric names / IDs.
- **Structured filters & boosts** via SQL `WHERE`/scoring (metric, owner, time, risk, lifecycle).
- **Fusion** (Reciprocal Rank Fusion) of vector + lexical, then optional **re-rank** (cross-encoder,
  e.g. bge-reranker, or LLM re-rank) for the top candidates.

### 3.3 Layer 2 — Graph / ontology awareness (lean on what we have)
- Make decision↔metric↔outcome↔entity relationships queryable. **Stay in Postgres first** (recursive
  CTEs, or the Apache AGE graph extension); reach for a dedicated graph DB (Neo4j / embedded KùzuDB)
  only when measured query needs justify it. Enables multi-hop / aggregative / "what-changed" queries.

### 3.4 Layer 3 — Temporal validity (audit)
- Bi-temporal knowledge (valid-time vs system-time) so replay answers "what was true when we decided".
  Aligns with EvidenceChain reproducibility. Optional; add when audit/replay demands it.

### 3.5 Outcome-weighted memory (our edge)
- Retrieval is **outcome-aware**: lessons gain/lose weight from `FeedbackEvent`s (adopted+worked →
  boosted; rejected/failed → demoted), plus recency and confidence. This rides directly on the
  existing FeedbackEvent → KnowledgeAsset loop and is hard for generic doc-RAG to replicate.

### 3.6 Freshness / cascade (re-embedding)
- Embeddings are derived snapshots; nothing recomputes them automatically. The cascade hook already
  exists in the write path: re-embed on `KnowledgeStore.register` / `register_version` (and when
  feedback folds in). Store `embedding_model` + `embedded_at`; a **model upgrade requires a batch
  re-embed (backfill)** of the whole corpus (mixed embedding spaces cannot be compared).

## 4. Staged rollout

1. **v1 — Hybrid-in-Postgres**: `Embedder` + `SqlKnowledgeRetriever` (pgvector HNSW + FTS + structured
   filters/boosts + RRF) + outcome/recency weighting + re-embed on write. No new infrastructure.
   Verifiable logic (fusion/weighting/filter) on SQLite; vector/FTS specifics behind guarded PG tests.
2. **v2 — Graph-aware + temporal**: relationship traversal over the Contract Spine (Postgres CTE/AGE),
   bi-temporal validity. Escalate to a graph DB only if measured.
3. **v3 — Retrieval-as-tools + advanced re-rank**: expose retrievers as Business-Agent tools for
   iterative retrieve→reason→verify-against-EvidenceChain; cross-encoder/LLM re-rank; community
   summaries IF a large unstructured corpus appears.

## 5. Decisions to ratify (before v1 implementation)

- **Embedding model/provider** (via Model Gateway; BYO-key) and **vector dimensions**.
- **Index**: pgvector HNSW vs `pgvectorscale` (StreamingDiskANN) — driven by corpus size + filtered-ANN needs.
- **Re-embed timing**: in-line on write (simple; one model call per version) vs background/async
  (no loop latency; eventual consistency). Lean in-line first (matches sync-first + low version churn).
- **Graph backend threshold**: stay in Postgres (CTE/AGE) until which measured query/latency need
  justifies a dedicated graph DB.

## 6. Deliberately rejected (and why)

- **Standalone graph DB now** — heavy new dependency; our structure + Postgres covers v1/v2.
- **Microsoft-style LLM graph extraction** — built for unstructured corpora; our decision records are
  already structured, so re-extracting via LLM is cost without benefit.
- **Full agentic retrieval now** — premature; adds latency/cost. Composes later in v3.
- **Opaque end-to-end neural retrieval** — violates the explainability/auditability constraint.

## 7. Boundary & verification

- **Boundary**: OS Core imports no pgvector/SQLAlchemy/graph driver; only the Port ABCs. Adapters and
  wiring live in the persistence/composition layer (grep-checkable).
- **Verification**: fusion/weighting/filter/score-breakdown logic unit-tested on SQLite or in-memory;
  pgvector/FTS/graph specifics behind PG-guarded integration tests (skip without `AGENT_OS_DATABASE_URL`).
  Every `RetrievalResult` must expose its score breakdown (the "why") — asserted in tests.

## 8. Strategy tie-in (8.8)

For this product the "advanced knowledge base" is **not** a fancier vector DB — it is **structured,
governed, outcome-linked organizational memory** (the Ontology / Contract Spine). That structure is
the moat; hybrid + graph + temporal + outcome-weighting are retrieval techniques that **ride on it**.
Generic competitors doing document-RAG cannot easily replicate outcome-weighted, governed, versioned,
explainable decision memory.
