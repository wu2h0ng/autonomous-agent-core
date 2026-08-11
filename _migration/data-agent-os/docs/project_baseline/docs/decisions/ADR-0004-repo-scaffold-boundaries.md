# ADR-0004: Repository Scaffold and Module Boundaries

> Status: Superseded by ADR-0007  
> Date: 2026-06-01  
> Owner: CTO  

> Supersession note: this ADR records the original scaffold decision. The approved implementation root and module layout are now governed by `ADR-0007-independent-project-boundary.md` and `repo_scaffold/README.md`; `business_data_os/` is no longer an approved top-level implementation root.

## Context

The current package is documentation-first. When implementation starts, Code Agents need a stable repository scaffold before writing code. Without a scaffold, agents may create inconsistent module boundaries, put domain logic into Core, or bypass safety/eval layers.

## Decision

Adopt the repository scaffold defined in:

```text
repo_scaffold/README.md
```

The original target top-level implementation layout was:

```text
business_data_os/
domain_packs/
providers/
action_connectors/
apps/
tests/
docs/
scripts/
```

Historical core boundaries:

- `business_data_os/` was the original OS Core placeholder; it has been replaced by `ai-native-business-data-agent-os/packages/os_core/`.
- `domain_packs/` contains domain-specific metrics, templates, mappings, and eval packs.
- `providers/` implements ProviderContract.
- `action_connectors/` implements controlled external actions behind OperationContract.
- `tests/eval/` owns golden and regression evals.

## Consequences

Benefits:

- Agents know where to place code.
- Reviewers can detect boundary violations.
- Domain logic and Core remain separate.

Tradeoffs:

- Some directories may start as interfaces/placeholders before full implementation.
- Any scaffold change requires ADR update or a superseding ADR.

## Boundary Red Lines

- Core must not import content-commerce-specific objects.
- Query execution must pass SQL Safety.
- Formal answers must use EvidenceChain.
- R4/R5 business actions are proposal-only in MVP.
