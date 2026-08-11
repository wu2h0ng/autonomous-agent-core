# Architecture Design Brief: Full OS Target Architecture

> Review ID: AR-20260601-full-os-target-architecture  
> Date: 2026-06-01  
> Prepared by: Architecture Agent  
> Review owner: CTO  
> Status: Proposed for CTO review  
> Scope: 3-year target architecture, not single-release implementation scope  

## 1. 需求摘要

本次设计目标是定义 AI Native Business Data OS 的完整目标架构，再将其拆解为模块架构和阶段架构。它不是替代已经批准的 MVP Trusted Loop，而是在 MVP 之上给出完整 OS 北极星，保证后续每个阶段都沿着同一套架构方向生长。

完整 OS 的核心链路是：

```text
Business Goal
  -> BusinessIntent
  -> Semantic Operating Layer
  -> Data Product Compiler
  -> Data Access Plane
  -> Validated DataProduct
  -> EvidenceChain
  -> Insight / Decision Support
  -> Business Agent Runtime
  -> Action Governance Plane
  -> Workflow / Approval / Execution
  -> OperationTrace
  -> Feedback / Evaluation / Memory
  -> Semantic and Knowledge improvement
```

该架构必须同时满足两类目标：

1. 长期产品目标：成为企业业务意图、可信数据产品、业务 Agent、治理动作和组织记忆的统一操作层。
2. 工程落地目标：每个阶段都可以独立验证价值，不把完整 OS 一次性塞进第一版。

结合最新生态位定义，完整 OS 的产品边界进一步明确为：面向企业 AI Agent 时代的 Business Data & Agentic Operations OS。它不能只消费外部数据平台已经准备好的语义层和数据产品，也不能只做 BI 结果之上的行动包装层；它必须逐步拥有或抽象 AI-ready data foundation 的关键能力，包括 Semantic Object、MetricContract、ProviderContract、DataProduct Compiler、metadata/lineage、EvidenceChain 和 Eval，并继续进入 Agent-ready Business Operation 与 Enterprise Knowledge Asset。Aloudata 类 Data Fabric、NoETL、Active Metadata、语义 Agent 能力是长期必须对标并逐步超越的平台能力，但进入 MVP 时必须被压缩为可验证的最小对象和接口。

技术护城河必须沉淀在以下内核中，而不是沉淀在单个模型、单个外部 Agent 框架或单个大数据组件中：

```text
Semantic Contract Kernel
  -> DataProduct Compiler
  -> EvidenceChain
  -> Operation Responsibility Chain
  -> Self-developed Agent Runtime
  -> Eval-driven Improvement
```

工程取舍：第一阶段采用 FastAPI、Pydantic、PostgreSQL JSONB、pgvector、sqlglot、可选 DuckDB、自研 Agent Runtime 和自研 Eval Harness；Trino、Calcite-style planning、OpenLineage、OPA、Temporal、图数据库和完整 Active Metadata Platform 只作为后续阶段能力，不进入 MVP 阻塞路径。

## 2. 架构结论

推荐：**Approve with conditions**。

完整 OS 目标架构成立，但只能作为分阶段建设基线。CTO 不应批准一次性实现完整 OS。第一阶段仍以已批准的 MVP Trusted Loop 为工程主线，后续阶段按模块成熟度逐步打开。

必须坚持三条主线：

1. **可信主线**：所有正式业务答案必须有 EvidenceChain。
2. **治理主线**：所有业务写操作必须经过 Policy、Approval、OperationTrace。
3. **复用主线**：行业差异必须进入 Domain Pack、Provider、Action Connector，不得污染 OS Core。

## 3. 架构原则

| 原则 | 含义 | 反模式 |
|---|---|---|
| Intent-first | 用户入口是业务目标，不是表、SQL、看板 | 把系统做成更会聊天的 BI |
| Contract-first | 数据、动作、模型、工具都通过契约接入 | 让 Agent 自由访问数据库和业务 API |
| Evidence-first | 结论先可复现、可解释、可审计，再追求自动化 | 无证据链直接给经营建议 |
| Policy-before-action | 行动前先做权限、风险、审批和回滚判断 | 高风险动作由模型直接执行 |
| Pack-over-custom | 行业和客户差异沉淀为 Pack，不堆一次性代码 | 每个客户单独定制 Core |
| Eval-gated AI | 模型、prompt、Agent、SQL 变化必须可回归 | 只靠人工感觉判断模型变好 |
| Observability-by-default | intent、query、evidence、action、feedback 全链路可追踪 | 出错后只能翻聊天记录 |

