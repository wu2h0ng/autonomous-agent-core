# ADR-0003 Merge Readiness: Agent Runtime Correction Channel

Date: 2026-06-27
Status: MERGE-READY EVIDENCE PACKET - NOT AUTHORIZATION
Branch: `codex/agent-runtime-correction-channel`
Target: deployment local `main`
Base before implementation: `main@dba87bc`
Implementation commits before this readiness packet:

- `1c36bd4 feat(runtime): route correction channel through runtime envelope`
- `2835a9b fix(runtime): preserve correction writes on checkpoint failure`

This packet is a merge-decision aid. It is not founder/CTO authorization, not
an independent review, not a push request, and not an external release claim.

## Readiness Verdict

The branch is ready for founder/CTO merge decision if the intended merge is:

1. fast-forward only;
2. local deployment `main` only;
3. followed by post-merge `make ci` and `ci-local-full`;
4. not pushed, released, or described as externally shipped without a later
   release gate.

As checked before creating this packet, the branch was linear on local `main`:

```text
git merge-base --is-ancestor main HEAD
git rev-list --left-right --count main...HEAD
0 2
```

After this readiness packet is committed, the ahead count is expected to
increase by one docs-only commit while preserving fast-forward eligibility.

## Scope To Merge

The branch adds the correction-channel runtime envelope for:

- `POST /outcomes`
- `POST /adoptions`
- `TrustedLoopCorrectionRuntimeAdapter`
- narrow correction-channel `RuntimePolicyGate` side-effect allowance
- post-write checkpoint-failure semantics for completed correction writes
- branch-local review and docs-state synchronization

It does not add public resume API, workflow-engine semantics, wall-clock
preemption, production telemetry export, automatic R4/R5 execution, external
agent framework dependency, or autonomous-core import.

## Runtime Objective Coverage

| Objective item | Merge evidence | Boundary |
|---|---|---|
| Typed run/tool/result/policy contracts | `AgentRunContext`, `ToolSpec`, `AgentToolCall`, `AgentToolResult`, and `PolicyDecision` are used on both correction routes. | No new business-truth authority in Agent Runtime. |
| Pre-execution policy gate | Missing runtime permission and paused shell tests deny before feedback/adoption writes. | HTTP auth remains separate from runtime permission. |
| Correction channel | `/outcomes` and `/adoptions` enter through request-scoped runtime adapters before existing services. | Self-report feedback cannot become external adoption. |
| Trace-safe envelope | Safe `agent_runtime.*` events persist only allowlisted metadata. | No raw metric deltas, causal payloads, secrets, or full feedback/adoption payloads. |
| Checkpoint/replay/recovery | Correction adapters receive the factory-selected checkpoint store; completed correction writes use explicit `preserve_result_on_checkpoint_failure`; checkpoint replay mismatch tests block authority swap. | Default runtime checkpoint failures still return `checkpoint_error`. |
| Permission and risk ceiling | Correction tools declare scoped permissions and risk `R1`/`R2`. | R4/R5 non-proposal execution remains denied before tool body. |
| Action proposal vs execution | No change to R4/R5 proposal-only policy. | Correction writes are not business action execution. |
| Trusted Loop / EvidenceChain / Approval / Trace path | Existing Trusted Loop services, feedback store, adoption ingest, knowledge promotion, and run trace persistence are called rather than bypassed. | SQL Safety and Approval semantics are not weakened or replaced. |
| Failure-first tests and evals | Branch tests cover bypass, pause, missing permission, trace safety, checkpoint failure, and replay mismatch; full `make ci` and `ci-local-full` passed before this packet. | This packet adds docs only and must not be used as a substitute for post-merge CI. |

## Required Post-Merge Commands

Run these from `/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os`
after explicit founder/CTO merge authorization:

```bash
git switch main
git merge --ff-only codex/agent-runtime-correction-channel
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
AGENT_OS_DATABASE_URL=postgresql+psycopg://mima1234@127.0.0.1:5432/agent_os_test make ci-local-full PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
```

Do not push or release as part of this merge gate.

## Stop Conditions

Stop before merge if any of these become true:

- `git merge --ff-only` would not fast-forward cleanly.
- A newer local `main` changes `AgentRuntime`, `RuntimePolicyGate`,
  `http_app.py`, `outcome_service.py`, `TrustedLoopRuntime`, approval,
  EvidenceChain, SQL Safety, trace, or checkpoint behavior.
- The branch requires conflict resolution.
- The branch requires `AgentRuntime` or `TrustedLoopRuntime` to hold
  `AdoptionIngest`.
- Correction-channel policy must broadly permit arbitrary non-read side
  effects.
- Trace/checkpoint surfaces need raw metric deltas, causal-attribution details,
  adoption payloads, SQL, connector payloads, or secrets.
- Post-merge `make ci` or `ci-local-full` fails.

If any stop condition is hit, return to review instead of merging, pushing, or
claiming completion.

## Non-Claims

This branch does not prove autonomous intelligence, does not implement the
autonomous-core object layer, does not replace Trusted Loop, does not make
Agent Runtime a workflow engine, does not ship a product release, and does not
authorize automatic R4/R5 business action execution.

## Gate Outcome

Outcome: READY FOR EXPLICIT FOUNDER/CTO MERGE DECISION.

Required next step: founder/CTO explicitly authorizes or rejects local
fast-forward merge. Until that happens, keep the branch unmerged and unpushed.
