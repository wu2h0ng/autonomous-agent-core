# AGENT-OS-SELFDEV-4 — Format-Symmetric Benchmark Round Prereg (DRAFT)

> Status: `DRAFT` — §1-§3, §5-§10 complete; §4 (frozen subset) is filled only
> after gold env validation dry-runs complete. No result-bearing run until
> independent review accepts and the freeze commit records the exact-content
> manifest.
> Date: 2026-07-26. Builder: kimi-cli session.
> Governing documents: ADR-0056, ADR-0058 (Accepted, diff channel implemented
> at 090f8f2), SELFDEV-2/SELFDEV-3 prergs and adjudications.

## 1. Purpose and claim boundary

Question: on a FRESH frozen 12-task SWE-bench Verified subset, with BOTH arms
on the same unified-diff output contract (chain via ADR-0058, baseline as
before), at pass@2 with equal budgets and ABAB interleaved scheduling, does
the Agent OS governed chain still beat the bare same-model one-shot scaffold?

This is the first HARNESS-VS-HARNESS measurement of the series: the E1-E3
output-contract asymmetry (complete-file vs diff, declared conservative) is
eliminated by ADR-0058 — what remains is the value of governance (seal,
exact-digest approval, evaluate, compensate) versus just asking the model.

NON-CLAIMS (carried verbatim): no comparability to published agentic-scaffold
rates (oracle localization + F2P/P2P id disclosure); no leaderboard claim
(12-task subset); no HCW-reduction claim (class B ledger only);
contamination — Verified is likely inside K2's training distribution
(upper bound); not release; not `Autonomy(S,E,O,V,T)` evidence.
The 19,000-byte INPUT-content truncation remains in force (ADR-0058
Consequences); the subset keeps the ≤19,000-byte gold-file bound.

## 2. Prior negative/result map (feeds design; not re-litigated)

- SELFDEV-3 (E2, window-unconfounded): SUPPORTS 11/12 vs 4/12; chain 19/20
  completed attempts solved; residual = sympy content-specific 600s timeouts
  (complete-file generation); baseline binding constraint = unified-diff
  reliability (13/24 DIFF_INVALID).
- ADR-0058 rationale (now implemented): the chain's complete-file contract
  was the residual bottleneck; the chain's correctness (~95%) was not.
- Failure classes to watch this round: chain-side DIFF_INVALID rate (the
  chain now pays the same diff contract the baseline pays) and
  content-specific latency in diff mode (expected to shrink sharply vs
  complete-file, since output volume drops to change size).

## 3. Arms, inputs, budgets

- Inputs (identical both arms, carried): issue text + base-commit bytes of
  the gold file + FAIL_TO_PASS node ids + PASS_TO_PASS node ids. Neither arm
  sees test_patch contents or the gold patch.
- Chain arm: frozen argv `agent-os benchmark-run-provider
  .agent_runs/selfdev-4/selection.json <instance_id> --approve
  --duration-seconds 3600` — the governed workflow with
  `patch_format: "unified_diff"` in run inputs (ADR-0058). Output:
  single-file unified diff, validated three-way (diff-header path ==
  proposal path == reviewed target) and applied via git apply fail-closed.
  2 attempts per task.
- Cheap baseline: frozen argv `agent-os benchmark-run-baseline
  .agent_runs/selfdev-4/selection.json <instance_id>` — same provider
  profile/timeout/sampling, same inputs, one-shot unified-diff output,
  `git apply` fail-closed. 2 calls per task. Equal budgets by construction.
  Output contracts are now IDENTICAL across arms; any residual difference is
  harness semantics only.
- Attempt accounting (carried verbatim from SELFDEV-3, incl. watchdogs
  baseline 1800s / chain 2400s, invoked markers, terminal classes, consumed
  preview rule, frozen argv = run integrity).
- Solve determination: ONLY the independent round-level verifier re-run
  (§6). Chain-internal outcomes are telemetry.
- Execution: strictly sequential; ABAB per-attempt interleaving
  (baseline a1 → chain a1 → baseline a2 → chain a2 per task); workspace
  restored to pinned base before EVERY attempt; no early stopping.

## 4. Frozen subset (FILLED AT FREEZE — placeholder)

- Source: the 162-entry candidate pool (`.agent_runs/selfdev-2/dataset/`),
  MINUS the 17 tasks consumed by SELFDEV-2/3, MINUS parametrized/unresolvable
  f2p ids; 130 candidates across 8 repos remain.
