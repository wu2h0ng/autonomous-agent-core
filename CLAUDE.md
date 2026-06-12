# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

This repository is the independent product implementation for AI Native Business Data Agent OS.

Two layers live side by side in the outer baseline package:

1. Strategy and architecture baseline: the numbered Chinese-named directories, `docs/`,
   `repo_scaffold/`, and `code_index.md`. These define product strategy, ADRs, CTO standards,
   terminology, scope, and evaluation samples.
2. Product implementation: everything under `ai-native-business-data-agent-os/`. All code
   implementation work happens here.

The current product identity is not a narrow Data Agent, BI assistant, control plane, or thin
middleware layer. Treat it as a Business Data & Agentic Operations OS: a system that turns
business intent into reusable trusted data products, evidence-backed decisions, governed
business operations, feedback traces, and enterprise knowledge assets.

Before non-trivial work, consult the authoritative product definition in the outer baseline:

- `00_对话总结与阅读指南/项目定义与价值叙事基线.md`
- `00_对话总结与阅读指南/关键术语表.md`
- `01_战略定位与技术PRD/AI_Native_Business_Data_OS_技术PRD与架构设计.md`
- `06_方案评估与落地边界/AI_Native_Business_Data_OS_MVP技术选型与工程工作流.md`
- `07_CTO_实施管理与工程标准/研发团队90天执行方案.md`

## Working Directory And Commands

Run all build, test, and lint commands from inside `ai-native-business-data-agent-os/`.

This is a pure-Python monorepo. Source is laid out as `src/`-style packages wired together via
`PYTHONPATH`. The Makefile is the canonical entry point and should mirror CI:

```bash
make ci
make lint
make format-check
make unit
make eval
make test
```

On Windows PowerShell, the Makefile's Unix-style `PYTHONPATH` may not work directly. Use
semicolon-separated paths and run the underlying commands manually:

```powershell
$env:PYTHONPATH="packages/contracts/src;packages/os_core/src;packages/sdk/src;action_connectors"
python -m unittest discover -s tests -p "test_*.py" -v
python -m unittest tests.unit.test_sql_safety
python -m ruff check .
```

CLI smoke entry point:

```powershell
$env:PYTHONPATH="apps/api_server/src;packages/contracts/src;packages/os_core/src;action_connectors"
python -m agent_os_api.cli --question "GMV" --start-date 2026-05-25 --end-date 2026-06-01 --limit 100
```

The CLI loads `domain_packs/content_commerce/` as the reference Customer-0 domain pack and invokes
the same loop tested by the unit/eval suite.

## Product Architecture

The first milestone is the minimum trusted business production loop:

```text
BusinessIntent
  -> SemanticObject lite
  -> MetricContract
  -> ProviderContract lite
  -> DataProduct candidate
  -> SQL Safety / Eval
  -> EvidenceChain
  -> ActionProposal
  -> Approval lite
  -> Feedback / Trace
  -> KnowledgeAsset candidate
```

Do not reduce this to "trusted Q&A". Trusted Q&A is only one surface of the product. The milestone
must prove that business intent can produce a reusable data-product candidate, evidence-backed
output, governed action proposal, approval/feedback trace, and knowledge-asset candidate.

Implemented orchestration centers on `TrustedLoopRuntime`
(`packages/os_core/src/agent_os_core/trusted_loop.py`). It should remain an injectable runtime that
coordinates collaborators such as intent parsing, semantic/metric/provider resolution,
data-product compilation, SQL safety, query execution, evidence building, action proposal,
governance, approval, feedback, trace, and knowledge memory.

## Package Boundaries

- `packages/contracts/` (`agent_os_contracts`): public typed contracts and dataclasses. Update
  contracts first when a change crosses module boundaries.
- `packages/os_core/` (`agent_os_core`): self-developed OS Core. It must remain domain-independent
  and must not import `domain_packs/`, `examples/`, `providers/`, or `action_connectors/`.
- `packages/sdk/` (`agent_os_sdk`): external SDK boundary.
- `apps/api_server/` (`agent_os_api`): application/composition layer. It owns wiring, runtime
  factories, domain pack loading, and concrete connector injection.
- `apps/workspace/`: future user workspace UI. It should expose BusinessIntent, DataProduct View,
  EvidenceChain, ActionProposal, approval state, Feedback/Trace, and KnowledgeAsset Review.
- `domain_packs/`: domain-specific packs as config/data/templates, not OS Core logic.
- `providers/` and `action_connectors/`: concrete data providers and controlled action connectors
  behind contracts.
- `examples/`: Customer-0/reference examples only.

OS Core must not contain FaSoLa, content-commerce, customer-specific, platform-specific, or SaaS
connector logic. FaSoLa/content-commerce is Customer-0 and reference material, never Core logic.

## Hard Rules

- No pseudo implementation. Empty shells, hard-coded success, unused adapters, docs-only behavior,
  or tests that merely assert fixture values are not complete.
- Every behavioral change must add or update tests.
- Every new runtime capability needs a real entry point, a typed contract/schema, at least one
  failure path, and a regression test or eval that would fail if the logic were bypassed.
- All formal data answers must pass through SQL Safety and EvidenceChain.
- DataProduct candidate and EvidenceChain must be available to downstream Business Agent behavior;
  Business Agent logic must not bypass the data/evidence path.
- R4/R5 business actions are proposal-only in MVP. Do not auto-execute high-risk writes.
- Feedback and adoption signals should feed Trace and KnowledgeAsset candidate creation.
- Privacy computing, TEE, blockchain, federated learning, full MCP gateway, full marketplace, full
  private deployment, and high-risk automatic execution are staged future capabilities unless an ADR
  and CTO approval explicitly say otherwise.
- Do not store secrets, tokens, cookies, API keys, or sensitive raw data in the repository.

## External Framework Policy

Agent OS Core and Agent Runtime are self-developed.

OpenAI Agents SDK, LangGraph, CrewAI, AutoGen, OpenHands, Goose, Aider, Cline, OpenCode, and similar
frameworks may be studied as references, benchmarks, or non-production prototypes only. They must not
become product Core runtime dependencies without a new ADR and CTO approval.

## Required Engineering Flow

Use this flow for code changes:

```text
Contract
  -> Safety
  -> Eval/Test
  -> Implementation
  -> Review
  -> Traceable result
```

For implementation planning, define:

- Real entry point.
- Contract/schema consumed or produced.
- Happy path.
- Negative or refusal path.
- Test/eval that fails if the real logic is bypassed.
- Trace/evidence/feedback/knowledge update.
- Boundary check proving OS Core independence remains intact.

## Changes Requiring Architecture Review

Create or update an ADR (`docs/decisions/ADR-*.md`) or architecture review
(`docs/architecture_reviews/AR-*.md`) before changing:

- Contracts, schemas, public APIs, or compatibility behavior.
- SQL Safety, EvidenceChain, Eval, Trace, Provider, ActionProposal, Approval, Feedback, or
  KnowledgeAsset behavior.
- OS Core boundaries or runtime dependency policy.
- Auth, permissions, secrets, deployment, data egress, or model routing.
- Connectors, provider execution, or R4/R5 business action behavior.
- Any deletion or weakening of tests, evals, safety rules, review gates, or auditability.

Keep `code_index.md` current when adding top-level modules or source-of-truth docs.

## Completion Gate

Before marking a task complete, state:

- The real entry point that invokes the new code.
- The contract/schema consumed or produced.
- The negative path covered by tests or explicitly documented as pending.
- The regression test or eval that would fail if the code were bypassed.
- The trace/evidence/feedback/knowledge update.
- The reason OS Core boundaries remain intact.
