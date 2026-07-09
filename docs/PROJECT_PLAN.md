# PROJECT_PLAN - autonomous-agent-core

> Last updated: 2026-07-10
> Status: Active handoff document
> First read: `docs/CURRENT_STATE.yaml` -> `docs/AGENT-OS-PRODUCT-BLUEPRINT-V1.md` -> this file -> `codebase_index.md` -> current ADRs.

## 1. Current Truth

This repository is now the complete Agent OS main monorepo by founder decision. It has a Product Track and a Research Track. The current implementation is still research-heavy; the product blueprint is final, while the market-parity product runtime remains to be built. Research verdicts keep their exact historical meaning and do not establish product delivery.

Product authority:

```text
docs/AGENT-OS-PRODUCT-BLUEPRINT-V1.md
```

Current research baseline:

```text
source: reconcile/igi-organstack-into-open-world-arc-2026-07-10
G10: narrow synthetic MET and trap-complete
G13: NOT_MET
G-ECO-REOPEN-1: NOT_MET
strong-locus Stage 4: INSUFFICIENT_DATA_HONEST_NEGATIVE
CWM-LEARN-5e-2: r-final MET for the hard non-enumerable functional-form channel only
product/autonomy claim from these results: NOT_AUTHORIZED
```

Do not describe the current stage as P1, P2, P3, or P4. Those are historical phases.

Latest test truth:

```text
PYTHONPATH=src python -m unittest discover -s tests -v
1237 tests OK (16 skipped in this worktree environment)
```

The current test count is copied from `docs/CURRENT_STATE.yaml`; rerun before code submission if you change code. Thirteen skips are intentional sentinels; three additional Replogle preprocessing methods are skipped because optional `anndata/numpy` are not installed in this worktree environment. This suite verifies the reconciled research tree, not Agent OS Product Done.

## 2. Product Track Immediate Task

### T-P-OS-SPINE-0 - Executable Product Spine

Status:

```text
P0A_CONTRACTS_AND_RUN_KERNEL_IMPLEMENTED_VERIFIED
SPINE-0 completion: NOT_MET
SPINE-0 donor migration dependency: NONE
```

Current authority:

- `docs/architecture/T-P-OS-SPINE-0-ARCHITECTURE-PACKET.md`
- `docs/adr/ADR-0054-one-time-data-agent-history-migration.md`
- `docs/architecture/T-P-OS-SPINE-1-DATA-AGENT-MIGRATION-MAP.yaml`
- `docs/research/AGENT-OS-RESEARCH-GAP-AND-BOTTLENECK-AUDIT-2026-07-10.md`
- `docs/research/AGENT-OS-PRODUCT-GROUNDED-EXPERIMENT-MATRIX.yaml`

Founder-selected path remains Option B, but Claude review split delivery into two bounded
tasks. SPINE-0 proves the generic durable developer vertical without donor import. SPINE-1
performs the ADR-0054-gated history-safe Data Agent migration and extraction. No runtime
cross-repo import is allowed.

Goal:

Build the first real vertical slice through `Goal -> Commitment -> WorkflowGraph -> AgentRun -> ActionContract -> ExpectedOutcome/ObservedOutcome` with a durable Task Workspace entry point. The slice must use a real provider credential reference, one typed tool, one failure/recovery path, policy enforcement, event persistence and an acceptance evaluator.

Required first architecture packet:

- canonical contract ownership and versioning;
- target package/app scaffold and dependency boundary;
- provider/BYOK secret-broker threat model;
- WorkflowGraph IR and natural-language/visual round-trip contract;
- durable execution/event-store choice;
- one developer golden-path acceptance test plus a versioned domain-capability registration
  contract; Data Agent seam acceptance belongs to SPINE-1;
- explicit `ResearchCandidateManifest` boundary; no raw `src/aac` experiment import.

Claude first returned `APPROVE_WITH_REQUIRED_CHANGES`; the required ADR, history-safety,
scope and connector-guarantee changes were applied. Independent remediation re-review
closed all six findings and returned `APPROVE`.

P0A implemented from the reviewed test-first plan:

- minimum strict immutable `Goal`, `Commitment`, `ExpectedOutcome`, `ObservedOutcome`
  contract shapes;
