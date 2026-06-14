# Architecture Design Brief: Full OS Stage Architecture

> Review ID: AR-20260601-full-os-stage-architecture  
> Date: 2026-06-01  
> Prepared by: Architecture Agent  
> Review owner: CTO  
> Status: Proposed for CTO review  
> Scope: staged architecture plan from MVP to full OS  

## 1. 阶段设计目标

完整 OS 必须分阶段建设。阶段架构的目的不是写路线图口号，而是明确每个阶段打开哪些模块、冻结哪些契约、验证哪些业务指标、禁止哪些范围膨胀。

总体演进链路：

```text
Stage 0  Scenario and data readiness
Stage 1  Trusted Data Agent MVP
Stage 2  Data Product Compiler v1
Stage 3  Proposal-based Business Agent
Stage 4  Domain Pack productization
Stage 5  Enterprise pilot and Hybrid support
Stage 6  Platform and ecosystem
```

## 2. 阶段总览

| 阶段 | 核心问题 | 架构状态 | 主要验收 |
|---|---|---|---|
| Stage 0 | 是否值得做、数据是否够用 | 无完整系统，只做样本和口径准备 | 30-50 问题、10-20 golden SQL、owner 明确 |
| Stage 1 | AI 问数能否可信，是否具备最小 AI-ready data foundation | Trusted Loop + semantic/data product lite | 每个正式答案有 EvidenceChain，且绑定 SemanticObject/Metric/Provider/DataProduct candidate |
| Stage 2 | 能否从问答升级为数据产品 | Compiler + DataProduct v1 | 可复用 DataProduct，结果可回放 |
| Stage 3 | 洞察能否转行动提案 | Business Agent proposal runtime | 提案有证据、审批、trace、反馈 |
| Stage 4 | 能否复制到第二业务域 | Domain Pack + eval pack | 新 Pack 不改 Core |
| Stage 5 | 能否服务企业试点 | Tenant、RBAC、Hybrid、audit | 客户数据边界可控、审计可导出 |
| Stage 6 | 能否平台化生态化 | SDK、MCP、Marketplace beta | 多领域、多客户、交付不靠定制 |

## 3. Stage 0：场景和数据准备

建议周期：2-4 周。

### 架构目标

不建设平台，只建立最小工程事实：

```text
business questions
  -> metric dictionary
  -> available data sources
  -> golden SQL
  -> golden business loops
  -> risk and permission list
```

### 必要产物

- 首发业务域和场景边界。
- 30-50 个真实业务问题。
- 10-20 条 golden query。
- 3-5 条 golden business loop。
- 指标字典、数据源清单、owner、敏感字段清单。
- MVP ROI 计算方式。

### 不允许

- 不生成完整 Core 目录。
- 不做平台化 UI。
- 不做自动业务执行。
- 不承诺跨行业。

### 进入 Stage 1 门槛

- 高频问题 80% 可映射已有数据源。
- 核心指标 owner 明确。
- golden SQL 可人工验证。
- 业务 owner 愿意每周参与评测。

## 4. Stage 1：Trusted Data Agent MVP

建议周期：1-3 个月。

### 激活模块

```text
contracts
intent_runtime
semantic_runtime semantic object / metric lite
data_product_compiler candidate only
provider_contract lite
lineage_snapshot lite
query_runtime
sql_safety
providers/postgres_provider
providers/file_provider
evidence_chain v1
action_proposal lite
feedback_runtime lite
trace
eval_hub golden query
apps/api_server
apps/web_workspace minimal
```

### 架构切片

```text
BusinessQuestion
  -> BusinessIntent
  -> SemanticObject lite
  -> MetricContract
  -> ProviderContract lite
  -> DataRequirement / DataProduct candidate
  -> SQLTemplate / QueryPlan
  -> SQLSafety
  -> QueryResult
  -> EvidenceChain v1
  -> Answer
  -> ActionProposal lite
  -> Feedback / Trace
  -> Golden query regression
```

### 关键 Contract

- BusinessIntent。
- SemanticObject lite。
- MetricContract。
- ProviderContract lite。
- DataRequirement lite。
- DataProductCandidate。
- LineageSnapshot lite。
- SQLTemplate。
- QueryPlan。
- QueryResult。
- EvidenceChain v1。
- ActionProposal lite。
- FeedbackEvent lite。
- TraceEvent。

### 不允许

- 不做完整 Data Product Compiler、Data Fabric、NoETL、Active Metadata Platform。
- 不做通用 Provider SDK。
- 不做自动写业务系统。
- 不做 MCP Gateway 全量治理。
- 不做完整 Tenant / Enterprise Admin。

### 进入 Stage 2 门槛

- golden query 正确率 >= 85%。
- 核心指标口径命中率 >= 90%。
- SQL Safety 对写操作和越权 schema 拦截率 100%。
- 每个正式答案 EvidenceChain completeness 达标。
- 业务用户能指出答案依据和限制。

## 5. Stage 2：Data Product Compiler v1

建议周期：3-6 个月。

### 激活模块

```text
data_product_compiler
data_requirement
data_product catalog
provider_contract minimal
quality_contract
lineage_snapshot
evidence_chain v2
eval_hub data product eval
```

### 架构切片

```text
BusinessIntent
  -> SemanticBinding
  -> DataRequirement
  -> ProviderPlan
  -> BuildPlan
  -> Query/Transform/Quality Plan
  -> Validated DataProduct
  -> EvidenceChain v2
  -> InsightOutput
```

### 关键 Contract

- DataRequirement。
- ProviderContract v1。
- BuildPlan。
- QualityContract。
- DataProduct。
- LineageSnapshot。
- EvidenceChain v2。

### 不允许

