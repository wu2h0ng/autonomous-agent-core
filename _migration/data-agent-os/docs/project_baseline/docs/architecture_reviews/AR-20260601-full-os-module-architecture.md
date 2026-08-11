# Architecture Design Brief: Full OS Module Architecture

> Review ID: AR-20260601-full-os-module-architecture  
> Date: 2026-06-01  
> Prepared by: Architecture Agent  
> Review owner: CTO  
> Status: Proposed for CTO review  
> Scope: Module-level decomposition for full OS target architecture  

## 1. 模块拆分原则

模块拆分必须服务两个目标：

1. OS Core 保持通用，不写入具体行业、客户、平台和业务系统逻辑。
2. 每个模块都能被 Contract、Eval、Trace、Policy 约束，方便 Code Agent 分工实现和审查。

模块按五类组织：

| 类别 | 说明 |
|---|---|
| Core Runtime | BusinessIntent、Semantic、Compiler、Evidence、Trace、Feedback 等核心运行时 |
| Access and Action | Provider、SQL Safety、Action Connector、Workflow、Approval |
| Governance and Quality | Policy、Identity、Audit、Eval、Observability、Cost |
| Extension | Domain Pack、Provider SDK、Action SDK、MCP Gateway、UI Block |
| Apps and DevOps | API、Workspace UI、Admin、AgentOps、CI/CD、Release |

## 2. 目标模块图

```text
apps/
  api_server/
  workspace/
  admin_console/

packages/
  contracts/
    src/agent_os_contracts/
  os_core/
    src/agent_os_core/
      identity_runtime/
      tenant_runtime/
      intent_runtime/
      semantic_runtime/
      data_product_compiler/
      data_access_plane/
      query_runtime/
      sql_safety/
      evidence_chain/
      insight_runtime/
      business_agent_runtime/
      action_governance/
      workflow_runtime/
      approval_runtime/
      operation_trace/
      feedback_runtime/
      knowledge_memory/
      eval_hub/
      policy_engine/
      model_gateway/
      tool_gateway/
      observability/
      cost_metering/
  sdk/
    src/agent_os_sdk/

extension/
  domain_pack_sdk/
  provider_sdk/
  action_connector_sdk/
  business_agent_pack_sdk/
  eval_pack_sdk/
  ui_block_sdk/
  mcp_gateway/
  workflow_bridge/

domain_packs/
  content_commerce/
  sales_ops/
  finance_ops/
  customer_service/
  supply_chain/

providers/
  postgres_provider/
  file_provider/
  warehouse_provider/
  saas_api_provider/
  browser_provider/
  event_provider/

action_connectors/
  notification_connector/
  work_management_connector/
  crm_connector/
  ads_connector/
  erp_connector/

ops/
  migrations/
  deployment/
  runbooks/
  release/
  incident_review/

tests/
  contract/
  unit/
  integration/
  eval/
  policy/
  security/
  smoke/
```

说明：这是完整 OS 目标模块图，不等于当前 repo scaffold 需要立即扩展。第一阶段仍使用已批准的 MVP scaffold。

## 3. 模块职责矩阵

