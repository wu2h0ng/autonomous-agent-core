# AGENT-OS-SELFDEV-1 — Slice Cast

> Status: `CAST / NOT_IMPLEMENTED / NOT_RUN`
> Date: 2026-07-22
> Track: `Product + Translational Research`
> Primary class: `P/R`
> Owner: Founder / CTO
> Scope: first bounded slice for Agent OS developing Agent OS in a rollback-safe repository environment

## 1. Decision

The near-term primary Product loop is **Agent OS develops Agent OS**.

The first validation environment is the Agent OS software repository because it has the right physics for governed self-development: exact bytes, diffs, tests, static checks, branch/worktree isolation, review, reversible history, durable evidence and outcome receipts.

This is not a generic coding-agent benchmark. The question is whether Agent OS can reduce founder/operator hidden cognitive work while making real Agent OS changes under Mandate, typed authority, C7, exact approval and rollback constraints.

## 2. First slice: SELFDEV-S1

`SELFDEV-S1` is a single rollback-safe Agent OS repository task executed through the existing Task Workspace/Agent Core spine.

Required task shape:

1. Target repository: `autonomous-agent-core` or an isolated worktree/copy with real Agent OS package/test layout.
2. Task: a bounded non-release Agent OS improvement with one clear failing or missing acceptance check.
3. Provider output: exactly one typed `ProviderToolProposal` for `workspace.apply_patch`.
4. Authority: no file effect before exact-digest human/founder approval.
5. Execution: patch applied only after approval on an isolated branch/worktree.
6. Verification: allowlisted command set only, at minimum targeted pytest plus targeted Ruff/Pyright when applicable.
7. Outcome: `ExpectedOutcome` and `ObservedOutcome` must bind evidence artifacts and fail closed if evidence disappears or verifier is unknown.
8. Rollback: `compensate_task` or equivalent repository rollback must restore pre-change bytes when invoked.
9. Help: if the task requires a value choice, secret, external service, release, main push or ambiguous tradeoff, the system emits a structured `HelpRequest` instead of guessing.

## 3. Acceptance gates

`SELFDEV-S1` passes only if all gates hold:

| Gate | Requirement | Failure semantics |
|---|---|---|
| G1 real target | The target file/test belongs to Agent OS code/docs, not a toy fixture | `INVALID_SELFDEV_TARGET` |
| G2 typed proposal | Provider emits one authorized `workspace.apply_patch` proposal | malformed/multiple/unauthorized proposal -> no file effects |
| G3 exact approval | Approval digest matches proposed action digest and is unexpired | `WAITING_APPROVAL` or fail closed |
| G4 isolated repo | Run occurs on isolated branch/worktree/copy, never unreviewed main/release | `RUN_DENIED` |
| G5 verification | Allowlisted tests/static checks produce durable artifacts | missing/non-zero/unknown verifier -> `UNRESOLVED` or `NOT_MET` |
| G6 outcome truth | Observed outcome is derived from frozen `ExpectedOutcome` and evidence | forged/missing evidence invalidates current outcome |
| G7 rollback | Compensation restores pre-change bytes and records receipt | rollback failure keeps failure authoritative |
| G8 HCW telemetry | Operator interventions and HCW minutes are recorded | result cannot support SELFDEV claim |
| G9 baseline | Same task has or can receive founder/user-driven model+tools baseline under same authority and budget | no comparative claim |

## 4. Baseline and metric

Primary metric is not task success alone.

Compare Agent OS self-development against founder/user-driven frontier model + tools on:

- effective verified repository changes;
- operator intervention count;
- HCW minutes across state maintenance, relevance judgment, next-step generation, result interpretation and escalation;
- failed-run recovery and rollback success;
- regression or bypass rate;
- cost and latency.

Positive evidence means: Agent OS reduces hidden cognitive work or improves recovery/outcome quality under the same repository task, authority envelope and budget. A green patch without HCW or baseline evidence is only `E`, not `P/R`.

## 5. Implementation route

Smallest useful implementation package:

1. Add a `SelfDevelopmentTaskSpec`/receipt or equivalent product contract that binds:
   - target repo identity and head;
   - isolated branch/worktree path;
   - allowed files and verifier commands;
   - expected outcome;
   - rollback strategy;
   - HCW telemetry fields;
   - baseline assignment metadata.
2. Add a product test that executes a SELFDEV-S1 task against an isolated Agent OS repository copy/worktree and proves:
   - no pre-approval file effect;
   - approved patch changes a real Agent OS file;
   - targeted verification passes;
   - outcome evidence is content-bound;
   - deleting evidence invalidates current outcome;
   - compensation restores bytes.
3. Add a negative test for a generic/toy target or non-Agent OS path, which must fail `INVALID_SELFDEV_TARGET`.

## 6. Non-claims

This slice does not authorize release, main merge, production activation, self-approval, gate mutation, C7 mutation, runtime self-modification or any `Autonomy(S,E,O,V,T)` claim.

It is the first product validation lane for M2 hidden cognitive work reduction and M3 governed adaptation in a precise, rollback-safe software environment.
