# Agent OS Project Plan

> Status: `ACTIVE / AUTHORIZED-SEQUENCE ONLY`
> Updated: 2026-08-11
> Product authority: `AGENT-OS-PRODUCT-BLUEPRINT.md`
> Live truth: `CURRENT_STATE.yaml`
> This file is not a historical changelog and does not authorize work by itself.

## 1. Planning rule

The repository has two tracks under one architecture:

- **Product Track** builds the Agent OS product body.
- **Research Track** produces falsifiable mechanism evidence and negative results.

Work may proceed concurrently, but evidence cannot jump tracks. A Research Track win needs a named Product Track consumer, stable contract and product-side held-out gate. A Product Track milestone does not validate autonomy theory.

Every task must declare: track, claim class, authority, entry point, contract, failure path, bypass-detecting verification, C6/C7 boundary, evidence level and next gate.

## 2. Current priority order

### P0 — Review and integrate canonical authority convergence

**Task:** `CANONICAL-CONVERGENCE-2026-07-15`

**Status:** `FEATURE_BRANCH_READY_FOR_INDEPENDENT_REVIEW / DOCS_ONLY / NOT_MERGED`

**Outcome:** combine the branch-contained SPINE/LH D1 ancestry at `7410a06df3182ec59da1d421916b5bf8086ea8c4` with the compact 2026-07-14 authority-document commit `4ee868d5d419a786c0f8339fffbccbcdf828a79e`.

**Required truth:** E2E-1/2/3 remain `INVALID`; E2E-4 remains one bounded local same-boot `PASS`; LH v5 has accepted Combined-D1 prerequisite receipts plus one-shot 432-case materialization and oracle `432/432`, but no D2 or formal result; B1 and RTM-1 remain separate-branch evidence; SPINE-1 is independently approved and main-integrated as a bounded Data Agent domain pack only.

**Hard boundary:** no runtime/frozen-result rewrite, experiment, push, main merge, migration, release, autonomy or AGI claim.

**Exit:** YAML, local links, conflict-marker scan and diff checks pass; independent reviewer accepts the exact feature commit before any separately authorized merge.

### P1 — Complete LH-RECOVERY-1A Tasks 7/8 only

**Task:** `LH-RECOVERY-1A-TASKS-7-8`

**Status:** `SEPARATE_BRANCH_ACTIVE / IMPLEMENTATION_ONLY / NO_D2 / NO_FORMAL_RESULT`

**Purpose:** implement the public four-arm protocol, frozen failure paths, real natural-time phase sequence and mechanical adjudicator required before any future child experiment.

**Immutable inputs:**

- Combined-D1 candidate `7410a06df3182ec59da1d421916b5bf8086ea8c4`;
- accepted v5 binding and reveal-order amendment;
- one-shot generation receipt for 432 cases / 1728 episodes;
- oracle receipt `ORACLE_PASS_432_OF_432`.

**Write scope:** only `product_evals/lh_recovery_1a/protocol.py`, `product_evals/lh_recovery_1a/cli.py` and `tests/product_eval/test_lh1a_protocol.py` on `codex/lh1a-task7-8-20260715`.

**Stop:** any frozen D1/corpus/oracle mutation, Product contract expansion, corpus regeneration, oracle rerun, D2 construction or formal outcome run.

### P2 — Keep D2 behind a new explicit gate

**Task:** `LH-RECOVERY-1A-D2`

**Status:** `NOT_CONSTRUCTED / NOT_AUTHORIZED_BY_THIS_PLAN / NOT_RUN`

Tasks 7/8 completion does not create D2 or run authority. A future D2 packet requires exact Task 7/8 implementation and independent reviews, intact frozen prerequisite hashes, a new scoped authority decision, preregistration review and freeze. Parent `LH-RECOVERY-1` remains `OPEN/BLOCKED/NOT_RUN` and cannot pass by implication.

### P3 — Preserve the completed B1 non-training harness

**Task:** `B1-UNIFIED-MODEL-SANDBOX`

**Status:** `SEPARATE_BRANCH_ACCEPTED / HARNESS_COMPLETE / SANDBOX_ONLY / NO_TRAINING`

The cross-model accepted falsifier baseline lives on `feat/b1-sandbox-harness-20260713` at `02b904cc7ad94d8ab430e9fc789563d0dbc9a5de`. Preserve it as a necessary pre-prereg screen. Do not admit a model, training, Gate R/P result, Agent OS integration or product claim without a new founder gate and the full preregistration chain.

### P4 — Preserve accepted RTM-1 resource-v4 implementation evidence

**Task:** `RTM-1-R6.2-RESOURCE-V4`

**Status:** `SEPARATE_BRANCH_IMPLEMENTATION_ACCEPTED / DESIGN_ONLY / NOT_BENCHMARKED / NOT_FROZEN / SEED_UNGENERATED / NOT_RUN`

Exact accepted implementation head: `368f8acc1062c989be1930133087d76856bf7384` on `codex/itc1-stage0-harness-20260713`. It is implementation evidence only. Benchmarking, successor freeze, production seed access, held-out opening, a result-bearing run, G-TC/G-PV movement, Product projection and autonomy claims all require separate authority.

### P5 — Preserve the bounded main-integrated SPINE-1 capability

**Task:** `T-P-OS-SPINE-1`

**Status:** `G0-G7_PASS / INDEPENDENT_REVIEW_APPROVE / PUSHED / MAIN_INTEGRATED / UNRELEASED`

The bounded donor-history import, capability extraction, staging removal, verification and exact-head independent review are integrated on Agent OS main through receipt `807a0590`, with reviewed code head `e1cf9c4c`. Root G0 is reconciled. Release, production activation, donor archival/deletion and broader capability admission remain separately gated.