| 模块 | 职责 | 输入 | 输出 | 不负责 |
|---|---|---|---|---|
| `contracts` | 所有公共 schema、API DTO、版本兼容 | module requirements | typed contracts | 业务实现逻辑 |
| `identity_runtime` | 用户、服务账号、Agent identity、token 上下文 | auth token | identity context | 企业 IAM 原生实现 |
| `tenant_runtime` | tenant/workspace/project 隔离和配置 | request context | tenant policy context | 业务权限判断 |
| `intent_runtime` | 解析、澄清、归一化业务意图 | raw question | BusinessIntent | 查询和行动执行 |
| `semantic_runtime` | 业务对象、指标、规则、冲突处理 | intent, registry | semantic binding | 自由生成指标口径 |
| `data_product_compiler` | 编译数据需求、构建计划、数据产品版本 | intent, semantic binding | build plan, DataProduct | 直接访问具体数据库 |
| `data_access_plane` | Provider 注册、能力发现、权限、成本、血缘 | DataRequirement | provider plan | 业务归因解释 |
| `query_runtime` | QueryPlan、QueryRun、QueryResult 生命周期 | query plan | result snapshot | 绕过 SQL Safety |
| `sql_safety` | SQL AST 校验、只读、白名单、limit、审计 | SQL/query plan | safety decision | 业务指标解释 |
| `evidence_chain` | 证据链构建、完整性校验、claim 支持 | results, quality, lineage | EvidenceChain | 编造无来源结论 |
| `insight_runtime` | 归因、摘要、图表、限制说明 | EvidenceChain | InsightOutput | 执行业务动作 |
| `business_agent_runtime` | 领域 Agent 编排、职责边界、计划生成 | EvidenceChain, policy context | ActionProposal | 自行解释底层数据 |
| `action_governance` | 风险分级、dry-run、幂等、回滚/补偿校验 | action proposal | governance decision | 具体 SaaS API 调用 |
| `workflow_runtime` | 长流程状态、重试、补偿、callback | operation plan | workflow state | 决定业务策略 |
| `approval_runtime` | 审批路径、审批状态、审批证据 | policy decision | approval decision | 替代责任人判断 |
| `operation_trace` | 操作审计链路、执行证据、状态回放 | action/approval/execution | OperationTrace | 业务结果归因 |
| `feedback_runtime` | 采纳、拒绝、结果指标、复盘事件 | trace, metrics | FeedbackEvent | 自动改规则 |
| `knowledge_memory` | KnowledgeAsset、SOP、案例、语义记忆 | feedback, docs | reviewed asset | 未审核自动发布 |
| `eval_hub` | golden case、回归、评分、上线门槛 | outputs, cases | EvalResult | 代替业务验收 |
| `policy_engine` | 数据访问、工具、模型、动作策略 | context, action | PolicyDecision | 直接执行动作 |
| `model_gateway` | 模型路由、成本、prompt 版本、调用审计 | model request | model response | 业务策略判断 |
| `tool_gateway` | 工具注册、权限映射、沙箱、MCP 接入 | tool request | tool result | 绕过 OS policy |
| `observability` | trace、metric、log、alert、SLO | runtime events | telemetry | 业务数据存储 |
| `cost_metering` | token、模型、查询、连接器成本计量 | invocation events | cost report | 财务结算系统 |

## 4. 模块依赖规则

允许依赖：

```text
apps/api_server -> packages/os_core
apps/api_server -> packages/contracts
apps/workspace -> API contracts
packages/os_core/* -> packages/contracts
packages/sdk -> packages/contracts
compiler -> semantic_runtime, data_access_plane, policy_engine
query_runtime -> sql_safety, providers via ProviderContract
business_agent_runtime -> evidence_chain, action_governance, policy_engine
action_governance -> action_connectors via ActionConnectorContract
extension SDKs -> contracts
domain_packs -> contracts and SDKs
providers -> ProviderContract
action_connectors -> ActionConnectorContract
eval_hub -> contracts and read-only result artifacts
```

禁止依赖：

```text
packages/os_core -> domain_packs/*
packages/os_core -> concrete provider SDK
packages/os_core -> concrete action connector SDK
semantic_runtime -> model_gateway as source of truth
sql_safety -> prompt/model logic
business_agent_runtime -> raw warehouse connection
action_connectors -> providers
providers -> action_connectors
eval_hub -> production write path
```

## 5. 关键接口

### 5.1 Data Agent 到 Business Agent

```text
EvidencePackage =
  evidence_chain_id
  intent_id
  data_product_ids
  claims
  affected_entities
  confidence
  limitations
  recommended_action_categories
  required_human_judgement
```

Business Agent 只能消费 EvidencePackage 或已发布 DataProduct，不允许直接从 QueryResult 拼接业务动作。

### 5.2 Business Agent 到 Action Governance

```text
ActionProposal =
  proposal_id
  evidence_chain_id
  business_agent_id
  target_object
  action_type
  parameters
  expected_impact
  risk_level
  approval_hint
  rollback_hint
  feedback_metrics
```

Action Governance 必须把 proposal 转成可审批的 OperationPlan，不能把自然语言建议直接交给 Connector。

### 5.3 Action Governance 到 Action Connector

