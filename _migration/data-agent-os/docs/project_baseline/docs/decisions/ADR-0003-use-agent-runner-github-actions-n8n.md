# ADR-0003: Use Agent Runner + GitHub Actions + n8n for AI Coding Workflow

> Status: Accepted  
> Date: 2026-06-01  
> Owner: CTO  

## Context

The project needs an AI coding workflow that can support high automation while preserving engineering quality and safety. Three candidate patterns exist:

- Script-based orchestration.
- Low-code workflow orchestration such as n8n.
- CI/CD pipeline orchestration such as GitHub Actions.

Using only one pattern creates risk. Scripts are flexible but weak on governance. n8n is convenient for cross-system flow but should not become a high-permission code execution center. CI/CD is reliable for quality gates but not ideal for local multi-round AI exploration.

## Decision

Use a hybrid workflow:

```text
Codex / Cursor Agent + Python Agent Runner
  -> local white-listed commands and repair loop
  -> GitHub Actions for quality gates
  -> n8n for outer orchestration, notifications, approvals, and reports
```

Rules:

- Agent Runner performs code generation and repair in isolated branch/worktree.
- GitHub Actions is the source of truth for quality gates.
- n8n does not execute arbitrary shell commands.
- First-stage automation stops at automatic PR creation; automatic production deployment is not allowed.

## Consequences

Benefits:

- Keeps AI automation flexible.
- Preserves auditable CI gates.
- Reduces risk from workflow tools holding excessive permissions.

Tradeoffs:

- Requires maintaining Agent Runner and workflow specs.
- Requires discipline around command whitelist and PR gates.

## Required Gates

- Format/lint/typecheck.
- Unit tests.
- Contract schema tests.
- SQL Safety tests.
- Golden query/eval tests.
- EvidenceChain completeness tests.
- Action risk tests.
- Secret and dependency scans.

