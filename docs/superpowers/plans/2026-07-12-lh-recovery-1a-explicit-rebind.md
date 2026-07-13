# LH-RECOVERY-1A-EXPLICIT-REBIND Strong-Baseline Evaluation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:subagent-driven-development`
> or `superpowers:executing-plans` task by task. Tests precede implementation. No task may
> weaken a frozen gate after observing an outcome.

**Status:** `D1_ARTIFACT_CONSTRUCTION_ALLOWED`; D2 materialization, execution, and final freeze
are blocked until a fresh `SPINE-E2E-1` result is `PASS` and the D1 blind-design lock below is
independently accepted.

**Goal:** Test a narrow Product mechanism: after a two-hour requirement-change wait, can one
explicit Principal-authorized workflow rebind preserve a completed prefix, adapt the unfinished
suffix to one of three predeclared structural regimes, survive one frozen failure, and reach an
accepted outcome? It must beat a blind single-DAG static baseline on accepted recovery and be
operationally non-inferior to an adaptive restart that receives the same ChangeNotice and graph
template, while preserving exact same-task/run continuity without claiming that stale prefix
work remains useful after the requirement change.

**Maximum claim:** In the frozen six-family synthetic generator mixture, with local same-boot
timing evidence, frozen provider replay, one explicit Principal topology choice, and current
public Agent OS APIs, explicit suffix rebind improved matched recovery over a blind fixed DAG
and preserved more work than adaptive restart if and only if every frozen `MET` gate passes.

**Forbidden claims:** This is not automatic or hierarchical planning, continuous reasoning,
multi-day/week autonomy, live-model reliability, continual learning, self-evolution, AGI, or a
pass of parent `LH-RECOVERY-1`. The parent remains `OPEN/BLOCKED` under every child verdict.
The 7,560-second wall interval proves elapsed-time persistence/recovery only, not 7,560 seconds
of continuous cognition.

This child is a mechanism/component gate. Its continuity evidence and a win over the static
no-rebind ablation do not establish useful improvement over the strongest adaptive baseline and
therefore cannot satisfy the parent matrix gate by implication.

## 1. Track, evidence, and hard boundaries

- Track: `translational_research`; architecture-review claim class: `research-environment`;
  implementation under test remains Product Track runtime.
- Target repo: `autonomous-agent-core`; fixed workflow runner commit:
  `804c8d54bf5b78d9d850edb452db4affe3c1cd22` from branch
  `codex/agent-os-product-prereg-target-20260712` in
  `/Users/mima1234/Documents/AI-Agent-Projects/ai-agent-engineering-workflow/.worktrees/lh-prereg-target-fix-20260712`.
  This exact clean worktree/common-dir/source binding is frozen before D1; no ambient runner,
  including runner HEAD `bb3337f`, and no later descendant is allowed without a new reviewed plan.
- Final D2 preregistration must bind a fresh SPINE run ID, lock digest, result digest, target
  commit, and verdict `PASS`.
- Product execution uses only public `AgentOSApplication` methods. Harness source may not read
  private composition organs or Product SQLite directly.
- Timing inherits the accepted SPINE `local_same_boot_monotonic_self_attestation_v1` kernel,
  runner anchors, conservative monotonic bounds, host/boot binding, and trust limitations.
- Actual correction/policy bypass is a valid negative result, never washed into `INVALID` by a
  simultaneous noncritical instrumentation defect.
- Complete evidence that ties or loses is `NOT_MET`. No seed change, case removal, baseline
  weakening, metric substitution, environment change, rerun, or threshold movement may rescue
  the version.

## 2. Population and randomization

The statistical unit is one generated task instance. Freeze `N=432`:

```text
6 task families
x 3 structural regimes
x 3 failure modes
x 4 Latin execution orders
x 2 independent replicates
= 432 paired instances = 1,728 arm episodes
```

Families are `string_transform`, `numeric_reducer`, `validator`, `formatter`,
`record_filter`, and `small_state_machine`. Every full family x regime x failure x order cell
contains exactly two instances. Thus every family has 72 instances, every regime and failure
has 144, and every arm appears in each execution position 108 times.

Generation uses HMAC-SHA256 per full cell and replicate, never sequential `random` state:

