# ADR-0003 Agent Runtime A7 Reconciliation Audit

- Date: 2026-06-25
- Scope: OS repo finalization-debt audit before `codex/agent-runtime-live-wiring`
- Branch carrying this audit: `codex/runtime-checkpoint-trace-security`
- Status: audit only; no merge, no push, no release claim

## Purpose

The runtime live-wiring packet must not start from a collision field. This audit classifies the current `ai-native-business-data-agent-os` unmerged branch/worktree state so the next runtime branch can start from a clean, founder-approved base.

This audit is limited to the deployment-layer Agent Runtime work. It does not authorize Workbench, autonomous-core, release, or product-integration merges.

## Evidence Snapshot

Commands inspected on 2026-06-25:

- `git status --short --branch`
- `git worktree list --porcelain`
- `git branch --no-merged main --format="%(refname:short)"`
- `git branch --merged main --format="%(refname:short)"`
- `git rev-list --left-right --count main...<branch>`
- `git diff --name-only main...<branch>`
- `git log --oneline main..<branch>`

Observed state:

- `main` is clean at `77c7b07` and is ahead of `origin/main` by 6 commits.
- 16 OS worktrees exist, including the main worktree.
- All inspected OS worktrees are clean.
- 12 branches are not merged into `main`.
- `codex/agent-runtime-v0-trusted-substrate` is already merged into `main`.
- `codex/runtime-checkpoint-trace-security` is a pure forward branch from `main`: left/right count `0 6`.
- `codex/runtime-durable-checkpoint-store` is a pure forward branch from `main`: left/right count `0 4`.
- `codex/runtime-durable-checkpoint-store` is an ancestor of `codex/runtime-checkpoint-trace-security`.

## Classification

`L/R` below means `git rev-list --left-right --count main...branch`, where `L` is commits only on `main` and `R` is commits only on the branch.

| Branch | L/R | Packet A collision surface | Recommendation | Rationale |
|---|---:|---|---|---|
| `codex/runtime-checkpoint-trace-security` | `0/6` | Direct: `agent_runtime`, checkpoint persistence, trace, docs | **LAND candidate after review gate** | Contains the full local runtime hardening stack: durable checkpoint store, checkpoint failure typing, R4/R5 proposal-only policy, case-insensitive trace redaction, checkpoint resume trace events. Because `main` is an ancestor, merge mechanics are simple FF after approval. |
| `codex/runtime-durable-checkpoint-store` | `0/4` | Direct: `agent_runtime`, checkpoint persistence, docs | **SUPERSEDE / abandon after trace-security lands** | This branch is a prefix of `codex/runtime-checkpoint-trace-security`; landing both separately duplicates the checkpoint work and keeps an obsolete worktree alive. |
| `codex/connector-semantics-generalization` | `13/1` | Indirect: `trusted_loop`, action connector audit semantics | **DEFER / do not land before runtime Packet A** | It is stale relative to main and is also contained in later integration stacks. It does not block landing the runtime hardening branch, but would add `trusted_loop.py` integration pressure before live wiring. |
| `codex/report-read-projection` | `13/1` | Indirect: API/report surfaces | **DEFER / do not land before runtime Packet A** | Side-effect-free report-read work touches API surfaces likely to overlap later live wiring. Replay from a fresh base if still wanted. |
| `codex/enterprise-integration-readiness` | `13/12` | Indirect: API, persistence, `trusted_loop` | **SUPERSEDE by reconcile/rerehearsal family** | It is an older integration stack that includes connector/report work and is stale relative to current main. |
| `codex/enterprise-integration-reconcile` | `6/14` | Indirect: API, persistence, `trusted_loop`, runtime factory | **PARK until runtime hardening is settled** | More current than readiness but still not a clean base for runtime live wiring. It should not be used as the Packet A base. |
| `codex/workspace-f1-contract-surface` | `6/16` | Indirect: API, persistence, `trusted_loop`, workspace docs/UI | **PARK / replay later if needed** | Frontend/workspace stack is outside current runtime scope and depends on integration commits that are stale relative to main. |
| `codex/workspace-f2-api-report-surface` | `6/18` | Indirect: API/report/workspace | **PARK / duplicate with F2 rehearsal branch** | Same HEAD as `codex/workspace-f2-integration-rehearsal`; keep at most one if this line resumes. |
| `codex/workspace-f2-integration-rehearsal` | `6/18` | Indirect: API/report/workspace | **SUPERSEDE duplicate** | Same HEAD as `codex/workspace-f2-api-report-surface`; it should not be part of runtime A7. |
| `codex/workspace-f3-live-run-surface` | `6/20` | Indirect: API runtime surface | **PARK / replay after runtime live wiring** | It touches future live-run surfaces, so merging it before Agent Runtime live wiring risks hiding whether `/runs` genuinely traverses the runtime envelope. |
| `codex/workspace-f3-integration-rehearsal` | `5/25` | Indirect: integration stack | **SUPERSEDE by current rerehearsal or replay** | Existing CURRENT_STATE already says not to merge the stale F3 rehearsal. |
| `codex/workspace-f3-rerehearsal-current` | `0/25` | Indirect: API/workspace/integration | **PARK, not Packet A base** | It is current-main-based, but it is a product-integration rehearsal, not a runtime substrate branch. Runtime live wiring should start from main after the runtime hardening branch is resolved. |

## A7 Decision State

A7 is **not cleared** yet.

To clear A7 for Agent Runtime live wiring:

1. Run a focused review gate on `codex/runtime-checkpoint-trace-security`.
2. If approved, fast-forward `main` to `codex/runtime-checkpoint-trace-security`.
3. Mark `codex/runtime-durable-checkpoint-store` as superseded and remove/abandon its worktree after the merge is durable.
4. Keep the non-runtime integration/workspace branches parked; do not use them as the base for runtime Packet A.
5. Create `codex/agent-runtime-live-wiring` only after steps 1-4 are complete.

## Non-Negotiable Runtime Boundaries

- Do not introduce LangGraph, CrewAI, LangChain, AutoGen, OpenAI Agents SDK, or any external agent framework as a product core runtime dependency.
- Do not claim this runtime proves autonomous intelligence or replaces autonomous-core.
- Do not auto-execute R4/R5.
- Do not bypass SQL Safety, EvidenceChain, Approval, or Trace.
- Do not use any integration/workspace branch as evidence that the live HTTP path traverses the Agent Runtime envelope unless a live endpoint test proves it.

## Next Runtime Work After A7

After A7 clears, the first live-wiring slice should be:

`POST /runs -> AgentRunContext -> RuntimePolicyGate.check -> invoke_tool envelope -> TrustedLoopAgentRuntimeAdapter.evaluate -> EvidenceChain + persisted RunTrace`

Required negative path:

`POST /runs -> R4 tool without approval -> DENY_REQUIRES_APPROVAL` through the live endpoint, before any tool body or business action execution.
