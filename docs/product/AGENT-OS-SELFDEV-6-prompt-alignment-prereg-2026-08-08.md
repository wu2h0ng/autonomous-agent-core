# AGENT-OS-SELFDEV-6 — Governed-Prompt Alignment Round Prereg (DRAFT)

> Status: `DRAFT` — no result-bearing run until independent review accepts and
> the freeze commit records the exact-content manifest.
> Date: 2026-08-08. Builder: kimi-cli session.
> Governing documents: ADR-0056/0058/0059, SELFDEV-2/3/4/5 prergs and
> adjudications. Harness change under test: governed diff-mode prompt aligned
> to the baseline's proven shape + capability denial-reason logging
> (a496442).

## 1. Purpose and claim boundary

Question: on the SAME frozen 12-task subset (byte-identical to SELFDEV-4/5),
with the chain's diff-mode prompt now aligned to the baseline's proven
prompt shape (a496442), at pass@2 with ABAB scheduling and the pre-round
health gate, does the governed chain's weather-free solve rate match or
approach the baseline's — i.e., is the SELFDEV-5 residual (the ~6.5×
weather-free solve-rate gap localized to the governed prompt/response
contract) closed by the prompt alignment?

This is the closure test for the series' localization chain. If the chain
matches the baseline on weather-free attempts, the harness-cost question
closes positively (the governed flow's cost was prompt design, fixable);
if not, the residual sits in the response-contract strictness itself.

NON-CLAIMS (carried verbatim): no comparability to published agentic
scaffolds; no leaderboard claim; no HCW-reduction claim; contamination
upper bound; not release; not `Autonomy(S,E,O,V,T)` evidence.

Secondary declared analysis (descriptive only, NO gate): E5-vs-E6 per-arm
comparison on the same subset — the prompt fix's effect on the chain's
weather-free failure classes (DIFF_INVALID / INVALID_ENVELOPE /
APPLY_FAILED), and the transport-invariant baseline movement (model drift
signal; model revision unpinned — LIMITATION carried).

## 2. Prior negative/result map (feeds design; not re-litigated)

- SELFDEV-5 (NEGATIVE): chain 1/12 vs baseline 5/12; transport fix changed
  nothing (weather-free 1/9 E4 → 1/13 E5); residual localized to the
  governed prompt/response contract (9/12 weather-free failures) plus an
  apply-gate class (3/12, denial reasons then unlogged).
- Fixes now implemented (a496442): governed diff-mode prompt aligned to
  the baseline's shape (statement + fenced file + minimal instruction,
  no SHA-256 line, no header-format prescription); CapabilityDenied reasons
  now logged (capability.py error_detail + execution.py propagation);
  whitelist-abort driver (abort only on genuine infra signatures, never on
  unrecognized provider output).
