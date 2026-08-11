# ADR-0003 Public Resume API Post-Verify

Date: 2026-06-28
Status: BRANCH-LOCAL VERIFIED - NOT MERGED/PUSHED/RELEASED
Repo: `ai-native-business-data-agent-os`
Branch: `codex/agent-runtime-public-resume-api`
Verified head: `d269822 docs(runtime): clarify public resume readiness head`

## Scope

Fresh verification of the branch-local Agent Runtime public resume API slice:

- internal-only `POST /agent-runtime/runs/{runtime_run_id}/resume`
- `runtime:resume` scope on the internal API principal only
- persisted-checkpoint `runtime_checkpoint_ref` projection from `POST /runs`
- external-report-key omission of `runtime_checkpoint_ref`
- `RuntimePolicyGate` recheck before checkpoint return
- fingerprint mismatch fail-closed behavior without Trusted Loop re-execution
- safe resume `output_ref` and safe RunTrace checkpoint-resume append
- typed OpenAPI error contracts for `404`, `409`, `500`, and `503`

This record is verification evidence only. It is not merge authorization, push
authorization, independent review, external release, wall-clock interruption,
workflow concurrency semantics, full RBAC/DLP, or an autonomy claim.

## Verification

```bash
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
```

Observed on 2026-06-28:

- ruff clean
- formatting clean (`114 files already formatted`)
- primary unittest discovery: `502` tests OK, `4` skipped
- eval suite: `12` tests OK
- OpenAPI snapshot up to date
- `=== All CI checks passed ===`

```bash
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test \
make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
```

Observed on 2026-06-28:

- ruff clean
- formatting clean (`114 files already formatted`)
- primary unittest discovery: `502` tests OK, `4` skipped
- eval suite: `12` tests OK
- OpenAPI snapshot up to date
- `=== Full local CI parity checks passed ===`

## Merge Boundary

The branch remains local after verification. Before any deployment local-main
merge, require explicit founder/CTO authorization and re-run the fast-forward
check immediately before merging. If founder/CTO requires independent review,
obtain it before merge. Push and external release remain separate gates.
