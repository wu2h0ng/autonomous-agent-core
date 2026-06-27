# API Server

Application boundary for API and local CLI entry points.

Current implemented entry points:

- `agent_os_api.runtime_factory.ContentCommerceRuntimeFactory`
- `agent_os_api.cli.run_cli` (subcommands `query` and `record-outcome`)
- `agent_os_api.outcome_service` (framework-agnostic service layer: `run_service`,
  `record_outcome_service`)
- `agent_os_api.http_app.create_app` (FastAPI app; optional, requires the `http` extra)

These entry points load `domain_packs/content_commerce/` contracts and build a runnable
Trusted Loop without importing domain logic into OS Core.

## Service layer

`outcome_service.py` is framework-agnostic (no FastAPI import). It is the single source of
truth shared by both the CLI and the HTTP app:

- `run_service(runtime, *, question, parameters, audience="internal") -> dict` — runs
  the loop and returns a summary keyed by `trace_id` (`result.evidence_chain.trace_id`).
  `audience` selects the read-side `user_result` projection only; it is not an
  identity-bound authorization check.
- `record_outcome_service(runtime, *, trace_id, outcome, reviewer=None, metric_deltas=None)
  -> dict` — records an outcome via `runtime.record_outcome(...)` and reports the resulting
  `knowledge_asset_id` / `knowledge_version`.

## CLI

```bash
# Run a query (the legacy bare-option form, with no subcommand, still works)
python -m agent_os_api.cli query --question "GMV" \
  --start-date 2026-05-25 --end-date 2026-06-01 --limit 100

# Record an observed outcome for a prior run's trace
python -m agent_os_api.cli record-outcome --trace-id <trace-id> --outcome adopted \
  --reviewer ops@example.com --metric gmv=1000.0 --metric orders=12
```

NOTE: the in-memory stores are per-process. A fresh CLI invocation cannot see a prior run's
trace, so `record-outcome` for an unknown trace honestly returns `knowledge_asset_id=null`
and `knowledge_version=0` (the feedback event is still recorded).

## HTTP server

FastAPI endpoints are now implemented with a minimal auth boundary. Install the optional
extra first:

```bash
pip install -e ".[http]"   # or: pip install fastapi httpx
```

Run the server with a configured API key (one shared runtime persists across requests):

```bash
AGENT_OS_API_KEY=your-secret \
  AGENT_OS_EXTERNAL_API_KEY=optional-external-report-secret \
  uvicorn --factory agent_os_api.http_app:create_app --host 127.0.0.1 --port 8000
```

Endpoints (protected by `X-API-Key` unless noted):

- `POST /runs` — body `{question, parameters, audience?}` -> `run_service` summary.
  `audience` is `internal` by default; `external` redacts non-public result details in
  `user_result` without changing the underlying Trusted Loop evidence. External public
  projections may show public metric data, but still strip physical schema/table names,
  bound parameter names, limit metadata, and SQL fingerprints. The optional
  `AGENT_OS_EXTERNAL_API_KEY` is projection-only for this endpoint: it may call `/runs`, but
  the response is always capped to the external projection even when the request body asks
  for `audience=internal`. That projection also omits top-level provider, trace-step, and
  related-knowledge metadata from the HTTP response.
- `GET /runs/{trace_id}/report` — returns an already-built `user_result` report snapshot.
  This read path does not call `runtime.evaluate`, does not re-run SQL, does not create
  approvals, and does not touch action connectors. The memory backend remains same-process;
  the postgres store backend persists report snapshots in `report_snapshots` so a fresh app
  instance on the same database can read the existing projection. `AGENT_OS_EXTERNAL_API_KEY`
  may call this endpoint only through the external projection, even when `?audience=internal`
  is requested. Internal and external report projections have distinct `artifact_id` values,
  so clients cannot cache or audit two redaction views as the same rendered artifact.
  Unknown snapshots return `404`.
- `POST /outcomes` — body `{trace_id, outcome, reviewer?, metric_deltas?}` ->
  `record_outcome_service` result.

Auth boundary:

- No key configured (neither `create_app(api_key=...)` nor `AGENT_OS_API_KEY`) -> protected
  routes reject with `503` so the operator configures a key rather than running open.
- Missing or wrong `X-API-Key` -> `401`.
- Recognized principal without the required scope -> `403`.
- `AGENT_OS_EXTERNAL_API_KEY` is not a general API key; non-run management surfaces such as
  `/outcomes`, `/adoptions`, `/knowledge/search`, `/traces/{id}`, and
  `/agent-runtime/runs/{runtime_run_id}/resume` still require the internal API key. On
  `POST /runs` it still triggers a new run execution; on
  `GET /runs/{trace_id}/report` it can only read an existing external report projection.
  This is a narrow HTTP principal/scope and report projection cap, not full RBAC or DLP.
- Configured internal, external-report, and operator keys must be distinct; duplicate key
  values fail closed during app creation.

Minimal principal/scope contract:

| Principal | Credential channel | Scopes | Notes |
|---|---|---|---|
| `internal` | `X-API-Key == AGENT_OS_API_KEY` | `runs:internal`, `runs:external`, `reports:read`, `outcomes:write`, `adoptions:write`, `knowledge:search`, `traces:read`, `runtime:resume` | Can request either internal or external run/report projection and resume checkpointed runtime runs; cannot execute approvals. |
| `external_report` | `X-API-Key == AGENT_OS_EXTERNAL_API_KEY` | `runs:external`, `reports:read` | Forced to external projection; cannot use management surfaces. |
| `operator` | `X-Operator-Key == AGENT_OS_OPERATOR_API_KEY` | `approvals:execute` | Header channel is separate from `X-API-Key`; approval execution remains operator-only. |

Approval execution on the postgres backend resumes the approval-bound context and writes through
the `action_record` connector ledger. That ledger audits idempotent replays and conflicts
connector-locally, including conflict fingerprints without raw conflicting payloads. It also
audits connector-local post-write ACK-uncertain attempts and surfaces recovered idempotent replays
through the approval execute response's typed `execution_audit`.

`execution_audit` is a conservative projection over connector-declared defaults plus whitelisted
connector-reported execution fields. The runtime fills defaults from the registered
`ActionConnectorContract.execution_semantics` before copying any safe connector payload fields. It
can show safe fields such as `durability_scope`, `execution_outcome`, `replay_status`,
`external_ack_status`, `ledger_status`, `record_id`, `external_request_id`,
`execution_certainty`, and `ack_status`. Raw action parameters, secrets, raw request/response
bodies, and connector payloads are not copied into this projection. `external_ack_status` defaults
to `unknown` for external connector semantics unless a connector explicitly reports otherwise.
This is not external-system exactly-once. The runtime can reclaim stale approval contexts that were
left `executing` after the configured lease, but this does not prove external ACK confirmation or
durable execution for arbitrary external connectors.
