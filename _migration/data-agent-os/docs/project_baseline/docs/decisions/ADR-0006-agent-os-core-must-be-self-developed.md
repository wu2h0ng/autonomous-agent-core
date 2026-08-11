# ADR-0006: Agent OS Core Must Be Self-Developed

> Date: 2026-06-01  
> Status: Accepted  
> Owner: CTO  

## Context

The project will study open-source Agent OS, coding agents, agent frameworks, MCP servers, and skill ecosystems to understand current design patterns and avoid blind spots.

However, the product vision depends on owning the core Agent OS architecture: contracts, runtime, permissions, evidence, trace, eval, skills, memory, and governance. If the project builds on top of an external Agent OS or multi-agent framework, the core product boundary becomes hard to audit, hard to differentiate, and hard to control.

## Decision

AI Native Business Data OS will implement Agent OS Core 100% in-house.

Open-source Agent OS / Agent framework projects may be used only as:

- architecture references;
- benchmark targets;
- design comparison material;
- implementation anti-pattern studies;
- non-production spikes;
- developer productivity tools outside the product runtime.

They must not become the product runtime base.

## Self-Developed Scope

The following must be implemented as project-owned code and contracts:

- `AgentRuntime`;
- `AgentRunContext`;
- `ToolRegistry`;
- `SkillRegistry`;
- `StructuredOutputValidator`;
- `AgentTraceWriter`;
- `AgentEval`;
- `AgentMemory`;
- `PolicyDecision` and permission gates;
- EvidenceChain integration;
- Action governance integration;
- project-specific `skills/`.

## Allowed External Use

The project may use open-source engineering tools, subject to license and security review:

- package managers, linters, formatters, type checkers, test runners;
- SQL parsers and deterministic safety tooling;
- CI helpers, code review helpers, secret scanners;
- documentation/context tools for development;
- model provider API clients through a replaceable `ModelProviderAdapter`.

Using an API client or SDK for model invocation does not allow delegating Agent OS runtime, tool orchestration, permission checks, memory, trace, or eval to that SDK.

## Explicitly Not Approved As Product Runtime

The following categories are not approved as product Core dependencies:

- OpenAI Agents SDK as Agent OS runtime;
- LangGraph as Agent OS runtime;
- CrewAI or AutoGen as multi-agent runtime;
- OpenHands, SWE-agent, Goose, Cline, Aider, OpenCode, Gemini CLI as product coding/operation runtime;
- Anthropic skills or community skills copied into production workflow without review;
- external MCP servers with write access to project or customer systems.

## Consequences

- Architecture reviews must treat external Agent OS projects as references only.
- `repo_scaffold/README.md` and future implementation repos must include self-developed Agent OS modules.
- Any proposal to introduce an external Agent framework into Core is rejected unless this ADR is superseded by CTO approval.
- Code Agent workflows can use open-source tools for development assistance, but generated product code must remain project-owned and pass the same review gates.

## References

- `docs/architecture_reviews/CTO-APPROVAL-20260601-full-os-architecture.md`
- `docs/architecture_reviews/CTO-APPROVAL-20260601-mvp-trusted-loop-architecture.md`
- `07_CTO_实施管理与工程标准/GitHub开源项目选型调研.md`
- `07_CTO_实施管理与工程标准/Code_Agent开源辅助项目选型.md`
