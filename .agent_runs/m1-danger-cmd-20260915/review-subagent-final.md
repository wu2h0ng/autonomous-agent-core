# Independent adversarial exact-diff review — S1 DESCOPED (typed enumerable shell denial)

> Reviewer: subagent (adversarial, exact-diff)
> Model: deepseek-flash
> Builder: wu2h0ng; builder model recorded as deepseek-flash in prior rounds ← SAME MODEL; see §0
> Worktree: `autonomous-agent-core/.worktrees/m1-danger-cmd-20260915`
> Commit under review: `d6142d8f` (parent `4cb5d298`; base `origin/main` `18d7b9b0`)
> Prior rounds: `a99502d5` → `6a48f811` → `4cb5d298` → **descope** `d6142d8f`
> Scope of write: this file only; all source/test files were treated READ-ONLY.

## 0. Independence limitation (must be recorded)

Root `AGENTS.md` §11 requires `builder_id != reviewed_by`. I am the **same model** as the
builder (deepseek-flash), as were all three prior rounds (`review-subagent.md`,
`review-subagent-r2.md`, `review-subagent-r3.md`). This review is therefore **not** an
independent sign-off and cannot, by itself, satisfy the independent exact-diff gate. A
different model or a human must confirm this verdict before promotion.

## 1. Exact revision binding

`git show --stat d6142d8f` and `git diff 4cb5d298..d6142d8f` were read. The commit is a
single coherent descope (10 files, +827 / −398):

- `.agent_runs/m1-danger-cmd-20260915/goal-card-cp-ab.md` (records the descope)
- `.agent_runs/m1-danger-cmd-20260915/review-subagent{,-r2,-r3}.md` (prior rounds committed)
- `domain_packs/developer_agent/dangerous_command.py` (**deleted**, 207 lines)
- `domain_packs/developer_agent/shell_denial.py` (**new**, 58 lines)
- `domain_packs/developer_agent/workspace_capability.py` (4 call sites swapped)
- `pyproject.toml` (`[tool.pyright].include` updated)
- `tests/product/test_dangerous_command.py` (**deleted**, 182 lines)
- `tests/product/test_shell_denial.py` (**new**, 102 lines)

Files read directly: `shell_denial.py` (full), `_preflight_shell`, `_preflight_run_tests`,
`_shell`, `_run_tests`, `_execute_confined`, `_assert_seatbelt_paths`, `_preflight`/`_dispatch`
routers in `workspace_capability.py`, `tests/product/test_shell_denial.py`,
`agent_os_core/trusted_commands.py`, `agent_os_core/_action_outcome.py`.

## 2. Verification against the requested checklist

| # | Check | Result |
|---|---|---|
| a | No classifier / ReDoS remains anywhere | **PASS** — `dangerous_command.py` and `test_dangerous_command.py` deleted; `shell_denial.py` imports no `re`; only residual `re.compile` uses on the *search/grep* path (`workspace_capability.py:445,1097`), unrelated to shell and pre-existing. `pyproject.toml` include points at `shell_denial.py`. Repo-wide grep for `dangerous_command`/`classify_*`/`DANGEROUS_PATTERN`/`require_safe_shell_command` matches **only** `.agent_runs/` history. |
| b | Shell behaviour == previous exact-match allowlist | **PASS** — against the pre-classifier baseline `origin/main` `18d7b9b0`, the four sites are behaviourally identical: same normalization `" ".join(str(...).split())`, same membership test, same message strings. `run_tests` allowlist extracted to `_ALLOWLISTED_TEST_COMMANDS = frozenset({"pytest","python -m pytest","python3 -m pytest"})` — value-for-value identical to the old local `set`. Nothing that passed before now fails; the only widening is allowlisted *dangerous* strings (e.g. `rm -rf /`) now passing, which is the intended descope. |
| c | Every shell denial (preflight AND execution) carries `NOT_IN_ALLOWLIST` | **PARTIAL** — all 4 allowlist call sites do (verified at runtime, §4). But other *shell-path* denials remain bare `CapabilityDenied`: `_execute_confined` non-darwin (`:1177`) and missing `sandbox-exec` (`:1182`), `_assert_seatbelt_paths` (`:111`), and the SELFDEV verifier (`:1392`). All pre-existing, none are allowlist failures (so `NOT_IN_ALLOWLIST` would be semantically wrong for them). See F1. |
| d | `ShellCommandDenied` still a `CapabilityDenied`/`PermissionError`; message unchanged | **PASS** — `shell_denial.py:30`; runtime probe confirms `issubclass(ShellCommandDenied, CapabilityDenied) and issubclass(CapabilityDenied, PermissionError)`. `super().__init__(detail)` with the two original literals; `test_terminal_chat_loop.py` ("not in the shell allowlist") still green in the 52-pass suite. No `type(x) is CapabilityDenied` check exists anywhere. |
| e | Bypass detection if the reason were dropped | **PASS (strong)** — 5 of 7 tests assert `reason_code`/`args[0]`; a dropped reason raises `AttributeError` or fails `pytest.raises(ShellCommandDenied)`. Minimal gaps: `test_denial_is_still_a_capability_denied` checks only the supertype (passes on a bare `CapabilityDenied`), and `_run_tests` has no *execution-site* test. See F2. |

