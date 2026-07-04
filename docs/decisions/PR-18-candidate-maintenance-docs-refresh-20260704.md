# PR-18 Candidate Maintenance Docs Refresh (2026-07-04)

- Status: verified locally / origin/main push remains HOLD / no release
- Layer: deployment / release-candidate maintenance documentation
- Verified local head: `201d582d2706212b238f33ced8f8a08e1eb4bd8c`

This record refreshes the release-candidate maintenance documentation anchor
after two docs-only commits on top of PR-17:

- `2c576a6` indexed the controlled-pilot RC records in
  `docs/decisions/README.md`.
- `201d582` documented the candidate maintenance gates in `README.md`.

These changes only improve source-of-truth discoverability. They do not change
product runtime behavior, release authorization, branch publication, tag state,
or R4/R5 execution boundaries.

## Verified Surface

- `README.md`
- `docs/decisions/README.md`
- `docs/CURRENT_STATE.yaml`
- `docs/decisions/PR-15-controlled-pilot-rc-branch-20260704.md`
- `scripts/release_gate/current_state_verification_check.py`
- `scripts/release_gate/rc_branch_verification_check.py`
- `scripts/release_gate/push_authorization_check.py`

## Commands

```bash
make current-state-verification-check PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
make rc-branch-verification-check PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
make push-authorization-check PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
git ls-remote origin refs/heads/rc/phase-1-controlled-pilot-20260704 refs/heads/main refs/tags/release/phase-1-controlled-pilot-20260704 refs/tags/rc/phase-1-controlled-pilot-20260704
```

## Observed Results

- `make current-state-verification-check`: passed against PR-17 before this
  refresh, confirming `bfcc0ce22e57a0d21242a35dd3cba15ab4bb51ab` is still an
  ancestor of current HEAD.
- `make rc-branch-verification-check`: passed and confirmed remote RC branch
  `rc/phase-1-controlled-pilot-20260704` at
  `b8834a644018e070e372be149fb758a928c7a242`, remote main at
  `dba87bc35ae2c7be3dfbcc022c64c0a04cbf9171`, and no release/rc tag.
- `make push-authorization-check`: exited 2 under `DEPLOYMENT_PUSH: HOLD` for
  current head `201d582d2706212b238f33ced8f8a08e1eb4bd8c`, preserving the
  origin/main promotion block.

## Non-Claims

This refresh does not:

- change product runtime behavior;
- push to `origin/main`;
- create a release tag;
- publish an external release or customer-facing claim;
- enable automatic R4/R5 business-action execution;
- expand autonomous-core, G10, AGI, or RSI claims.