- Selection rule (declared): seeded RNG (seed recorded in manifest);
  stratified cap 2 per repo EXCEPT django/sympy/sphinx cap 3 (their
  candidate stocks are 84/20/15; without the exception the 8-repo cap
  structurally tops at 16 < 17); N=12 main + 5 reserve; drawn ONLY from the
  gold-validation-passing pool (§8).
- Per-task manifest fields: as SELFDEV-2 §4 (commits, issue hash, gold file
  path/bytes/lines ≤19000, resolved f2p/p2p node ids, image tag,
  interpreter, verifier timeout, min output tokens, gold-validation
  evidence digest, p2p_vacuous flag).
- Reserve swaps: only before the round's first provider call; each swap a
  declared, recorded, re-hashed manifest event; post-first-call swaps
  forbidden (task-level INVALID then counts toward kill criterion 1).

## 5. Environment freeze

- Provider: `openai-compatible`, model `kimi-k2-0711-preview`,
  `model_revision_digest: null` (LIMITATION carried),
  `AGENT_OS_PROVIDER_TIMEOUT_SECONDS=600`, commitment
  `duration_seconds=3600`. Sampling = provider defaults (LIMITATION).
- Execution boundary: unchanged from ADR-0056 D5 (containers, no network,
  read-only rootfs, rw task mount only, resource caps, env allowlist,
  per-task verifier timeout, env scrubbing). Repo head: the freeze commit.
- Docker daemon required; pre-round re-verification (workspaces clean at
  pinned heads, images present) is mandatory (failure ⇒ no start).

## 6. Verifier flow (carried)

checkout base → apply candidate (chain diff | baseline diff) → apply hidden
test patch → F2P ids → curated P2P ids → solve iff both green → restore
(always). Solve ONLY via the independent round-level verifier; vacuous-p2p
tasks f2p-only (flagged per task).

## 7. Verdict and kill criteria

- SUPPORTS the narrow claim iff chain pass@2 solve count > baseline pass@2
  solve count on the frozen subset, no task-level integrity failure. Strict
  inequality; ties do not support. SUPPORTS reads exactly as: "observed
  difference on this fresh frozen 12-task subset under format-symmetric
  contracts" — nothing more.
- NEGATIVE iff a kill criterion fired or chain < baseline; MIXED otherwise.
- Kill criteria (carried from SELFDEV-3 incl. the L-2 abort semantics):
  1. env/infra failure on >25% of frozen tasks (task-environment failures,
     NOT provider-infra attempt classes) ⇒ INVALID;
  2. any manifest/fixture/argv drift other than a declared §4 swap ⇒ INVALID;
  3. cheap-baseline data loss ⇒ INVALID;
  4. any parallel provider call or early stop ⇒ INVALID (driver
     infra-collapse abort = kill-4 event, recorded as INVALID);
  5. two or more tasks with restore/compensation failure ⇒ INVALID;
  6. pre-round re-verification fails and is waived ⇒ INVALID (no waiver).

## 8. Pre-freeze gold validation (gate for the selection pool)

Per candidate task, in its container (existing per-repo images from the
SELFDEV-2 dry-runs, rebuilt only if missing): base+test_patch must leave
F2P RED; base+gold+test_patch must leave F2P and P2P GREEN (ADR-0056
Decision 5). Only passing tasks enter the selection pool. Evidence digests
recorded per task.

## 9. Freeze mechanics

1. Independent reviewer (reviewed_by != builder_id, RR-0031 blind anchoring)
   reviews this prereg INCLUDING the filled §4; literal verdict; changes
   re-open review.
2. Freeze commit: this prereg, subset manifest, per-task env manifests,
   gold-validation evidence, acquisition reports, exact-content sha256
   manifest over all mechanism files. Workspaces materialized at
   `.agent_runs/selfdev-4/workspaces/` (gitignored) with the SELFDEV-3
   freeze precondition (full verification HEAD==pinned AND clean, recorded
   in the freeze commit message). Drift ⇒ round INVALID.
3. Round order: ABAB per §3; run to completion.
4. Adjudication: receipts per task, verdict per §7, E3-vs-E4 descriptive
   analysis (no gate), negative map, paradigm learning, state sync —
   independent-adjudication discipline as before.

## 10. C6/C7/SD4 and security boundary

- The chain's approval/exact-digest/compensation semantics are unchanged by
  ADR-0058; untrusted code stays containerized with no network/credentials;
  no untyped model output becomes a consequential command (diffs validated
  three-way + git apply --check before any byte changes).
- Operator ledger (class B): minutes/interventions per task recorded per the
  carried accounting rules; no founder baseline work; no HCW claim.