- structural `WorkflowGraph` with stable digest and fail-closed duplicate/endpoint/cycle/
  terminal/bound validation;
- typed append-only `TaskEventStore` port and local in-memory adapter;
- event-rehydrated `TaskAggregate` with `DRAFT -> COMMITTED -> RUNNING` invariants;
- public `TaskService.create_task/commit_task/start_run/get_task` call path;
- Product/Research AST import boundary test.

P0A evidence:

```text
python3 -m pytest tests/product -q
45 passed
ruff: All checks passed
pyright: 0 errors, 0 warnings
package smoke: separate wheels clean-install/import; aac/envs absent
Research regression: 1237 OK (16 skipped)
```

Honest boundary: `InMemoryTaskEventStore` is a port adapter for tests/local composition,
not process durability. Commitment budget/expiry, explicit outcome failure semantics,
complete executable-graph semantics, queued durable run coordination, PostgreSQL,
provider/CredentialRef, PolicyKernel/correction, CapabilityBroker/tools, API/CLI/UI and full
SPINE-0 acceptance remain `NOT_IMPLEMENTED`.

Next packet: P0B governed capability/provider contracts and negative paths. It must bind
CredentialRef/ProviderPort, DecisionPolicy vs PolicyKernel, external CorrectionAuthority
and sandbox capability guarantee classes before any real tool effect.

This task is not complete with schemas, mocks or a UI shell. It needs a real call path, denial/failure behavior, restart recovery and verified outcome.

### T-P-OS-SPINE-1 - Data Agent History-Safe Migration (Successor / Blocked)

Status:

```text
DESIGN_ONLY_NOT_EXECUTED
blocked_by: T-P-OS-SPINE-0_ACCEPTED + ADR-0054 gates G0/G1
donor_pin/history_scan/import: NOT_STARTED
```

Authority:

- `docs/adr/ADR-0054-one-time-data-agent-history-migration.md`
- `docs/architecture/T-P-OS-SPINE-1-DATA-AGENT-MIGRATION-MAP.yaml`

SPINE-1 pins and scans the donor's complete reachable history before any import. Direct
no-squash import is eligible only after `PASS`; `REMEDIATE` requires a filtered migration
mirror and rescan, while `ABORT` stops migration. It then extracts generic Product Track
packages and `domain_packs/data_agent` and proves the Data Agent shared-spine seam.

## 3. Research Track Current Queue and History

### T-R-GECO-REOPEN-1 - G-Eco Fresh-Variant Reopen Packet (Completed NOT_MET)

Authority:

- `docs/CURRENT_STATE.yaml`
- `../docs/research/founder-decision-2026-07-04-reopen-g-eco.md`
- `../docs/research/G-ECO-REOPEN-1-foundational-problem-lock-2026-07-04.md`
- `../docs/research/architecture-theory-review-G-ECO-REOPEN-1-2026-07-04.md`
- `docs/adr/ADR-0039-g-eco-reopen-1-nonbijective-stake-channel.md`
- `../docs/research/formal-model-spec-G-ECO-REOPEN-1-2026-07-04.md`
- `../docs/research/algorithm-spec-G-ECO-REOPEN-1-2026-07-04.md`
- `../docs/research/implementation-cast-G-ECO-REOPEN-1-2026-07-04.md`
- `../docs/research/G-ECO-REOPEN-1.PREREG-DRAFT-2026-07-04.yaml`
- `../docs/research/G-ECO-REOPEN-1-seed-allocation-2026-07-04.json`
- `../docs/research/G-ECO-REOPEN-1-rfinal-report-2026-07-04.md`
- `../docs/research/architecture-lesson-G-ECO-REOPEN-1-2026-07-04.md`
- `../docs/research/paradigm-learning-G-ECO-REOPEN-1-2026-07-04.md`
- `../docs/research/route-product-projection-update-G-ECO-REOPEN-1-2026-07-04.md`
- `../docs/research/architecture-lesson-geco-vh-halt-2026-06-27.md`
- `../docs/research/paradigm-learning-geco-vh-halt-2026-06-27.md`

Goal:

