# LH-RECOVERY-1A-D1-REBIND-1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox
> (`- [ ]`) syntax for tracking.

**Document status:** `PLAN_ONLY_CANDIDATE_BYTES_IMMUTABLE`

**Goal:** Replace the stale SPINE-E2E-1/runner-804c8d5 execution bindings in the accepted
LH-RECOVERY-1A design with exact SPINE-E2E-4 evidence and then execute the already bounded
strong-baseline chain without allowing a child result to pass parent `LH-RECOVERY-1`.

**Architecture:** This document is a digest-bound successor overlay over the complete 2026-07-12
LH-RECOVERY-1A design. It changes only execution identity, prerequisite evidence, runner
authority, permission authority, and stale-binding controls. The old design remains the semantic
payload for population, arms, fairness, timing, statistics, C7 priority, D1/D2 ordering, and
automatic PARK rules; any conflict is resolved by this successor. D1-E freezes before blind
builder exposure, D1-F is sealed independently, and D2 cannot exist until combined D1 plus
commit-reveal plus a one-shot `432/432` oracle are valid.

**Tech Stack:** Python 3.11+, stdlib hashing/HMAC/JSON/SQLite/subprocess/time, existing Product
packages and public `AgentOSApplication`, pytest, Ruff, Pyright, and workflow-runner commit
`50eb4d27b17688f0943f80207dddb702983afd51`.

## Global Constraints

- Track is `translational_research`; Product runtime is the object under test and research
  evidence never becomes a Product or autonomy claim by implication.
- Parent `LH-RECOVERY-1` remains `OPEN/BLOCKED`, not preregistered, not frozen, and not run under
  every child outcome.
- `SPINE-E2E-1`, `SPINE-E2E-2`, and `SPINE-E2E-3` remain immutable `INVALID` predecessor evidence.
- `SPINE-E2E-4` is the sole prerequisite PASS and must never be rerun, rewritten, or rescued.
- No D1 implementation file, corpus, assignment, provider bank, oracle output, D2 spec, or formal
  ledger may exist before its preceding gate explicitly permits it.
- Every production behavior change follows RED -> observed expected failure -> minimal GREEN ->
  focused tests -> broader tests; tests written after code do not count as TDD evidence.
- Claude is primary architecture reviewer. Kimi and OpenCode are independent mechanical reviewers.
  If Claude is unavailable, a fresh high-capability subagent may substitute only when its exact
  identity and non-Claude status are recorded; no silent provider/model substitution counts.
- Before any fresh Claude/substitute architecture judgment, RR-0031 is mandatory in the same run:
  the reviewer receives only the L0 constitutional/current-state/negative-result pack, writes a
  blind calibration record, and passes runner `context-calibration record` plus `verify` in blind
  phase. Only then may that same identity receive the exact bounded plan/evidence slice. Its
  architecture review must contain the controlled-exposure delta review and be re-recorded and
  verified in `delta_review` phase. An uncalibrated review is `INVALID_REVIEW`, even if its prose
  verdict says ACCEPT. Kimi/OpenCode may remain uncalibrated only while making byte/mechanical
  claims; any architecture or route conclusion from them has no authority in Task 0.
- Builder, fixed-baseline builder, skeptic, environment reviewer, and result adjudicator identities
  must be pairwise separated where the underlying gate requires independence.
- No model, provider, builder, skeptic, or coordinator may see either nonce before its commitment
  is durably appended. No corpus may exist before both valid reveals.
- The 432-case corpus is materialized exactly once. The oracle runs exactly once and must return
  `432/432`; any other outcome terminates this version as `INVALID_GENERATOR`.
- No seed change, case replacement, baseline weakening, threshold movement, environment change,
  metric substitution, rerun, or rescue is allowed after an observed outcome.
- No LLM enters the Product control path. C7 remains external, deterministic, non-writable, and
  non-bypassable; SD4 and ADR-0033 L4/L5 remain founder-reserved/forbidden.
