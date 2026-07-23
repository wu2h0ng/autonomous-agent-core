# AGENT-OS-SELFDEV-2 — Benchmark-Baseline Round Prereg (DRAFT pending subset freeze)

> Status: `DRAFT` — Sections 1-10 complete for review; §4 (frozen subset) is
> filled ONLY after gold env validation dry-runs complete. No result-bearing
> run is authorized until independent review accepts and the freeze commit
> records the exact-content manifest.
> Date: 2026-07-23. Builder: kimi-cli session.
> Governing documents: design packet `AGENT-OS-SELFDEV-2-benchmark-baseline-design-2026-07-23.md`
> (GATED, review TECHNICAL_APPROVE ×3), ADR-0056 (Accepted).

## 1. Purpose and claim boundary

Question: on a frozen subset of SWE-bench Verified tasks, inside a declared
oracle-localized, single-shot, single-file repair envelope, does the Agent OS
chain (seal/approve/resume/evaluate/compensate, complete-file output) beat a
bare same-model one-shot scaffold (unified-diff output) given IDENTICAL
inputs, at pass@2 with equal budgets?

Class A only: internal A/B capability gate. NON-CLAIMS (verbatim from the
GATED design): no comparability to published agentic-scaffold rates (our
inputs include oracle localization and FAIL_TO_PASS ids); no leaderboard claim
(12-task subset, 8.3pp granularity, no inferential power); no HCW-reduction
claim (class B is a recorded ledger only); contamination — Verified is likely
inside K2's training distribution, results are an upper bound on novelty-free
execution. Not release, not `Autonomy(S,E,O,V,T)` evidence.

## 2. Prior negative/result map

- MT round (self-made targets): adjudicated NEGATIVE
  (`.agent_runs/selfdev-mt-20260723/round-adjudication.md`) — kill criterion 1;
  negative map classes: parallel-load provider timeouts 2/7, neighbor breakage
  2/2 on self_development.py, large-file full-replacement syntax failure 2/2.
- The full-file output contract degrades on large files; this round's 19,000-byte
  bound makes tasks solvable by construction, and the diff-vs-full-file
  asymmetry vs the cheap baseline is declared conservative (against the chain).
- Fair single-target round: one VERIFIED receipt (SELFDEV_HCW_LOWER) plus one
  malformed-envelope rejection in two samples — attempt-accounting rules below
  are carried over unchanged.

## 3. Arms, inputs, budgets

- Inputs (identical both arms): issue text + base-commit bytes of the gold
  file + FAIL_TO_PASS node ids. Neither arm sees test_patch contents or the
  gold patch.
- Chain arm: frozen argv `agent-os selfdev-run-provider <spec> --baseline-record
  <record> --approve --duration-seconds 3600 --statement <issue+contract>`.
  Output: complete-file replacement of the gold file. 2 attempts per task.
- Cheap baseline: same provider profile/timeout/sampling, same inputs, one-shot
  unified-diff output, `git apply` fail-closed (malformed diff = attempt
  failure, no human repair). 2 calls per task. Equal budgets by construction.
- Attempt accounting (carried over): an attempt is consumed the moment the
  provider node is invoked; terminal classes VERIFIED / NOT_MET (verifier
  non-zero) / INVALID (malformed envelope, provider infra failure, any other
  termination incl. interrupt or WAITING_APPROVAL abandonment); every consumed
  attempt is logged; preview-and-discard consumes an attempt + one
  intervention; the frozen argv is run-integrity, deviation ⇒ round INVALID.
- Solve determination: ONLY the independent round-level verifier re-run on the
  final workspace state (ADR-0056 Decision 3). Chain-internal VERIFIED is
  telemetry, never evidence.
- Execution is SEQUENTIAL for both arms (no parallel provider calls). No
  early stopping: the round runs to completion regardless of standings.

## 4. Frozen subset (FILLED AT FREEZE — placeholder)

- Selection: seeded RNG (seed recorded in manifest), stratified cap 2 tasks
  per repo, N=12 + 6 reserve, drawn ONLY from the gold-validation-passing
  pool (§8). The manifest pins: instance_id, repo, base_commit,
  environment_setup_commit, issue_text_hash, gold_file_path/bytes/lines,
  f2p/p2p node ids (resolved to pytest form, `benchmark_node_ids` evidence),
  per-task interpreter, pinned deps with hashes, verifier timeout seconds,
  min output-token budget, gold-validation evidence digest.