Preserve the completed G-ECO-REOPEN-1 result as a negative result. The fresh non-bijective / longer-horizon stake-channel variant was run through RR-0029 review, accepted ADR/spec, implementation cast, RR-0031 independent review, prereg review/freeze, and r-final. It failed against the strengthened cheap baseline: fair `MINIMAX_FAIR` consumes the same public probe path as the candidate.

Final status:

```text
RR-0029 architecture-theory review: accepted by machine gate before freeze
ADR: ADR-0039 accepted for one fresh attempt only
RR-0031 independent review: blind calibration + controlled delta re-review, ACCEPT_FOR_FREEZE
Prereg review/freeze: accepted and frozen at .agent_runs/geco-reopen-2026-07-04/prereg.lock
R-final seeds: 7500..7529, count 30
Verdict: NOT_MET
Failure reasons: candidate_mean_loss_advantage_vs_best_non_oracle, candidate_vs_minimax_action_overlap, no_stake_retained_advantage_share
```

Non-authority:

- no old VH/G-Eco rescue;
- no reuse of old calibration/rate/threshold/r-final seed bands as fresh evidence;
- no retune, reseed, metric swap, weakened `MINIMAX_FAIR`, or r-final rerun;
- no Gate-2 revival, ADR-0037 movement, C6/C7 change, autonomy claim, or product claim.

### T-R-D1 - Direction 1 Cheap Falsifier (Pre-ADR / Pre-Build)

Authority:

- `docs/CURRENT_STATE.yaml`
- `../docs/research/route-selection-direction-1-policy-conversion-2026-06-27.md`
- `../docs/research/r-csl-1-PARK-reduces-to-memory-2026-06-27.md`
- `../docs/research/paradigm-learning-record-3-route-reduction-2026-06-27.md`

Goal:

Run or design the near-free falsifier over the existing G10/P0 substrate: sweep confidence-to-temperature coupling against non-stationarity rate. If the optimum is flat/insensitive, record and stop. Only a rate-sensitive result earns a new ADR/prereg/mechanism.

Current disposition:

This is no longer the immediate next task after the 2026-07-04 founder G-Eco reopen cast. Its tracked exploratory artifact remains useful negative pressure but does not authorize a new mechanism by itself.

Tracked exploratory readout:

```text
Artifacts:
  experiments/direction1_rate_sensitivity.py
  tests/test_direction1_rate_sensitivity.py
  experiments/direction1_rate_sensitivity.spec.json
  experiments/direction1_rate_sensitivity.seeds.json
  experiments/direction1_rate_sensitivity.lock.json
  experiments/direction1_rate_sensitivity.development.json

30-seed run-local exploratory artifact:
  seeds: 2400..2429
  verdict: NO_NEW_DIRECTION_1_MECHANISM
  FAST:    best fixed BT_COLD 2484.4203 | best gated K025 1418.6127
  DEFAULT: best fixed A1_O1  1249.0454 | best gated P0_FROZEN 749.5643
  SLOW:    best fixed A1_O1   604.3839 | best gated K025 354.4753

Disposition:
  The gated family wins on mean post-shift regret area in all three cells, but
  FAST and SLOW share the same best gated arm (K025), so the current cheap
  falsifier does not separate a new mechanism. Record and stop at exploratory
  status; do not open ADR/prereg/freeze/r-final from this artifact alone.
```

Non-authority:

- no R-CSL-1 rescue;
- no VH/G-Eco retune, reseed, Gate-2, r-final, or verdict;
- no C6/C7 change;
- no ADR-0037 decision;
- no autonomy or product claim.

### T-P6.4 - P6 Consolidation And Handoff

Authority:

- `docs/P6-research-synthesis.md` (P6 synthesis package, claim ledger, negative-result map, reproducibility/publication outline)
- `docs/adr/ADR-0024-g10-subject-side-win-confirmation.md` (G10 MET)
- `docs/adr/ADR-0026-c3-idle-productivity-de-risk.md` (C3 RED)
- `docs/adr/ADR-0027-post-c3-route-disposition.md` (G11/C1 parked until a second independent axis exists)
- `docs/adr/ADR-0028-survival-axis-de-risk.md` (survival RED)
- `docs/adr/ADR-0029-risk-calibration-axis-de-risk.md` (risk RED; close the multi-axis hunt)
- `docs/adr/ADR-0030-g10-completeness-trap-avoidance.md` (G10 trap-complete)
- `docs/adr/ADR-0031-prediction1-residual-calibrator-vs-g10.md` (PRED1-HOLDS)
- `docs/adr/ADR-0032-frontier-architecture-intake-and-structured-env-route.md` (frontier intake lanes)
- `docs/adr/ADR-0033-hyperagents-dgm-assimilation-boundary.md` (self-recursive assimilation boundary)
- `docs/adr/ADR-0034-relevance-aware-g10-theory-test.md` (B/R/K relevance-aware G10 theory test)
- `docs/adr/ADR-0035-p7-ecological-environment-axis.md` (P7 transferable ecological-structure environment axis, G12 2x2 gate)
- `docs/adr/ADR-0036-bounded-consequence-prior-gate.md` (G13 bounded consequence-prior scar-specific gate)
- `docs/adr/ADR-0038-g-eco-mechanism-lower-half.md` (Route C / G-Eco lower-half mechanism only)
- `ENGINEERING.md` section 4 items 5-6

Goal:

Keep the handoff state honest after the full P6 de-risk sequence. Do not freeze G11/C1 as originally scoped: after C3, survival, and stationary risk all returned RED, only the reframe/adaptation axis has a confirmed vs-cheap-baseline win. G10 is the consolidated positive result; any future system-level gate needs a new founder-level ADR and a new independent winning axis first.

Deliverable status:

```text
docs/P6-research-synthesis.md published on 2026-06-15
docs/adr/ADR-0034-relevance-aware-g10-theory-test.md accepted on 2026-06-15
docs/adr/ADR-0035-p7-ecological-environment-axis.md accepted on 2026-06-15
docs/adr/ADR-0036-bounded-consequence-prior-gate.md accepted on 2026-06-15
docs/adr/ADR-0038-g-eco-mechanism-lower-half.md accepted on 2026-06-22
```

### T-P6.5 - Relevance-Aware G10 Theory Test (Completed)

Authority:

- `docs/adr/ADR-0034-relevance-aware-g10-theory-test.md`
- `../docs/research/RR-0019-channel-decomposition-principle.md` section 13

Goal:

Test the amended B/R/K theory in the real `Agent + RelevanceField` harness. This does
not re-open G11/C1 and does not alter the G10 result; it tests the mechanism attribution:
how much of P0's old margin remains after a relevance-aware non-gated control (`RSTAR`)
is calibrated on disjoint seeds.

Serial slices:

```text
T-P6.5a  severity/noise environment path + default-compatibility tests
T-P6.5b  policy diagnostics for rho/conf/tau/w_e + C6/C7 guards
T-P6.5c  RSTAR calibration harness on seeds 1400..1419
T-P6.5d  r-final on seeds 1500..1529 and ADR-0034 result update
```

Result:

```text
RSTAR frozen on calibration seeds 1400..1419:
  base_temperature=0.03, inertia=0.25, surprise_gain=1.0

r-final seeds 1500..1529:
  PRED-A' severity threshold: PASS
  PRED-B' difficulty band: FAIL
  PRED-C' relevance-aware control share: PASS

Disposition:
  G10 empirical result preserved; trajectory account weakened.
  Relevance-aware exploration explains a substantial part of the A1->P0 margin
  (share_R=0.373), but P0 retains a decisive severe/default advantage over RSTAR
  (adv=+0.235).
```

### T-P7.0 - Transferable Ecological-Structure Environment Axis (Completed, Inconclusive)

Authority:

- `docs/adr/ADR-0035-p7-ecological-environment-axis.md`

Goal:

Open P7 as an environment-axis investigation, not a mechanism retune. G12 tests a 2x2
matrix:

```text
thin/reversible        thin/irreversible
ecological/reversible  ecological/irreversible
```

The column factor is **transferable environmental structure** (affordance topology,
niche/route structure, or reusable state-action relations), not resource scarcity or
external damage. Scarcity, damage, and rollback belong to the external-reversibility axis
and evaluator metrics.

The load-bearing distinction is:

```text
internal reset = subject belief/policy reset, allowed in every cell
external rollback = environment undoing consequences, allowed only in reversible cells
```

