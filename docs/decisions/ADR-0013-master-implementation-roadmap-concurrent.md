# ADR-0013: Master Implementation Roadmap — Concurrent Execution of Staged-Out Capabilities

- Status: **Accepted — concurrent execution authorized**
- Date: 2026-07-07
- Authorization: founder/CTO
- Scope: Execute all staged-out capabilities concurrently rather than sequentially tightend
- Risk class: R4/R5 (architecture-wide concurrency risk; risk accepted by authorizer)

## 1. Context

MVP / Stage 1 is complete. The following capabilities were explicitly staged-out during MVP:

- Full Data Fabric / NoETL / federated query engine
- Full Domain Pack SDK
- Full MCP Gateway
- Full BPM / approval workflow
- R4/R5 automatic execution
- Frontend F3+ full live API integration
- Temporal / OPA / Trino heavy infrastructure

This ADR records a founder/CTO decision to **implement these capabilities concurrently** rather than the tightened sequential framework recommended during initial review.

## 2. Decision

**Execute all staged-out capabilities in parallel workstreams.**

The authorizer accepts the following trade-offs in exchange for speed:

- Higher integration risk between workstreams.
- Higher review and CI bandwidth requirements.
- Potential temporary instability in contracts and OpenAPI snapshot.
- Need for stronger coordination gates.

## 3. Workstreams

| ID | Workstream | Capability | Owner Target |
|---|---|---|---|
| A | Data Fabric / NoETL / Compiler v1 | ProviderContract lifecycle, federated query planning, logical views, materialization hints | Data Query Agent / Architecture Agent |
| B | Domain Pack SDK | Pack registry, lifecycle, SDK templates, validation, marketplace shape | Product Agent / Backend Core Agent |
| C | MCP Gateway | MCP Server registration, scope/sandbox/audit, tool risk classification | AI Runtime Agent / Security Agent |
| D | Full BPM / Approval Workflow | Multi-step approval, delegation, timeout, escalation, state machine | Backend Core Agent |
| E | R4/R5 Auto Execution | PolicyEngine, tenant policy, policy pre-approval, ADR-0012 implementation | Action Proposal Agent / Security Agent |
| F | Frontend F3+ | Full live API integration, approval UI, knowledge asset management UI | Frontend Workspace Agent |
| G | Heavy Infrastructure | Temporal, OPA, Trino/Calcite — introduced on demand | Architecture Agent / CTO gate |

## 4. Integration Rules (mandatory to manage concurrency)

### 4.1 Contract-first discipline

Every workstream must define its contract changes **before** implementation:

- New/changed contracts go to `packages/contracts/src/agent_os_contracts/`.
- Contract PRs are reviewed first.
- Implementation PRs reference the merged contract PR.

### 4.2 Feature flags / configuration gates

All new capabilities must be behind explicit configuration flags:

```python
class RuntimeFeatureFlags:
    data_fabric_v1: bool = False
    domain_pack_sdk: bool = False
    mcp_gateway: bool = False
    full_bpm_workflow: bool = False
    r4_r5_auto_execution: bool = False
    frontend_f3_live_api: bool = False
```

Default for all flags is `False`. MVP behavior remains unchanged unless explicitly enabled.

### 4.3 OpenAPI drift gate management

- Each workstream owns its own OpenAPI delta during development.
- A single integration branch (`integration/staged-out-capabilities`) is the collision point.
- OpenAPI snapshot regeneration happens only on the integration branch after contract conflicts are resolved.

### 4.4 OS Core boundary protection

- OS Core continues to not import domain packs, providers, action connectors, or examples.
- MCP Gateway lives in OS Core but only hosts contract/adapter interfaces; concrete MCP servers live outside.
- Temporal/OPA/Trino are adapters outside OS Core unless a later ADR specifically moves them in.

### 4.5 Test-first discipline

Every workstream must produce red-first tests before implementation. Tests must fail if:

- Feature flag off → new behavior is absent.
- Feature flag on → new behavior works.
- Contract violations are not caught.

### 4.6 Weekly integration checkpoint

- Every 7 days, all workstreams rebase onto `integration/staged-out-capabilities`.
- Conflicts resolved at the integration checkpoint, not ad-hoc.

## 5. Dependencies and Collision Points

| Collision | Mitigation |
|---|---|
| A changes `DataProduct` contract while B builds Domain Pack SDK | B builds against A's contract PR branch; B does not merge before A's contract PR |
| C MCP Gateway needs policy engine from E | C builds MCP tool registration first; policy enforcement added when E's contract is ready |
| D Full BPM changes approval state machine used by E | D owns the approval state contract; E consumes it as a port |
| F Frontend needs stable API | F maintains contract-shaped mocks; live API integration gated per endpoint |
| All workstreams touch OpenAPI | Integration branch reconciliation |

## 6. Gated Entry Conditions

Before a workstream starts implementation:

- Workstream lead ADR or design brief exists.
- Contract delta PR is drafted.
- Eval plan is drafted.
- Failure paths are listed.

## 7. Boundaries / Non-Goals

- **No default-on behavior.** All new capabilities default to off.
- **No external agent framework in OS Core.** ADR-0006 remains in force.
- **No cross-repo import.** ADR-0007 / Hard Boundary #19 remains in force.
- **No weakening of SQL Safety / EvidenceChain.** Grounding invariant remains.
- **No production claim of autonomy.** External narrative remains governed.

## 8. Risk Acceptance

The authorizer explicitly accepts:

- Higher integration risk.
- Potential temporary CI instability.
- Need for larger review bandwidth.
- Possible need to revert or park individual workstreams if they block others.

## 9. Approval

- Approved by: founder/CTO
- Date: 2026-07-07
- Scope: Concurrent execution of all staged-out capabilities
