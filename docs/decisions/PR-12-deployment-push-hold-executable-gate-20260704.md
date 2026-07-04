# PR-12 Deployment Push-Hold Executable Gate (2026-07-04)

- Status: implemented locally / no push authorization / no release
- Layer: deployment / governed data-agent OS
- Current decision consumed: `DEPLOYMENT_PUSH: HOLD`
- Scope: local release/push discipline tooling, not product runtime behavior

This record adds a small executable gate for the current deployment push-hold
decision. It turns the existing PR-10 decision into a local fail-closed command
so local CI completeness cannot be mistaken for push authorization.

## Implemented Surface

- `scripts/release_gate/push_authorization_check.py`
- `make push-authorization-check`
- `tests/unit/test_push_authorization_gate.py`

The script is read-only. By default it reads:

- `docs/decisions/PR-10-deployment-push-hold-decision-20260704.md`

Behavior:

- `DEPLOYMENT_PUSH: HOLD` -> non-zero exit and "push is not authorized".
- `DEPLOYMENT_PUSH: AUTHORIZED` -> zero exit.
- `DEPLOYMENT_PUSH: AUTHORIZED` plus `PUSH_EXPECTED_HEAD=<hash>` -> zero only
  when the decision record also contains `candidate_head: <hash>`.
- Authorized decision with mismatched `candidate_head` -> non-zero exit.
- Missing decision token or conflicting HOLD/AUTHORIZED tokens -> non-zero
  exit.

The target is intentionally not part of `make ci`, because current HOLD should
block push attempts without making ordinary local verification impossible.

## Verification

TDD evidence:

- RED: `tests.unit.test_push_authorization_gate` failed because the script and
  Makefile target did not exist.
- GREEN: the focused suite passed after adding the script and target.
- FOLLOW-UP RED: a decision record containing both HOLD and AUTHORIZED tokens
  was incorrectly accepted.
- FOLLOW-UP GREEN: conflicting HOLD/AUTHORIZED tokens now fail closed with an
  ambiguous-decision message.

Commands:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python -m unittest tests.unit.test_push_authorization_gate -v
make push-authorization-check PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
make push-authorization-check PUSH_EXPECTED_HEAD="$(git rev-parse --short HEAD)" PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
```

Observed results:

- Focused gate tests: 6 tests OK.
- `make push-authorization-check`: exits 2 under current HOLD with
  `DEPLOYMENT_PUSH: HOLD - push is not authorized.`
- `make push-authorization-check PUSH_EXPECTED_HEAD=<current-head>`: still
  exits 2 under current HOLD, proving HOLD remains the primary blocker even
  when a candidate head is supplied.
- `make ci`: passed with ruff clean, format clean, 615 primary unittest tests
  OK / 4 skipped, 12 eval tests OK, threshold report passed, and OpenAPI up to
  date.
- PostgreSQL `ci-local-full`: passed with 615 primary unittest tests OK / 4
  skipped, 12 eval tests OK, threshold report passed, OpenAPI up to date, and
  full local CI parity checks passed.

## Non-Claims

This gate does not:

- push to `origin/main`;
- authorize release or deployment;
- change product runtime behavior;
- replace founder/CTO push authorization;
- prove production environment readiness;
- create autonomous-core / G10 / AGI / RSI evidence.