```text
OperationRequest =
  operation_contract_id
  idempotency_key
  principal
  approved_by
  dry_run
  input
  policy_decision_id
  trace_id
```

Connector 返回：

```text
OperationResult =
  status
  external_id
  audit_payload
  rollback_token
  compensating_action
  feedback_observation_window
```

### 5.4 Provider 到 EvidenceChain

Provider 必须返回：

```text
ProviderResult =
  result_ref
  schema_snapshot
  row_count
  freshness
  quality_results
  lineage
  source_classification
  execution_cost
```

EvidenceChain 不直接信任结果文本，只信任 ProviderResult、QueryRun、QualityResult、LineageSnapshot。

## 6. 模块测试和评测要求

| 模块 | 必测内容 |
|---|---|
| contracts | schema backward compatibility、sample validation |
| intent_runtime | golden intent、clarification、bad input |
| semantic_runtime | alias、metric conflict、versioning、owner approval |
| compiler | build plan determinism、policy/cost/quality gate |
| sql_safety | write-block、schema allowlist、injection、limit、AST edge cases |
| query_runtime | parameter binding、provider errors、result snapshot |
| evidence_chain | completeness、claim support、limitation propagation |
| business_agent_runtime | evidence-only planning、forbidden raw data path |
| action_governance | R0-R5 policy simulation、approval route、rollback requirement |
| connectors | dry-run、idempotency、audit、error mapping |
| feedback_runtime | outcome capture、trace linkage、eval case generation |
| eval_hub | regression reproducibility、threshold enforcement |
| model_gateway | prompt/model version、cost logging、PII policy |
| tool_gateway/MCP | scope mapping、risk class、tool audit |

## 7. 模块成熟度阶段

| 模块 | Stage 1 | Stage 2 | Stage 3 | Stage 4 | Stage 5-6 |
|---|---|---|---|---|---|
| Intent Runtime | P0 | P1 | P2 | P2 | P3 |
| Semantic Runtime | MetricContract v1 | semantic object v1 | action semantic lite | pack templates | ontology governance |
| Data Product Compiler | not full | v1 | v1.5 | reusable catalog | platform compiler |
| Data Access Plane | postgres/file | provider contract | more providers | provider mapping | SDK/marketplace |
| EvidenceChain | v1 | v2 | action evidence | pack evidence | enterprise audit |
| Business Agent Runtime | proposal only | proposal | lite runtime | pack agent | platform agent runtime |
| Action Governance | risk model lite | dry-run | approval/task | domain templates | full policy/action SDK |
| Knowledge Memory | feedback notes | eval lessons | SOP/case | domain knowledge | governed knowledge graph |
| Eval Hub | golden query | data product eval | golden loop | pack eval | tenant eval platform |
| Deployment | local/single tenant | single tenant | single tenant | early SaaS | SaaS/hybrid/private |

## 8. Code Agent 分工建议

| Agent | 可负责模块 | 强制前置 |
|---|---|---|
| Contract Agent | `contracts`, compatibility tests | Architecture approval |
| Backend Core Agent | intent, trace, feedback, API | Contract freeze |
| Data Query Agent | semantic, query, provider | SQL Safety design |
| SQL Safety Agent | sql_safety | Security review |
| EvidenceChain Agent | evidence_chain, insight | Contract + query result |
| Business Agent Runtime Agent | action proposal, business agent runtime | Evidence contract |
| Security Governance Agent | policy, approval, audit | risk taxonomy |
| Eval Agent | eval_hub, golden cases | product acceptance criteria |
| Frontend Workspace Agent | intent workspace, evidence viewer, action center | API contract |
| DevOps Workflow Agent | CI, release, eval runner | test matrix |

## 9. CTO 审批项

1. 是否接受目标模块图作为完整 OS 演进方向。
2. 是否确认当前 repo scaffold 不立即扩展到全部目标模块。
3. 是否确认所有模块必须有 owner、contract、tests/eval、trace 入口。
4. 是否确认 Core 不允许依赖 Domain Pack、Provider 实现、Action Connector 实现。
5. 是否确认每次开启新模块，都必须生成对应 Architecture Design Brief 或 ADR。