- Runtime or preregistration code may not contain handwritten copies of runner event field sets,
  historical target constants, or mutable-ledger whole-file digests. It must consume exported
  schemas, generated receipts, Git-resolved target identities, and canonical row digests.

---

## 1. Successor authority and precedence

### 1.1 Bound predecessor payload

The semantic base plan is:

```text
docs/superpowers/plans/2026-07-12-lh-recovery-1a-explicit-rebind.md
raw_sha256 = 014b9d8c37952292f7564c1a75c4c482185a6fde4e528fcacbd3bc8b006563e1
byte_length = 29521
```

The base plan is incorporated by exact digest. If its bytes drift, this successor is
`INVALID_PLAN_BINDING`; do not reinterpret or re-copy it. This successor supersedes only:

1. every executable prerequisite reference to `SPINE-E2E-1` with the exact E2E-4 binding in §2;
2. every executable runner reference to `804c8d54...` with the exact runner binding in §2;
3. the old run identity/date with `LH-RECOVERY-1A-D1-REBIND-1` and run-local identities derived
   from `lh-recovery-1a-d1-rebind-1-20260714`;
4. any implication that D1 construction can begin without the review acceptance in Task 0;
5. any static D1/D2 Product target copied from an earlier phase with the live-target rule in §3.

Historical occurrences inside predecessor result/spec files remain audit evidence and are not
stale executable bindings. New executable artifacts must not refer to them.

### 1.2 Successor run identity

```text
successor_id = LH-RECOVERY-1A-D1-REBIND-1
governance_run_id = lh-recovery-1a-d1-rebind-1-20260714
document_status = PLAN_ONLY_CANDIDATE_BYTES_IMMUTABLE
acceptance_authority = run-local exact-digest receipt plus message-bus event
```

Task 0 must never mutate this document to record acceptance. After all three required reviews
accept the exact bytes, the coordinator writes run-local `plan_acceptance.json` binding the plan
digest plus each review artifact digest, identity, and verdict, the primary architecture reviewer’s
verified same-run RR-0031 `delta_review` record digest, and appends the corresponding message-bus
event.
The receipt verifier must rehash all four artifacts and replay `context-calibration verify`; prose
or a receipt file alone cannot promote the plan. That external verified receipt is the sole
`PLAN_ONLY_ACCEPTED` authority. Any plan-byte change creates a new candidate digest, invalidates
every earlier review/receipt, and requires a complete three-review cycle.

## 2. Exact prerequisite bindings

### 2.1 SPINE-E2E-4

| Binding | Exact value |
|---|---|
| Product target under SPINE test | `b2bc9f5b4eb3e90c46527075346ab3b0178aafb4` |
| Runner target | `50eb4d27b17688f0943f80207dddb702983afd51` |
| Raw prereg spec SHA-256 | `b29c9f477122c409165c113df6eaac1b9d71ae2407266e84bea95469ec484219` |
| Canonical spec SHA-256 | `3846810fbe7c63bb264f9869af02a33c4b4224d00e9cfd781101c9dfb1ea6495` |
| Raw prereg lock SHA-256 | `bc99dbfe82ed935a9277a6a28272908b970744a519b7a67001c418e5acd5582b` |
| Raw result SHA-256 | `14f388383af717d99a76b70380569e2a94550459869f48febb7eff322c5e1470` |
| Result verdict | `PASS` |
| Result run ID | `spine-e2e-4-20260713` |

Before Task 0 review and again before D1 freeze, machine verification must prove:

```bash
sha256sum .agent_runs/spine-e2e-4-20260713/prereg.lock
sha256sum .agent_runs/spine-e2e-4-20260713/evaluation/result.json
PYTHONPATH=src python3 -m agent_workflow_runner.cli prereg verify \
  --workspace-root <workspace-root> \
  --run-id spine-e2e-4-20260713 \
  --target <product-worktree> \
  --result .agent_runs/spine-e2e-4-20260713/evaluation/result.json
```

Expected: the two raw digests above and `{"intact": true, "drift": []}`. Any mismatch blocks
D1; no rebinding after an observed D1 outcome is permitted.

### 2.2 Founder permission record for this successor

