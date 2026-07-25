# AGENT-OS-SELFDEV-3 — Envelope-Upgrade Round Prereg (DRAFT)

> Status: `DRAFT` — no result-bearing run until independent review accepts and
> the freeze commit records the exact-content manifest.
> Date: 2026-07-25. Builder: kimi-cli session.
> Governing documents: SELFDEV-2 prereg (frozen at 9843d5f),
> SELFDEV-2 round adjudication (`.agent_runs/selfdev-2/round/round-adjudication.md`,
> independent ADJUDICATION_AMENDED → SUPPORTS with caveats).

## 1. Purpose and claim boundary

Question: on the SAME frozen 12-task SWE-bench Verified subset, under an
upgraded envelope E2 (provider timeout 180s → 600s for BOTH arms; ABAB
interleaved arm scheduling replacing baseline-first), does the Agent OS chain
still beat the bare same-model one-shot scaffold at pass@2?

This is a single-variable-envelope measurement against a fixed subset. It
exists because SELFDEV-2's adjudication identified (a) the 180s timeout as
the envelope's binding constraint and (b) the baseline-first schedule as the
source of the arm-window confound. E2 removes both defects structurally.

NON-CLAIMS (carried verbatim): no comparability to published agentic-scaffold
rates (oracle localization + F2P/P2P id disclosure); no leaderboard claim
(12-task subset); no HCW-reduction claim (class B ledger only);
contamination — Verified is likely inside K2's training distribution
(upper bound); not release; not `Autonomy(S,E,O,V,T)` evidence.
Additional non-claim specific to this round: the diff-format patch channel
is NOT under test here (it is an ADR-level execution-contract change tracked
separately); the chain still emits complete-file replacements.

Secondary declared analysis (descriptive only, NO gate): per-arm solve-rate
comparison E1 (SELFDEV-2, 180s/baseline-first) vs E2, measuring how much of
each arm's E1 result was envelope artifact. This analysis changes no verdict.

## 2. Prior negative/result map (feeds design; not re-litigated)

- SELFDEV-2 (same subset): SUPPORTS with caveats — chain 9/12 vs baseline
  2/12; caveat 1 arm-window asymmetry (margin unreliable); caveat 2 two
  f2p-only solves. Mechanism evidence: baseline 18 UNAVAILABLE + 2 timeouts
  + 2 diff-invalid; chain 7 timeouts (4/4 on the two ≥13.5KB tasks) + 1
  malformed envelope; chain solved 15/16 completed attempts in a healthy
  window.
- MT round: full-file replacement degrades on large files; neighbor breakage;
  parallel-load timeouts (sequential mandated since).
- Read of the map: chain correctness is NOT the bottleneck; the envelope's
  time contract and the scheduling confound are. E2 targets exactly those.

## 3. Frozen envelope deltas vs SELFDEV-2 (everything else IDENTICAL)

| Parameter | E1 (SELFDEV-2, frozen) | E2 (this round, frozen) |
|---|---|---|
| Provider timeout (both arms) | 180s | **600s** |
| Arm scheduling | baseline arm fully first, then chain | **ABAB interleaved per attempt** |
| Everything else | — | unchanged |

- Justification for 600s: observed chain generation ~130–200s on ~10KB
  complete-file outputs in a healthy window; the 19KB envelope ceiling at
  K2 reasoning latency is ~400s; 600s gives ~50% margin without being
  unbounded. Applies identically to both arms via
  `AGENT_OS_PROVIDER_TIMEOUT_SECONDS=600` at round time.
- ABAB schedule (attempt granularity): for each main task in the frozen §4
  order: baseline attempt-1 → chain attempt-1 → baseline attempt-2 → chain
  attempt-2; then the next task. Both arms of one task complete inside the
  same wall-clock window, eliminating the E1 arm-window confound by
  construction. Execution remains strictly sequential (no parallel provider
  calls, no parallel containers).
- Unchanged (carried from the SELFDEV-2 prereg verbatim): subset; inputs
  (issue + base-commit file bytes + F2P + P2P ids); pass@2 budgets per arm;
  solve determination ONLY by the independent round-level verifier;
  workspace restore between attempts; sequential execution; no early
  stopping; claim boundaries.
- Attempt accounting (carried from the SELFDEV-2 prereg verbatim): an attempt
  is consumed the moment the provider node is invoked; terminal classes
  VERIFIED / NOT_MET (verifier non-zero) / INVALID (malformed envelope,
  provider infra failure, any other termination incl. interrupt or
  WAITING_APPROVAL abandonment); every consumed attempt is logged;
  preview-and-discard consumes an attempt + one intervention; the frozen argv
  is run integrity, deviation ⇒ round INVALID. Driver watchdogs
  (`baseline: 1800s`, `chain: 2400s`) are NOT the provider timeout — they cap
  total attempt wall time (provider + verifier + container ops); a
  `driver_timeout` after provider-node invocation records a consumed INVALID
  attempt. The driver writes an `invoked` marker before each attempt; a
  marker without a final attempt record at adjudication counts as a consumed
  INVALID attempt (interrupted), never silently re-consumed.

