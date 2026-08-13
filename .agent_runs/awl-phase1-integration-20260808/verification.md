# AWL Phase 1 Integration — Verification Record

- Run: `awl-phase1-integration-20260808`
- Date: 2026-08-09
- Goal card: AWL Phase 1 集成（Goal Card 三项验证：AWL-1 验证、AWL-2 验证、本地集成 merge）
- Owner: CTO (OpenCode, single writer)
- Scope: `autonomous-agent-core` only; no push, no release
- Integration main: `main-merge-b4-20260718` worktree, pre-merge HEAD `cbc55a4`
- AWL-2 branch: `feature/awl-2-capability-adapter`, rebased onto `main@802ad98`, 13 commits (`bda89f8`..`cac9378` + `7adeaa0` style fix)

## 1. AWL-1 Verification (pre-merge baseline, prior session)

- AWL-1 (`C7 read/admin port split`) previously integrated at `cbc55a4` (`merge(awl): AWL-1 C7 port split (no-ff integration)`).
- Baseline failure set captured: `/tmp/main_failures.txt` — 19 failures (provider_trajectory_binding ×16, spine0 ×2, package_metadata ×1), all pre-existing.

## 2. AWL-2 Rebase + Verification (branch worktree)

Rebase: `feature/awl-2-capability-adapter` rebased onto `main@802ad98`, 12 original commits + 1 integration fix `cac9378` + 1 style fix `7adeaa0`. All 6 execution.py conflict regions resolved with `ActionPipeline` injection scheme; `repository_patch_profile.py` extended with SELFDEV acceptance criteria + `selfdev_verification_snapshot` pass-through.

Integration fixes (commit `cac9378`):
- Restore main risk tiers (apply_patch=2, edit=2, shell=3) and `.agent_os` reservation + symlink enforcement in `DeveloperWorkspaceAdapter`
- Preserve tool error messages in adapter `execute` output
- Align boundary/composition tests with merged 7-capability spec set
- Adapt AWL-1 runtime construction test + `agent_cli_v0` import to CapabilityPort/DeveloperWorkspaceAdapter seams

Verification results (branch tip, pre-merge):

| Check | Command | Result |
|---|---|---|
| Product suite full | `PYTHONPATH=packages/contracts/src:packages/os_core/src:. uv run --extra product-test pytest tests/product -q` | 19 failed / 1889 passed / 1 skipped — **failure set byte-identical to `/tmp/main_failures.txt` (zero new failures)** |
| Ruff check (changed files) | `python3 -m ruff check --no-cache <changed .py>` | All checks passed |
| Ruff format (changed files) | `python3 -m ruff format --check --no-cache <changed .py>` | Only pre-existing baseline unformatted files remain; 2 new AWL-2 files formatted via `7adeaa0` |
| Diff check | `git diff --check` | clean |

## 3. Local Integration Merge + Post-Merge Verification

Merges onto integration main (`cbc55a4`):
- `82f8d2e` — no-ff merge of rebased AWL-2 (12 commits + `cac9378`)
- `cb07ab5` — no-ff merge of style fix `7adeaa0`
- `3c1d5c4` — docs: CURRENT_STATE.yaml AWL-2 status → `REBASED_ONTO_MAIN_802AD98 / INTEGRATED_LOCAL_MERGE_ONLY`

Post-merge verification (merged main HEAD `3c1d5c4`):

| Check | Command | Result |
|---|---|---|
| Product suite full | pytest tests/product -q | 19 failed / 1889 passed / 1 skipped — failure set `diff /tmp/main_failures.txt` = **IDENTICAL TO PRE-MERGE BASELINE** (zero new) |
| Ruff check (merge-introduced files) | `ruff check --no-cache <git diff --name-only cbc55a4..HEAD *.py>` | All checks passed |
| Ruff format (merge-introduced files) | `ruff format --check --no-cache <changed>` | 7 files would-reformat are all pre-merge-baseline unformatted (verified per-file `pre_merge_formatted=0`); zero new format debt |
| Research suite | `python3 -m unittest discover -t . -s tests -p "test_*.py"` | 732 tests, errors=54 skipped=16 — **error set identical to cbc55a4 baseline** (`diff /tmp/base_unittest.txt /tmp/merged_unittest.txt` = identical; research deps missing, pre-existing) |
| Diff check | `git diff --check` | clean |

## 4. Verdict

- AWL-1 verify: PASS (baseline evidence `/tmp/main_failures.txt`)
- AWL-2 rebase + verify: PASS (zero new failures, ruff clean, format debt zero)
- Local no-ff merge: PASS (merged suite failure set identical to pre-merge baseline)
- No main push, no release, no promotion claim.

## 5. Artifacts

- `/tmp/main_failures.txt` — pre-merge baseline failure set (cbc55a4)
- `/tmp/awl2_failures2.txt` — branch failure set (identical)
- `/tmp/merged_failures.txt` — merged main failure set (identical)
- `/tmp/base_unittest.txt` / `/tmp/merged_unittest.txt` — research suite error sets (identical)

## 6. Next Steps

- b32f2cb scoped verifier exact review of the merge diff (independent reviewer)
- SELFDEV route progression (P-AGENT-SELFDEV-ORGAN-1 gate + AgentLoop SELFDEV bridge + repository patch profile verification)