Mutable append-only ledger files are not bound by their changing whole-file digest. The exact
canonical rows that authorize this chain are bound independently:

| Binding | Exact value |
|---|---|
| Permission request ID | `perm_4d4634d17eabc8f0` |
| Canonical request row SHA-256 | `d5145e1f641aa0f78600e0aead767fde23f7c33891be40df65c37378b5a5e582` |
| Canonical approval row SHA-256 | `d15b3354fcc8c2de0c489d55cf07d34467d0eeaa23648df2ce54f42cf6b317fc` |
| Decision | `approved_session` |
| Decided by | `founder` |
| Source decision | `founder-2026-07-14-lh1a-d1-rebind` |
| Source goal | `LH-RECOVERY-1A-D1-REBIND-1` |
| Evidence root | `autonomous-agent-core/.worktrees/spine-e2e4-runner-contract-20260713` |

The binder must locate exactly one request and one approval row with these identities, canonicalize
each row independently, and verify the row digests. Later appended permissions do not invalidate
these rows and cannot broaden their affected paths.

`perm_891a1330af6034af` is preserved as an earlier superseded record but is forbidden as an
execution binding: its repo-relative evidence path resolves to the stale default checkout rather
than this linked worktree. A binder that selects it must fail.

## 3. Live Product target rule

Two Product identities must remain distinct:

1. `spine_product_target` is the immutable E2E-4 target in §2.1.
2. `d1_product_target` is the clean Git commit containing accepted Task 1 plus accepted D1
   mechanism code. It does not exist at plan-only time.

Current clean execution base is
`a632dc569851428f9e24fcc47d46f162034c2f15`. This is orientation, not the future D1 target.
No agent may copy it into D1 or D2 as a final target. The D1 binder must resolve `git rev-parse
HEAD`, branch, common-dir, worktree, clean status, source paths, and mechanism digests at the
pre-freeze boundary. An unresolved placeholder such as `PRE_FREEZE_TARGET_UNBOUND` is allowed only
in plan/review material; generic freeze must reject it in an executable preregistration.

## 4. Gated state machine

```text
PLAN_ONLY_DRAFT
  -> fresh Claude or explicitly recorded substitute identity RR-0031 blind
     PASS_TO_CONTROLLED_EXPOSURE/verify before plan exposure
  -> bounded plan/evidence exposure -> RR-0031 delta_review phase record/verify
  -> exact primary architecture reviewer ACCEPT
  -> exact Kimi mechanical ACCEPT
  -> exact OpenCode mechanical ACCEPT
  -> external exact-digest PLAN_ONLY_ACCEPTED receipt
  -> Task 1 C7 RED/GREEN/review ACCEPT
  -> D1-E implement + independent review + freeze/runner anchor
  -> blind fixed builder receives only frozen D1-E
  -> builder submits sealed D1-F
  -> skeptic reduction verdict
       reducible     -> PARK_AS_SCHEDULE_ENGINEERING (terminal; no combined D1/corpus/D2)
       not_reducible -> combined D1 candidate review ACCEPT
  -> two nonce commitments
  -> combined D1 freeze/acceptance binding both commitments
  -> two nonce reveals
  -> derived root seed -> one materialization -> one oracle
       oracle != 432/432 -> INVALID_GENERATOR (terminal; no repair/rerun)
       oracle == 432/432 -> four-arm public protocol/failures implementation
  -> real phase protocol + mechanical adjudicator implementation
  -> D2 construction/review/freeze allowed
  -> one frozen LH-RECOVERY-1A run -> mechanical + independent adjudication
```

No transition may be inferred from green unit tests alone. Each transition requires its named
durable artifact and message-bus event.

## Task 0 — Plan-only successor and three independent reviews

**Files:**

- Create: `docs/superpowers/plans/2026-07-14-lh-recovery-1a-d1-rebind-1.md`
- Create: `.agent_runs/lh-recovery-1a-d1-rebind-1-20260714/reviews/claude-plan-architecture.md`
- Create before Claude sees the plan:
  `.agent_runs/lh-recovery-1a-d1-rebind-1-20260714/reviews/claude-plan-architecture-blind-calibration.md`
