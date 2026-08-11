# PR-32: M9 deployment push / RC tag decision packet

- Date: 2026-07-08
- Status: **Founder/CTO authorized (Option B + Option C)**
- Evidence: `PR-31-m9-operator-walkthrough-verification-20260708.md`, `M9-OPERATOR-PILOT-LOG-20260708.md`

## Current candidate head

```text
candidate_head: e11ebadaf955bc51c1911acb1dc7b0236787af91
origin/main:    e11ebadaf955bc51c1911acb1dc7b0236787af91 (M8 pushed)
```

## M9 evidence summary

| Check | Status |
|-------|--------|
| Default pilot walkthrough | PASS |
| Staging C/D/E walkthrough | PASS |
| M8 compose E2E (prior) | PASS @ M8 commit |
| `make ci-local-full` | PASS — format-check drift fixed |
| Internal pilot loop demonstrable | YES |

## Decision options (founder/CTO)

### Option A — Continue HOLD (recommended default)

```text
DEPLOYMENT_PUSH: HOLD
```

- No additional `origin/main` promotion claims
- No release/RC tag
- Continue Customer-0 operator rehearsal and fix format-check drift before lift

### Option B — Authorize promotion record (not executed by this packet)

```text
DEPLOYMENT_PUSH: AUTHORIZED
candidate_head: e11ebadaf955bc51c1911acb1dc7b0236787af91
```

Requires:
1. Green `make ci-local-full` at candidate head
2. Explicit founder/CTO authorization line in a new PR record (supersedes PR-11 HOLD scope for next push only)
3. Still no external GA claim without separate release gate

**Founder/CTO authorization:** Option B is authorized for candidate head `e11ebadaf955bc51c1911acb1dc7b0236787af91`. The next `origin/main` promotion may proceed under this PR-32 record, subject to the separate release gate for any external GA claim.

### Option C — RC tag for POC pin (optional, separate from push authorization)

```text
tag: rc/phase-1-internal-pilot-20260708
ref: e11ebadaf955bc51c1911acb1dc7b0236787af91
```

- Does not by itself change `DEPLOYMENT_PUSH`
- Useful for frozen POC deployments
- Requires explicit release authorization to push tag to remote

## Active decision (until superseded)

```text
DEPLOYMENT_PUSH: AUTHORIZED
candidate_head: e11ebadaf955bc51c1911acb1dc7b0236787af91
```

Prior record: `PR-11-deployment-push-authorization-20260705.md` (HOLD after ADR-0013 push @ `89c2e9b`).

PR-32 supersedes PR-11 for candidate head `e11ebad`: format-check drift is resolved, operator walkthrough evidence is recorded, and the founder/CTO has explicitly authorized Option B. No external GA claim is made.

## RC branch note

`rc/phase-1-controlled-pilot-20260704` @ `b8834a6` remains historical handoff. Creating Option C tag on `e11ebad` is cleaner for new POC pins than advancing the old RC branch.
