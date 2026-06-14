# PROJECT_PLAN - autonomous-agent-core

> Last updated: 2026-06-14
> Status: Active handoff document
> First read: `docs/CURRENT_STATE.yaml` -> this file -> `codebase_index.md` -> `ROADMAP.md` -> current ADRs.

## 1. Current Truth

This repository is the object-layer primary artifact: a domain-agnostic autonomous-agent prototype. The enterprise OS is a deployment projection, not the main research line.

Current branch:

```text
feat/p6-consolidate-g10
```

Current stage:

```text
P6 consolidated
  -> G10: P0 confidence-gated policy confirmed on fresh seeds (MET) and trap-complete (ADR-0030)
  -> C3: idle-productivity de-risk returned RED
  -> ADR-0028: survival-axis de-risk returned RED; survival shadows reframe/adaptation speed
  -> ADR-0029: stationary risk-axis de-risk returned RED; cheap broad explorer wins
  -> result: no independent second axis after endogeny/survival/risk probes; G10 stands
  -> next: publish consolidation; continue P5 deployment projection in the enterprise repo
```

Do not describe the current stage as P1, P2, P3, or P4. Those are historical phases.

Latest test truth:

```text
PYTHONPATH=src python -m unittest discover -s tests -v
380 tests OK
```

The 380-test result is recorded by ADR-0030 completeness integration on 2026-06-14. Re-run before code submission if you change code.

## 2. Immediate Task

### T-P6.4 - P6 Consolidation And Handoff

Authority:

- `docs/adr/ADR-0024-g10-subject-side-win-confirmation.md` (G10 MET)
- `docs/adr/ADR-0026-c3-idle-productivity-de-risk.md` (C3 RED)
- `docs/adr/ADR-0027-post-c3-route-disposition.md` (G11/C1 parked until a second independent axis exists)
- `docs/adr/ADR-0028-survival-axis-de-risk.md` (survival RED)
- `docs/adr/ADR-0029-risk-calibration-axis-de-risk.md` (risk RED; close the multi-axis hunt)
- `ENGINEERING.md` section 4 items 5-6

Goal:

Keep the handoff state honest after the full P6 de-risk sequence. Do not freeze G11/C1 as originally scoped: after C3, survival, and stationary risk all returned RED, only the reframe/adaptation axis has a confirmed vs-cheap-baseline win. G10 is the consolidated positive result; any future system-level gate needs a new founder-level ADR and a new independent winning axis first.

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

G10, G10 completeness, C3, survival, and risk results are written back. Handoff is unsafe if a document still says G10 is pending, C3 has not run, ADR-0028/0029/0030 do not exist, or G11/C1 is ready to freeze.

## 6. Non-Negotiable Boundaries

- No LLM in the control path.
- No business semantics in this repository.
- No cross-repo imports.
- No moving preregistered gates after seeing results.
- No claiming post-hoc winners on the same r-final seeds; fresh-seed confirmation is mandatory.
- C6 remains intact: organs may affect belief only, not action/policy/shell.
- C7 remains intact: pause/tighten/forbidden must dominate all action paths.

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
