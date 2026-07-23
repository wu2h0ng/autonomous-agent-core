# AGENT-OS-SELFDEV-2 — Public-Benchmark Baseline Round: Design Packet (for CTO gate)

> Status: `GATED` — founder/CTO gate passed 2026-07-23: D1 yes, D2 SWE-bench
> Verified filtered subset, D3 yes (N=12 + reserve 6, 2 attempts per task per
> arm), D4 yes (ADR scope authorized), D5 containerized per-task runner.
> Date: 2026-07-23. Author: kimi-cli session.
> Independent review: kimi subagent (blind-anchored per RR-0031, no builder run
> history). Round 1: CHANGES_REQUESTED (F-1..F-11). Round 2: CHANGES_REQUESTED
> (R-1 reserve-swap/manifest-drift semantics). Round 3: TECHNICAL_APPROVE.
> Supersedes the evaluation method (not the receipts) of round
> SELFDEV-MT-20260723 (adjudicated NEGATIVE, `.agent_runs/selfdev-mt-20260723/round-adjudication.md`).

## 1. Why this change, stated honestly

Founder direction (2026-07-23): use a public benchmark as the baseline instead of
matched founder/model+tools HCW baselines.

Claim classes are kept strictly separate (constitution §6):

- Class A (PRIMARY this round): capability comparability INSIDE a frozen,
  oracle-localized, single-shot, single-file repair envelope — does the Agent OS
  chain (seal/approve/resume/evaluate/compensate) beat a bare same-model
  one-shot scaffold given identical inputs, on a frozen task subset. This is an
  internal A/B gate, not a leaderboard or published-scaffold comparison.
- Class B (SECONDARY ledger): operator HCW minutes/interventions, recorded with
  zero founder cost. Published benchmark numbers contain no HCW; A never
  backfills B. No HCW-reduction claim can come out of this round.