## 4. Frozen subset (REUSED, hash-pinned)

- The SELFDEV-2 frozen subset is reused VERBATIM:
  `.agent_runs/selfdev-2/selection.json` at freeze-commit `9843d5f`
  (sha256 recorded in `.agent_runs/selfdev-2/manifest.json`). The 12 MAIN
  tasks only; the 5 reserve tasks are not consumed (they remain reserve for
  a future round; reserve-swap rules are NOT exercised in this round — a
  task failure records task-level INVALID, no replacement).
- Rationale for reuse (declared): provider arms carry no cross-run memory;
  the subset's environment cost is already paid and hash-pinned; reusing it
  makes E1-vs-E2 a within-subset comparison, which is the point of the
  secondary analysis. The reuse is declared, not hidden.
- Vacuous-p2p tasks (`pydata__xarray-4075`, `pylint-dev__pylint-6903`)
  remain f2p-only solves per the E1 rule, flagged identically.

## 5. Environment freeze

- Provider: `openai-compatible`, model `kimi-k2-0711-preview`,
  `model_revision_digest: null` (LIMITATION carried: revision not pinned;
  model-id drift mid-round invalidates the round),
  `AGENT_OS_PROVIDER_TIMEOUT_SECONDS=600`, commitment
  `duration_seconds=3600`. LLM sampling = provider defaults (LIMITATION,
  recorded).
- Frozen argv (verbatim):
  chain — `agent-os benchmark-run-provider .agent_runs/selfdev-2/selection.json <instance_id> --approve --duration-seconds 3600`
  baseline — `agent-os benchmark-run-baseline .agent_runs/selfdev-2/selection.json <instance_id>`
  (`python -m apps.cli` is the same entry point as `agent-os`, per
  E1-adjudicated precedent.)
- Execution boundary: unchanged from ADR-0056 D5 (containers, `--network
  none`, read-only rootfs, rw task mount only, resource caps, env allowlist,
  per-task verifier timeout, env scrubbing).
- Pre-round re-verification (mandatory): docker daemon up; all 12 main
  workspaces `git rev-parse HEAD` == pinned base_commit AND empty
  `git status --porcelain`; per-repo images present (`docker images`).
  Failure ⇒ round does not start (infra, not capability).
- Repo head: the freeze commit of this prereg package on
  `codex/canonical-convergence-20260715`.

## 6. Verifier flow (unchanged)

As SELFDEV-2 §6: checkout base → apply candidate (chain bytes | baseline
diff) → apply hidden test patch → F2P node ids → curated P2P node ids →
solve iff both green → restore (always). Solve ONLY by the independent
round-level verifier re-run on final workspace state. Vacuous-p2p tasks:
f2p-only.

## 7. Verdict and kill criteria

- SUPPORTS the narrow claim iff chain pass@2 solve count > baseline pass@2
  solve count on the frozen subset with no task-level integrity failure.
  Strict inequality; ties do not support. SUPPORTS reads exactly as:
  "observed difference on this frozen 12-task subset under envelope E2" —
  nothing more. The 2 vacuous-p2p solves count as f2p-only.
- NEGATIVE iff a kill criterion fired or chain < baseline; MIXED otherwise.
- Kill criteria (carried + one addition):
  1. env/infra failure on >25% of frozen tasks — task-environment failures
     (workspaces/containers/daemon/manifests), NOT §3 provider-infra attempt
     classes (independent adjudicator's E1 ruling, carried) ⇒ round INVALID;
  2. any manifest/fixture/argv drift ⇒ INVALID;
  3. cheap-baseline data loss ⇒ INVALID;
  4. any parallel provider call or early stop ⇒ INVALID;
  5. two or more tasks with restore/compensation failure ⇒ INVALID;
  6. pre-round re-verification (§5) fails and is waived ⇒ INVALID (there is
     no waiver path).
  The driver's infra-collapse abort (3 consecutive non-provider infra
  errors) terminates the round early; that termination is a kill-4 event
  (round INVALID — infrastructure, not capability), recorded as such.

## 8. Freeze mechanics

1. Independent reviewer (reviewed_by != builder_id, RR-0031 blind anchoring)
   reviews this prereg; literal verdict; changes re-open review.
2. Freeze commit: this prereg, the round driver (ABAB), an exact-content
   manifest binding: prereg, driver, the REUSED selection.json's sha256 from
   the SELFDEV-2 manifest (proving byte-identity), and the E1 adjudication
   reference. Workspaces/images are re-verified per §5, not re-frozen.
3. Round order: ABAB per §3; run to completion.
4. Adjudication: receipts per task, verdict per §7, E1-vs-E2 secondary
   analysis (descriptive), negative map, paradigm learning, state sync —
   same independent-adjudication discipline as E1.

## 9. Boundaries (carried)

C7/approval/verifier semantics unchanged; untrusted code stays containerized
with no network/credentials; no mid-round envelope changes; any further
envelope change (incl. the diff channel) is a NEW prereg; the diff channel
itself is an ADR-level execution-contract change, tracked separately from
this round.
