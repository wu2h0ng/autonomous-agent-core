# AR-20260607 Knowledge retrieval design (Phase 3)

> Status: **Proposed (design only — not implemented).** Sequels the persistent store
> (AR-20260606-persistent-store-design). Defines how the KnowledgeAsset corpus is searched/retrieved.
> **Revised 2026-06-07 (PR #6 review):** two design blockers resolved — (1) v1 filters/boosts run on
> projected, indexed columns, never JSON scans (§3.2.1); (2) the re-embed cascade lives in a
> persistence-layer decorator, NOT in `KnowledgeStorePort` / OS Core (§3.6).
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
- `Embedder` (ABC): `embed(text) -> vector`, `model_id` / `dimensions`. A **pure contract** only — the
  concrete model lives behind the Model Gateway / an adapter, and **nothing in OS Core invokes it**
  (re-embedding is a persistence-layer concern; see §3.6). OS Core does not bind a model.
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

#### 3.2.1 Queryable projection (resolves: filters must not degrade to JSON scans)
The Phase 2 schema stores each asset as `payload JSON`. v1 structured filtering/boosting/outcome-
weighting on `metric / owner / time / risk / outcome / lifecycle` **MUST run on real, indexed columns**,
not JSON scans — JSON scans break both explainability (no clean predicate to cite) and the eval/release
gate (unstable, unbounded). Therefore extend `knowledge_assets` with **projected, indexed columns**,
populated in the write path from the asset (and from feedback for outcome), with `payload` remaining the
canonical source of truth:

| Column | Source | Index |
|---|---|---|
| `metric_name`, `owner`, `risk_level`, `lifecycle_state` | projected from the asset | btree |
| `decided_at` (time) | projected from the asset / trace | btree |
| `latest_outcome`, `outcome_score` (or `confidence`) | **denormalized from the latest FeedbackEvent**, updated when feedback folds in | btree |
| `embedding vector(N)` | Embedder (see §3.6) | HNSW |
| `search_doc tsvector` | derived text | GIN |

- These columns are **derived** and kept in sync in the *same write path* that writes `payload`; they
  are never hand-edited, and `payload` stays canonical (re-derivable). An Alembic migration adds the
  columns + indexes (PostgreSQL).
- Outcome filters/boosts read the denormalized `latest_outcome`/`outcome_score` (index-friendly).
- **Alternative considered, rejected for v1:** a join/materialized view to `feedback_events` — MV
  refresh lag hurts the freshness/explainability the gate needs; revisit only if denormalization cost
  becomes a problem.

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

### 3.6 Freshness / cascade (re-embedding) — placement

Embeddings are derived snapshots; nothing recomputes them automatically, so re-embedding is an
explicit cascade on write. **It must NOT live in `KnowledgeStorePort` / OS Core.** The port is a pure
storage contract; putting an embedding/model side effect inside `register` / `register_version` would
drag a model dependency into Core and break the boundary. (This corrects an earlier phrasing that said
"re-embed on `KnowledgeStore.register`".)

Placement — a **persistence/composition-layer write-side decorator**:
- `EmbeddingKnowledgeStore(base: KnowledgeStorePort, embedder: Embedder)` wraps any
  `KnowledgeStorePort`. It delegates to `base` for storage, then computes the embedding via the
  `Embedder` adapter and writes the `embedding` / `search_doc` (and the §3.2.1 projected columns).
- The **factory injects** this decorator, so `TrustedLoopRuntime` still sees a plain
  `KnowledgeStorePort`. OS Core imports no embedder/model and runs no model side effect.
- The same write-side hook maintains the projected columns (§3.2.1) and the outcome denormalization
  when feedback folds in (the `record_outcome` path / feedback-knowledge unit of work).

Versioning & backfill:
- Store `embedding_model` + `embedded_at` per row.
- A **model upgrade requires a batch re-embed (backfill)** of the whole corpus — mixed embedding
  spaces cannot be compared. A standalone backfill command (not the loop write path) handles it.

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

- **Boundary**: OS Core imports no pgvector/SQLAlchemy/graph driver and **no embedder/model**; only the
  Port ABCs. Adapters, the `EmbeddingKnowledgeStore` decorator, and all wiring live in the
  persistence/composition layer (grep-checkable: `os_core` imports no `Embedder` adapter).
- **Projection is derived, payload is canonical**: the §3.2.1 queryable columns are written from
  `payload` in the same write path; filters/boosts query those columns, **never JSON scans**.
- **Verification**: fusion/weighting/filter/score-breakdown logic unit-tested on SQLite or in-memory;
  pgvector/FTS/graph specifics behind PG-guarded integration tests (skip without `AGENT_OS_DATABASE_URL`).
  Every `RetrievalResult` must expose its score breakdown (the "why") — asserted in tests. A test must
  assert filters resolve to indexed-column predicates (no JSON-scan fallback).

## 8. Strategy tie-in (8.8)

For this product the "advanced knowledge base" is **not** a fancier vector DB — it is **structured,
governed, outcome-linked organizational memory** (the Ontology / Contract Spine). That structure is
the moat; hybrid + graph + temporal + outcome-weighting are retrieval techniques that **ride on it**.
Generic competitors doing document-RAG cannot easily replicate outcome-weighted, governed, versioned,
explainable decision memory.
