# PR-14 CURRENT_STATE Verification Gate (2026-07-04)

- Status: implemented and verified locally / no push authorization / no release
- Layer: deployment / release-candidate maintenance tooling
- Verified local head: `6f233eb`
- Scope: read-only verification of deployment truth-source references

This record adds a local fail-closed verifier for `docs/CURRENT_STATE.yaml`
verification-source freshness. It prevents a later agent from treating a stale
or missing `last_verified_*` source as current truth.

## Implemented Surface

- `scripts/release_gate/current_state_verification_check.py`
- `make current-state-verification-check`
- `tests/unit/test_current_state_verification_gate.py`

The verifier is read-only. It checks that:

- `docs/CURRENT_STATE.yaml` can be parsed as a YAML mapping;
- `last_verified_tests.source` and `last_verified_eval.source` are present and
  equal;
- the referenced source path stays inside the repository root;
- the referenced source values are strings;
- the referenced verification source file exists;
- the source file declares a `Verified local head: <hash>` marker;
- when run inside a git checkout, the declared verified head is an ancestor of
  the current `HEAD`.

The Make target is intentionally not part of normal `make ci`; it is a
release-candidate maintenance gate, like `make push-authorization-check`.

## TDD Evidence

- RED: `tests.unit.test_current_state_verification_gate` failed because
  `scripts/release_gate/current_state_verification_check.py` did not exist.
- GREEN: the verifier passes on the current repository state and fails closed
  when `CURRENT_STATE` points to a missing verification source.
- FOLLOW-UP RED: the Makefile did not expose a stable
  `current-state-verification-check` target.
- FOLLOW-UP GREEN: the Make target now invokes the verifier and remains outside
  the normal `ci` target.
- FOLLOW-UP RED: an absolute verification source path was only treated as a
  missing file, not as an invalid outside-repository source.
- FOLLOW-UP GREEN: absolute paths and `..` path traversal are rejected before
  file existence checks.
- FOLLOW-UP RED: a non-string `last_verified_*` source produced a Python
  traceback instead of a controlled fail-closed message.
- FOLLOW-UP GREEN: non-string source values fail closed without traceback.
- FOLLOW-UP COVERAGE: tests now cover `last_verified_tests.source` and
  `last_verified_eval.source` mismatch fail-closed behavior.
- FOLLOW-UP COVERAGE: tests now cover a referenced verification record that
  exists but does not declare a `Verified local head` marker.

## Commands

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src /Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python -m unittest tests.unit.test_current_state_verification_gate -v
make current-state-verification-check PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
make push-authorization-check PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
```

## Observed Results

- Focused current-state verification gate tests: 7 tests OK.
- `make current-state-verification-check`: passed and confirmed
  `docs/decisions/PR-13-deployment-current-docs-head-verification-refresh-20260704.md`
  exists and declares verified head `7a4f391`.
- `make push-authorization-check`: exits 2 under the current
  `DEPLOYMENT_PUSH: HOLD` decision with `push is not authorized`; the Make
  target binds `--expected-head` to `6f233eb10a71fa0ca1385fea895c065f8c9ab5e0`.
- `make ci`: passed with 628 primary unittest tests OK / 4 skipped, 12 eval
  tests OK, threshold report passed, and OpenAPI contract up to date.
- PostgreSQL `ci-local-full`: passed with 628 primary unittest tests OK / 4
  skipped, 12 eval tests OK, threshold report passed, OpenAPI contract up to
  date, and full local CI parity checks passed.

## Non-Claims

This gate does not:

- push to `origin/main`;
- authorize release or deployment;
- change product runtime behavior;
- create new P1 product surface;
- expand autonomous-core / G10 / AGI / RSI claims.
