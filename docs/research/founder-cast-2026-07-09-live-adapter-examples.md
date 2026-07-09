# Founder/CTO Cast: Live Adapter Examples and Ground-Truth-Free Metrics

- Date: 2026-07-09
- Cast by: founder (in-session authorization)
- Scope: `autonomous-agent-core` object-layer research mechanism
- Authorizing ADR: `docs/adr/ADR-0052-real-data-intervention-binding-protocol.md`

## Authorization

I authorize the implementation of reference `RealDataInterventionEnv` adapters and
ground-truth-free CWM evaluation metrics under the following hard constraints.
This cast does **not** authorize connection to production systems, real patient
records, financial transaction executors, or any actuator that can cause
irreversible external effects.

## Allowed adapter examples

1. **CSV adapter** (`adapters/csv_adapter.py`)
   - Reads observations from a CSV file.
   - Writes intervention requests to a log CSV.
   - Optionally reads back post-intervention samples from a second CSV.
   - No network access, no actuator.

2. **HTTP webhook adapter** (`adapters/http_adapter.py`)
   - Reads observations via HTTP GET.
   - POSTs intervention proposals to an external webhook.
   - Returns the response body as the read-back sample.
   - The webhook endpoint must be owned and operated by the human team; the core
     does not execute.

3. **Queue adapter** (`adapters/queue_adapter.py`)
   - Reads observations from a Python `queue.Queue`.
   - Publishes intervention requests to a second queue.
   - Consumes read-back samples from a third queue.
   - Intended for local integration tests and harnesses only.

## Mandatory safety constraints

- `GovernedInterventionBinding.dry_run` must default to `True` in all example
  code and documentation.
- Live mode (`dry_run=False`) is allowed only when:
  - `allowed_handles` is an explicit whitelist supplied by the operator;
  - `safe_value_ranges` is supplied per handle;
  - `budget` is capped per session (default ≤ 50);
  - the external `approval` callable returns `True` for every intervention;
  - an `audit` callback records every proposal and outcome.
- No adapter may bypass the `approval` gate or call an actuator from inside the
  adapter's `intervene` method without first receiving explicit approval.
- All three adapters must be read-only with respect to the core runtime: they
  implement the protocol and return samples; they do not modify core state.

## Evaluation metrics authorization

I authorize the implementation of two ground-truth-free metrics:

- `predictive_validation_score`: predicts held-out interventional samples from a
  fitted linear model implied by the predicted DAG and compares to a marginal
  mean baseline.
- `interventional_agreement_score`: compares the sign and magnitude of empirical
  interventional shifts to the shifts predicted by the model.

These metrics are research instruments, not product guarantees. They may be used
to compare predicted DAGs when ground truth is unknown, but they cannot prove
causality.

## What is not authorized

- Connecting any adapter to a production database, API, or physical actuator.
- Removing or weakening `GovernedInterventionBinding` safety checks.
- Running live interventions without a per-handle approval gate and audit trail.
- Claiming these adapters or metrics as product capabilities of the deployment
  layer.

## Next gate

Before any of these adapters is used with real data or a real actuator, a
separate founder/CTO cast must approve the specific data source, actuator,
handle whitelist, value ranges, and kill criteria.