```text
case_seed = HMAC-SHA256(root_seed, canonical_length_delimited_json({
  "family": family,
  "regime": regime,
  "failure": failure,
  "latin_order": latin_order,
  "replicate": replicate
}))
```

The held-out inference boundary is exactly the equal-weight frozen generator mixture. Unique
IDs/nonces do not count as semantic uniqueness: fixture, v1/v2 requirement, initial/final
content, test, prompt, expected result, and provider-response semantic digests must each satisfy
the frozen uniqueness rules.

## 3. Structural regimes and arm-neutral environment

All four arms for one instance receive the same immutable ChangeNotice and the same
instance-level event availability. The environment may vary by regime, never by arm or outcome.

| Regime | Required post-change event order | Candidate action |
|---|---|---|
| `R0_DIRECT_REFRESH` | `change -> read_v2 -> provider -> approval -> apply -> test` | zero replan; schedule/null control |
| `R1_DEPENDENCY_BEFORE_PROVIDER` | `change -> dependency WAIT_SATISFIED -> provider -> approval -> apply` | exactly one rebind inserting pre-provider wait |
| `R2_RELEASE_BEFORE_APPLY` | `change -> provider -> release WAIT_SATISFIED -> approval -> apply` | exactly one rebind inserting post-provider/pre-apply wait |

`ChangeNotice` may contain only `schema_version`, `case_id`, `change_id`, `goal_v2`, regime,
required gate position, signal name, and correlation key. It must not contain expected content,
expected/final digest, provider response, test answer, arm identity, or outcome-derived field.

The instance event journal exposes only the event(s) belonging to that regime. Every arm can
observe the same journal. A fixed DAG may consume any event its precommitted graph requests,
but the harness may not emit a missing-regime event just to rescue it. Before D1, an independent
skeptic must attempt to construct a same-budget single DAG from current public node semantics.
If it can cover all three regimes without dynamic graph interpretation, the experiment is
`PARK_AS_SCHEDULE_ENGINEERING` before the two-hour run.

The evaluator inspects final outcome, public event/evidence order, failures, budgets, and safety.
It is forbidden to inspect arm name or treat `RUN_PLAN_REBOUND` itself as success.

## 4. Four matched arms and fairness

### Candidate C — explicit suffix rebind

Common v1 prefix:

```text
read_v1 -> provider_v1 -> wait_change
```

The initial candidate workflow is fully frozen as:

```text
read_v1 -> provider_v1 -> wait_change
-> read_v2 -> provider_v2 -> approval -> apply -> test -> evaluate
```

R0 resumes that already-committed direct suffix. R1/R2 replace only the unfinished suffix;
completed prefix nodes and incoming edges remain identical.

The v1 proposal is not approved before the long wait. After receiving the change signal, the
harness repeats the identical signal ID/payload once to prove idempotency. For R0 it continues
without replan. For R1/R2 it calls:

```text
signal_task x2 -> pause_task -> replan_task
```

The new workflow comes only from the precommitted regime template library. No model/provider
creates a graph. R1/R2 must have exactly one rebind, version increment of one, `max_replans=1`,
and immutable completed-prefix nodes/edges.

### Blind fixed F — static strong schedule baseline

An independent fixed-baseline builder freezes one single DAG before root seed, assignments,
fixtures, answers, provider bank, or traces exist. The builder may see the three regime schemas,
their equal weights, ChangeNotice schema, current public runtime semantics, and the candidate's
maximum node/retry/context/token/tool ceilings. It may choose any generic or superset DAG within
those ceilings. It receives the same ChangeNotice and environment events at run time, but the
graph cannot change and `max_replans=0`.

If a universal fixed DAG ties, the result is honestly `NOT_MET`; fixed actual compute is not
artificially reduced after early failure.

### Adaptive restart R — strongest adaptation control

Restart receives the same ChangeNotice, regime template, topology information, budgets, and
Principal authorization as candidate. It creates a fresh public task/run after change and may
not reuse candidate-private state. Episode-1 evidence is retained as evidence but not silently
inserted into the new task. Candidate rebind and restart task creation each receive the same
fixed `TOPOLOGY_SELECTION=2.0` human-minute charge; recreation is automated and has no extra
human penalty. This prevents a by-definition human-cost win.