- Create: `.agent_runs/lh-recovery-1a-d1-rebind-1-20260714/reviews/kimi-plan-mechanical.md`
- Create: `.agent_runs/lh-recovery-1a-d1-rebind-1-20260714/reviews/opencode-plan-mechanical.md`
- Create after all three exact ACCEPT verdicts:
  `.agent_runs/lh-recovery-1a-d1-rebind-1-20260714/plan_acceptance.json`

- [ ] Verify every §2 digest and canonical permission row before dispatch.
- [ ] Start a fresh primary architecture reviewer identity (Claude, or the explicitly recorded
      substitute only after the fallback condition is met) with L0 only:
      `docs/GOAL-BLUEPRINT.md`, linked-worktree `docs/CURRENT_STATE.yaml`, RR-0024, RR-0029,
      RR-0030, and the two run-selected negative maps.
      Do not expose this candidate, the base plan, SPINE artifacts, implementation, or PR history.
      Have it write the blind calibration record, then use runner `context-calibration record` and
      `verify` with claim class `research-theory`, target `autonomous-agent-core`, and a distinct
      `reviewed_by` identity. Anything other than verified `PASS_TO_CONTROLLED_EXPOSURE` stops.
- [ ] Only after blind verification, give the same primary reviewer identity the exact candidate,
      bound base plan, SPINE-E2E-4 result/lock, and canonical permission rows. Have it write the primary
      architecture review including explicit controlled-exposure delta sections: claim boundary,
      base-plan incorporation, D1-E-before-exposure ordering, fairness, C7, independence, PARK
      logic, and D2 impossibility before every gate. Record the exact exposure refs plus review as
      a runner `delta_review` calibration packet and verify its digest.
- [ ] Dispatch Kimi read-only for exact identity/digest/path/row verification and stale-constant
      scan.
- [ ] Dispatch OpenCode read-only for an independent exact mechanical review, including mutation
      cases for one-character digest drift, appended permission rows, wrong Product target, and
      unresolved freeze placeholders.
- [ ] If Claude is unavailable, dispatch a fresh high-capability Codex subagent through the same
      RR-0031 blind-then-delta sequence; record the exact substitute identity and reason.
- [ ] Resolve every required change and every Critical/Important finding by changing the plan and
      rerunning all three exact reviews. Do not partially carry forward a verdict across changed
      bytes.
- [ ] Without changing the accepted plan bytes, write the exact-digest acceptance receipt and
      message-bus event. The verifier must reject a changed plan/review artifact, missing or
      non-`delta_review` calibration digest, failed replay verification, identity mismatch, or any
      non-ACCEPT review verdict.
- [ ] Commit only the accepted plan document. Review artifacts remain run-local evidence.

## Task 1 — Public C7 evidence hardening

**Files (exactly inherited from base-plan §7):**

- Modify: `apps/api_server/app.py`
- Modify: `apps/api_server/server.py`
- Modify: `tests/product/test_public_long_horizon_negative_paths.py`
- Modify: `tests/product/test_api_surface.py`

- [ ] Write RED tests for the exact base-plan §7 prerequisite: optional keyword-only `principal` on
      `correct_task`; Principal/Tenant Admin role; tenant/workspace; committed active/FAILED run;
      nonblank normalized reason before mutation; rejection of missing run/commitment,
      `SUCCEEDED`, and `CANCELLED`; exact correction event fields and current-run correlation ID;
      and HTTP refusal to synthesize a reason. Record exact expected failures before production
      edits.
- [ ] Implement only that minimum compatible public-local evidence behavior. Do not add an LLM
      decision, production auth/RBAC claim, hidden identity authority, expected-epoch/CAS command,
      atomic cross-store command, test-only bypass, private-database read path, or D1 evaluator.
      Durable external identity, correction-state/event atomicity, and stale correction-command CAS
      remain `PARK` under base-plan §7 rather than silently expanding Task 1.
