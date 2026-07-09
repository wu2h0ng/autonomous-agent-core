# PR-33: Clean deployment push authorization (post-M9)

- Date: 2026-07-09
- Status: **Option A selected by founder/CTO (Active decision = HOLD; no origin/main push)**
- Supersedes for push-gate purposes: `PR-11-deployment-push-authorization-20260705.md`
- Evidence: `PR-31-m9-operator-walkthrough-verification-20260708.md`, `M9-OPERATOR-PILOT-LOG-20260708.md`, `PR-32-deployment-push-decision-m9-20260708.md`
- Why this record exists: PR-32 mixed Option-A HOLD example lines with an Active AUTHORIZED token, so `push_authorization_check` reports ambiguous decision tokens. This PR is the single clean decision file.

## Candidate under consideration

```text
origin/main tip (already published): fed54d620b70cca083bd3c43209c94d79e9bbead
pending local docs (uncommitted):   PR-15 remote-main refresh + CURRENT_STATE@fed54d6 alignment
```

If Option B is chosen for the next `origin/main` promotion, `candidate_head` must be updated to the **exact 40-character commit** that will be pushed (after the pending docs commit lands), then this Active decision flipped to AUTHORIZED with that hash only.

## Evidence summary

| Check | Status |
|-------|--------|
| Default pilot walkthrough | PASS (`trace-4a5db21ec92c`) |
| Staging C/D/E walkthrough | PASS (`trace-4adf8da2d7d4`) |
| Format-check drift | RESOLVED (`2cc86af`) |
| `make ci` | PASS at `fed54d6` + pending PR-15/CURRENT_STATE refresh |
| `make ci-local-full` | PASS recorded at `e11ebad`; re-run recommended before any new push |
| External GA | NOT authorized by this record |

## What Option A / B / C mean

These are **founder/CTO release-process choices**, not product features.

### Option A — Keep HOLD (safe default)

Meaning: do **not** authorize further `origin/main` pushes from this gate.

Effects if chosen:
- `make push-authorization-check` stays fail-closed (exit 2) — expected
- `make controlled-pilot-readiness-check` can stay green (it requires HOLD)
- No new remote promotion; continue Customer-0 rehearsal / docs hygiene only

You choose A if: evidence is enough for internal notes, but you do **not** want agents or humans to push `origin/main` yet.

### Option B — Authorize one `origin/main` push

Meaning: allow **one** promotion of a named commit to `origin/main`.

Effects if chosen:
- Active decision becomes a single AUTHORIZED token plus exactly one `candidate_head: <40-char-sha>`
- That SHA must match the commit being pushed
- Does **not** authorize release tags, external GA, default-on flags, or R4/R5 auto-exec
- After that push completes, flip back to HOLD (new PR) or issue a fresh AUTHORIZED binding for the next tip

You choose B if: you want the pending PR-15 / CURRENT_STATE (and this PR-33) committed and pushed to `origin/main`.

### Option C — RC tag pin (optional, independent of B)

Meaning: create a frozen POC pin tag, e.g. `rc/phase-1-internal-pilot-20260708`, on a named commit.

Effects if chosen:
- Does **not** by itself authorize `origin/main` push
- Useful for Customer-0 / staging pin
- Pushing the tag to remote still needs an explicit release/tag authorization (separate from DEPLOYMENT_PUSH)

You choose C if: you want a named RC pointer for pilot deploys. Can combine with A (tag only, no main push) or B (push then tag).

## Boundaries (unchanged regardless of A/B/C)

- No external GA / public product claim from this record
- No default-on staged-out feature flags in deployed environments
- R4/R5 automatic execution remains proposal-only unless tenant policy + flag + ADR-0012 review explicitly authorize a pilot profile
- Do not add more P1 feature slices under the controlled-pilot maintenance boundary

## Active decision (machine-readable; exactly one token line)

DEPLOYMENT_PUSH: HOLD

## How to flip to Option B (founder/CTO only)

1. Commit pending docs (`PR-15`, `CURRENT_STATE`, this file) so the tip SHA is known.
2. Edit **only** the Active decision section above:
   - Change the single Active token line from HOLD to AUTHORIZED (same `DEPLOYMENT_PUSH:` prefix; do not leave both as exact standalone lines in this file).
   - Add exactly one matching line: `candidate_head: <full-40-char-sha-of-the-commit-to-push>`.
   - Do not paste Option A/B examples as exact-line tokens elsewhere in this file (that is what made PR-32 ambiguous).
3. Point `scripts/release_gate/push_authorization_check.py` default decision file at this PR-33 (or pass `--decision-file` explicitly).
4. Run `make push-authorization-check` with `--expected-head` equal to that SHA; expect exit 0.
5. Push only that commit family to `origin/main`.
6. Immediately open a follow-up HOLD record (or restore HOLD here) so the next tip is not accidentally authorized.

## Option C tag template (not a DEPLOYMENT_PUSH token)

If founder/CTO also selects Option C after the pin commit exists:

```text
tag: rc/phase-1-internal-pilot-20260708
ref: <full-40-char-sha>
```

Tag creation/push remains a separate release gate; this section is documentation only.

## Prior records

- `PR-11-deployment-push-authorization-20260705.md` — HOLD after ADR-0013 push; still the default file for `push_authorization_check` until Makefile/default path is switched to PR-33
- `PR-32-deployment-push-decision-m9-20260708.md` — historical Option B/C intent at `e11ebad`, but ambiguous for the machine gate; do not use as the active decision file