Candidate must be operationally success-non-inferior to restart and preserve the exact
same-task/run completed-prefix contract. `read_v1`, the stale v1 provider proposal, wait event,
old task identity, and old evidence are never classified as useful post-change work. A win over
fixed alone cannot produce `MET`, and this child makes no economic/useful-work superiority claim
over restart.

### Checkpoint K — stale-proposal negative control

Checkpoint replays the v1 proposal after the requirement change. It obtains a fresh approval
after change and immediately attempts the action, so rejection must be the real expected-SHA
binding rather than ten-minute approval expiry. Checkpoint is diagnostic/negative-control only
and cannot become the post-hoc primary comparator.

### Information and budget parity

- C, F, K, and R receive the same instance fixture, ChangeNotice, event journal, provider
  responses, retry limits, context ceiling, tool/token/cost ceilings, evaluator, and failure.
- C and R receive the same precommitted Principal graph-selection information and equal human
  charge. F knows the regime distribution and allowed capabilities before its blind freeze.
- Provider responses are served only by the frozen server. Harness/evaluator code cannot read
  stored response content or future entries.
- Arm order follows the frozen Latin schedule; every arm uses isolated file-backed SQLite and
  workspace state.

## 5. Two-stage commit-reveal freeze

### D1-E — environment precommit before fixed-builder exposure

Before the fixed builder sees any design packet, the environment owner creates a separately
reviewed and runner-anchored sealed precommit binding:

- generator source/version;
- regime schemas/proportions and event emitter;
- evaluator and exact event-order acceptance rules;
- candidate initial workflow and R0/R1/R2 template library;
- budgets, metrics, statistics, failure injector, and no-rescue rules.

The fixed builder receives only this immutable D1-E packet. Any D1-E byte/digest drift after
handoff terminates the version; the environment cannot adjust a regime after seeing the fixed
submission.

### D1-F and combined D1 — blind baseline then design lock

The fixed builder submits a separately sealed D1-F artifact with its single DAG, allowed/forbidden
exposure declaration, and D1-E digest. Then create and independently freeze
`LH-RECOVERY-1A-DESIGN-PRECOMMIT` binding:

- D1-E and D1-F locks, submission timestamps, runner receipts, and role separation;
- generator source/version and semantic-uniqueness checks;
- three immutable regime schemas/proportions and event emitter;
- candidate template library;
- blind fixed DAG/builder artifact and exposure declaration;
- adaptive-restart mapping and checkpoint contract;
- evaluator, failure injector, metrics, verdict code, power code/output;
- public API allowlist, budget/timeout constants, C7 taxonomy, and no-rescue rules.

Environment owner and independent reviewer each create an unpublished 32-byte nonce and first
publish a commitment:

```text
commit_i = SHA256("LH1A-NONCE" || run_id || role || nonce_i)
```

Only after D1 acceptance do both reveal. The coordinator verifies both commitments and derives:

```text
root_seed = SHA256(
  "LH-RECOVERY-1A-v1"
  || D1_lock_digest
  || SPINE_lock_digest
  || SPINE_result_digest
  || environment_nonce
  || reviewer_nonce
)
```

Nonce commitment/reveal rows are write-once and runner-anchored. Neither party alone can choose
the corpus after seeing the other's nonce.

### D2 — execution lock after one materialization

Materialize exactly once: 432-case corpus, assignments/Latin schedule, phase-gated provider
bank, and oracle report. The oracle applies expected v2 content directly in an isolated
reference fixture and must solve `432/432`; it receives no arm/failure/timing state. Any oracle
failure terminates this version as `INVALID_GENERATOR`; cases may not be replaced and code may
not be patched. A new attempt requires a new experiment version, both new nonces, and full review.

D2 binds D1 lock, nonce commitments/reveals, root-seed derivation, every generated digest,
oracle result, target/runner/SPINE bindings, phase protocol, and all Product/harness files.
Any D1 source drift between locks is rejected.

## 6. Product contract, time, expiry, approvals, and failures

Frozen constants:

```text
PREPARE_TO_CHANGE_MIN_SECONDS = 7200
CHANGE_TO_RECOVERY_MIN_SECONDS = 360
PREPARE_TO_ADJUDICATE_MIN_SECONDS = 7560
WAIT_CHANGE_TIMEOUT_SECONDS = 21600
SECONDARY_WAIT_TIMEOUT_SECONDS = 300
COMMITMENT_TTL_SECONDS = 28800
APPROVAL_TTL_SECONDS = 600          # live Product contract
MAX_APPROVAL_TO_APPLY_SECONDS = 120
STALE_LEASE_SECONDS = 300           # live SQLite lease
```

Goal/Commitment/Workflow/ExpectedOutcome/inputs are exact frozen Product contracts. Every wait
deadline and Commitment expiry remains beyond the real phase window. Long-wait approvals are
forbidden. Every consequential attempt records a fresh approval no more than 120 seconds before
apply; checkpoint does so after change. Correction arms may use an approval to prove halted
denial, but after the 360-second gate must record another fresh approval before recovery.

Failure modes, balanced 144 each:

1. `PRE_CONSEQUENCE_PROCESS_EXIT`: exit a fresh process at the matched post-change,
   pre-provider/pre-apply checkpoint; no live lease may remain.
2. `POST_APPLY_WORKER_INTERRUPTED`: inject public `stop_after_node="apply"`, require durable
   logical receipt, exit the process, then after 360 seconds naturally reacquire with
   `recover_stale_lease=False` and no duplicate effect.
3. `CORRECTION_HALT_BEFORE_APPLY`: write authorized task correction, attempt the approved action
   while halted, require correction denial and zero effect, then after 360 seconds authorize
   resume and create a fresh approval.

An arm that naturally fails before reaching its injection point is a valid `Z=0`. A harness that
claims injection but cannot prove the frozen injection event is `INVALID_INSTRUMENTATION`.
At recovery/adjudication every arm must be terminal, or carry a typed expired-wait/failure event
created by the public runtime after the 300-second secondary deadline. A remaining
`WAITING_EVENT` arm is `INVALID_PROTOCOL`, never silently converted to `Z=0`.

Exact public-call sequence after the change signal:

```text
R0 candidate:
  signal change with fixed signal_id -> repeat identical signal -> run committed direct suffix
  -> reach the assigned failure checkpoint

R1 candidate:
  change signal x2 -> pause -> replan -> run_task until dependency WAITING_EVENT
  -> deliver matching dependency signal once -> persist satisfied-wait projection
  -> reach the assigned pre-consequence/provider checkpoint

R2 candidate:
  change signal x2 -> pause -> replan -> run read_v2/provider_v2 until release WAITING_EVENT
  -> deliver matching release signal once -> persist satisfied-wait projection
  -> reach the assigned pre-approval/apply checkpoint
```

F and R follow their own frozen graph with the same instance event journal. A mismatch that waits
for an unavailable event reaches the 300-second public timeout before the 360-second recovery
phase and must materialize a typed timeout/failure on the next public call.

## 7. C7 public-evidence prerequisite

Before D1, minimally harden public local correction evidence; this is not production auth/RBAC.

**Files:** `apps/api_server/app.py`, `apps/api_server/server.py`,
`tests/product/test_public_long_horizon_negative_paths.py`, and
`tests/product/test_api_surface.py`.

Harden `correct_task` by adding optional keyword-only
`principal: PrincipalIdentity | None = None`; retain the already-present optional principal on
`resume_correction`. Both validate Principal/Tenant Admin role,
tenant/workspace, committed active/FAILED run, and nonblank normalized reason before epoch
mutation; reject no commitment/run, `SUCCEEDED`, and `CANCELLED`. HTTP must not synthesize a
reason. Successful `CORRECTION_WRITTEN` contains exact `scope`, incremented `epoch`, `halted`,
`reason`, `written_by`, and current run correlation ID.

Correction-state and task-event persistence remain separate local transactions. Epoch/event gap
is `INVALID_INSTRUMENTATION`; production atomic correction command and durable external identity
remain `PARK` in a separate hardening packet.

Required C7 suites:

```bash
uv run --extra product-test pytest \
  tests/product/test_public_long_horizon_negative_paths.py \
  tests/product/test_e2_long_horizon_recovery.py \
  tests/product/test_long_horizon_compensation.py \
  tests/product/test_api_surface.py -q
uv run --extra product-test ruff check apps/api_server tests/product
uv run --extra product-test ruff format --check apps/api_server tests/product
uv run --extra product-test pyright
```

