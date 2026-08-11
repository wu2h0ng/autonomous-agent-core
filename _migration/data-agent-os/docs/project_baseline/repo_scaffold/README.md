# Repository Scaffold

> Date: 2026-06-01  
> Owner: CTO  
> Status: independent project scaffold baseline.

## 1. Purpose

This scaffold defines the implementation repository shape for `AI_Native_Business_Data_Agent_OS`.

The implementation must be created as an independent `ai-native-business-data-agent-os/` project. The FaSoLa monorepo is not the product code host; it is only a Customer-0 source, Reference Domain Pack source, and Connector reference source.

This scaffold exists to prevent uncontrolled directory creation, Core/domain coupling, missing tests, and bypassed quality gates.

## 2. Target Structure

```text
ai-native-business-data-agent-os/
  README.md
  AGENTS.md
  pyproject.toml
  package.json
  .editorconfig
  .gitignore

  packages/
    os_core/
      src/
        agent_os_core/
          agent_runtime/
          intent_runtime/
          semantic_runtime/
          data_product_compiler/
          query_runtime/
          sql_safety/
          evidence_chain/
          action_proposal/
          approval_lite/
          feedback/
          trace/
          eval_hub/
          model_gateway/
    contracts/
      src/
        agent_os_contracts/
    sdk/
      src/
        agent_os_sdk/

  apps/
    api_server/
    workspace/

  domain_packs/
    content_commerce/
      metrics/
      questions/
      golden_queries/
      golden_loops/
      action_templates/
      eval_pack/

  providers/
    postgres_provider/
    file_provider/

  action_connectors/
    notification_connector/
    work_management_connector/

  examples/
    fasola_customer_0/

  tests/
    unit/
    integration/
    eval/
    smoke/

  docs/
    architecture_reviews/
    decisions/
    release-notes/
    runbooks/

  scripts/
    agent_runner/
    ci/
    eval/
```

## 3. Module Ownership

| Path | Owner | Purpose |
|---|---|---|
| `packages/os_core/src/agent_os_core/agent_runtime/` | AI Runtime Agent | Self-developed AgentRuntime, ToolRegistry, run context, validator, trace writer |
| `packages/os_core/src/agent_os_core/intent_runtime/` | Backend Core Agent | BusinessIntent parsing and lifecycle |
| `packages/os_core/src/agent_os_core/semantic_runtime/` | Data Query Agent | SemanticObject lite, MetricContract, and semantic resolution |
| `packages/os_core/src/agent_os_core/data_product_compiler/` | Data Query Agent | DataRequirement, DataProduct candidate, metadata/lineage snapshot lite |
| `packages/os_core/src/agent_os_core/query_runtime/` | Data Query Agent | QueryPlan, QueryRun, QueryResult |
| `packages/os_core/src/agent_os_core/sql_safety/` | SQL Safety Agent | SQL validation, schema allowlist, audit |
| `packages/os_core/src/agent_os_core/evidence_chain/` | EvidenceChain Agent | EvidenceChain builder and validators |
| `packages/os_core/src/agent_os_core/action_proposal/` | Action Proposal Agent | ActionProposal and risk mapping |
| `packages/os_core/src/agent_os_core/approval_lite/` | Backend Core Agent | MVP approval records and states |
| `packages/os_core/src/agent_os_core/feedback/` | Backend Core Agent | FeedbackEvent and outcome capture |
| `packages/os_core/src/agent_os_core/trace/` | Backend Core Agent | TraceEvent and run correlation |
| `packages/os_core/src/agent_os_core/eval_hub/` | Eval Agent | Eval runner integration and result storage |
| `packages/os_core/src/agent_os_core/model_gateway/` | AI Runtime Agent | Model routing, logging, cost metadata |
| `packages/contracts/src/agent_os_contracts/` | Contract Agent | Public contracts, schemas, examples, compatibility tests |
| `packages/sdk/src/agent_os_sdk/` | SDK Agent | External-facing client SDK and extension interfaces |
| `domain_packs/content_commerce/` | Product/Data/Eval Agents | First reference domain pack; must not be imported by OS Core |
| `providers/` | Data Query Agent | Data provider implementations behind ProviderContract |
| `action_connectors/` | Action Proposal/Security Agents | Controlled action connectors behind OperationContract |
| `apps/api_server/` | Backend Core Agent | API application |
| `apps/workspace/` | Frontend Workspace Agent | User workspace UI |
| `examples/fasola_customer_0/` | Solution Agent | Customer-0 sample wiring, fixture data, and reference workflows |
| `tests/` | Test/Eval Agents | Unit, integration, eval, smoke |
| `scripts/agent_runner/` | DevOps Workflow Agent | AI coding workflow runner |

