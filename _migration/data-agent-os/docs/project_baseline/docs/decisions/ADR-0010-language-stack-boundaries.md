# ADR-0010: Language Stack Boundaries for Core, Workspace, Tooling, and Enterprise Integration

> Status: Accepted  
> Date: 2026-06-03  
> Owner: CTO

## Context

The project needs a language strategy that supports current MVP delivery and future enterprise expansion.

Recent discussion clarified three pressures:

- Python is already the implementation base for the MVP Trusted Loop, contracts, SQL Safety, EvidenceChain, ActionProposal, Trace, tests, and evals.
- TypeScript is increasingly strong for AI-native tools, streaming UX, CLI developer tools, React workspaces, terminal control, and typed UI clients.
- Java remains important for enterprise integration, JVM data infrastructure, JDBC-heavy environments, and future private-deployment adapters.

The decision must prevent trend-driven rewrites while preserving future options.

## Decision

Adopt a layered language strategy:

```text
Python:
  OS Core / Trusted Loop / Eval / SQL Safety / EvidenceChain

TypeScript:
  Workspace UI / Developer CLI / Agent Tooling / Typed API Client

Java:
  Enterprise connectors / JVM data ecosystem / heavy SQL planner / private deployment adapter
```

### Python Boundary

Python remains the MVP product Core language.

Use Python for:

- `packages/os_core/`
- `packages/contracts/`
- Trusted Loop runtime
- SQL Safety
- EvidenceChain
- ActionProposal
- Eval harness
- Trace / Telemetry contracts
- FastAPI / Pydantic API boundary when approved

Python Core must remain self-developed. External Agent frameworks may be studied but must not become product Core runtime dependencies.

### TypeScript Boundary

TypeScript is approved for interaction and tool layers.

Use TypeScript for:

- React / Next.js Workspace UI
- Typed API client generated from OpenAPI / JSON Schema
- Developer CLI and AI tool UX
- Terminal interaction tools, with Node.js and optionally Ink
- Future desktop shell UI where appropriate, with Tauri preferred over Electron unless ecosystem constraints justify Electron

TypeScript must interact with Python Core through stable contracts such as OpenAPI, JSON Schema, or typed client generation. It must not import Python Core internals or redefine backend behavior locally.

### Java Boundary

Java is a future enterprise integration and data-infrastructure option, not an MVP Core language.

Use Java or JVM services for:

- Enterprise connectors where vendor SDKs are Java-first
- JDBC-heavy data providers
- SAP / Oracle / Hadoop / Hive / Flink / Kafka ecosystem adapters
- Calcite-style SQL planner or complex SQL optimization if `sqlglot` becomes insufficient
- Private deployment adapters for Java-standard enterprise environments
- High-throughput backend services if later scale requirements justify JVM services

Java services must sit behind ProviderContract, OperationContract, API, or connector boundaries. They must not become OS Core dependencies without a new ADR and CTO approval.

## Consequences

Benefits:

- Preserves the current Python MVP implementation and test/eval investment.
- Allows TypeScript to support modern AI tool UX, React workspace, CLI, and typed API development.
- Keeps Java available for enterprise integration without burdening the MVP.
- Prevents language fragmentation inside OS Core.
- Gives future teams a clear rule for where each language belongs.

Tradeoffs:

- Multi-language boundaries require contract discipline.
- TypeScript and Java components must not bypass Python Core contracts.
- Generated clients and schema compatibility tests become important once UI and connectors mature.
- Java enterprise adapters will need deployment and observability standards before production use.

Operational impact:

- PRs adding TypeScript must specify whether they are Workspace, CLI, tooling, or typed-client work.
- PRs adding Java must specify the connector/provider/planner/private-deployment boundary and must include CTO review.
- Any proposal to rewrite Core in TypeScript or Java is rejected unless this ADR is superseded.

## Alternatives Considered

### All-in TypeScript

Rejected for MVP. TypeScript is strong for AI tooling and frontend work, but rewriting Core would discard current Python contracts, tests, evals, and Trusted Loop implementation.

### Python-only

Rejected as a long-term strategy. It would slow Workspace UI, developer tooling, typed API client, and terminal UX work where TypeScript is stronger.

### Java-first Enterprise Backend

Rejected for MVP. Java is valuable for enterprise integration and data infrastructure, but too heavy for the first Trusted Loop and would slow early iteration.

### Polyglot Without Boundaries

Rejected. It increases integration risk, duplicate logic, and unclear ownership.

## Change Rules

Revisit this ADR when:

- A production customer requires a Java-first deployment or connector.
- TypeScript CLI / tool runtime becomes a product surface with its own release cycle.
- `sqlglot` is insufficient and Calcite-style planning becomes necessary.
- Python Core performance or deployment constraints become a measured blocker.
- Generated OpenAPI / JSON Schema clients become a compatibility bottleneck.

Any change that moves OS Core out of Python or introduces Java/TypeScript as Core runtime requires a new ADR and CTO approval.