## 8. Metrics and prospective power

Per instance/arm:

```text
Accepted = 1 iff Product VERIFIED, final digest/test/evidence/budget match,
             duplicate logical effects = 0, and severe safety breach = 0.

Recovered = 1 iff the assigned failure was reached and proven, a fresh-process frozen
              recovery path ran, and Accepted = 1.

Z = Accepted * Recovered

WorkUnits = provider requests + tool invocations
NoncontributingUnits = work not consumed by final accepted evidence or invalidated by
                       rebind/restart
DuplicateWorkRatio = sum(NoncontributingUnits) / max(1, sum(WorkUnits))
HumanMinutesPerZ = total frozen human-minute charges / max(1, sum(Z))
CostPerZ = total frozen cost / max(1, sum(Z))
```

Frozen charge and aggregation table:

```text
APPROVAL = 0.5 human minutes
TOPOLOGY_SELECTION = 2.0 human minutes  # includes pause for C; same charge for R
CORRECTION_RESUME = 1.0 human minutes
TASK_RECREATE = 0 additional human minutes

IncrementalHumanPerNetRecovered_C_vs_F =
  max(0, HumanMinutes_C - HumanMinutes_F) / (sum(Z_C) - sum(Z_F))
  denominator <= 0 => infinity

ProviderTokensPerZ = total frozen provider usage tokens / max(1, sum(Z))
ToolCallsPerZ = total public tool invocations / max(1, sum(Z))
CostPerZ = sum(provider tokens * frozen token rate + tool calls * frozen tool rate)
           / max(1, sum(Z))
```

The event classifier is frozen before D1: contributing units are the fresh v2 read/provider
evidence referenced by the accepted action, the accepted apply receipt, final test artifact,
required regime wait evidence, and evaluator outcome. Noncontributing units are stale v1
proposal/provider output, rejected checkpoint action, invalidated duplicate fresh outputs, or
work absent from the final required-evidence manifest. Task/run identity and event counts are
never WorkUnits. If a unit cannot be classified mechanically from public events and final
evidence refs, the metric is `INVALID`.

Primary estimand is `Delta_CF = E_G[Z_C - Z_F]` over the frozen generator mixture. Let
`n10=count(Z_C=1,Z_F=0)`, `n01=count(Z_C=0,Z_F=1)`, and
`delta_hat=(n10-n01)/432`. The only confirmatory p-value is one-sided exact McNemar/sign test:

```text
p = P(Binomial(n10+n01, 0.5) >= n10); p=1 when n10+n01=0
```

Alpha is .05 and observed effect gate/SESOI is `delta_hat >= .10` (integer gate
`n10-n01 >= 44`). Prospective design alternative is true delta `.15`, not `.10`. With N=432
and simultaneous `p<.05` plus observed delta `.10`, exact unconditional power is frozen as:

```text
discordance=.60 -> .911
discordance=.75 -> .885
discordance=.90 -> .863
discordance=1.0 -> .856
```

At true delta `.10`, power is only about `.50` because the observed floor equals the mean;
no document may claim 80% power at the effect floor. The table above is a pooled homogeneous-
discordance sensitivity analysis, not yet the exact power claim for the fixed stratified sample.
D1 must freeze `H0: P(C-only | discordant, full family x regime x failure cell) <= .5`, the
conditional case-independence/exchangeability assumptions, and a cell-wise alternative (R0 may
be a null control while R1/R2 carry the effect). Frozen stratified exact/dynamic-program power
code must show at least .80 prospective power before D1 acceptance. Family/regime/failure
analyses are predeclared secondary with Holm correction and cannot change the primary verdict.

## 9. Exact MET gates

All must pass:

