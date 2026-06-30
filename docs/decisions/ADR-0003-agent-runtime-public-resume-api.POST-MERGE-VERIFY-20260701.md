# ADR-0003 Public Resume API Post-Merge Verification

Date: 2026-07-01
Status: LOCAL MAIN POST-MERGE VERIFICATION - NOT PUSHED/RELEASED
Repo: `ai-native-business-data-agent-os`
Merged branch: `codex/agent-runtime-public-resume-api`
Deployment local main head: `31d8ea7 docs(runtime): refresh public resume verification`

## Scope

Founder authorization allowed the branch-local public resume API stack to be
fast-forward merged into deployment local `main`. This record captures the
post-merge state correction and verification boundary.

The merged local-main capability remains internal-only:

- `POST /agent-runtime/runs/{runtime_run_id}/resume`;
- `runtime:resume` scope on the internal API principal only;
- internal `POST /runs` `runtime_checkpoint_ref` projection only when a
  matching checkpoint is actually persisted;
- external report-key omission and management-surface denial;
- checkpoint fingerprint validation before current `RuntimePolicyGate` recheck;
- mismatch-visible `CHECKPOINT_MISMATCH` before paused-shell policy denial;
- matching paused resumes still fail closed with `DENY_PAUSED`;
- safe resume `output_ref` and safe RunTrace checkpoint-resume append;
- typed OpenAPI error contracts for `404`, `409`, `500`, and `503`;
- typed `CHECKPOINT_READ_FAILED` for checkpoint backend read failures in both
  the HTTP route and `AgentRuntime.resume_from_checkpoint(...)`.

This merge does not authorize push, release, external API shipment, workflow
replacement, wall-clock preemption, automatic R4/R5 execution, or any
autonomous-core evidence claim.

## Merge

```bash
git merge --ff-only codex/agent-runtime-public-resume-api
```

Observed on 2026-07-01:

- deployment local `main` advanced from `8556efc` to `31d8ea7`;
- merge was fast-forward only;
- no push;
- no release.

## Post-Merge Verification

```bash
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
```

Observed on 2026-07-01:

- ruff clean;
- formatting clean (`114 files already formatted`);
- primary unittest discovery: 505 tests OK, 4 skipped;
- eval suite: 12 tests OK;
- OpenAPI snapshot up to date;
- `=== All CI checks passed ===`.

```bash
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python3
```

Observed on 2026-07-01:

- ruff clean;
- formatting clean (`114 files already formatted`);
- primary unittest discovery: 505 tests OK;
- eval suite: 12 tests OK;
- OpenAPI snapshot up to date;
- `=== Full local CI parity checks passed ===`.

## Boundary

Deployment local `main` now contains the public resume API stack, but
`origin/main` is not updated. Push, release, external exposure, independent
review substitution, production telemetry policy, true interruption/cancellation,
concurrency/workflow runtime semantics, and autonomous-core adoption remain
separate gates.