## 4. 完整 OS 逻辑架构

```text
┌─────────────────────────────────────────────────────────────────────┐
│ Experience Plane                                                     │
│ Intent Workspace, Evidence Viewer, Action Center, Admin Console      │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────────────┐
│ API and Orchestration Plane                                          │
│ API Gateway, Workflow Runtime, Agent Orchestrator, Event Bus          │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────────────┐
│ Semantic Operating Layer                                             │
│ BusinessIntent, Semantic Object, MetricContract, Rules, Policies      │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────────────┐
│ Data Product Plane                                                   │
│ DataRequirement, DataProduct Compiler, Query/Transform/Quality Plan   │
└───────────────┬───────────────────────────────┬─────────────────────┘
                │                               │
┌───────────────▼──────────────┐  ┌─────────────▼─────────────────────┐
│ Data Access Plane             │  │ Model and Tool Plane              │
│ Providers, SQL Safety, Cache   │  │ Model Gateway, MCP Gateway, Tools │
└───────────────┬──────────────┘  └─────────────┬─────────────────────┘
                │                               │
┌───────────────▼───────────────────────────────▼─────────────────────┐
│ Evidence and Insight Plane                                            │
│ EvidenceChain, Insight Builder, Report Builder, Confidence, Limits     │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────────────┐
│ Business Agent and Action Plane                                       │
│ Business Agents, ActionProposal, OperationContract, Policy, Approval   │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────────────┐
│ Execution, Trace, Feedback, Memory                                    │
│ Action Connectors, OperationTrace, FeedbackRuntime, KnowledgeAsset     │
└─────────────────────────────────────────────────────────────────────┘
```

横向支撑平面：

```text
Control Plane:
  tenant, workspace, identity, RBAC/ABAC/ReBAC, policy, credential broker,
  quota, cost, audit, deployment registry

Quality Plane:
  eval hub, golden cases, model/prompt regression, contract tests,
  data quality, action policy simulation, release gates

Extension Plane:
  domain pack SDK, provider SDK, action connector SDK, business agent pack,
  eval pack, UI block, workflow handoff, MCP server manifest

Operations Plane:
  observability, trace, logs, metrics, alerts, backup/restore,
  incident review, runbooks, release management
```

## 5. 核心运行流

### 5.1 问数到可信答案

```text
1. 用户提交业务问题或目标。
2. Business Intent Runtime 解析目标、指标、时间、约束和输出形态。
3. Semantic Runtime 绑定 Semantic Object、MetricContract、规则和权限上下文。
4. Data Product Compiler 生成 DataRequirement 和 BuildPlan。
5. Data Access Plane 选择 Provider，生成 QueryPlan 或 TransformPlan。
6. SQL Safety 和 Policy Engine 校验只读、白名单、参数、成本和权限。
7. Provider 执行查询、profile、sample、quality check。
8. EvidenceChain Runtime 汇总数据来源、口径、SQL、质量、血缘、限制。
9. Insight Builder 输出结论、置信度、图表、可解释文本。
10. Eval Hub 记录样本、对比 golden case，失败进入回归集。
```

### 5.2 可信答案到业务行动

```text
1. Business Agent 消费 EvidenceChain，不直接解释底层数据。
2. Action Planner 生成 ActionProposal 或 OperationPlan。
3. Policy Engine 判断风险等级、权限、预算、审批人、职责分离。
4. Action Governance Plane 执行 dry-run、幂等检查、回滚/补偿检查。
5. Approval Workflow 路由人工审批或自动放行低风险动作。
6. Action Connector 执行或创建任务、审批单、通知、业务系统草稿。
7. OperationTrace 记录 evidence、approval、request、response、operator。
8. Feedback Runtime 在观察窗口结束后回收业务指标和人工反馈。
9. Memory Runtime 将成功/失败案例沉淀为 KnowledgeAsset、规则、eval case。
```

### 5.3 组织记忆到持续改进

```text
FeedbackEvent
  -> OutcomeMetrics
  -> EvalCase / GoldenLoop
  -> SemanticConflict or RuleUpdate
  -> Owner review
  -> Versioned KnowledgeAsset
  -> Next run retrieval / policy / compiler improvement
```