- Recurrent defect fixed: classifier-misfire aborts (S4/S5) — the driver
  now uses whitelist abort (adjudicator's structural fix).

## 3. Arms, inputs, budgets

- Inputs (identical both arms, carried): issue text + base-commit bytes of
  the gold file + FAIL_TO_PASS + PASS_TO_PASS node ids. Neither arm sees
  test_patch contents or the gold patch.
- Chain arm: frozen argv `agent-os benchmark-run-provider
  .agent_runs/selfdev-4/selection.json <instance_id> --approve
  --duration-seconds 3600` — governed workflow, diff mode, prompt now
  aligned with the baseline shape (a496442). 2 attempts per task.
  astropy-14182 enters with a fresh 2-attempt budget (new round; S4/S5
  exhaustion was those rounds' accounting — declared, carried).
- Cheap baseline: frozen argv `agent-os benchmark-run-baseline
  .agent_runs/selfdev-4/selection.json <instance_id>` — unchanged. 2 calls
  per task. Equal budgets by construction.
- Attempt accounting (carried verbatim: watchdogs 1800/2400, invoked
  markers, terminal classes, preview=consumed, frozen argv = run integrity,
  retention rule binding).
- Solve determination: ONLY the independent round-level verifier (§6).
- Execution: strictly sequential; ABAB per-attempt; workspace restored
  before EVERY attempt; no early stopping. **The driver aborts ONLY on
  whitelisted genuine-infra stderr signatures** (docker daemon,
  workspace missing/dirty/drift, restore failure, configuration drift);
  unrecognized provider output records a consumed FAILED_UNCLASSIFIED
  attempt and the round continues (SELFDEV-5 adjudicator's structural fix).
- Pre-round provider health gate (carried): 3 small probes + 1 medium probe
  with an extractable-diff check, within 30 minutes before the first
  attempt; failure ⇒ no start.

## 4. Frozen subset (REUSED, hash-pinned)

- The SELFDEV-4 frozen subset is reused VERBATIM for the third round:
  `.agent_runs/selfdev-4/selection.json` at 5fa6f69 (sha256 in
  `.agent_runs/selfdev-4/manifest.json`; byte-identity proven in this
  round's manifest). The 12 MAIN tasks only; reserve tasks are not
  consumed (the health-gate medium probe reads one reserve task's file
  bytes only — not an attempt).
- Rationale (declared): provider arms carry no cross-run memory; reuse
  makes E4/E5/E6 within-subset comparisons — the point of the series'
  envelope isolation.

## 5. Environment freeze

- Provider: `openai-compatible`, `kimi-k2-0711-preview`,
  `model_revision_digest: null` (LIMITATION), timeout 600s, commitment
  3600s. Sampling = provider defaults (LIMITATION).
- Execution boundary: unchanged (ADR-0056 D5 containers; no network; env
  scrubbing).
- Pre-round re-verification (mandatory): docker up; all 12 main workspaces
  clean at pinned heads; images present; solver sanity (extraction handles
  content + diff candidates); the workspace object self-containment is
  intact (alternates detached).
- Repo head: the freeze commit of this prereg package.

## 6. Verifier flow (carried)

As before: checkout base → apply candidate → apply hidden test patch →
F2P → curated P2P → solve iff both green → restore (always). Solve ONLY
via the independent round-level verifier re-run.

## 7. Verdict and kill criteria

- SUPPORTS the narrow claim iff chain pass@2 solve count > baseline pass@2
  solve count on the frozen subset, no task-level integrity failure. Strict
  inequality; ties do not support. SUPPORTS reads exactly as: "observed
  difference on this frozen 12-task subset under the aligned-prompt
  envelope" — nothing more.
- NEGATIVE iff a kill criterion fired or chain < baseline; MIXED otherwise.
- Kill criteria (carried verbatim): 1. env/infra failure on >25% of frozen
  tasks (task-environment, not provider-infra attempt classes) ⇒ INVALID;
  2. manifest/fixture/argv drift other than a declared §4 swap ⇒ INVALID;
  3. cheap-baseline data loss ⇒ INVALID; 4. parallel provider calls or
  early stop ⇒ INVALID (driver whitelist-abort = kill-4 event);
  5. two or more tasks with restore/compensation failure ⇒ INVALID;
  6. pre-round re-verification or health gate fails and is waived ⇒
  INVALID (no waiver path).

## 8. Freeze mechanics

1. Independent reviewer (reviewed_by != builder_id, RR-0031 blind anchoring)
   reviews this prereg; literal verdict; changes re-open review.
2. Freeze commit: this prereg, driver6.py, solve6.py, an exact-content
   manifest binding those plus the reused selection.json's sha256
   cross-pin (byte-identity to the SELFDEV-4 manifest).
3. Round order: health gate → ABAB; run to completion.
4. Adjudication: receipts, verdict per §7, E5-vs-E6 descriptive (no gate),
   negative map, paradigm learning, state sync, independent adjudication.

## 9. Boundaries (carried)

C7/approval/verifier semantics unchanged; untrusted code stays containerized
with no network/credentials; no untyped model output becomes a consequential
command; no mid-round envelope changes; any further envelope change is a
NEW prereg.
