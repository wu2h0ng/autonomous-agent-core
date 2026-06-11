# AR-20260611: Knowledge recall inside run() + composition-layer environment wiring

- **Status**: Accepted
- **Date**: 2026-06-11
- **Related**: AR-20260607-knowledge-retrieval-design (the retrieval semantics this AR
  feeds back into the production loop), AR-20260611-api-contract-openapi-stabilization
  (the snapshot gate this change must regenerate)

## Problem

1. **The knowledge read-side is not closed.** Since PR #7–#9 the learning loop writes
   end-to-end (run → candidate → outcome → version bump → re-embedded index), but
   `TrustedLoopRuntime.run()` never consults the retriever: organizational knowledge is
   only reachable through manual search (CLI/HTTP). The product claim — knowledge assets
   feeding back into production — is unrealized. This is the exact "elegant orchestration
   first, dirty wiring postponed" failure mode documented in the 2026-06-03 deviation
   analysis.
2. **The default HTTP surface is a demo.** `create_app()`'s default factory hardcodes
   `executor=static` (fixture rows) and `store_backend=memory`, with no environment
   wiring (only the API key reads env). Worse, the default memory-backend retriever is a
   fresh instance never indexed by the runtime's writes, so `/knowledge/search` on the
   default app ALWAYS returns empty results.

## Decision

### 1. Recall is a first-class, advisory, traceable step of run()

- `TrustedLoopRuntime` accepts an optional `knowledge_retriever: KnowledgeRetriever`
  (port already in OS Core) and a `recall_k` (default 3).
- After semantic resolution (metric is known; the current run's own candidate is NOT yet
  registered, so no self-hit), run() searches
  `KnowledgeQuery(text=question, metric_name=<resolved metric>, k=recall_k)`.
- Results land on `TrustedLoopResult.related_knowledge: tuple[RetrievalResult, ...]`
  (contract change) and a `knowledge_recall` trace event records asset ids + scores.
- **Advisory contract**: recall failure must not block a governed answer. A retriever
  exception is caught, recorded in the `knowledge_recall` trace event as an error, and
  the run proceeds with empty recall. This is the ONLY broad catch in the loop and it is
  trace-visible, never silent.
- Surfaces: `run_service` (and therefore `POST /runs`) returns `related_knowledge`
  (asset_id/title/score per hit) — the OpenAPI snapshot is regenerated in the same PR.

### 2. Shared projection semantics live in OS Core

The asset→index projection (metric parsed from the "[metric] …" title convention,
content, outcome, outcome→score weight) was private to the persistence layer. It moves
to `agent_os_core.knowledge_retrieval` (`project_asset`, `outcome_to_score`) and the
persistence `default_projector` delegates to it — one source of truth for both backends.

### 3. In-memory write-side indexing decorator (parity with SQL)

`IndexingKnowledgeStore` (OS Core, dependency-free) wraps any `KnowledgeStorePort` and
indexes into an `InMemoryKnowledgeRetriever` on register/register_version, using the
shared projection; assets without a trace are skipped and the retriever now replaces
entries per `source_trace_id` (version bumps replace, never accumulate) — exactly
mirroring the SQL `EmbeddingKnowledgeStore`/knowledge_index semantics.

The factory builds ONE retriever per backend and shares it between the runtime (recall)
and `build_knowledge_retriever()` (search surfaces): memory = the same
`InMemoryKnowledgeRetriever` instance; postgres = `SqlKnowledgeRetriever` over the same
engine (state shared through the database).

### 4. 12-factor environment wiring for the default app

`RuntimeFactoryConfig.from_env()` reads:

| Variable | Default | Values |
|---|---|---|
| `AGENT_OS_DOMAIN_PACK` | `domain_packs/content_commerce` | path |
| `AGENT_OS_EXECUTOR` | `static` | `static` \| `sqlite` |
| `AGENT_OS_STORE_BACKEND` | `memory` | `memory` \| `postgres` |
| `AGENT_OS_DATABASE_URL` | — | SQLAlchemy DSN (required for `postgres`) |

`create_app()`'s default factory uses `from_env()`, so the deployed FastAPI surface can
run the real SQL data plane and the durable store without code changes — same DSN
convention as Alembic's env.py. Defaults preserve current behavior exactly.

## Boundaries

- OS Core gains no new dependencies: `KnowledgeRetriever`/`InMemoryKnowledgeRetriever`/
  the projection are already-pure modules; `IndexingKnowledgeStore` composes existing
  Core ports. Env parsing lives in the composition layer (`runtime_factory`), not Core.
- Recall MUST NOT alter the data/evidence path: it adds context to the result and trace
  only. SQL Safety / EvidenceChain are untouched.

## Completion gate mapping

- **Entry points**: run()/`POST /runs` (recall in result + trace), `/knowledge/search`
  on the DEFAULT app now reflects runtime writes; env vars activate real backends.
- **Contract**: `TrustedLoopResult.related_knowledge`; regenerated `openapi.json`.
- **Negative paths**: failing retriever → governed answer still produced, error traced;
  `from_env` with `postgres` but no DSN → explicit ValueError.
- **Bypass-detection**: tests fail if recall is skipped (trace event + result field),
  if the memory retriever is not shared (search after run must hit), or if version
  bumps duplicate index entries.
