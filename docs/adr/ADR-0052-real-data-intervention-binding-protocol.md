# ADR-0052: Real-Data Intervention Binding Protocol for CWM Live Discovery

- Status: Accepted
- Date: 2026-07-09
- Deciders: founder (explicit authorization in goal turn)
- Claim class: `research-mechanism` / `research-environment`
- Target layer: `autonomous-agent-core` object layer
- Related CURRENT_STATE anchor: `autonomous-agent-core/docs/CURRENT_STATE.yaml` (bounded adaptive optimization completed; next step: real-data intervention binding design)
- Related ADR/RR: ADR-0045, ADR-0048, ADR-0049, ADR-0051, RR-0029, RR-0032

## Context

The CWM live-intervention pipeline has been validated on four simulation families
(linear, regime-shift, nonlinear polynomial, latent-confounder) with bounded
adaptive optimization (`change_point_detector` reset + conservative edge-marginal
filtering).  The next growth boundary is to bind the same `observe`/`intervene`
surface to real data and real actuators, while keeping the core C7
offline/verify-only.

This ADR defines the protocol.  It does **not** implement a connector to any
external database, API, or physical system.  It defines the contract, governance
wrapper, and failure modes so that a future external adapter can safely plug into
the core without giving the core execution authority.

## Architecture-Theory Review Gate (RR-0029 §5)

This section satisfies the mandatory pre-ADR review for new autonomous-core
mechanisms.

| # | Required answer | ADR-0052 response |
|---:|---|---|
| 1 | **Claim class and exact claim sentence** | `research-mechanism`: A governed `RealDataInterventionEnv` protocol plus `GovernedInterventionBinding` wrapper lets the existing `OnlineInteractiveDiscoveryLoop` consume real-world observational and interventional samples without the core holding execution authority. |
| 2 | **Null hypothesis and route killer** | The protocol fails if the wrapper cannot prevent the core from selecting/proposing an unsafe handle, if the adapter can be silently swapped to autonomously execute, or if C7 cannot enforce dry-run-only as the default. |
| 3 | **Channel map and write matrix** | Core writes **B** (belief/posterior/edge-marginal) and **S** (audit/proposal records) only.  It never writes **K** (action/policy selection), **R** (representation), **T** (temporal abstraction), or **P** (product verdict).  The external adapter owns actuation. |
| 4 | **Control path and consumption path** | `GovernedDiscoveryLoop` → `_execute_intervention` → `environment.intervene(node, value)`.  With this ADR, `environment` is a `GovernedInterventionBinding` that validates the proposal, requires external approval in live mode, and then delegates to an external adapter.  The adapter's return value is consumed as a single observation row; it cannot rewrite the loop's budget, gate, confidence threshold, or correction boundary. |
| 5 | **Value/norm source** | No autonomy/intelligence/value essence is invoked.  The design is operational: allowed handles, forbidden nodes/edges, value ranges, budget, dry-run flag, approval callback, audit callback. |
| 6 | **Prior negative-result mapping** | G13 (consequence prior) failed partly because unsafe/unidentifiable interventions were hard to bound.  ADR-0052 addresses this by forbidding any intervention outside an explicit `allowed_handles` set and by making dry-run the default.  G12 (ecological axis) was inconclusive because environment pressure was not isolated; this protocol isolates the binding problem to a clearly bounded interface.  ADR-0033 (LLM-in-control) is avoided: the protocol is a typed numeric interface, not an LLM action channel. |
| 7 | **Environment pressure and cheap baseline** | Pressure: real systems have no ground truth, missing readbacks, and unsafe handles.  Cheap baseline is the same loop running with `CausalSimulationEnv` (known truth, no actuator risk).  The protocol is necessary only when truth is unknown and interventions must be gated. |
| 8 | **Consumption-path proof** | The loop consumes only `list[list[float]]` observations and `list[float]` interventional samples.  The binding wrapper returns either a sample or `None`; it cannot modify loop parameters, shell, gate, or verdict.  The approval callback is external and can return `False` independently of the core. |
| 9 | **Representation/abstraction ownership** | Variable abstraction (node → real-world quantity) is owned by the external adapter and declared in `observed_variables`/`safe_value_ranges`.  The core operates on integer node indices and floats; it does not learn or rewrite the mapping. |
| 10 | **C6/C7/SD4 boundary** | C7 is enforced as a hard boundary: dry-run default, allowed-handle whitelist, forbidden-node/edge blacklist, value ranges, budget, mandatory external approval for live mode.  SD4 is untouched: the core cannot modify its own correction gate or safety boundary.  C6 is preserved because the wrapper only consumes belief records and cannot become an action selector. |
| 11 | **Legal interaction budget** | The protocol explicitly caps `budget` per session and logs every proposal/outcome.  If an intervention is unsafe or unidentifiable, the adapter must omit the handle from `allowed_handles`; the core will then never propose it. |
| 12 | **Product/process boundary** | This is object-layer research mechanism.  It is **not** a product capability.  The enterprise OS may later consume a governed decision through the RR-0032 seam, but only after a separate cast and CTO approval. |
| 13 | **Decision owner** | Founder authorized the design; CTO-level review is required before any live adapter is instantiated with real data or real actuators. |