## 3. (c)/(d)/(e) runtime probe (author-run, verbatim)

Adapter `shell_allowlist=("git status", "rm -rf /")`:

```
subclass: True True
git status preflight: OK
rm -rf / allowlisted preflight: PASSES (descope)
preflight reason: ShellDenialReason.NOT_IN_ALLOWLIST is_enum: True msg: command is not in the shell allowlist
execute   reason: ShellDenialReason.NOT_IN_ALLOWLIST is_enum: True msg: command is not in the shell allowlist
rt-preflight reason: ShellDenialReason.NOT_IN_ALLOWLIST
rt-execute   reason: ShellDenialReason.NOT_IN_ALLOWLIST
```

All four call sites (shell/run_tests × preflight/execute) raise the typed denial with the
enumerable reason, and the legacy free-text message is preserved exactly.

## 4. Bypass-detection analysis of `tests/product/test_shell_denial.py`

- Delete the allowlist check entirely → 5 denial tests fail (`pytest.raises` sees no
  exception); only the two positive/subtype tests would pass.
- Replace `ShellCommandDenied` with bare `CapabilityDenied` → 5 tests fail (type mismatch
  or missing attribute).
- `test_denial_reason_is_machine_consumable_after_the_rewrite` additionally pins the
  human message (`args[0]`), so a message drift also fails.
- Trusted profile: all 9 `TRUSTED_SHELL_PROFILE_V1` entries are exact allowlist members;
  they pass through unconditionally equivalently to baseline.

## 5. Test runs (exact)

- `uv run --extra product-test pytest tests/product/test_shell_denial.py -q`
  → **7 passed in 0.32s**
- `uv run --extra product-test pytest tests/product/test_chat_trusted_shell_optin.py tests/product/test_os_sandbox.py tests/product/test_terminal_chat_loop.py -q`
  → **52 passed in 3.89s**
- `uv run --extra product-test ruff check` on the 2 changed modules + new test
  → **All checks passed!**
- `git diff --check 4cb5d298..d6142d8f` → clean (exit 0).
- Full `tests/product` baseline not re-run here (not requested); commit claims 24 failed ==
  base and zero new.

## 6. Findings (severity-ranked)

1. **[LOW — scope precision, non-blocking]** The claim "every dev-shell denial is now
   machine-consumable" (commit message; checklist c as literally worded) is not literally
   true: non-allowlist shell-path denials still raise bare `CapabilityDenied`
   (`_execute_confined:1177,1182`, `_assert_seatbelt_paths:111`, SELFDEV
   `workspace_capability.py:1392`). These are pre-existing, unreachable in the default
   `trusted_workspace_only` profile, and are NOT allowlist failures — so forcing
   `NOT_IN_ALLOWLIST` on them would mislabel. The module docstring is honest ("one allowlist
   refusal reason is the whole contract"). Recommended: either add e.g.
   `SANDBOX_UNAVAILABLE`/`SELFDEV_UNSAFE` reasons, or scope the wording to "allowlist
   denials". No functional/security defect.
2. **[LOW — test gap]** `_run_tests` has no *execution-site* test (only preflight,
   `test_shell_denial.py:90`); `test_denial_is_still_a_capability_denied` (`:65`) does not
   assert `reason_code`, so it alone would pass with the reason dropped. The suite still
   detects a reason-drop overall (§4), so this is coverage polish, not a bypass.
3. **[INFO]** Prior-round review files are committed inside this product commit
   (`.agent_runs/...`). Process artifact only; harmless, but worth noting for repo hygiene.

No HIGH/MEDIUM findings. No behavior change vs `origin/main`; no ReDoS/classifier residue;
no security or authority-boundary regression; the change stays entirely inside the domain
pack (`workspace_capability.py` + new `shell_denial.py`), touching no C7/permit/permission
surface.

## 7. Verdict

**APPROVE_WITH_CHANGES**

The descope is correct and safe. All functional requirements hold: the regex classifier and
its ReDoS are gone (a), the shell semantics are exactly the pre-classifier exact-match
allowlist with byte-identical denial messages and the identical `run_tests` allowlist (b),
the four allowlist denial sites are typed and enumerable at both preflight and execution
(c/d), and the tests are genuinely bypass-detecting (e). Both test suites pass (7 + 52) and
ruff/diff-check are clean.

The two required changes are LOW-severity and do not affect the default runtime path:
1. Reconcile the "every shell denial" wording with reality — either extend
   `ShellDenialReason` to cover the sandbox/SELFDEV denials or scope the claim to allowlist
   denials (the code docstring already does the latter).
2. Close the two test gaps in §6.2 (add a `_run_tests` execution-site test; assert
   `reason_code` in the subtype test).

Additionally, per §0 this review is **not independent** (same model as builder); an
independent model/human must confirm before promotion.
