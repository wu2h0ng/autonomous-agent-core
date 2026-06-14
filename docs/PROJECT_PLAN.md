# PROJECT_PLAN - autonomous-agent-core

> Last updated: 2026-06-14
> Status: Active handoff document
> First read: `docs/CURRENT_STATE.yaml` -> this file -> `codebase_index.md` -> `ROADMAP.md` -> current ADRs.

## 1. Current Truth

This repository is the object-layer primary artifact: a domain-agnostic autonomous-agent prototype. The enterprise OS is a deployment projection, not the main research line.

Current branch:

```text
feat/g9-confidence-gated-policy
```

Current stage:

```text
P6 route C
  -> G10: P0 confidence-gated policy confirmed on fresh seeds (MET)
  -> C3: idle-productivity de-risk returned RED
  -> ADR-0027: G11/C1 parked until a second independent winning axis exists
  -> next: consolidate G10, or open a new-axis ADR / P5 projection
```

Do not describe the current stage as P1, P2, P3, or P4. Those are historical phases.

Latest test truth:

```text
PYTHONPATH=src python -m unittest discover -s tests -v
370 tests OK
```

The 370-test result is recorded by ADR-0026's C3 r-final on 2026-06-14. Re-run before code submission if you change code.

## 2. Immediate Task

### T-P6.3 - Post-C3 Route Disposition

Authority:

- `docs/adr/ADR-0024-g10-subject-side-win-confirmation.md` (G10 MET)
- `docs/adr/ADR-0026-c3-idle-productivity-de-risk.md` (C3 RED)
- `docs/adr/ADR-0025-system-level-autonomy-signature-gate.md` (G11 route accepted, gate not frozen)
- `docs/adr/ADR-0027-post-c3-route-disposition.md` (current route ruling)
- `ENGINEERING.md` section 4 items 5-6

Goal:

Keep the handoff state honest after G10 MET and C3 RED. Do not freeze G11/C1 as originally scoped: after C3, only the reframe axis has a confirmed vs-cheap-baseline win. Consolidate G10 as the current positive result; any new system-level gate needs a new independent winning axis first.

Confirmed G10 result:

```text
A0 baseline + none       = 1304.7
A1 baseline + O1         = 1268.6
P0 gated policy + none   = 759.8
P0 vs A1 reduction       = 40.1%, 30/30, p<1e-6, bootstrap CI [457.0, 562.9]
```

Confirmed C3 result:

```text
DIRECTED IdleDrives = 1.691
RANDOM idle         = 1.676
POLICY no drive     = 1.701
Verdict             = RED; endogeny axis dropped
```

Do not:

- Build C1 before a new ADR freezes a valid multi-axis gate.
- Reopen IdleDrives, RAP, or G7/G8 organ tuning to rescue a gate.
- Claim G11 is ready while it would collapse to G10 plus weak side metrics.

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
| P6 / G11 | Route accepted, parked | Not frozen; original C1 scope lacks a true multi-axis basis after C3 RED |

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

G10 and C3 results are written back. Handoff is unsafe only if a document still says G10 is pending or C3 has not run.

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
