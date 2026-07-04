# PR-15 Controlled Pilot RC Branch Record (2026-07-04)

- Status: RC branch pushed under founder authorization / no origin/main push / no release
- Layer: deployment / Phase-1 controlled-pilot release-candidate handoff
- Verified local head: `943defde786c633ea4273c636c260aefb75b2c77`
- RC branch: `rc/phase-1-controlled-pilot-20260704`
- RC branch head: `b8834a644018e070e372be149fb758a928c7a242`
- Remote main head: `dba87bc35ae2c7be3dfbcc022c64c0a04cbf9171`

## Decision Boundary

Founder authorization allowed pushing the current verified candidate to a remote
RC branch for Phase-1 controlled-pilot closure preparation.

This did not authorize:

- pushing `origin/main`;
- creating a formal release tag;
- publishing external release or product claims;
- enabling automatic R4/R5 business-action execution;
- expanding autonomous-core, G10, AGI, or RSI claims.

The executable `DEPLOYMENT_PUSH: HOLD` gate still blocks `origin/main` push and
formal release promotion.

## Observed Remote State

```bash
git ls-remote --heads origin 'rc/phase-1-controlled-pilot-20260704'
# b8834a644018e070e372be149fb758a928c7a242 refs/heads/rc/phase-1-controlled-pilot-20260704

git ls-remote --heads origin main
# dba87bc35ae2c7be3dfbcc022c64c0a04cbf9171 refs/heads/main

git ls-remote --tags origin | rg 'b8834a644018e070e372be149fb758a928c7a242|943defde786c633ea4273c636c260aefb75b2c77|refs/tags/(v|release|rc)' || true
# no matching release/rc tag output
```

## Candidate Verification Evidence

Before the RC branch push, the pushed candidate `b8834a6` was checked in an
isolated detached worktree:

```bash
make current-state-verification-check PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
```

Observed result: current-state verification passed, `make ci` passed with 627
primary unittest tests OK / 4 skipped plus 12 eval OK, and PostgreSQL
`ci-local-full` passed with the same 627 primary unittest tests OK / 4 skipped
plus 12 eval OK.

After local candidate-maintenance hardening, the current local line anchored by
verified ancestor `943defde786c633ea4273c636c260aefb75b2c77` passed:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python -m unittest tests.unit.test_current_state_verification_gate -v
make current-state-verification-check PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
make rc-branch-verification-check PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
make push-authorization-check PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
```

Observed result: focused current-state verification gate tests passed with 7
tests OK; `make current-state-verification-check` passed; `make
rc-branch-verification-check` passed against the remote RC branch, origin/main,
and release/rc tag state; `make push-authorization-check` exited 2 under
`DEPLOYMENT_PUSH: HOLD`, as expected for `origin/main` push; `make ci` passed
with 632 primary unittest tests OK / 4 skipped plus 12 eval OK; PostgreSQL
`ci-local-full` passed with the same 632 primary unittest tests OK / 4 skipped
plus 12 eval OK.

## Non-Claims

This RC branch record is not a release note and not a customer-facing claim. It
only records the controlled-pilot branch handoff boundary so later agents do not
confuse RC publication with `origin/main` promotion or formal release.