```text
sum(Z_C)/432 >= .90
AcceptedRate_C >= .90
RecoveredRate_C >= .90
Z_C within every regime >= .85
Z_C within every failure >= .85

delta_C_vs_F >= .10
exact_one_sided_p_C_vs_F < .05
delta_C_vs_F_on_R1_R2 >= .10

sum(Z_C) >= sum(Z_R) - 8             # operational -2% restart guardrail
DuplicateWorkRatio_C <= DuplicateWorkRatio_R
HumanMinutesPerZ_C <= HumanMinutesPerZ_R
ProviderTokensPerZ_C <= 1.10 * ProviderTokensPerZ_R
ToolCallsPerZ_C <= 1.10 * ToolCallsPerZ_R
candidate preserved-prefix contract == 100%

IncrementalHumanPerNetRecovered_C_vs_F <= 20 minutes
duplicate logical side effects across all arms == 0
proven severe safety breaches across all arms == 0
```

The restart guardrail is an operational point-estimate gate, not a formal noninferiority claim.
Metrics aggregate by totals exactly as defined; arm/family/failure repetitions never inflate N.
Fixed early failure does not create a lower actual-token veto: budget ceilings are matched, while
actual efficiency comparisons use adaptive restart `per Z`.

F is explicitly the static no-rebind feature ablation. R is the strongest adaptive comparator.
Child `MET` requires R success non-inferiority and exact continuity, but does not claim that
continuity is economically superior to restart.

## 10. Safety, integrity, and verdict priority

Result schema separates:

```text
safety_status: PASS | SAFETY_REGRESSION | UNVERIFIABLE
integrity_status: VALID | INVALID
capability_verdict: MET | NOT_MET | INVALID
```

Priority:

1. If intact independent receipt, mutation, policy, epoch, or unauthorized-resume evidence
   proves a real bypass: `capability_verdict=NOT_MET`,
   `safety_status=SAFETY_REGRESSION`. A simultaneous noncritical integrity defect is recorded
   as `integrity_status=INVALID` but cannot erase the safety negative.
2. If bypass is not proven but the safety interval is unverifiable, or corpus/provider/
   evaluator/timing/private-access/commit-reveal/budget evidence is incomplete:
   `capability_verdict=INVALID`.
3. With valid evidence, any failed MET gate: `NOT_MET`.
4. Only all gates passing: `MET`, scoped solely to this child claim.

## 11. Files and implementation tasks

### Task 1 — Public C7 evidence hardening

- [ ] Write the RED authority/scope/state/reason/epoch/event/HTTP tests described in section 7.
- [ ] Implement only the compatible public event hardening; do not add production identity claims.
- [ ] Run the four Product suites, Ruff, format, Pyright, independent security diff review, and
      commit `fix(product): expose complete correction authority events`.

### Task 2 — D1-E environment precommit, blind baseline, and combined D1

**Create:**

- `product_evals/lh_recovery_1a/generator.py`
- `product_evals/lh_recovery_1a/regimes.py`
- `product_evals/lh_recovery_1a/templates.py`
- `product_evals/lh_recovery_1a/fixed_baseline.py`
- `product_evals/lh_recovery_1a/evaluator.py`
- `product_evals/lh_recovery_1a/statistics.py`
- `tests/product_eval/test_lh1a_design.py`
- `docs/research/LH-RECOVERY-1A-DESIGN-PRECOMMIT.yaml`

- [ ] RED-test exact regimes, no arm-name evaluator dependency, fixed-builder exposure limits,
      signal/pause/replan order, metrics, integer gates, and the frozen power table.
- [ ] Freeze and runner-anchor D1-E before the fixed builder receives it. Have an independent
      baseline builder submit sealed D1-F and an independent skeptic attempt the schedule-
      reduction proof before seeing seed/corpus/bank.
- [ ] If reducible, record `PARK_AS_SCHEDULE_ENGINEERING`; otherwise complete exact-content and
      architecture review, then freeze D1. No corpus file may exist before D1 lock.

### Task 3 — Commit-reveal, one-shot corpus, provider bank, and oracle

**Create after D1:**

- `product_evals/lh_recovery_1a/frozen_tasks.json`
- `product_evals/lh_recovery_1a/failure_schedule.json`
- `product_evals/lh_recovery_1a/provider_responses.json`
- `.agent_runs/lh-recovery-1a-20260712/evaluation/generation_receipt.json`
- `.agent_runs/lh-recovery-1a-20260712/evaluation/oracle_report.json`
- `tests/product_eval/test_lh1a_population.py`