Status:

```text
G12 r-final completed on seeds 1700..1729.

Cell wins:
  C00 thin/reversible:        no  (adv=+0.175 < +0.20 threshold)
  C01 thin/irreversible:      yes (adv=+0.340, damage_adv=+0.436)
  C10 ecological/reversible:  yes (adv=+0.208)
  C11 ecological/irreversible:yes (adv=+0.300, damage_adv=+0.340)

Disposition:
  Inconclusive. The mixed pattern does not isolate a distinct ecological-irreversible axis.
  No retuning or G11/C1 revival follows.
```

### T-P7.1 - Bounded Consequence Prior Gate (Completed, NOT MET)

Authority:

- `docs/adr/ADR-0036-bounded-consequence-prior-gate.md`
- `../docs/research/RR-0023-p7x-candidate-backlog-and-consequence-prior-admission.md`

Goal:

Test one narrow B-channel candidate over already-strong P0:

```text
CP = P0 confidence-gated policy + bounded consequence prior
P0 = frozen confidence-gated policy, no consequence prior
```

ADR-0036 is explicitly not a G12 rescue. It asks whether a belief-only prior about
external action consequences creates a scar-specific improvement in irreversible cells
while staying near-null in reversible cells.

Frozen seeds:

```text
development/calibration: 1750..1769
r-final:                 1800..1829
```

Serial slices:

```text
T-P7.1a  scar validity screen and reversible/irreversible harness guards - complete
T-P7.1b  consequence-prior interface, belief-only merge path, and C6/C7 tests - complete
T-P7.1c  frozen controls: P0, RSTAR, and CAUTIOUS where applicable - complete
T-P7.1d  G13 development harness on non-r-final seeds - complete
T-P7.1e  one r-final on seeds 1800..1829 and ADR-0036 result update - complete
```

Development audit (not a scientific result):

```text
Result artifact: experiments/consequence_prior_g13.development.json
Scar validity screen: PASS
R0 reversible CP vs P0: adv=-0.274, first-window stale_prior_harm=13.094, any reversible-cell harm seeds=17/20, stale guard FAIL
R1 irreversible CP vs P0: adv=+0.048, wins=14/20, p=0.00604, damage_adv=+0.434
Specificity contrast: +0.264, CI lower +0.125, PASS preview
CAUTIOUS capture: 0.470
Gate preview: NOT MET preview because G13-1 irreversible benefit and G13-3 stale-prior guard fail.
R-final: completed after experiments/consequence_prior_g13.freeze.json unlock.
```

R-final result:

```text
Result artifact: experiments/consequence_prior_g13.result.json
Freeze artifact: experiments/consequence_prior_g13.freeze.json
Scar validity screen: PASS
G13 verdict: NOT MET
R0 reversible CP vs P0: adv=-0.255, first-window stale_prior_harm=12.679, any reversible-cell harm seeds=21/30
R1 irreversible CP vs P0: adv=+0.083, wins=25/30, p=0.000001895, CI=[291.66,589.94], damage_adv=+0.463
Specificity contrast: +0.317, CI lower +0.150, PASS
CAUTIOUS capture: 0.533
Gate: G13-1 FAIL (net adv below +0.10), G13-2 PASS, G13-3 FAIL, G13-4 PASS by tests.
```

Interpretation:

```text
CP carries a real irreversible-damage reduction signal, but not enough net loss advantage,
and it harms reversible cells. This is the pre-registered stale-prior failure pattern,
not an invalid apparatus result. G10/P0 remains the dominant confirmed lever.
```

Confirmed G10 result:

```text
A0 baseline + none       = 1304.7
A1 baseline + O1         = 1268.6
P0 gated policy + none   = 759.8
P0 vs A1 reduction       = 40.1%, 30/30, p<1e-6, bootstrap CI [457.0, 562.9]
```

Confirmed G10 completeness result (ADR-0030):

```text
B-temp fixed-low baseline = 1292.9 window area
P0 gated policy           = 739.8 window area
T1 vs B-temp              = 30/30, p<1e-6 PASS
T3 real-stake survival    = P0 1734.8 vs A0 1245.3 and B-temp 1482.6 PASS
T5b StalenessEnv          = P0 advantage 36.4%, GENERAL FIX not structure theft
Verdict                   = COMPLETENESS PASS
```

