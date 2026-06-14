# ADR-0007: Independent Project Boundary

> Date: 2026-06-01  
> Status: Accepted  
> Owner: CTO  
> Related: ADR-0004, ADR-0005, ADR-0006

## Context

The documentation package has evolved from a monorepo document backup into an independent project startup baseline. It now contains strategy, PRD, architecture reviews, ADRs, repository scaffold, CTO approvals, Agent rules, MVP technology choices, and engineering management standards.

Keeping implementation inside the existing FaSoLa monorepo would blur product boundaries:

- Product Core would be coupled to a single Customer-0 codebase.
- Domain-specific content-commerce assumptions could leak into OS Core.
- Code Agent memory, review, eval, and CI rules would be harder to enforce.
- Future enterprise pilots, domain packs, SDKs, and deployment profiles would inherit monorepo-specific constraints.

## Decision

`AI_Native_Business_Data_Agent_OS` must be implemented as an independent project.

The implementation repository/directory is:

```text
ai-native-business-data-agent-os/
```

The approved first structure is:

```text
ai-native-business-data-agent-os/
  packages/
    os_core/
    contracts/
    sdk/
  apps/
    api_server/
    workspace/
  domain_packs/
    content_commerce/
  providers/
    postgres_provider/
    file_provider/
  action_connectors/
    notification_connector/
    work_management_connector/
  examples/
    fasola_customer_0/
  tests/
  docs/
  scripts/
```

FaSoLa monorepo is only allowed to serve as:

1. Customer-0 business scenario source.
2. Reference Domain Pack source.
3. Connector and integration reference source.
4. Sample data, sample workflow, and pilot feedback source.

FaSoLa monorepo is not the product Core implementation host.

## Consequences

Positive:

- OS Core ownership is clean.
- Product architecture can evolve independently from Customer-0 delivery pressure.
- Domain Pack and Connector boundaries become testable.
- Code Agent workflow can use project-local rules, eval gates, and repo-level CI without monorepo leakage.
- The project is easier to package for enterprise pilot, Hybrid deployment, SDK, and later ecosystem work.

Tradeoffs:

- Initial setup requires duplicating some engineering baseline files.
- Customer-0 integration needs explicit examples and adapters instead of direct monorepo imports.
- Changes from FaSoLa must be curated into domain packs, connectors, or eval cases instead of copied into Core.

## Boundaries

Allowed:

```text
examples/fasola_customer_0 -> domain_packs/content_commerce
examples/fasola_customer_0 -> providers
examples/fasola_customer_0 -> action_connectors
domain_packs/content_commerce -> packages/contracts
providers -> packages/contracts
action_connectors -> packages/contracts
packages/os_core -> packages/contracts
```

Forbidden:

```text
packages/os_core -> examples/fasola_customer_0
packages/os_core -> domain_packs/content_commerce
packages/os_core -> FaSoLa monorepo modules
packages/contracts -> Customer-0-specific schema assumptions
```

## Implementation Rules

1. New product code must be created under `ai-native-business-data-agent-os/`.
2. `business_data_os/` is no longer an approved top-level implementation root.
3. `packages/os_core/` contains self-developed OS Core and Agent Runtime.
4. `packages/contracts/` owns cross-module public contracts.
5. `domain_packs/content_commerce/` contains domain-specific assumptions and examples.
6. `examples/fasola_customer_0/` may demonstrate wiring but must not become a Core dependency.
7. Any future exception requires a new ADR and CTO approval.

## Validation

Before the first implementation milestone is accepted:

- `ai-native-business-data-agent-os/` must be importable and testable independently.
- The first Trusted Loop must run without importing FaSoLa monorepo code.
- OS Core tests must pass without domain pack imports.
- Domain pack tests may depend on public contracts only.
- Code index and scaffold must reference `ai-native-business-data-agent-os/` as the implementation root.