Explicit non-claims: the harness gives the provider arm oracle fault
localization (gold file path) and FAIL_TO_PASS node ids — real SWE-bench
agentic evaluation does NOT (agents get issue + repo and localize themselves).
Our numbers are therefore NOT comparable to published agentic-scaffold rates
(including K2's), and the single-file filter bounds the write scope, not the
read/exploration mismatch. What this round validates is whether the governance
chain adds value over just asking the model, within the declared envelope.

## 2. Verified facts (checked 2026-07-23; primary pins due at prereg)

- Provider model: `kimi-k2-0711-preview`. Vendor-published SWE-bench Verified:
  **65.8% pass@1** (single attempt, no test-time compute) and **71.6%** with
  parallel test-time compute (Kimi K2 tech-report figures, to be pinned to the
  primary vendor source at prereg). Context only — never the gate; the vendor
  regime (agentic scaffold, multi-turn) differs from our envelope anyway.
- SWE-bench Verified = 500 tasks; contamination-inflation is widely documented
  (the model has likely seen these tasks; our subset results are an upper
  bound on novelty-free execution). SWE-bench Pro (Scale AI, 1,865 tasks,
  41 repos) and SWE-rebench (arXiv 2505.20411, continuous decontaminated
  pipeline) are the cleaner follow-up options if this round validates the
  machinery.
- Current sandbox reality (code-checked, `capability.py` `_run_tests`): NO
  general shell — capabilities are read/apply_patch/run_tests/artifact.write;
  run_tests executes an exact-string allowlisted pytest argv via subprocess
  with `cwd` confinement, `env = os.environ + sandbox vars` (FULL host
  environment, including any provider API keys), no network namespace, no
  container, timeout hard-capped at 120s. "Isolated workspace" today means
  cwd-confinement, NOT security isolation.

## 3. Round design (amended)

### Task source and frozen subset

- Source: SWE-bench Verified. Filters (all frozen, all recorded per task in the
  manifest): (a) gold patch touches exactly ONE file; (b) the gold file is at
  most **19,000 bytes** at base commit — the provider prompt truncates file
  content at 20,000 chars (`execution.py:1088`) with no marker, so anything
  larger is unsolvable by construction; bytes/lines recorded per task;
  (c) repo env builds in a plain venv on this host — VERIFIED BY DRY-RUN
  before freeze, not assumed (see §6 sequencing).
- Selection: seeded RNG with the seed recorded in the manifest; stratified,
  cap 2 tasks per repo; N=12 plus a frozen reserve list of 6. The frozen
  manifest includes the reserve list and per-task env manifests for all 18
  tasks. A reserve swap executed before the round's first provider call is a
  declared, recorded, re-hashed manifest event (not drift); swaps after the
  first provider call are forbidden — a round-time task failure then records
  task-level INVALID and counts toward kill criterion 1.
- Per-task env manifest: repo url, base commit, gold file path + byte/line
  counts, FAIL_TO_PASS node ids, curated PASS_TO_PASS node ids (SWE-bench
  per-instance lists, not full suites — full P2P suites blow the timeout),
  pinned deps with hashes (pre-fetched at freeze time), per-task verifier
  timeout seconds, interpreter version, minimum provider output-token budget
  per task (the chain must generate a complete ~19KB file; unbounded output
  limits would create a systematic failure class).

### Arms and inputs (identical for both arms)

- Inputs: issue text + base-commit bytes of the gold file + FAIL_TO_PASS node
  ids. Neither arm sees the test patch contents or the gold patch. (This is
  oracle localization — declared in §1, not SWE-bench's standard setup.)
- Chain arm: frozen argv (`selfdev-run-provider --approve --duration-seconds
  3600 --statement <issue+contract>`), output = complete-file replacement.
  2 attempts per task (pass@2; attempt classes per the MT prereg — consumed on
  provider-node invocation, INVALID/NOT_MET recorded, no free retries).
- Cheap baseline: same provider profile/timeout/sampling, same inputs, bare
  one-shot scaffold (no chain, no approval, no receipts), output = unified
  diff applied with `git apply` FAIL-CLOSED (malformed diff = attempt failure,
  no human repair; new negative-map class). 2 calls per task (pass@2) —
  budgets are equal by construction.
- Declared asymmetry (limitation on interpretation, conservative direction):
  unified diff is an easier output contract than complete-file replacement,
  so any residual format advantage runs AGAINST the chain. Output-contract
  difficulty is conflated with governance value; both are recorded.

### Verifier flow (same for both arms, per task)

1. checkout base commit; 2. apply candidate (chain bytes or baseline diff);
3. apply the hidden test patch; 4. run declared FAIL_TO_PASS ids then curated
   PASS_TO_PASS ids with the per-task timeout; 5. solve = F2P all green AND
   P2P all green; 6. compensation restores base bytes.
- Verifier argv: enumerated node-id pytest patterns only, with node-id
  argument validation — no general shell (ADR enumerates the patterns).
- Verifier subprocess env scrubbing: provider credentials and unrelated
  secrets stripped before any third-party code runs.
- Solve determination (made explicit at prereg): a task solves only via the
  independent round-level verifier flow re-run on the final workspace state —
  the chain's internal VERIFIED outcome is never itself accepted as evidence.

### Verdict and kill criteria

- SUPPORTS the narrow claim iff chain pass@2 solve count > cheap-baseline
  pass@2 solve count on the frozen subset, with no task-level integrity
  failure. Strict inequality; ties = not supports. SUPPORTS means "observed
  difference on this frozen 12-task subset" — 8.3pp granularity, no
  inferential/power claim, no leaderboard reading (kept verbatim in prereg).
- NEGATIVE iff a kill criterion fired or chain < baseline; MIXED otherwise.
- Kill criteria: (1) env/infra failure on >25% of frozen tasks (round
  INVALID — infrastructure, not capability); (2) any manifest/fixture/argv
  drift (INVALID); (3) cheap-baseline data loss (INVALID); (4) any parallel
  provider calls — execution is SEQUENTIAL for both arms (MT negative-map
  class 1: parallel load caused 2/7 timeouts); (5) early stopping is forbidden
  — the round runs to completion regardless of intermediate standings.

### Operator ledger (class B, secondary)

Operator minutes/interventions per task (launches, failure reads, retry
decisions) recorded exactly as in the MT prereg. No founder baseline work.

## 4. Required product changes (ADR-level, before the prereg freeze)

1. ADR: external benchmark task admission — a `SelfDevelopmentBenchmarkTask`
   path separate from `_AGENT_OS_REPOSITORIES`, binding repo url + base commit
   + env manifest + F2P/P2P sets + issue text hash. Agent OS admission
   untouched.
2. Env builder: per-task venv from pinned, hash-locked, pre-fetched deps.
   Declared network policy: network only at freeze-time prefetch; NO network
   during runs. Third-party code execution is arbitrary code on the founder's
   host — the ADR must contain EITHER a founder-signed host-execution risk
   acceptance (cwd-confined + env scrubbing) OR a containerized per-task
   runner (decision D5).
3. Verifier: §3 flow, node-id argv validation, env scrubbing, per-task
   configurable timeout (fail-closed default; current 120s cap is
   ADR-adjustable per task).
4. Cheap-baseline runner: §3 spec, same verifier, `git apply` fail-closed.
5. Gold env validation harness: for every candidate task, prove base+test-patch
   FAILS the F2P set and base+gold+test-patch PASSES both sets; evidence per
   task recorded in the env manifest. Tasks failing validation are replaced
   from the reserve BEFORE freeze completes.
6. All behind the standard gates: tests first, targeted pytest/ruff/pyright,
   no CI bypass.

## 5. Boundaries (unchanged unless noted)

- 12-task subset: no public ranking claim, ever.
- Contamination: Verified is likely inside K2's training distribution; subset
  results are an upper bound on novelty-free execution. Follow-up candidate:
  SWE-rebench recent-vintage slice (new prereg).
- Oracle-localized single-shot single-file envelope: no comparability claim to
  published agentic scaffolds.
- No HCW-reduction claim (class A only).
- C7/approval/verifier semantics unchanged; exact-digest approval and
  fail-closed compensation per task; frozen argv, no mid-stream contract
  rescue.

## 6. Execution sequence after CTO gate

1. ADR draft (§4) → independent review → implement with tests.
2. Dataset acquisition + filter pass + per-task env DRY-RUNS (incl. gold
   validation, §4.5). Only dry-run-passing tasks enter the selection pool.
3. Seeded stratified selection (N=12 + reserve 6) → freeze manifest.
4. New prereg (subset, statements, comparators, budgets, verifier flow,
   verdicts, kill criteria, exact-content manifest) → independent reviewer →
   freeze commit.
5. Round: cheap baseline pass@2 first (cheap), then chain pass@2 per task,
   sequential, run to completion.
6. Receipts, adjudication, negative map, paradigm learning, state sync.

## 7. Decision points for the CTO gate

- D1: claim-class split (A primary, B ledger) — yes/no.
- D2: task source — SWE-bench Verified filtered subset (recommended) vs
  SWE-rebench vintage slice (cleaner, +1-2 days pipeline).
- D3: N=12 + reserve 6, 2 attempts per task per arm — yes/no.
- D4: authorize the §4 ADR scope — yes/no.
- D5 (new per review F-4): third-party code execution — host with
  cwd-confinement + env scrubbing + founder risk acceptance (faster, weaker),
  or containerized per-task runner (slower to build, stronger boundary)?