Confirmed PREDICTION 1 result (ADR-0031):

```text
Calibration seeds          = 1200..1219
Frozen params              = lambda 0.8 / eta 0.1
Prereg hash                = f87c23a43d2e0abd0130cee1ffab34b5741018ec8376f291139c2a5928abc936
R-final seeds              = 1300..1329
P0 frozen G10              = 788.8
PR gate + calibrator       = 793.3
PR vs P0                   = margin -0.006, 13/30, p=0.550830, CI [-30.8, 19.0]
PR-B vs A1                 = margin -0.039, CI [-67.9, -32.6]
Verdict                    = PRED1-HOLDS
```

Confirmed C3 result:

```text
DIRECTED IdleDrives = 1.691
RANDOM idle         = 1.676
POLICY no drive     = 1.701
Verdict             = RED; endogeny axis dropped
```

Confirmed survival-axis result (ADR-0028):

```text
EXPLORER regret/budget  = 1.876 / 549
EXPLOITER regret/budget = 1.613 / 1709
GATED regret/budget     = 1.048 / 2787
Verdict                 = RED; validity failed, survival shadows adaptation speed
```

Confirmed stationary risk-axis result (ADR-0029):

```text
EXPLORER survival = 1814
EXPLOITER survival = 1335
GATED survival = 1313
GATED vs best cheap = 2/30, p=0.97, gap CI [-570, -321]
Verdict = RED; no independent risk-aversion
```

Do not:

- Build C1 before a new ADR freezes a valid multi-axis gate.
- Reopen IdleDrives, RAP, or G7/G8 organ tuning to rescue a gate.
- Claim G11 is ready while it would collapse to G10 plus weak or non-independent side metrics.

### T-RouteC.1 - G-Eco Lower-Half + Pre-Gate-2 Candidate Writer/Verifier (Completed, No Verdict)

Authority:

- `../docs/research/founder-decision-2026-06-22-route-c-reset-and-geco-freeze.md`
- `../docs/research/G-Eco-preregistration-spec.md`
- `../docs/research/G-Eco-codex-handoff.md`
- `docs/adr/ADR-0038-g-eco-mechanism-lower-half.md`

Goal:

Implement only the G-Eco mechanism and pre-Gate-2 candidate surface that is safe before Gate-2:

```text
shared substrate observation/predictor/lookahead/H
ecological_4cond environment
VH + VH_noStake + 9-arm fixed-preference battery
HOMEOSTATIC_ORACLE + WCREF calibration-only refs
mechanism-check entrypoint
pregate2-candidates writer for candidate JSON only
pregate2-verify integrity/firewall verifier for candidate JSON only
deterministic replay, reset-boundary, C6/C7, and Gate-2 refusal guards
```

Implemented files:

```text
src/aac/g_eco.py
src/envs/ecological_4cond.py
experiments/g_eco.py
tests/test_g_eco.py
docs/adr/ADR-0038-g-eco-mechanism-lower-half.md
```

Boundary:

```text
Candidate `g_eco.rates.json` / `g_eco.battery.json` / `g_eco.thresholds.json` / `g_eco.baseline_audit.json` can be written only to an operator-selected output directory.
Candidate JSON existence or `pregate2-verify` pass is not Gate-2 unlock.
No founder/CTO co-signed freeze.
No Gate-2 crossing.
No r-final run.
No verdict row or autonomy/intelligence claim.
```

## 3. Current Research Interpretation

G9 is the key pivot:

- G9 is formally **NOT MET** because the preregistered candidate was `P4 = gate + O4`, and G9-2 failed.
- The data nevertheless showed the first decisive positive signal:

```text
A0 baseline + none       = 1361.6
A1 baseline + O1         = 1325.6
A4 baseline + O4         = 1224.3
P0 gated policy + none   = 746.5
P4 gated policy + O4     = 893.4
```

Interpretation:

- The real bottleneck was not belief quality; it was belief-to-action coupling inside the subject policy.
- `P0` is subject-side and C6-preserving because it reads the agent's own `ActionOutcomeModel`.
- O4 becomes counterproductive under the gate because it re-inflates uncertainty and delays exploitation.
- G10 confirmed P0 on fresh seeds without HARKing.
- C3 showed the endogeny axis has no directed signal even in the structured environment.
- ADR-0028 showed survival-under-cost is not independent; budget and regret are both driven by adaptation speed.
- ADR-0029 showed the gate has no stationary risk-calibration advantage; the cheap broad explorer wins.
- ADR-0031 showed a residual belief calibrator does not beat frozen G10; RR-0019 Claim 1/3 survives this attack.
- ADR-0032 classifies frontier systems into admissible lanes: P4.x bounded organs, external research automation, product/deployment layers, or forbidden core paths.
- ADR-0033 specifically confines HyperAgents/DGM-style systems to external candidate generation; runtime self-modification and safety-substrate self-editing remain forbidden.

## 4. Phase Ledger

| Phase/Gate | Status | Meaning |
|---|---|---|
| P0 / G0 | Complete, NOT MET for relevance v0 | First vertical slice; v0 RelevanceField falsified |
| P1 / G1 family | Complete, NOT MET | Attention/relevance mechanisms did not clear recovery/regret gates |
| P1.5 / G1'/G2 | Complete, NOT MET | Contextual and causal relevance routes hard-stopped |
| P2 / G3 | Complete, mixed | Claim 1 viability/metabolic necessity supported; IdleDrives gain not established |
| P3 / G4 | Complete, NOT MET | RAP v0 archived; coordination did not beat strong baselines |
| P4 / G5 | Complete, NOT MET | Learned prior O2 did not beat cheap reset O1 |
| P4.x / G6a | MET | Structured reusable regime can make richer prior useful |
| P4.x / G6b | de-risk only | Semantic environment exploitable offline; real LLM requires founder spend/key ADR |
| P4.x / G7 | NOT MET | O4 beats O1 significantly but not O2 at 90% seed dominance |
| P4.x / G8 | NOT MET | Ensemble O5 did not improve over O4 |
| P4.x / G9 | NOT MET formally; P0 discovery positive | P0 gate-alone decisive, but not preregistered candidate |
| P6 / G10 | MET | Fresh-seed confirmation of P0; first decisive positive gate |
| P6 / ADR-0031 | PRED1-HOLDS | Residual calibrator failed to beat frozen G10; channel-decomposition prediction survived |
| P6 / ADR-0032 | Accepted | Frontier architecture intake lanes accepted; structured semantic/hierarchical environment route allowed as future docs/gate work |
| P6 / ADR-0033 | Accepted | HyperAgents/DGM assimilation boundary accepted; L0-L3 external use allowed, L4/L5 runtime self-editing forbidden |
| P6 / ADR-0034 | Completed | Relevance-aware full-Agent theory test: PRED-A/C pass, PRED-B fail; B/R/K account stands with weakened trajectory story and decisive K residue |
| P7 / ADR-0035 | Completed, inconclusive | G12 mixed pattern: C01/C10/C11 win, C00 does not; distinct ecological-irreversible axis not established |
| P7.x / ADR-0036 | Completed, NOT MET | CP reduces irreversible damage but fails net R1 advantage and stale-prior guard |
| Route C / ADR-0038 | Lower-half implemented + discipline fixes + pre-Gate-2 candidate writer/verifier, no verdict | G-Eco mechanism substrate/env/arms/refs/guards plus candidate freeze/audit writer and integrity/firewall verifier; founder/CTO co-signed freeze/Gate-2/r-final locked |
| P6 / C3 | RED | Idle-productivity de-risk drops the endogeny axis |
| P6 / survival axis | RED | Gated policy wins both measured metrics, but survival is a shadow of reframe/adaptation speed |
| P6 / risk axis | RED | Stationary risk calibration not improved by the gate; cheap broad explorer wins |
| P6 / G11 | Closed/parked | Not frozen; original C1 scope lacks a true multi-axis basis after C3/survival/risk RED |

## 5. ADR Ledger

Recent authoritative ADRs:

- `ADR-0020-g7-latent-regime-organ.md` - G7, NOT MET.
- `ADR-0021-p1-spectrum-ablation.md` - spectrum/ablation strengthening around O4.
- `ADR-0022-g8-ensemble-regime-organ.md` - G8, NOT MET.
- `ADR-0023-g9-confidence-gated-policy.md` - G9, confidence-gated policy, formal NOT MET with decisive P0 discovery.
- `ADR-0024-g10-subject-side-win-confirmation.md` - G10 MET; P0 confirmed on fresh seeds.
- `ADR-0025-system-level-autonomy-signature-gate.md` - route accepted; gate not frozen.
- `ADR-0026-c3-idle-productivity-de-risk.md` - C3 RED; endogeny axis dropped.
- `ADR-0027-post-c3-route-disposition.md` - G11/C1 parked until a second independent winning axis exists.
- `ADR-0028-survival-axis-de-risk.md` - survival RED; not independent of reframe/adaptation speed.
- `ADR-0029-risk-calibration-axis-de-risk.md` - risk RED; third single-lever confirmation; close the multi-axis hunt.
- `ADR-0030-g10-completeness-trap-avoidance.md` - G10 COMPLETENESS PASS; P0 survives every flip-the-conclusion trap.
- `ADR-0031-prediction1-residual-calibrator-vs-g10.md` - PRED1-HOLDS; residual calibrator did not open a second axis over frozen G10.
- `ADR-0032-frontier-architecture-intake-and-structured-env-route.md` - frontier intake lanes; P4.x bounded organs and external research automation only.
- `ADR-0033-hyperagents-dgm-assimilation-boundary.md` - HyperAgents/DGM external candidate-generation boundary; no runtime self-modification.
- `ADR-0034-relevance-aware-g10-theory-test.md` - B/R/K relevance-aware G10 theory test completed; RSTAR explains part but not most of the margin.
- `ADR-0035-p7-ecological-environment-axis.md` - P7 transferable ecological-structure environment axis and G12 2x2 gate; completed inconclusive.
- `ADR-0036-bounded-consequence-prior-gate.md` - G13 bounded consequence-prior gate; r-final complete, NOT MET.
- `ADR-0037-self-determination-depth-vs-corrigibility.md` - proposed docs-only SD0-SD4 vocabulary and SD4-separability question.
- `ADR-0038-g-eco-mechanism-lower-half.md` - G-Eco lower-half mechanism plus pre-Gate-2 candidate writer/verifier implemented; no co-signed freeze/r-final/verdict.

G10, G10 completeness, ADR-0031, ADR-0032, ADR-0033, ADR-0034, ADR-0035/G12, ADR-0036/G13 r-final, ADR-0038 lower-half, C3, survival, and risk results are written back. Handoff is unsafe if a document still says G10 is pending, C3 has not run, ADR-0028/0029/0030/0031/0032/0033/0034/0035/0036/0038 do not exist, ADR-0034 is pending, ADR-0035/G12 is pending, ADR-0036/G13 is pending/locked instead of NOT MET, ADR-0038 implies a G-Eco verdict, self-recursive systems may enter runtime, or G11/C1 is ready to freeze.

## 6. Non-Negotiable Boundaries

- No LLM in the control path.
- No business semantics in this repository.
- No cross-repo imports.
- No moving preregistered gates after seeing results.
- No claiming post-hoc winners on the same r-final seeds; fresh-seed confirmation is mandatory.
- C6 remains intact: organs may affect belief only, not action/policy/shell.
- C7 remains intact: pause/tighten/forbidden must dominate all action paths.
- ADR-0032 remains intact: every frontier candidate must be classified by lane and channel before implementation.
- ADR-0033 remains intact: HyperAgents/DGM-style systems are external candidate generators only, never runtime self-modifiers.

## 7. Handoff Discipline

Every material research/code change must update, in this order:

1. `docs/CURRENT_STATE.yaml`
2. `docs/PROJECT_PLAN.md`
3. `codebase_index.md`
4. `ROADMAP.md` if the phase/route changed
5. relevant ADR result/status section
6. root `../code_index.md` if the workspace-level truth changed
7. root `../MEMORY.md` only as a concise cross-agent summary

Agents should not read the whole repository by default. Start from `docs/CURRENT_STATE.yaml` and follow its `handoff_read_order`.
