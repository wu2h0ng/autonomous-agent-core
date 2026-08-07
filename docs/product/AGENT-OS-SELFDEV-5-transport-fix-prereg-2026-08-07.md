# AGENT-OS-SELFDEV-5 — Transport-Fix Round Prereg (DRAFT)

> Status: `DRAFT` — no result-bearing run until independent review accepts and
> the freeze commit records the exact-content manifest.
> Date: 2026-08-07. Builder: kimi-cli session.
> Governing documents: ADR-0056, ADR-0058, ADR-0059 (Accepted; implemented at
> c93d0e2), SELFDEV-2/3/4 prergs and adjudications.

## 1. Purpose and claim boundary

Question: on the SAME frozen 12-task subset as SELFDEV-4 (byte-identical
selection), with the chain's diff transport fixed per ADR-0059 (free-text
output + server-side extraction — the same transport the baseline has
always used), at pass@2 with ABAB scheduling and a pre-round provider
health gate, does the governed chain beat the bare same-model one-shot
scaffold?

This round isolates harness value with NO format or transport confound:
both arms emit unified diffs as free text; extraction, validation, and the
verifier are identical. The only difference is the governed flow (seal,
exact-digest approval, evaluate, compensate) vs a bare provider call.

NON-CLAIMS (carried verbatim): no comparability to published agentic
scaffolds; no leaderboard claim (12-task subset); no HCW-reduction claim;
contamination upper bound (Verified likely in K2's training distribution);
not release; not `Autonomy(S,E,O,V,T)` evidence.

Secondary declared analysis (descriptive only, NO gate): E4-vs-E5 per-arm
comparison on the same subset — quantifying the transport fix's effect
(chain weather-free failure rate E4 8/9 vs E5) and the transport-invariant
baseline (expected flat E4 4/12 vs E5, any movement = model drift signal,
since model revision is unpinned — LIMITATION carried).

## 2. Prior negative/result map (feeds design; not re-litigated)

- SELFDEV-4 (NEGATIVE): chain tool-call JSON diff transport failed 8/9
  weather-free attempts; baseline free-text diff solved 5/11 usable in the
  same window; chain complete-file was 19/20 at E3. Regression localized to
  the transport by the independent adjudicator.
- Operator violations/infra events of record (S4): over-budget smokes on
  astropy-14182 (task INVALID); /tmp mirror wipe (mirrors now durable,
  workspaces object-self-contained); non-attempt artifact retention is now
  a binding rule.
- sklearn-14141 (E1/E2/E3) a2 f2p exit=4 replication pattern — watch for
  per-task bimodality; not a target of this round.

## 3. Arms, inputs, budgets

- Inputs (identical both arms, carried): issue text + base-commit bytes of
  the gold file + FAIL_TO_PASS node ids + PASS_TO_PASS node ids. Neither
  arm sees test_patch contents or the gold patch.
- Chain arm: frozen argv `agent-os benchmark-run-provider
  .agent_runs/selfdev-4/selection.json <instance_id> --approve
  --duration-seconds 3600` — the governed workflow, diff mode per ADR-0059
  (text output + server-side extraction, three-way binding, git apply
  fail-closed). 2 attempts per task. astropy-14182 enters this round with a
  FRESH 2-attempt budget (new round; its S4 exhaustion was that round's
  accounting — declared).
- Cheap baseline: frozen argv `agent-os benchmark-run-baseline
  .agent_runs/selfdev-4/selection.json <instance_id>` — unchanged. 2 calls
  per task. Equal budgets by construction.
- Attempt accounting (carried verbatim incl. watchdogs 1800/2400, invoked
  markers, terminal classes, preview=consumed, frozen argv = run
  integrity; PLUS the binding retention rule: non-attempt artifacts are
  retained, never deleted).
- Solve determination: ONLY the independent round-level verifier (§6).
- Execution: strictly sequential; ABAB per-attempt interleaving; workspace
  restored to pinned base before EVERY attempt; no early stopping (driver
  infra-collapse abort = kill-4 event, recorded INVALID).
- **Pre-round provider health gate (new)**: within 30 minutes before the
  first attempt, a probe suite must pass: 3 sequential small calls
  (≤8 output tokens, each < 30s, HTTP 200) AND 1 medium call (a
  diff-producing prompt on one RESERVE task's file, completing < 300s with
  an extractable diff). If any probe fails, the round does not start; wait
  and re-probe (probe results recorded in the round log; the probe is NOT
  an attempt — it touches no main task).

## 4. Frozen subset (REUSED, hash-pinned)

- The SELFDEV-4 frozen subset is reused VERBATIM:
  `.agent_runs/selfdev-4/selection.json` at freeze-commit 5fa6f69 (sha256
  recorded in `.agent_runs/selfdev-4/manifest.json`; byte-identity proven
  in this round's manifest). The 12 MAIN tasks only; reserve tasks are not
  consumed (the health-gate medium probe reads one reserve task's FILE BYTES
  only — no provider attempt on any reserve task is produced by it; the
  probe's task target is never run this round).
- Rationale for reuse (declared): provider arms carry no cross-run memory;
  reuse makes E4-vs-E5 a within-subset transport comparison — the point of
  the secondary analysis.
- No vacuous-p2p tasks in this subset (as S4).

## 5. Environment freeze

- Provider: `openai-compatible`, model `kimi-k2-0711-preview`,
  `model_revision_digest: null` (LIMITATION carried),
  `AGENT_OS_PROVIDER_TIMEOUT_SECONDS=600`, commitment 3600s. Sampling =
  provider defaults (LIMITATION, recorded).
- Execution boundary: unchanged (containers, no network, read-only rootfs,
  rw task mount only, resource caps, env allowlist, per-task verifier
  timeout, env scrubbing).
- Pre-round re-verification (mandatory, extended per the S4 ruling):
  docker daemon up; all 12 main workspaces clean at pinned heads; per-repo
  images present; **solver sanity check** — solve5.py's extraction handles
  both content and diff candidates (the S4 freeze-defect class).
- Repo head: the freeze commit of this prereg package.

## 6. Verifier flow (carried)

As SELFDEV-3/4 §6: checkout base → apply candidate → apply hidden test
patch → F2P → curated P2P → solve iff both green → restore (always).
Solve ONLY via the independent round-level verifier re-run.

## 7. Verdict and kill criteria

- SUPPORTS the narrow claim iff chain pass@2 solve count > baseline pass@2
  solve count on the frozen subset, no task-level integrity failure. Strict
  inequality; ties do not support. SUPPORTS reads exactly as: "observed
  difference on this frozen 12-task subset under transport-symmetric
  contracts" — nothing more.
- NEGATIVE iff a kill criterion fired or chain < baseline; MIXED otherwise.
- Kill criteria (carried from SELFDEV-3/4 verbatim):
  1. env/infra failure on >25% of frozen tasks (task-environment failures,
     NOT provider-infra attempt classes) ⇒ INVALID;
  2. any manifest/fixture/argv drift other than a declared §4 swap ⇒ INVALID;
  3. cheap-baseline data loss ⇒ INVALID;
  4. any parallel provider call or early stop ⇒ INVALID (driver
     infra-collapse abort = kill-4 event);
  5. two or more tasks with restore/compensation failure ⇒ INVALID;
  6. pre-round re-verification (§5) or the health gate (§3) fails and is
     waived ⇒ INVALID (no waiver path).

## 8. Freeze mechanics

1. Independent reviewer (reviewed_by != builder_id, RR-0031 blind anchoring)
   reviews this prereg; literal verdict; changes re-open review.
2. Freeze commit: this prereg, the round driver (ABAB + health gate), an
   exact-content manifest binding: prereg, driver, solver, and the REUSED
   selection.json's sha256 from the SELFDEV-4 manifest (byte-identity).
3. Round order: health gate → ABAB per §3; run to completion.
4. Adjudication: receipts per task, verdict per §7, E4-vs-E5 descriptive
   analysis (no gate), negative map, paradigm learning, state sync —
   independent-adjudication discipline as before.

## 9. Boundaries (carried)

C7/approval/verifier semantics unchanged; untrusted code stays containerized
with no network/credentials; no mid-round envelope changes; any further
envelope change is a NEW prereg.