**Reviewer attack (strongest case against the architecture):**  The protocol
still lets the loop *propose* interventions on real handles.  A bug in the
approval callback or adapter could ignore the dry-run flag and execute an unsafe
intervention.  The defense is layered: (a) dry-run is the default and must be
explicitly disabled, (b) live mode requires an external `approval` callable that
receives the full `InterventionProposal`, (c) the adapter—not the core—owns the
actuator, (d) every attempt is audited, and (e) the allowed-handle whitelist is
supplied by the operator/system, not inferred by the core.  This does not
eliminate risk, but it keeps the core on the verify-only side of the boundary.

**Gate outcome:** `ACCEPT_FOR_SPEC`.

## Options Considered

### Option A: Build a real database/API connector inside `autonomous-agent-core`
- Rejected.  It would import business semantics and external dependencies into
  the object layer, violate Hard Boundary #19 (no cross-repo imports), and blur
  C7 by giving the core direct write paths.

### Option B: Minimal protocol + external adapter (selected)
- Accepted.  The core defines a small `RealDataInterventionEnv` protocol and a
  `GovernedInterventionBinding` policy wrapper.  The external adapter implements
  data ingestion, actuator safety, and read-back.  This mirrors the existing
  simulation-env surface and preserves the cross-repo seam defined in RR-0032.

### Option C: Generic causal-inference platform integration
- Rejected.  Building a full data plane is out of scope for the object layer and
  duplicates ProviderContract work in the deployment layer.

## Decision

1. Introduce `RealDataInterventionEnv` protocol in
   `src/aac/real_data_intervention_env.py` with the same surface the discovery
   loop already expects:
   - `observe(n_samples) -> list[list[float]]`
   - `intervene(node, value) -> list[float] | None`
   - `n_nodes`, `observed_variables`, `allowed_handles`, `safe_value_ranges`
   - `ground_truth_edges` may be `None`
   - `structural_hamming_distance` may return `None`

2. Introduce `GovernedInterventionBinding` wrapper that enforces:
   - Allowed-handle whitelist (`allowed_handles`).
   - Forbidden-node and forbidden-edge blacklist.
   - Per-handle value-safety ranges.
   - Per-session intervention budget.
   - Dry-run default: no external actuation; returns synthetic sample.
   - Live mode: external `approval` callback must return `True` before the
     adapter's `intervene` is called.
   - Audit callback receives an `InterventionOutcome` for every proposal.

3. Discovery loop integration:
   - `OnlineInteractiveDiscoveryLoop` consumes the binding exactly like any other
     environment; no changes to the loop's core logic.
   - The wrapper may carry a `change_point_detector` (existing ADR-0052 adaptive
     optimization) to pause on detected distribution shifts.

4. Data contract:
   - Observations are rectangular numeric matrices; missing values are handled by
     the adapter before reaching the core.
   - Variable schema and handle schema are declared by the adapter.
   - Readback samples must match the observation column order.

5. Failure modes:
   - Forbidden/disallowed handle → blocked, audited, returns `None`.
   - Value out of range → blocked, audited, returns `None`.
   - Budget exhausted → blocked, audited, returns `None`.
   - Approval denied → denied, audited, returns `None`.
   - Adapter returns `None` → `readback_missing`, audited, loop skips update.
   - Distribution shift detected → adapter or wrapper pauses and escalates.

## Consequences

- The CWM discovery loop can now be connected to real systems without modifying
  its posterior engine or governance logic.
- The default mode remains verify-only.  Any live adapter must pass an explicit
  approval gate and is outside the core repository.
- The object layer gains no business semantics, no external framework
  dependencies, and no execution authority.
- A future deployment-layer integration must use the RR-0032 RPC seam, not a
  library import.

## Open items

- Concrete adapter examples (CSV reader, HTTP webhook, queue consumer) are
  intentionally deferred to a later cast; they belong outside the core.
- Knobs for partial observability, latent confounders, and regime-shift handling
  reuse ADR-0051 / bounded adaptive optimization; no new mechanism needed.
- Real-data evaluation metric: SHD is unavailable when ground truth is unknown;
  a downstream `PredictiveValidation` or `InterventionalAgreement` metric must
  be designed separately.
