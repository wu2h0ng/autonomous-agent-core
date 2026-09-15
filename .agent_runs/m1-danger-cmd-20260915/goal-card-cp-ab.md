# Goal Card + CP/AB + CTO gate — S1 DANGEROUS-COMMAND-CLASSIFICATION

> Status: `CTO_GATE_ASSIGNED / TEST_FIRST_IMPLEMENTED / PENDING_INDEPENDENT_EXACT_DIFF_REVIEW`
> Track: Product Track (medium risk: touches the shell preflight on the path to a
> risk-bearing capability; adds a new typed denial surface).
> Cast: P2-7 M1 route = A (finish M1 kernel), target = Python core, first slice = S1.
> Base: `origin/main` @ `18d7b9b0`; branch `feature/m1-dangerous-command-classification-20260915`.
> Claim ceiling: no parity / Alpha / Autonomy(S,E,O,V,T) / release claim.

## 1. Goal Card

**Problem.** The developer shell preflight refuses commands by *exact-match allowlist*
only, and its denial is an untyped `CapabilityDenied` with a free-text message. There is
no independent check that a command is intrinsically destructive, and no
machine-consumable denial reason (GAP-ANALYSIS: "危险命令识别库 ❌ … but out-of-allowlist
fail-closed already covers its worst consequence").

**Target U/P.** U: an operator who (mis)allowlists a destructive command still gets it
refused, with a stable, enumerable reason a harness can consume. P: a typed classifier
module + a typed shell denial, integrated at the shell preflight, covered by
bypass-detecting tests.

**Non-goals.** No OS sandbox (the classifier is NOT isolation); no shell grammar parser;
no new event/storage; no change to C7 / permit / permission matrix; no new capability.

## 2. Context Pack (verified against origin/main)

- Shell preflight: `domain_packs/developer_agent/workspace_capability.py` `_preflight_shell`
  (exact allowlist, free-text denial) and `_preflight_run_tests`.
- Public preflight entry: `DeveloperWorkspaceAdapter.preflight(capability_id, args, action_key)`.
- Trusted profile: `agent_os_core/trusted_commands.py` `TRUSTED_SHELL_PROFILE_V1`
  (pytest / python -m pytest / git status|diff|log / ruff check) — must classify clean.
- Denial precedent: `CapabilityEffectUnknown` carries a `reason_code` (so a typed denial
  with `reason_code` is consistent with the codebase).
- `CapabilityDenied` is a `PermissionError`; the existing allowlist message is preserved.

## 3. Architecture Brief

```text
workspace.shell args -> DeveloperWorkspaceAdapter._preflight_shell
  -> classify_dangerous_command(command)         # new, runs FIRST
       if matches: raise ShellCommandDenied(DANGEROUS_PATTERN, classes=...)
  -> exact-match allowlist
       if miss:    raise ShellCommandDenied(NOT_IN_ALLOWLIST)
  -> timeout parse
```

- New module `domain_packs/developer_agent/dangerous_command.py` (domain pack, not
  os_core — shell semantics stay out of the domain-independent kernel).
- `DangerousCommandClass` (7 bounded classes) + `ShellDenialReason` (2) + `ShellCommandDenied`.

## 4. CTO gate conditions (assigned by the CTO cast)

| # | Condition | Landing |
|---|---|---|
| 1 | The classifier runs BEFORE the allowlist (defense-in-depth, not just a nicer message) | `_preflight_shell` |
| 2 | Every shell denial carries an enumerable `reason_code` | `ShellCommandDenied` |
| 3 | A dangerous command is refused EVEN IF allowlisted (bypass-detecting RED test) | `test_dangerous_command_is_denied_even_when_allowlisted` |
| 4 | The classifier is not constant and does not flag the trusted profile | parametrised tests |
| 5 | No false confidence: documented as a classifier, not isolation; no sandbox claim | module docstring + this packet |
| 6 | New file explicitly added to `[tool.pyright].include` | `pyproject.toml` |

## 5. Verification

- `tests/product/test_dangerous_command.py`: 31 tests, all pass.
- Adjacent shell/security suites: 106 passed.
- Full `tests/product` (minus tui): 24 failed == base `18d7b9b0` exactly (22 deterministic
  env/date failures + 2 flaky; verified with the diff stashed).
- Ruff: clean on all changed files. Pyright: 0 on the new module + changed file; the
  configured run is 118 errors at base and 118 with the change (zero new).

## 6. Residual / honesty

- The classifier is heuristic and incomplete by design; it is an additional deny layer,
  never a guarantee, never isolation. An unlisted benign command is still denied by the
  allowlist (fail-closed), so the classifier's marginal effect is on *allowlisted*
  dangerous commands and on the enumerable reason code.
- Independent exact-diff review is still required before this slice is promotable.