- 不承诺自动生成任意复杂 ETL。
- 不替代 dbt、Airflow、Dagster。
- 不做所有数据源自动发现。
- 不做业务动作自动执行。

### 进入 Stage 3 门槛

- 至少 10 个 DataProduct 可复用。
- 关键结果可从 EvidenceChain 回放。
- 新增相似问题交付时间低于人工方式 50%。
- DataProduct 有 owner、version、lineage、quality status。

## 6. Stage 3：Proposal-based Business Agent

建议周期：6-9 个月。

### 激活模块

```text
business_agent_runtime lite
action_governance
operation_contract lite
approval_runtime
workflow_runtime lite
operation_trace lite
action_connectors/notification_connector
action_connectors/work_management_connector
feedback_runtime outcome metrics
eval_hub golden business loop
```

### 架构切片

```text
EvidenceChain
  -> BusinessAgentRun
  -> ActionProposal
  -> PolicyDecision
  -> DryRun
  -> ApprovalRoute
  -> Task / Notification / Approval draft
  -> OperationTrace
  -> Outcome Feedback
```

### 动作边界

允许：

- 生成建议。
- 生成审批单。
- 创建任务。
- 推送通知。
- 生成变更计划。
- 对低风险动作执行 dry-run。

不允许默认自动执行：

- 调整广告预算。
- 暂停高价值投放计划。
- 修改 ERP、财务、库存系统。
- 变更客户主数据。
- 绕过审批流执行写操作。

### 进入 Stage 4 门槛

- 至少 3 条 golden business loop 跑通。
- 每个行动提案都有 EvidenceChain 引用。
- 每个审批或任务都有 OperationTrace。
- 行动采纳率、拒绝原因和结果指标可统计。

## 7. Stage 4：Domain Pack 产品化

建议周期：9-12 个月。

### 激活模块

```text
domain_pack_sdk
domain_pack manifest
metric templates
question templates
action proposal templates
provider mappings
eval_pack
ui_block optional
```

### 架构切片

```text
DomainPack
  -> Semantic templates
  -> MetricContract templates
  -> Question templates
  -> Provider mapping
  -> Action templates
  -> EvalPack
  -> UI blocks
```

### 关键原则

Domain Pack 是从复用中抽象出来，不是先验设计大 SDK。只有当首发场景稳定，且第二个业务域开始接入时，才允许把重复能力抽象成 Pack。

### 进入 Stage 5 门槛

- 第二业务域接入周期明显短于第一个。
- 新 Domain Pack 不需要修改 OS Core。
- Pack 自带 eval cases。
- 至少 50% 内核能力可复用。

## 8. Stage 5：Enterprise Pilot and Hybrid

建议周期：12-18 个月。

### 激活模块

```text
tenant_runtime
identity_runtime
RBAC/ABAC basic
credential_broker
connector_agent
secure_tunnel
BYO key governance
audit_export
cost_metering
deployment_profile hybrid
admin_console basic
```

### 架构切片

```text
Tenant / Workspace / User / Role
  -> Identity and policy context
  -> Provider / Connector credential broker
  -> Customer-side Connector Agent
  -> OS control plane
  -> Audit export
  -> Cost and quota
```

### 不允许

- 不做完整 Air-gapped。
- 不做所有云厂商适配。
- 不做复杂 Marketplace。
- 不做完全自助开发者生态。

### 进入 Stage 6 门槛

- 至少一个外部客户或准客户完成试点。
- 客户数据无需完全出内网即可完成核心闭环。
- 审计日志可导出并被客户安全团队理解。
- 客户 key 不进入业务代码、prompt 或日志。

## 9. Stage 6：Platform and Ecosystem

建议周期：18-36 个月。

### 激活模块

```text
multi-tenant control plane
provider_sdk
action_connector_sdk
business_agent_pack_sdk
eval_pack_sdk
mcp_gateway
workflow_bridge
marketplace beta
private deployment template
advanced audit and policy
observability enterprise
```

### 架构切片

```text
Developer / Partner
  -> SDK and manifest
  -> Contract validation
  -> Sandbox eval
  -> Security review
  -> Marketplace publishing
  -> Tenant installation
  -> Runtime policy and audit
```

### 平台化要求

- 扩展包必须声明 owner、version、risk、permissions、eval、rollback。
- Marketplace 只发布通过 contract/eval/security 的包。
- MCP Gateway 必须经过 Tool Registry 和 PolicyEngine。
- Private deployment 必须有 backup/restore、upgrade、compatibility check、incident runbook。

## 10. 阶段推进 Gate

每个阶段进入下一阶段前必须通过 CTO Gate：

| Gate | 必问问题 |
|---|---|
| Business value | 是否有可量化业务收益 |
| Evidence | 关键答案是否可追溯 |
| Eval | golden/regression 是否达标 |
| Usage | 业务用户是否持续使用 |
| Action | 建议是否被采纳或验证 |
| Learning | 失败案例是否进入 eval/memory |
| Architecture | 新能力是否沉淀为 Contract、DataProduct、Pack 或 Eval |
| Customization | 是否出现大量一次性定制代码 |
| Security | 权限、审计、凭证边界是否仍可解释 |
| Maintainability | 团队是否有能力运维当前复杂度 |

## 11. CTO 审批项

1. 是否确认 Stage 1 仍沿用 MVP Trusted Loop。
2. 是否确认 Stage 2 才打开完整 DataProduct / Compiler。
3. 是否确认 Stage 3 只做提案型 Business Agent，不默认自动执行高风险动作。
4. 是否确认 Stage 4 之前不做通用 Domain Pack SDK。
5. 是否确认 Stage 5 之前不承诺企业 Hybrid。
6. 是否确认 Stage 6 之前不承诺 Marketplace 和完整平台生态。