- [ ] Run focused GREEN tests, the four exact Product suites required by base-plan §7, Ruff,
      format, Pyright, and mutation checks demonstrating that omitted epoch/authority/reason/event
      data fails. Existing public C7 bypass-denial regressions must remain green; the later
      safety-verdict priority belongs to the frozen evaluator/adjudicator tasks, not Task 1.
- [ ] Obtain independent security/diff review. Fix and re-review every Critical/Important finding.
- [ ] Commit `fix(product): expose complete correction authority events` on the isolated branch.

## Task 2 — D1-E environment precommit

**Files:** exact files from base-plan Task 2 except `fixed_baseline.py`, which the environment
owner must not create or inspect before D1-E freeze.

- [ ] Write RED tests for the six families, three regimes, three failures, four Latin orders, two
      replicates, arm-neutral events, evaluator arm-name blindness, candidate templates, restart
      parity, checkpoint negative control, integer gates, power table, and all automatic PARK rules.
- [ ] Implement generator/regimes/templates/evaluator/statistics and the D1-E manifest without a
      root seed, corpus, assignments, provider bank, fixed DAG, or future answer material.
- [ ] Independently review exact D1-E bytes, bind live Product/runner/SPINE/permission identities,
      freeze and runner-anchor D1-E, then emit a read-only builder exposure packet.
- [ ] Verify no forbidden post-D1 artifact exists. Any exposure before the accepted D1-E lock
      invalidates this version.

## Task 3 — Blind fixed DAG and skeptic reduction

- [ ] Give the independent fixed builder only the frozen D1-E packet and allowed public runtime
      semantics. Do not reveal seed, corpus, assignments, answers, provider bank, traces, or either
      nonce.
- [ ] Builder submits one sealed D1-F DAG, budget declaration, exposure declaration, D1-E digest,
      timestamp, and runner receipt. The environment owner may not edit it.
- [ ] A separate skeptic attempts to construct a same-budget single DAG covering R0/R1/R2 under
      current public node semantics and arm-neutral event availability.
- [ ] If the skeptic proves coverage, record `PARK_AS_SCHEDULE_ENGINEERING`, freeze the lesson, and
      terminate before combined D1/nonces/corpus/D2.
- [ ] If not proved, record `NOT_REDUCIBLE_UNDER_FROZEN_PUBLIC_SEMANTICS` with explicit attempted
      construction and failed assumptions; this is permission to review D1-F, not evidence the
      candidate will win.

## Task 4 — Combined D1 candidate and pre-acceptance nonce commitments

- [ ] Combine exact D1-E and sealed D1-F with candidate/restart/checkpoint contracts, evaluator,
      failures, statistics, budgets, public API allowlist, C7 taxonomy, and no-rescue rules.
- [ ] Run exact-content, architecture, fairness, leakage, and role-separation reviews on the
      combined-D1 candidate. Resolve every required change and re-review changed bytes before any
      nonce commitment.
- [ ] After the candidate is review-accepted but before D1 freeze/acceptance, the environment owner
      and independent reviewer each generate an unpublished 32-byte nonce in separate sessions and
      publish only
      `SHA256("LH1A-NONCE" || run_id || role || nonce_i)` as write-once runner rows.
- [ ] Verify both commitments predate combined-D1 acceptance and neither actor can read the other
      nonce or write the other's row. Any D1-candidate drift after either commitment terminates this
      version rather than triggering a replacement commitment.

## Task 5 — Combined D1 freeze, nonce reveals, and root seed

- [ ] Freeze and runner-anchor `LH-RECOVERY-1A-DESIGN-PRECOMMIT`, binding exact D1-E, D1-F, live
      Product/runner/SPINE/permission identities, both commitment rows, reviews, timestamps, and
      role separation. Any mismatch or D1-E/D1-F drift terminates the version.
- [ ] Only after combined-D1 acceptance reveal both nonces, verify both commitments, derive the root
      seed exactly as the base plan specifies, and bind canonical derivation evidence.
- [ ] Any early reveal, duplicate/conflicting row, invalid commitment, role overlap, or second
      derivation terminates this version.