系统学习的对象不是模型参数本身，而是企业可治理资产：指标口径、业务规则、审批经验、失败案例、Action 模板、评测样本、数据质量规则。

## 6. 核心对象模型

| 对象 | 归属层 | 核心职责 | 生命周期 |
|---|---|---|---|
| `BusinessIntent` | Semantic / Intent | 记录业务目标、约束和期望输出 | created -> clarified -> planned -> closed |
| `SemanticObject` | Semantic | 表达业务实体、关系、事件和动作 | draft -> reviewed -> published -> deprecated |
| `MetricContract` | Semantic | 稳定指标口径、owner、质量和 verified query | draft -> active -> superseded |
| `DataRequirement` | Compiler | 将 intent 转成数据需求 | generated -> validated -> fulfilled |
| `ProviderContract` | Data Access | 声明数据能力、权限、成本、质量和血缘 | registered -> active -> suspended |
| `DataProduct` | Data Product | 可复用、可验证的数据产物 | planned -> built -> validated -> published |
| `EvidenceChain` | Evidence | 串联证据、限制、质量、口径、血缘和置信度 | built -> validated -> attached -> archived |
| `ActionProposal` | Action | 基于证据生成业务行动候选 | proposed -> approved/rejected -> converted |
| `OperationContract` | Action | 定义动作输入、风险、审批、幂等、回滚 | draft -> active -> retired |
| `OperationTrace` | Trace | 审计业务操作全过程 | opened -> executed -> observed -> closed |
| `FeedbackEvent` | Feedback | 记录采纳、拒绝、业务结果和人工评价 | captured -> classified -> learned |
| `KnowledgeAsset` | Memory | 组织可复用知识、规则、SOP、案例 | draft -> reviewed -> published -> expired |
| `EvalCase` | Eval | 回归测试业务问题、SQL、行动和结果 | added -> active -> retired |

## 7. 数据架构

完整 OS 使用分层数据存储，不把业务数据复制为单一大库。

```text
Metadata Store:
  tenant, workspace, identity, contract, semantic, provider, policy, config

Execution Store:
  intent_run, query_run, compiler_run, agent_run, workflow_run, operation_trace

Evidence Store:
  evidence_chain, claim, quality_result, lineage_snapshot, result_snapshot

Knowledge Store:
  knowledge_asset, business_rule, SOP, lesson, semantic_memory, embeddings

Eval Store:
  eval_case, eval_run, eval_result, golden_query, golden_loop, regression_suite

Audit Store:
  access_log, policy_decision, credential_use, action_audit, admin_change

Object Store:
  uploaded files, report artifacts, chart snapshots, query result snapshots,
  connector payload snapshots with classification
```

推荐默认技术路线：

- PostgreSQL + JSONB 作为 Metadata / Execution / Eval 初始主库。
- pgvector 作为早期 KnowledgeAsset 检索增强。
- Object Store 保存报告、文件、快照和大对象。
- ClickHouse / lakehouse 后置，用于高规模事件、审计和分析型负载。
- 不把客户业务库作为 OS 内部状态库，必须通过 ProviderContract 访问。

## 8. 控制面与权限架构

完整 OS 的权限模型分三层：

| 层 | 控制内容 | 示例 |
|---|---|---|
| Identity | 谁在操作 | tenant、workspace、user、service account、agent identity |
| Authorization | 能访问什么 | RBAC、ABAC、ReBAC、field-level policy、tool scope |
| Governance | 能否执行 | risk policy、approval route、budget/quota、SoD、audit |

关键机制：

1. 每个 Agent 和 Tool 必须有独立 identity，不允许共用系统超级权限。
2. Provider 凭据进入 Credential Broker，不进入 prompt、业务代码或日志。
3. SQL 执行默认只读，写操作只能通过 Action Connector。
4. R4/R5 动作必须人工审批；无回滚能力的动作自动提高风险等级。
5. 敏感字段进入 data classification，EvidenceChain 展示时按权限脱敏。
6. 每次 policy decision 必须记录原因、输入、版本和 trace_id。

## 9. Agent 与模型架构

完整 OS 的 Agent 不是一组自由聊天机器人，而是受契约约束的运行单元。

