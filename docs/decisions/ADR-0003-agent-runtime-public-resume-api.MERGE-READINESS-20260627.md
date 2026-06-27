# ADR-0003 Merge Readiness: Agent Runtime Public Resume API

Date: 2026-06-27
Status: READY FOR FOUNDER/CTO LOCAL MERGE DECISION - NOT MERGE/PUSH/RELEASE AUTHORIZATION
Branch: `codex/agent-runtime-public-resume-api`
Target: deployment local `main`
Base before implementation: `main@69389a5`
Implementation head before readiness packet: `2a3150f`
Readiness packet commit: `497ce17`

Implementation commits before this readiness packet:

- `80fffdd feat(runtime): expose internal checkpoint resume API`
- `9b98286 fix(runtime): only expose persisted checkpoint refs`
- `12e0f53 docs(runtime): record public resume self-review`
- `2a3150f feat(runtime): type resume error contracts`

This packet is a merge-decision aid. It is not an independent review, not merge
authorization, not a push request, and not an external release claim.

## Readiness Verdict

The branch is ready for founder/CTO merge decision under these conditions:

1. fast-forward only;
2. local deployment `main` only;
3. no push and no release;
4. post-merge `make ci` and `ci-local-full` must pass on local `main`;
5. if founder/CTO requires independent review, obtain it before merge.

As checked before creating this packet, the implementation head was linear on
local `main`:

```text
git rev-list --left-right --count main...2a3150f
0 4

git merge-base --is-ancestor main 2a3150f
exit 0
```

The readiness packet itself is docs-only. Re-run the same fast-forward checks
immediately before any founder/CTO-authorized merge instead of relying on this
record as a live branch-state assertion.

## Scope To Merge

The branch adds the internal-only public resume API for checkpointed
`POST /runs` execution:

- `POST /runs` internal responses include `runtime_checkpoint_ref` only when a
  matching persisted checkpoint exists;
- external report-key `POST /runs` projections force `runtime_checkpoint_ref =
  null`;
- `POST /agent-runtime/runs/{runtime_run_id}/resume` requires the internal
  `runtime:resume` scope;
- resume rechecks `RuntimePolicyGate` before checkpoint return;
- resume validates the original call, context, and tool fingerprints;
- successful resume returns a safe `RuntimeResumeResponse.output_ref`;
- successful resume appends safe checkpoint resume events to the business
  `RunTrace`;
- resume failure statuses `404`, `409`, `500`, and `503` declare a typed
  `RuntimeResumeErrorResponse` OpenAPI schema;
- missing store, missing checkpoint, mismatched trace id, mismatched call args,
  and paused shell fail closed.

## Runtime Objective Coverage

| Objective item | Merge evidence | Boundary |
|---|---|---|
| Typed runtime/API contract | `RuntimeCheckpointRef`, `RuntimeResumeRequest`, `RuntimeResumeResponse`, `RuntimeResumeOutputRef`, `AgentRunContext`, `AgentToolCall`, and `AgentToolResult` are used on the HTTP route and runtime boundary. | No new business-truth authority in Agent Runtime. |
| Principal/scope boundary | `runtime:resume` exists only on the internal API principal; external report and operator principals do not receive it. | This is not full RBAC or tenant isolation. |
| Recoverable checkpoint ref | `POST /runs` emits a resume ref only after the checkpoint store proves a matching persisted checkpoint with a stored result. | No ref is emitted for an unconfigured or failed checkpoint store. |
| Policy gate on resume | `resume_from_checkpoint` resolves the tool spec and calls `RuntimePolicyGate` before reading and returning checkpoint data. | Paused shell and missing permission deny before checkpoint return. |
| Replay safety | Resume validates call/context/tool-spec fingerprints and fails closed on mismatch. | Resume never reruns the Trusted Loop body. |
| Trace/output safety | Resume output is projected to `output_ref`; runtime trace events are allowlisted. | No raw args, raw SQL, raw tool output, connector payloads, or caller-supplied secret-like trace ids are exposed. |
| API error contract | OpenAPI declares `RuntimeResumeErrorResponse` for `404`, `409`, `500`, and `503`. | This does not make the route external-release ready. |
| Trusted Loop / EvidenceChain / Approval path | The original checkpointed result is from the existing `TrustedLoopRuntime.evaluate` path, with SQL Safety and EvidenceChain already in the run. | Resume itself is recoverability, not new analysis/action execution. |
| Failure-first tests and evals | Branch tests cover no-store ref omission, external-report denial, paused resume denial, mismatch fail-closed behavior, no rerun, safe trace append, and OpenAPI contract. Full `make ci` and `ci-local-full` passed on the current branch while preparing this packet. | Post-merge CI is still required on local `main`. |

## Evidence Records

- Implementation log: `ADR-0003-agent-runtime-public-resume-api.IMPLEMENTATION-20260627.md`
- Self-review: `ADR-0003-agent-runtime-public-resume-api.SELF-REVIEW-20260627.md`
- Capability gap audit: `ADR-0003-agent-runtime-capability-gap-audit-20260626.md`
- Live handoff: `docs/CURRENT_STATE.yaml`

Fresh branch-local verification after this packet was written:

```text
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
```

Result: ruff clean, format clean, `502` primary unittest tests OK with `4`
skipped, `12` eval tests OK, OpenAPI drift check passed, and
`=== All CI checks passed ===`.

```text
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
```

Result: full local CI parity passed with `502` primary unittest tests OK, `12`
eval tests OK, OpenAPI up to date, and
`=== Full local CI parity checks passed ===`.

## Required Post-Merge Commands

If founder/CTO authorizes local merge, use a fast-forward merge only and then
run:

```bash
git switch main
git merge --ff-only codex/agent-runtime-public-resume-api
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
```

Do not push or release as part of this merge gate.

## Stop Conditions

Stop before merge if any of these become true:

- `git merge --ff-only` would not fast-forward cleanly.
- Local `main` moves and changes `http_app.py`, `AgentRuntime`,
  `RuntimePolicyGate`, `TrustedLoopAgentRuntimeAdapter`, checkpoint stores,
  `RunTrace`, HTTP auth, OpenAPI generation, SQL Safety, EvidenceChain, or
  approval behavior.
- The branch requires conflict resolution.
- The route would expose resume to `external_report` or operator principals.
- `POST /runs` would return `runtime_checkpoint_ref` without a proven persisted
  checkpoint.
- Resume would return raw args, raw SQL, raw tool output, connector payloads, or
  caller-supplied secret-like trace ids.
- Resume would rerun `TrustedLoopRuntime.evaluate`.
- Resume would bypass `RuntimePolicyGate`.
- Post-merge `make ci` or `ci-local-full` fails.

If any stop condition is hit, return to implementation/review instead of
merging, pushing, or claiming completion.

## Non-Claims

This branch does not prove autonomous intelligence, does not implement the
autonomous-core object layer, does not replace Trusted Loop, does not make Agent
Runtime a workflow engine, does not implement wall-clock interruption,
streaming cancellation, workflow concurrency semantics, production telemetry
export, full RBAC/DLP, tenant isolation, external release readiness, or
automatic R4/R5 business action execution.

## Gate Outcome

Outcome: READY FOR EXPLICIT FOUNDER/CTO LOCAL MERGE DECISION.

Keep the branch unmerged, unpushed, and unreleased unless explicitly
authorized. If merged locally, record post-merge verification before any later
push or release discussion.