### P6 — Keep governed core evolution at plan-only

**Program:** `GOVERNED-CORE-EVOLUTION`

**Status:** `PARK / DESIGN_AND_PLAN_ONLY / NO_RUNTIME_AUTHORIZATION`

GCE-O1/M1/K1 packets may be prepared only under the root founder decision. L4 active-runtime self-modification remains closed; L5 safety-substrate self-edit, self-evaluation ownership, self-approval and self-promotion remain forbidden.

## 3. Product horizon after the current priorities

The dependency order, not a calendar commitment:

### H1 — One complete Agent OS spine

- persistent Task Workspace and task/run lifecycle;
- production-grade provider/credential plane;
- typed capability/plugin host;
- WorkflowGraph authoring and versioning;
- evidence/outcome and failure-attribution plane;
- identity, policy, C7 and operator controls.

### H2 — Three complete paths

- developer work with broad repository actions, review and recovery;
- private personal work with durable context and changing constraints;
- Data Agent on the shared spine after SPINE-1.

### H3 — Operational body

- tenancy, encrypted credentials, SSO/policy administration;
- deployment, observability, SLOs, backup/restore and incident response;
- admin and operator surfaces;
- supported capability/domain-pack ecosystem.

### H4 — Outcome compounding

- product belief ledger;
- staleness/conflict/correction and invalidation;
- governed model/tool/workflow selection;
- learned-procedure candidates with held-out eval and rollback;
- long-horizon planning/recovery benchmark.

### H5 — Evidence-gated research promotion

- CWM only in identifiable product workflows;
- G10-like decision policy only after product revalidation;
- additional mechanisms only through an explicit candidate manifest and fair product comparison.

## 4. Research route admission

No new Research Track route starts from an interesting paper, benchmark or component. Admission requires:

1. foundational problem lock;
2. frontier/anomaly intake where external evidence is involved;
3. paradigm thesis and null/reduction hypothesis;
4. independent architecture designs and skeptic reduction;
5. architecture-theory review with claim channel, product/process boundary, prior negative map, cheap baseline and C6/C7/SD4 analysis;
6. founder route cast;
7. formal/algorithm spec and implementation cast before mechanism files;
8. preregistration, independent review, manifest integrity and freeze;
9. one result-bearing run under locked rules;
10. independent adjudication, claim review, negative-map update and paradigm learning.

If a route reduces to a cheap baseline, lacks independent truth, depends on an oracle or cannot name a consumption path, use `PARK` rather than extending the ladder.

## 5. Existing results that constrain planning

- SPINE-E2E-1/2/3 remain immutable `INVALID`; SPINE-E2E-4 is one bounded local same-boot `PASS`, not a predecessor rewrite or general long-horizon claim.
- LH-RECOVERY-1A v5 reached Combined-D1 acceptance, one-shot 432-case materialization and oracle `432/432`; these are prerequisite receipts, not D2 or a formal result.
- The B1 falsifier harness is complete only on a separate sandbox branch; `SANDBOX_ONLY / NO_TRAINING` remains binding.
- RTM-1 resource-v4 is accepted implementation only on a separate branch and remains `NOT_BENCHMARKED / NOT_RUN`.
- SPINE-1 is independently approved and main-integrated as a bounded domain pack; the standing Data Agent repository remains physically retained for provenance and fallback pending a separate archival decision.
- G10 remains a narrow positive task/regret result; Product Track must revalidate it before use.
- G13 and G-ECO-REOPEN-1 are final `NOT_MET`; no rescue runs.
- survival/risk/endogeny did not establish an independent axis.
- GSE42528 Branch-M and the adaptivity-gap route are parked.
- non-oracle real structure/mechanism discovery remains unresolved.
- CWM hard-form evidence is narrow and does not justify universal use.
- RR-0034/SD4 terminus is a scoped theoretical record; autonomy claims still use RR-0024.

These constraints narrow work; they do not imply that all future mechanisms are impossible.

## 6. Task completion gates

### Product implementation

Must identify the real entry point, typed contract, unsafe/invalid failure path, bypass-detecting test, integration surface, evidence/trace and deployment/authorization state.

### Research implementation

Must match frozen spec bytes, mechanism hashes, seed/data policy, baseline manifests and architecture/prereg reviews. Green unit tests do not authorize a run.

### Documentation

Must update CURRENT_STATE only for live truth, plans only for authorized next work and indexes only for routing. Historical detail belongs in ADR/RR/result/Git, not CURRENT_STATE.

### Git

Run `git status --short` and `git diff --check`; separate task changes from pre-existing experiment/worktree changes. Do not push, merge, migrate or release without separate authorization.

## 7. Explicitly not authorized by this plan

- rewriting SPINE-E2E-1/2/3 `INVALID` or widening SPINE-E2E-4 beyond its bounded result;
- constructing LH-RECOVERY-1A D2 or running a formal outcome under the Tasks 7/8 authority;
- benchmarking, freezing, seeding or running RTM-1 resource-v4;
- releasing Agent OS, activating production, or archiving/deleting the standing Data Agent donor;
- Agent OS Product Alpha, production or superiority claims;
- B1 model training or result-bearing experiment;
- SPINE-1 release, production activation, donor archival/deletion or unreviewed capability expansion;
- CWM real-actuator promotion;
- G13/G-Eco rescue, reseed or gate changes;
- general autonomy or AGI claims;
- L4 runtime self-modification or L5 safety-root editing;
- product execution by Research Track or workflow tooling.