- [ ] Record both nonce commitments, freeze/anchor D1, then reveal and verify.
- [ ] Materialize once; test the full crossed quotas, semantic uniqueness, HMAC sub-seeds,
      provider phase gating, server-only bank access, and exact reproducibility.
- [ ] Run oracle once. Any result other than `432/432` terminates this version.

### Task 4 — Four public-surface arms and failures

**Create:** `product_evals/lh_recovery_1a/protocol.py`,
`product_evals/lh_recovery_1a/cli.py`, and `tests/product_eval/test_lh1a_protocol.py`.

- [ ] RED-test isolated DB/workspaces, public API/AST allowlist, exact contracts, arm information
      parity, R0 zero replan, R1/R2 exact signal x2 -> pause -> replan, fixed zero replan,
      exact secondary wait delivery/timeout/terminalization, adaptive restart parity, fresh
      checkpoint approval/SHA rejection, and all failure proofs.
- [ ] Implement using only `create_task`, `commit_task`, `run_task`, `signal_task`,
      `pause_task`, `replan_task`, `record_approval`, `correct_task`, `resume_correction`,
      `task_json`, `evidence_json`, and `recovery_json`.
- [ ] Run focused suites and commit in scoped increments; no final outcome is run yet.

### Task 5 — Real phases and mechanical adjudicator

Frozen phase sequence:

```text
prepare -> runner anchor
wait >=7200s
resume-change -> runner anchor
wait >=360s
resume-recovery -> runner anchor
adjudicate -> runner anchor
finalize-result
```

- [ ] Inherit the accepted SPINE phase/context/boot/runner-anchor implementation; expose no
      clock, threshold, short-timing, or test-mode override.
- [ ] RED-test early/late/replay/context/boot/anchor/partial-phase zero-mutation behavior and
      all safety/integrity/capability priorities.
- [ ] Implement exact metrics/statistics; known fixtures must prove p-values, integer gate 44,
      zero denominators, safety priority, and restart guardrail.

### Task 6 — D2 preregistration, freeze, real run, and truth update

- [ ] Write `docs/research/LH-RECOVERY-1A-preregistration-spec.yaml` only after SPINE PASS,
      D1 lock, valid nonce reveals, corpus materialization, and oracle `432/432`.
- [ ] Bind every identity, role separation, target/runner/SPINE/D1/D2 digest, population quota,
      regime/event contract, arm graph/budget, timeout/expiry, failure proof, metric denominator,
      statistic/power assumption, safety taxonomy, no-rescue rule, and result schema.
- [ ] Run RR-0031 controlled delta review, exact-content manifest verification, independent
      content review, architecture review, and `prereg freeze`. Any mismatch stops.
- [ ] Run the real phases and persistent monitoring; no mocked wait or injected clock.
- [ ] Run `prereg verify --result` and independent result adjudication. Preserve `MET`,
      `NOT_MET`, `INVALID`, or `SAFETY_REGRESSION` exactly.
- [ ] Update only `docs/research/LH-RECOVERY-1A-result.md`, `docs/CURRENT_STATE.yaml`, and
      `codebase_index.md`; parent `LH-RECOVERY-1` remains `OPEN/BLOCKED`.

## 12. Automatic PARK conditions before D1/D2

`PARK` without running if any is true:

- parent/child IDs and status cannot be mechanically separated;
- D1-E environment cannot freeze before fixed-builder exposure, or changes after D1-F handoff;
- fixed builder cannot freeze blind D1-F before seed/corpus/provider bank;
- environment differs by arm;
- C/F/R cannot receive the same ChangeNotice, event availability, context, retries, or ceilings;
- restart cannot receive the same topology information/human charge as candidate;
- evaluator depends on arm name or rebind event rather than outcome/order/evidence;
- skeptic proves a current-runtime same-budget single DAG covers all regimes;
- candidate wins only through a hidden/missing signal, answer, digest, or provider response;
- SPINE PASS, C7 public evidence, exact `signal x2 -> pause -> replan`, expiry/fresh approval,
  or natural lease recovery is not first verified;
- commit-reveal, independent sub-seeds, semantic uniqueness, or one-shot generation cannot be
  mechanically enforced;
- a remaining WAITING arm cannot be terminalized by the frozen public timeout path;
- N=432/1,728 episodes is unaffordable and no new power/sample-size version is preregistered.
