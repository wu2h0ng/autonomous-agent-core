# ADR-0053: Real-Data Adapter Examples and Ground-Truth-Free Evaluation Metrics

- Status: Accepted
- Date: 2026-07-09
- Deciders: founder (explicit in-session authorization recorded in `docs/research/founder-cast-2026-07-09-live-adapter-examples.md`)
- Claim class: `research-mechanism` / `research-environment`
- Target layer: `autonomous-agent-core` object layer
- Related ADR/RR: ADR-0052, RR-0029, RR-0032

## Context

ADR-0052 defined the `RealDataInterventionEnv` protocol and the C7-offline
`GovernedInterventionBinding` wrapper.  This ADR implements three reference
adapters (CSV, HTTP webhook, queue) and two ground-truth-free evaluation metrics
(predictive validation, interventional agreement).  The adapters live in the
`adapters/` directory, outside the core runtime; the metrics live in
`src/aac/cwm_evaluation.py` because they are core evaluation instruments.

## Architecture-Theory Review Gate (RR-0029 §5)

| # | Required answer | ADR-0053 response |
|---:|---|---|
| 1 | **Claim class and exact claim sentence** | `research-mechanism/environment`: Reference CSV/HTTP/queue adapters and two linear ground-truth-free metrics can be built on top of the ADR-0052 protocol without giving the core execution authority, and they do not require a known ground-truth DAG to score predictions. |
| 2 | **Null hypothesis and route killer** | The route fails if any adapter can execute an intervention without external approval, if the metrics reward spurious graphs on placebo data, or if the adapters are imported into the core runtime. |
| 3 | **Channel map and write matrix** | Adapters write **S** (audit/proposal logs, HTTP POSTs, queue messages) and consume **B** (observation rows) only.  Metrics write **B** (scores).  Neither writes **K/R/T/P**. |
| 4 | **Control path and consumption path** | `OnlineInteractiveDiscoveryLoop` → `GovernedInterventionBinding` → adapter `observe`/`intervene`.  The adapter's return value is consumed as a numeric row.  The adapter never consumes core belief state or modifies the loop. |
| 5 | **Value/norm source** | No autonomy/intelligence/value essence.  Safety is operational: dry-run default, whitelist, value ranges, budget, approval callback, audit. |
| 6 | **Prior negative-result mapping** | G13 showed unsafe interventions can leak harm.  ADR-0052/0053 prevent this by forbidding any handle outside `allowed_handles` and requiring external approval.  ADR-0033 (LLM-in-control) is avoided: adapters are typed numeric interfaces.  Prior B-channel ceiling (belief organs failing to open independent axes) is irrelevant here: adapters and metrics are plumbing/evaluation, not new belief organs. |
| 7 | **Environment pressure and cheap baseline** | Pressure: real systems have unknown DAG and expensive interventions.  Cheap baseline is simulation with known truth (`CausalSimulationEnv`).  The adapters are necessary only when truth is unknown and the interface must cross a process boundary.  Metrics are tested against the cheap baseline to ensure true DAG scores higher than empty/random DAGs. |
| 8 | **Consumption-path proof** | The loop consumes only numeric rows.  Adapters cannot modify loop parameters.  Metrics consume only observations, interventions, and a predicted DAG; they do not feed back into discovery except as externally logged scores. |
| 9 | **Representation/abstraction ownership** | Variable-to-column mapping is declared by the adapter owner via `observed_variables`.  The core uses integer indices.  Metrics use linear models on those integer-indexed columns and do not learn a new representation. |
| 10 | **C6/C7/SD4 boundary** | C7 is preserved: `GovernedInterventionBinding` defaults to dry-run, whitelists handles, enforces value ranges and budget, and requires external approval.  Adapters are outside the core runtime.  SD4 untouched.  C6 preserved because adapters cannot become action selectors. |
| 11 | **Legal interaction budget** | Per-session `budget` is enforced by the binding.  Real-world budget/cost must be enforced by the external system, not the adapter. |
| 12 | **Product/process boundary** | This is object-layer research plumbing and evaluation.  It is not a product capability.  Enterprise consumption remains through the RR-0032 seam and requires separate CTO approval. |
| 13 | **Decision owner** | Founder cast recorded in `docs/research/founder-cast-2026-07-09-live-adapter-examples.md`; CTO review required before any production adapter. |

**Reviewer attack:**  Reference adapters could be mistaken for production
connectors and deployed against real systems without the binding wrapper.  The
defense is: (a) every adapter file begins with a comment that it lives outside
the core runtime, (b) all example scripts use `dry_run=True` by default, (c) the
founder cast explicitly forbids production connection, (d) live mode requires an
external approval callable that is not provided in the examples.

**Gate outcome:** `ACCEPT_FOR_SPEC`.

## Options Considered

### Option A: Implement only one adapter (CSV)
- Rejected.  A single adapter does not expose the protocol boundary clearly;
  HTTP and queue surfaces are common integration patterns and help keep the
  protocol honest.

### Option B: Three reference adapters + linear metrics (selected)
- Accepted.  CSV is file-based, HTTP is network-based, queue is in-process-based.
  All use stdlib only.  Metrics are cheap linear baselines that do not require
  ground truth.

### Option C: Full real-data connector framework with config files and plugins
- Rejected.  Would import business semantics, add dependencies, and blur the
  boundary between core and external systems.

## Decision

1. Implement three reference adapters in `adapters/`:
   - `csv_adapter.py`: file-based observations, intervention log, optional
     read-back CSV.
   - `http_adapter.py`: GET observations, POST interventions, parse JSON
     response.
   - `queue_adapter.py`: Python `queue.Queue` based, for local harnesses.

2. Implement ground-truth-free metrics in `src/aac/cwm_evaluation.py`:
   - `predictive_validation_score`: fit linear models implied by the predicted
     DAG, predict held-out interventions, compare to marginal-mean baseline.
   - `interventional_agreement_score`: compare empirical intervention shifts to
     model-predicted shifts in sign and magnitude.

3. All adapters must pass the `RealDataInterventionEnv` protocol and be usable
   through `GovernedInterventionBinding`.

4. Live mode remains opt-in and approval-gated.  Examples default to dry-run.

## Consequences

- The CWM discovery loop can now be exercised against three common external
  surface patterns without modifying core logic.
- Metrics allow comparison of predicted DAGs in settings where SHD is
  unavailable.
- No production connector is implemented or authorized.
- The core runtime gains no new dependencies.

## Open items

- Production adapter for a specific domain requires a separate cast.
- Nonlinear metrics (e.g. poly2) may be added later if linear metrics prove
  insufficient.