- Reserve swaps: only before the round's first provider call; each swap is a
  declared, recorded, re-hashed manifest event. Post-first-call swaps are
  forbidden; a round-time task failure records task-level INVALID and counts
  toward kill criterion 1.

## 5. Environment freeze

- Provider: `openai-compatible`, model `kimi-k2-0711-preview`,
  `model_revision_digest: null` (LIMITATION: revision not pinned; model-id
  drift mid-round invalidates the round), `AGENT_OS_PROVIDER_TIMEOUT_SECONDS=180`,
  commitment `duration_seconds=3600`. LLM sampling = provider defaults, not
  seedable (LIMITATION, recorded).
- Execution boundary (ADR-0056 D5): all third-party code runs only inside
  per-task containers — `--network none`, `--read-only` rootfs, rw bind of the
  task workspace only, `--memory 2g --cpus 2 --pids-limit 512`, env allowlist
  only (host credentials never enter), per-task verifier timeout, fail-closed.
  Host-side file operations touch only our own controlled bytes.
- Repo heads: worktree branch `codex/canonical-convergence-20260715`; freeze
  head = the freeze commit of this prereg package.
- Docker daemon (colima) required at freeze and round time; absence = infra
  INVALID, not capability.

## 6. Verifier flow (both arms, per task)

checkout base → apply candidate (chain bytes | baseline diff) → apply hidden
test patch → run F2P node ids → run curated P2P node ids → solve iff both
green → restore base bytes (always, finally). Verifier argv: `python -m
pytest <ids...>` lists only, node-id validated, no shell. Verifier subprocess
env scrubbed of credentials.

## 7. Verdict and kill criteria

- SUPPORTS the narrow claim iff chain pass@2 solve count > cheap-baseline
  pass@2 solve count on the frozen subset, with no task-level integrity
  failure. Strict inequality; ties do not support. SUPPORTS reads exactly as:
  "observed difference on this frozen 12-task subset" — nothing more.
- NEGATIVE iff a kill criterion fired or chain < baseline; MIXED otherwise.
- Kill criteria: (1) env/infra failure on >25% of frozen tasks (round
  INVALID); (2) any manifest/fixture/argv drift other than a declared §4
  reserve-swap event (INVALID); (3) cheap-baseline data loss (INVALID);
  (4) any parallel provider call or early stop (INVALID);
  (5) two or more tasks with restore/compensation failure (INVALID — the
  rollback path itself is suspect).

## 8. Pre-freeze gold validation (gate for the selection pool)

Per candidate task, in its container: base+test_patch must leave F2P RED;
base+gold+test_patch must leave F2P and P2P GREEN (ADR-0056 Decision 5).
Only passing tasks enter the selection pool. Validation evidence digests are
recorded in the manifest. Dry-runs run sequentially; a repo whose image
cannot be built (historic deps on linux/arm64) drops out with the reason
recorded in the negative map.

## 9. Freeze mechanics

1. Independent reviewer (reviewed_by != builder_id, RR-0031 blind anchoring)
   reviews this prereg INCLUDING the filled §4; literal verdict required;
   changes re-open review.
2. Freeze commit: this prereg, subset manifest, per-task env manifests,
   gold-validation evidence, acquisition reports, exact-content sha256
   manifest over all mechanism files. Drift ⇒ round INVALID.
3. Round order: cheap baseline pass@2 for all 12 tasks, then chain pass@2
   per task; sequential; to completion.
4. Adjudication: receipts per task, round verdict per §7, negative map,
   paradigm learning, state sync — same discipline as the MT round.

## 10. C6/C7/SD4 and security boundary

- The chain's approval/exact-digest/compensation semantics are unchanged;
  untrusted third-party code never runs on the host, never sees credentials,
  never has network. The cheap baseline runs the same model on the host only
  for TEXT generation (provider API); candidate application is `git apply`
  fail-closed on our own bytes.
- Operator ledger (class B): minutes/interventions per task recorded per the
  MT accounting rules; no founder baseline work; no HCW claim.