## Task 6 — One-shot corpus and oracle

- [ ] Materialize exactly 432 cases/1,728 arm episodes once from the derived root seed using
      HMAC-SHA256 per full cell/replicate; produce crossed-quota and semantic-uniqueness receipts.
- [ ] Generate assignments/Latin schedule, phase-gated provider bank, failure schedule, and their
      canonical digests without exposing bank contents to harness/evaluator code.
- [ ] Run the isolated direct-apply oracle once. It must solve exactly `432/432`.
- [ ] If oracle is not `432/432`, write `INVALID_GENERATOR` and terminate without patch, case
      replacement, second oracle, D2, or formal run.

## Task 7 — Four public-surface arms and failure paths

**Files (inherited from base-plan Task 4):**

- Create: `product_evals/lh_recovery_1a/protocol.py`
- Create: `product_evals/lh_recovery_1a/cli.py`
- Create: `tests/product_eval/test_lh1a_protocol.py`

- [ ] RED-test isolated DB/workspaces, public API/AST allowlist, exact contracts, arm-information
      parity, R0 zero replan, R1/R2 exact signal x2 -> pause -> replan, fixed zero replan, exact
      secondary-wait delivery/timeout/terminalization, adaptive-restart parity, fresh checkpoint
      approval/SHA rejection, and all failure proofs.
- [ ] Implement only through the public entry points enumerated by base-plan Task 4 and the frozen
      public API allowlist. Harness/evaluator code may not read the provider bank or private stores.
- [ ] Run focused and mutation suites and commit scoped implementation; do not run a formal outcome.

## Task 8 — Real phases and mechanical adjudicator

- [ ] Implement and RED-test the exact base-plan Task 5 phase sequence
      `prepare -> wait >=7200s -> resume-change -> wait >=360s -> resume-recovery -> adjudicate ->
      finalize-result`, with a runner anchor at every named boundary and no injected clock, short
      mode, replay, or partial-phase mutation.
- [ ] Implement exact metrics/statistics and mechanical safety/integrity/capability priority.
      Known fixtures must prove p-values, integer gate 44, zero denominators, real-bypass priority,
      and the restart guardrail.
- [ ] Run focused tests, broader Product/eval suites, Ruff, format, Pyright, independent diff and
      architecture reviews. No final experiment outcome is run in this task.

## Task 9 — Conditional D2, freeze, and one formal child run

- [ ] Only after Tasks 0-8 PASS, including the one-shot oracle `432/432` and accepted protocol/phase/
      adjudicator code, construct the D2 preregistration binding every exact identity, target, role,
      digest, quota, regime/event contract, graph/budget, timeout/expiry, failure, metric/statistic,
      safety priority, and no-rescue rule.
- [ ] Run RR-0031 controlled-delta calibration, exact-content manifest verification, Claude/Kimi/
      OpenCode reviews with builder separation, and machine `prereg freeze`/`verify`.
- [ ] Execute the frozen real phases once with natural waits and runner anchors. No injected clock,
      short mode, retry, rescue, or identity reuse.
- [ ] Mechanically adjudicate first; independently adjudicate second. Preserve `MET`, `NOT_MET`,
      `INVALID`, `SAFETY_REGRESSION`, or `PARK_AS_SCHEDULE_ENGINEERING` exactly.
- [ ] Update only the minimum authority set. Parent `LH-RECOVERY-1` remains `OPEN/BLOCKED`.

## Completion evidence

The objective is complete only if either:

1. the skeptic reduction gate terminates honestly as `PARK_AS_SCHEDULE_ENGINEERING`, with all
   preceding plan/C7/D1-E/sealed-D1-F evidence and the skeptic construction proof valid; or
2. D1-F, combined D1, commit-reveal, one-shot `432/432` oracle, D2, one formal run, mechanical
   adjudication, independent adjudication, and authority updates all exist and verify, with the
   four-arm protocol and real-phase adjudicator implemented and frozen before D2.

A plan review, green Task 1, D1-E freeze, corpus generation, or oracle alone is progress—not
completion.
