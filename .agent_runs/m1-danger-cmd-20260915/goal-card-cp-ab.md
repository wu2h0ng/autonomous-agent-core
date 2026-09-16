# Goal Card + CP/AB + CTO gate — S1 TYPED ENUMERABLE SHELL DENIAL (DESCOPED)

> Status: `DESCOPED_2026-09-15 / TYPED_ENUMERABLE_DENIAL_ONLY / FINAL_REVIEW_APPROVE_WITH_CHANGES`
> Track: Product Track (low risk after descope: adds a typed denial, no behaviour change).
> Cast: P2-7 M1 route = A (finish M1 kernel), target = Python core, first slice = S1.
> Base: `origin/main` @ `18d7b9b0`; branch `feature/m1-dangerous-command-classification-20260915`.
> Claim ceiling: no parity / Alpha / Autonomy(S,E,O,V,T) / release claim.

## 1. Descope (founder, 2026-09-15)

The original S1 shipped a **regex dangerous-command classifier**. Three same-model
exact-diff reviews found it brittle (wrapper/quoted/bypass forms) and, worse, that it
introduced **catastrophic backtracking (ReDoS) on the product shell path**. The
classifier was REMOVED. A sound dangerous-command classifier needs a real token parser
behind its own gate — not regex-on-string — and is deferred.

## 2. What S1 actually ships

`domain_packs/developer_agent/shell_denial.py`:

- `ShellDenialReason` (only `NOT_IN_ALLOWLIST`) — enumerable, machine-consumable.
- `ShellCommandDenied` — a `CapabilityDenied` (hence `PermissionError`) subtype.
- `require_allowlisted_command()` — exact-match allowlist enforcement used by **both**
  the shell preflight and the execution sites (`_shell`, `_run_tests`).

Behaviour is otherwise **byte-identical to the pre-existing exact-match allowlist**
(same normalisation, membership, messages). No authority/permission/C7 change; no
capability; no event/storage.

## 3. Why this is worth shipping

- The denial is now typed/enumerable so a harness can consume the reason (previously a
  bare `CapabilityDenied` with free text).
- The allowlist is enforced at the execution site too, so reaching execution without a
  preflight pass cannot bypass it.

## 4. CTO gate conditions (assigned by the CTO cast)

| # | Condition | Landing |
|---|---|---|
| 1 | Every shell denial carries an enumerable `reason_code` | `ShellCommandDenied` |
| 2 | Enforced at BOTH the preflight and the execution sites | `require_allowlisted_command` |
| 3 | Still a `CapabilityDenied`/`PermissionError` subtype; message preserved | `ShellCommandDenied` |
| 4 | No regex/backtracking on the shell path (no ReDoS) | module has no `re` |

## 5. Verification

- `tests/product/test_shell_denial.py` (8): allowlisted passes; unlisted denied with
  `NOT_IN_ALLOWLIST`; subtype; machine-consumable after the rewrite; execution-site
  denial; `run_tests` execution-site denial; helper raises the typed denial.
- Adjacent shell/security suites 82 pass. Full `tests/product` == base, zero new.
- Ruff clean; pyright 0 on changed files.

## 6. Residual / honesty

- No dangerous-command classification exists after the descope; the exact-match allowlist
  remains the sole check (it fail-closes everything unlisted). A real classifier is
  deferred to its own gate.
- Final review (same-model, 2026-09-15) returned APPROVE_WITH_CHANGES whose only MEDIUM
  was this file's stale body, now rewritten.