## 4. Dependency Rules

Allowed:

```text
apps/api_server -> packages/os_core
apps/api_server -> packages/contracts
apps/workspace -> API contracts
packages/os_core -> packages/contracts
packages/sdk -> packages/contracts
domain_packs -> packages/contracts
providers -> packages/contracts
action_connectors -> packages/contracts
examples/fasola_customer_0 -> packages/contracts
examples/fasola_customer_0 -> domain_packs/content_commerce
```

Forbidden:

```text
packages/os_core -> domain_packs/content_commerce
packages/os_core -> concrete provider SDKs
packages/os_core -> concrete action platform SDKs
packages/os_core/agent_runtime -> OpenAI Agents SDK
packages/os_core/agent_runtime -> LangGraph
packages/os_core/agent_runtime -> CrewAI / AutoGen / OpenHands / Goose / Aider / Cline / OpenCode
packages/os_core/sql_safety -> AI prompt logic
packages/contracts -> packages/os_core
providers -> action_connectors
action_connectors -> providers
MVP core -> Trino / Calcite / Temporal / OPA / OpenLineage as required runtime dependencies
```

## 5. First Implementation Slice

The first runnable slice should be:

```text
BusinessIntent
  -> SemanticObject lite
  -> MetricContract
  -> ProviderContract lite
  -> DataRequirement / DataProduct candidate
  -> SQLTemplate / QueryPlan
  -> SQL Safety
  -> QueryResult
  -> EvidenceChain
  -> ActionProposal
  -> Feedback / Trace
```

MVP stack boundary:

```text
FastAPI + Pydantic / JSON Schema
PostgreSQL + JSONB + pgvector
sqlglot-first SQL Safety
DuckDB optional for local/eval fixtures only
self-developed AgentRuntime
self-developed Eval Harness
app-level Trace lite
```

Do not introduce full Data Fabric, NoETL, Active Metadata Platform, federated query optimizer, platform-level materialization engine, or enterprise DataOps runtime before a CTO-approved ADR opens that scope.

Recommended first PR sequence:

1. Independent repo skeleton and importable packages.
2. Contracts and schema tests.
3. Self-developed minimal AgentRuntime interfaces.
4. Semantic Runtime lite and DataProduct candidate contracts.
5. SQL Safety checker and tests.
6. Query runtime with mock/file provider.
7. EvidenceChain builder and completeness tests.
8. ActionProposal model and risk tests.
9. Eval harness with golden query fixtures.
10. API endpoints.
11. Minimal web workspace.

## 6. Files To Generate When Code Starts

Generate:

```text
ai-native-business-data-agent-os/README.md
ai-native-business-data-agent-os/AGENTS.md
ai-native-business-data-agent-os/pyproject.toml
ai-native-business-data-agent-os/package.json
ai-native-business-data-agent-os/.github/workflows/ci.yml
ai-native-business-data-agent-os/.gitignore
ai-native-business-data-agent-os/.editorconfig
ai-native-business-data-agent-os/tests/README.md
ai-native-business-data-agent-os/docs/decisions/
ai-native-business-data-agent-os/docs/architecture_reviews/
```

Do not generate placeholder modules without tests or ownership notes.

## 7. Update Rules

Update this scaffold when:

- A new major module is introduced.
- Module ownership changes.
- Dependency rules change.
- A first-stage non-goal becomes an approved implementation target.
- CTO approves a superseding ADR.

Changes to this scaffold require CTO approval and usually an ADR.
