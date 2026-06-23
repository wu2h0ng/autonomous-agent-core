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
  uvicorn --factory agent_os_api.http_app:create_app --host 127.0.0.1 --port 8000
```

Endpoints (all require the `X-API-Key` header):

- `POST /runs` — body `{question, parameters, audience?}` -> `run_service` summary.
  `audience` is `internal` by default; `external` redacts non-public result details in
  `user_result` without changing the underlying Trusted Loop evidence.
- `POST /outcomes` — body `{trace_id, outcome, reviewer?, metric_deltas?}` ->
  `record_outcome_service` result.

Auth boundary:

- No key configured (neither `create_app(api_key=...)` nor `AGENT_OS_API_KEY`) -> protected
  routes reject with `503` so the operator configures a key rather than running open.
- Missing or wrong `X-API-Key` -> `401`.