| Agent | 主要输入 | 主要输出 | 必须通过的 Gate |
|---|---|---|---|
| Intent Agent | raw question, user context | BusinessIntent | schema validation |
| Semantic Agent | intent, registry | semantic resolution | metric/ontology conflict check |
| Compiler Agent | intent, semantic binding | build plan | contract/policy/cost validation |
| Provider Broker Agent | data requirement | provider plan | provider permission and SLA check |
| Quality Agent | data product/result | quality result | quality contract |
| Analyst Agent | evidence inputs | claims, insight | evidence completeness |
| Business Agent | EvidenceChain, policy context | ActionProposal / OperationPlan | action policy simulation |
| Policy Agent | operation plan | policy decision | deterministic policy rules |
| Memory Agent | feedback, trace | KnowledgeAsset / eval case | owner review |
| Eval Agent | candidate output | eval result | golden/regression thresholds |

模型网关负责：

- 统一模型调用、路由、限流、重试、缓存。
- 记录 prompt、model、token、cost、latency、data classification。
- 支持模型升级回归，禁止静默替换关键模型。
- 高风险判断必须由 deterministic policy + 独立审核链路完成，不能只依赖生成模型。

## 10. 扩展生态架构

扩展不是插件随便执行，而是契约化能力接入：

```text
DomainPack:
  semantic objects, metric contracts, question templates, action templates,
  eval packs, UI blocks, provider mappings

Provider:
  inspect, profile, sample, plan, fetch, validate, lineage

ActionConnector:
  dry-run, propose, execute, rollback/compensate, audit, feedback metrics

MCP Server:
  tools/resources/prompts manifest, scopes, risk class, owner, version, signature

Workflow Bridge:
  handoff payload, callback, status mapping, approval state, trace mapping
```

OS Core 只依赖契约，不依赖具体行业、具体 SaaS API、具体采集脚本、具体客户工作流。

## 11. 部署架构

| 形态 | 适用阶段 | 关键能力 |
|---|---|---|
| Local dev | 阶段 0-1 | file provider、sample DB、mock connector、eval harness |
| Single-tenant SaaS | 阶段 1-3 | managed metadata DB、model gateway、basic audit |
| Multi-tenant SaaS | 阶段 5+ | tenant isolation、quota、cost、admin、audit export |
| Hybrid | 阶段 5+ | connector agent、secure tunnel、BYO key、customer data boundary |
| Private deployment | 阶段 6+ | Helm/Docker compose、OIDC、Vault/KMS、backup/restore |
| Air-gapped | 远期 | offline model、offline eval、signed upgrade、local vulnerability mirror |

CTO 判断：阶段 1-3 不应承诺完整私有化。Hybrid 可以作为企业试点能力，但必须在核心闭环有真实客户价值后启动。

## 12. 可靠性、观测和运维

每次运行必须至少产生：

```text
trace_id
intent_id
tenant_id
workspace_id
agent_run_id
model_invocation_id
query_run_id
evidence_chain_id
policy_decision_id
operation_trace_id
eval_result_id
```

关键 SLO：

- Intent 到 EvidenceChain 的成功率。
- SQL Safety 拦截准确率。
- EvidenceChain completeness。
- Golden query regression pass rate。
- Action policy simulation pass rate。
- OperationTrace completeness。
- Feedback capture rate。
- Model cost per successful business run。

运维要求：

- 每次发布前跑 contract、sql safety、evidence、eval、policy simulation。
- 每个事故必须生成 incident review 和 regression eval。
- 高成本模型调用必须可追踪到具体业务价值或失败原因。

## 13. 不做事项

完整 OS 目标架构不意味着现在要做：

- 不一次性实现 Marketplace。
- 不一次性实现所有 Provider 和 Action Connector。
- 不让 Agent 绕过 SQL Safety 或 Action Governance。
- 不把首发内容电商逻辑写进 OS Core。
- 不承诺第一版支持完整私有化或 Air-gapped。
- 不让模型直接决定高风险业务动作。
- 不把评测、审计、权限视为后补能力。

## 14. CTO 审批项

需要 CTO 明确批准：

1. 是否接受完整 OS 目标架构作为未来 3 年技术北极星。
2. 是否确认第一阶段仍只按 MVP Trusted Loop 落地。
3. 是否确认完整 OS 模块只能按阶段门槛逐步打开。
4. 是否要求所有新增平台能力必须有 Contract、Eval、Trace、Policy。
5. 是否要求后续 repo scaffold 在进入阶段 2 前再扩展，而不是现在一次性生成全部目录。
