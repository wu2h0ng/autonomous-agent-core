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
- Chain arm: frozen argv `agent-os benchmark-run-provider <task-manifest>
  --approve --duration-seconds 3600` (ADR-0056 Decision 1-3 CLI surface for
  benchmark tasks; create → commit → seal → run → WAITING_APPROVAL →
  in-process approve → resume → container-backed tests → evaluate).
  Output: complete-file replacement of the gold file. 2 attempts per task.
- Cheap baseline: frozen argv `agent-os benchmark-run-baseline <task-manifest>`
  — same provider profile/timeout/sampling, same inputs, one-shot unified-diff
  output, `git apply` fail-closed (malformed diff = attempt failure, no human
  repair), then the §6 independent verifier. 2 calls per task. Equal budgets
  by construction.
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

## 4. Frozen subset (FROZEN at freeze commit)

- Selection (executed 2026-07-23): seed `20260723`,
  `random.Random(seed).shuffle` over the 17 gold-validation-passing
  instance_ids sorted lexicographically; first 12 = main, last 5 = reserve;
  cap 2 per repo enforced by pool construction. Machine-readable selection:
  `.agent_runs/selfdev-2/selection.json` (pins every field in §4 of the
  design: commits, issue hash, gold file path/bytes/lines, resolved
  f2p/p2p node ids, image tag, interpreter, verifier timeout, min output
  tokens 8192, gold-validation evidence digest). Per-repo Dockerfiles and
  dependency pins: `.agent_runs/selfdev-2/env/<repo>/`.
- Vacuous-P2P declaration: two MAIN tasks (`pydata__xarray-4075`,
  `pylint-dev__pylint-6903`) have fully-parametrized raw PASS_TO_PASS lists
  and therefore an EMPTY resolved p2p set (`p2p_vacuous: true`). For these
  two tasks, solve = f2p green only, with no regression coverage; this is
  declared upfront, affects both arms symmetrically, and is flagged in
  adjudication. All other tasks carry real p2p coverage (2–20 ids).
- Reserve swaps: only before the round's first provider call; each swap is a
  declared, recorded, re-hashed manifest event. Post-first-call swaps are
  forbidden; a round-time task failure records task-level INVALID and counts
  toward kill criterion 1.

### Main set (12)

| instance_id | repo | gold file | bytes | f2p | p2p |
|---|---|---|---|---|---|
| astropy__astropy-13453 | astropy/astropy | astropy/io/ascii/html.py | 17668 | 1 | 9 |
| django__django-13670 | django/django | django/utils/dateformat.py | 10850 | 1 | 17 |
| django__django-14089 | django/django | django/utils/datastructures.py | 9891 | 1 | 20 |
| matplotlib__matplotlib-22719 | matplotlib/matplotlib | lib/matplotlib/category.py | 7921 | 1 | 3 |
| psf__requests-1766 | psf/requests | requests/auth.py | 6063 | 6 | 20 |
| pydata__xarray-4075 | pydata/xarray | xarray/core/weighted.py | 8032 | 2 | 0 (VACUOUS) |
| pylint-dev__pylint-6903 | pylint-dev/pylint | pylint/lint/run.py | 8258 | 1 | 0 (VACUOUS) |
| pylint-dev__pylint-7080 | pylint-dev/pylint | pylint/lint/expand_modules.py | 5982 | 1 | 20 |
| scikit-learn__scikit-learn-14141 | scikit-learn/scikit-learn | sklearn/utils/_show_versions.py | 2513 | 1 | 2 |
| sphinx-doc__sphinx-10449 | sphinx-doc/sphinx | sphinx/ext/autodoc/typehints.py | 7033 | 1 | 20 |
| sphinx-doc__sphinx-10466 | sphinx-doc/sphinx | sphinx/builders/gettext.py | 11238 | 1 | 6 |
| sympy__sympy-13974 | sympy/sympy | sympy/physics/quantum/tensorproduct.py | 13565 | 1 | 4 |

### Reserve (5)

| instance_id | repo | gold file | bytes | f2p | p2p |
|---|---|---|---|---|---|
| astropy__astropy-14182 | astropy/astropy | astropy/io/ascii/rst.py | 1649 | 1 | 9 |
| pytest-dev__pytest-5631 | pytest-dev/pytest | src/_pytest/compat.py | 9930 | 1 | 15 |
| pytest-dev__pytest-7490 | pytest-dev/pytest | src/_pytest/skipping.py | 10727 | 2 | 16 |
| scikit-learn__scikit-learn-13328 | scikit-learn/scikit-learn | sklearn/linear_model/huber.py | 11056 | 1 | 9 |
| sympy__sympy-12419 | sympy/sympy | sympy/matrices/expressions/matexpr.py | 14874 | 1 | 13 |

### Frozen per-task statement template (chain `--statement`; cheap baseline gets the same information content)

```
Repository: <repo> (base commit <base_commit>)
Issue report:
<issue.txt verbatim>

Target file: <gold_file_path>
Acceptance contract: after your change, the following tests must pass:
<f2p_node_ids, one per line>
Existing behavior to preserve (regression tests, when non-empty):
<p2p_node_ids, one per line; omitted when empty>

Replace ONLY the target file. Do not modify any other file.
```

The chain injects this as the task goal (execution.py:320); the cheap
baseline receives the same template text plus the same file bytes.

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
