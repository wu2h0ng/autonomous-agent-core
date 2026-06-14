# AI Native Business Data OS MVP 技术选型与工程工作流

> 日期：2026-05-31  
> 定位：补充 `AI_Native_Business_Data_OS_阶段性落地方案.md`，把第一版产品的技术选型、组件边界、代码工作流、Code Agent 使用方式、Prompt/Skill 设计和云算力策略收敛到可执行范围。

---

## 1. 核心结论

第一版不做完整 OS、Marketplace、全私有化和全自动业务写操作。

第一版只证明一个可信闭环：

```text
BusinessIntent
  -> SemanticObject lite
  -> MetricContract
  -> ProviderContract lite
  -> DataProduct candidate
  -> SQL Safety / Eval
  -> EvidenceChain
  -> ActionProposal
  -> Approval lite
  -> Feedback / Trace lite
  -> KnowledgeAsset candidate
```

产品成败的核心不在于 Agent 多聪明、UI 多完整、数据源多丰富，而在于：

1. 指标口径是否稳定。
2. SQL 和数据访问是否安全。
3. 每个关键答案是否由 DataProduct candidate 和 EvidenceChain 支撑。
4. 每个行动提案是否有证据引用、风险分级、审批建议和 OperationTrace。
5. 失败样本、采纳反馈和业务结果是否能进入回归评测与 KnowledgeAsset candidate。

因此，MVP 的技术策略是：

```text
战略上保留 Business Data & Agentic Operations OS 架构边界
工程上只实现业务生产闭环最小集
复杂治理和生态组件先留接口，不拖慢闭环验证
```

定位修正后的补充判断：MVP 不能退化为 Aloudata 或传统 BI 之上的 Action layer，也不能退化为“可信问数 + 解释文本”。第一版仍然不做完整 Data Fabric、NoETL、主动元数据平台、跨组织数据协作和高风险自动写操作，但必须证明一层可控的 AI-ready data foundation 最小形态，并把它接入 Agent-ready Business Operation 的最小闭环：SemanticObject lite、MetricContract、ProviderContract lite、SQLTemplate、DataProduct candidate、EvidenceChain、Eval、ActionProposal、Approval lite、Feedback/Trace 和 KnowledgeAsset candidate 要能形成端到端链路。否则长期业务生产 OS 定位和 Aloudata 核心竞争者对标会在工程上失焦。

---

## 2. MVP 技术栈

### 2.1 第一版推荐组合

| 层 | MVP 选型 | 说明 |
|---|---|---|
| 前端 | React / Next.js + TypeScript | 用于 Intent Workspace、DataProduct View、Evidence Viewer、Action/Approval Panel 和 KnowledgeAsset Review |
| API 后端 | FastAPI + Pydantic | 契约优先、结构化输出、AI/数据生态成熟 |
| 主数据库 | PostgreSQL | 存储业务对象、契约、DataProduct candidate、OperationTrace、Approval 状态、评测结果和知识资产元数据 |
| 半结构化存储 | PostgreSQL JSONB | 存储 EvidenceChain、Trace、Contract 版本、Agent 输出、DataProduct build plan 和 KnowledgeAsset candidate |
| 向量能力 | pgvector | 支持轻量知识召回、样例问题召回、指标/意图相似度和 KnowledgeAsset 检索 |
| 本地分析 | DuckDB 可选 | 用于 CSV/Excel/样本数据、本地 demo 和 eval fixture，不作为核心生产仓库 |
| 语义与数据产品底座 | 自研 Semantic Runtime lite + DataProduct candidate | 覆盖 SemanticObject lite、MetricContract、ProviderContract lite、DataRequirement/DataProduct candidate、lineage/metadata snapshot，防止产品退化为单纯行动提案层 |
| Agent Runtime | 自研最小 Agent Runtime | 第一版只实现 `AgentRuntime`、`AgentRunContext`、`ToolRegistry`、`StructuredOutputValidator`、`AgentTraceWriter`、`PolicyHook` 的最小闭环 |
| 模型访问 | 轻量 Model Gateway | 支持模型路由、BYO Key 引用、调用日志和预算基础字段 |
| SQL 安全 | 自建 SQL Safety Checker + sqlglot first | 白名单 schema、只读校验、参数绑定、limit、危险语句拦截；后续再评估 ANTLR/Calcite-style compiler |
| 评测 | 自建 Eval Harness | golden intent、golden SQL、metric alias、evidence completeness |
| 异步任务 | RQ / Celery / Arq 任选其一 | 用于短任务、轻队列、评测运行、数据刷新 |
| Trace | 应用内 Trace lite | 先串起 intent、SQL、evidence、proposal、approval |

### 2.2 第一版不必全量引入

| 组件 | MVP 策略 | 后续增强方式 |
|---|---|---|
| Temporal | 留 `WorkflowRuntime` 接口，不默认接管所有异步任务 | 审批、回调、失败恢复、长流程稳定后再接入 |
| OPA | 留 `PolicyEngine` 抽象，不一开始 Rego 化所有规则 | 策略稳定后把高复用规则下沉到 OPA |
| OpenLineage | 留 lineage 字段和事件结构，不先接完整标准 | DataProduct 和编排后端稳定后再映射 OpenLineage |
| MCP Gateway | 留 Tool/MCP Plane 边界，不先做完整 Gateway | 当第三方 MCP 工具进入生产前再做注册、鉴权、沙箱和审计 |
| Domain Pack SDK | 先用首发领域配置表达，不做 SDK | 第二个领域复用成功后再抽象 |
| Marketplace | 不做 | 有可复制 Pack 后再做 |
| 完整私有化 | 不做 | 先做 SaaS / Hybrid 的部署边界和 Connector Agent 概念 |

---

### 2.3 对 Aloudata 技术路线的 MVP 取舍

Aloudata 公开路线可以概括为 Data Fabric、Active Metadata、NoETL 指标语义层和 NL2MQL2SQL Agent。MVP 必须正面对标其 AI-ready data foundation，但不能照搬重型平台建设节奏。

| 能力 | MVP 取舍 | 后续打开条件 |
|---|---|---|
| Data Fabric / 联邦查询 | 只做 `ProviderContract lite`、`ProviderPlan`、单 Provider 或少量 Provider 的 QueryPlan | 第二个真实数据源接入并出现跨源查询刚需 |
| Active Metadata | 只做 metadata/lineage snapshot lite，进入 EvidenceChain | 数据产品、Provider、ActionTrace 稳定后再做主动治理 |
| NoETL 指标语义层 | 只做 `MetricContract` + verified query + DataProduct candidate | 指标 owner、quality contract、materialization 需求稳定后扩展 |
| NL2MQL2SQL Agent | 先做 BusinessIntent -> MetricContract / SQLTemplate 的确定性解析，模型只做候选生成 | golden eval 覆盖足够后再做更自动的 MQL/QueryPlan 编译 |
| 物化加速 | 不做平台级物化，只允许简单 cache / snapshot | 查询频率和成本数据证明 ROI 后再做 |

第一版技术栈的护城河不是大数据组件堆叠，而是 `SemanticObject`、`MetricContract`、`ProviderContract`、`DataProduct candidate`、`EvidenceChain`、`Eval`、`ActionProposal`、`OperationTrace`、`KnowledgeAsset candidate` 和自研 `AgentRuntime` 的组合。

---

## 3. 优先级分层

### 3.1 P0：必须进入 MVP

```text
FastAPI + Pydantic
React / Next.js
PostgreSQL + JSONB + pgvector
DuckDB optional for local/eval only
MetricContract
SemanticObject lite
ProviderContract lite
DataRequirement / DataProduct candidate
Metadata / Lineage snapshot lite
SQL Template / SQL Safety
EvidenceChain
SQL / Intent / Metric Eval
轻量 Model Gateway
自研最小 Agent Runtime
ActionProposal
Approval lite
Trace lite
KnowledgeAsset candidate
```

P0 的验收标准是端到端闭环能被真实业务问题打穿，而不是平台模块看起来完整。

### 3.2 P1：轻实现，不平台化

```text
PolicyEngine abstraction
RiskLevel rules
Provider lifecycle and multi-provider capability
OperationContract lite
OperationTrace lite
Feedback table
```

P1 可以先用 Python 规则、数据库表、配置文件和测试集实现，不急于做成通用规则引擎、知识图谱或治理平台。

### 3.3 P2：只留接口和方向

```text
Temporal
OPA
OpenLineage
MCP Gateway
Domain Pack SDK
Marketplace
Hybrid / Private deployment
完整 Data Fabric / NoETL / Active Metadata Platform
Trino / Calcite-style federated query planning
ANTLR-based compiler if sqlglot becomes insufficient
完整 Business Agent Runtime
```

P2 不进入 MVP 主工程路径。代码结构可以预留边界，但不能成为第一版交付阻塞项。

---

## 4. Agent Runtime 选择

第一版 Agent Runtime 以 ADR-0006 为准：产品 Core Runtime 必须自研。

OpenAI Agents SDK、LangGraph、CrewAI、AutoGen、OpenHands、Goose、Aider、Cline、OpenCode 等开源或商业 Agent 框架，只允许用于：

1. spike 验证。
2. 参考实现研究。
3. 非生产 benchmark。
4. 外部模型、工具调用和 trace 设计参考。

它们不得作为产品 `AgentRuntime`、工具编排、状态管理、权限边界、Agent Memory、Agent Eval 或 Action Governance 的 Core runtime 依赖。

MVP 内部必须自研并稳定这层接口：

```text
agent_runtime/
  AgentRuntime
  AgentRunContext
  ToolRegistry
  StructuredOutputValidator
  AgentTraceWriter
```

模型访问可以通过自研 `ModelProviderAdapter` 调用 OpenAI-compatible API 或客户 BYO Model，但不得把外部 Agent SDK 引入为产品编排内核。

未来如果参考外部框架能力，也只能沉淀到自研 `agent_runtime` 的内部设计和测试用例中，不重写 `intent_runtime`、`data_product_compiler`、`evidence_chain` 和 `action_runtime` 的边界。

---

## 5. 核心对象与数据表

MVP 不追求一次性建完整语义操作系统，但需要从第一天保留核心对象。

### 5.1 Contract 对象

```text
BusinessIntent
SemanticObject
MetricContract
ProviderContract
DataRequirement
DataProductCandidate
SQLTemplate
QueryPlan
QueryResult
EvidenceChain
ActionProposal
ApprovalRecord
OperationTrace
TraceRecord
EvalCase
EvalResult
```

### 5.2 建议表结构方向

```text
core.business_intents
core.semantic_objects
core.metric_contracts
core.provider_contracts
core.data_requirements
core.data_product_candidates
core.lineage_snapshots
core.sql_templates
core.query_runs
core.evidence_chains
core.action_proposals
core.approvals
core.trace_events
core.feedback_events
eval.eval_cases
eval.eval_runs
eval.eval_results
model.model_invocations
```

所有核心表从第一天包含：

```text
tenant_id
workspace_id
created_by
created_at
updated_at
```

如果暂时不做多租户，也要保留字段，避免后续大迁移。

---

## 6. EvidenceChain 优先级

EvidenceChain 是 MVP 的信任基础和正式答案准入门槛，优先级高于 Agent 多智能体、复杂 UI、多数据源和自动写操作。但产品灵魂不是单独的 EvidenceChain，而是可信数据生产、行动提案、审批追踪、反馈学习和知识资产沉淀组成的业务生产闭环。

一个正式答案必须至少包含：

```text
原始业务问题
解析后的 BusinessIntent
命中的 MetricContract
指标口径和 owner
使用的数据源、表、字段
SQL Template / QueryPlan
参数值
SQL Safety 校验结果
权限和数据范围说明
查询结果摘要
质量检查结果
结论、置信度、限制
行动提案引用
Trace id
```

没有 EvidenceChain 的输出只能算 AI 草稿，不能进入正式业务决策。

---

## 7. SQL Safety 与 Eval

### 7.1 SQL Safety 必须覆盖

1. 只允许 `SELECT`。
2. 禁止 `INSERT`、`UPDATE`、`DELETE`、`TRUNCATE`、`DROP`、`ALTER`、`CREATE`。
3. 只允许白名单 schema。
4. 必须使用参数绑定，禁止字符串拼接。
5. 必须有时间范围或行数限制。
6. 必须限制最大扫描成本或最大返回行数。
7. 除零保护、NULL 处理和单位字段要进入模板审查。
8. 记录每次实际执行 SQL、参数、发起用户和 Trace id。

### 7.2 Eval 必须覆盖

| 对象 | 评测方式 |
|---|---|
| Intent 解析 | golden question -> expected intent |
| Metric 命中 | alias / 口径 / owner 命中率 |
| SQL 生成或模板匹配 | golden SQL + result diff |
| SQL 安全 | 危险语句、越权 schema、缺少 limit 拦截 |
| EvidenceChain | 必填字段完整度、证据引用一致性 |
| ActionProposal | 风险等级、审批建议、证据引用 |
| 模型升级 | 回归集对比 |

MVP 的工程习惯应该是：每次修复一个错误，都沉淀一个 eval case。

---

## 8. ActionProposal 与 Approval lite

第一版 Business Agent 不默认执行高风险写操作，只生成行动提案、审批建议、任务、dry-run 结果和反馈指标绑定。

ActionProposal 至少包含：

```text
proposal_id
evidence_chain_id
target_object
recommended_action
reason
risk_level
expected_impact
approval_required
approver_role
dry_run_available
rollback_hint
feedback_metrics
feedback_window
```

风险策略建议：

| 风险 | MVP 处理 |
---|---|
| R0 术语解释、公开信息 | 自动 |
| R1 只读查询、图表 | 自动但审计 |
| R2 报告、数据产品候选 | 自动或轻审批 |
| R3 创建任务、发送通知 | 可配置审批 |
| R4 改业务参数、触发外部同步 | 只提案，强审批 |
| R5 预算、价格、库存、删除、权限 | 只提案，双人复核，MVP 不自动执行 |

---

## 9. Coding Workflow

### 9.1 推荐研发流程

```text
业务问题样本
  -> Contract 设计
  -> Threat / Safety 边界
  -> Eval case
  -> Reference implementation
  -> Local smoke
  -> PR review
  -> Regression eval
  -> Release note
```

### 9.2 PR 必须回答

1. 改动属于 Core、Provider、Action、Eval 还是 UI？
2. 是否改变 Contract？
3. 是否新增或修改 golden case？
4. 是否影响 SQL Safety？
5. 是否影响 EvidenceChain 完整性？
6. 是否引入新的工具、模型或数据出域？
7. 是否影响风险分级或审批路径？
8. 是否有 Trace 可回放？

### 9.3 CI 最小集

```text
unit tests
contract schema tests
sql safety tests
golden query tests
intent / metric eval
evidence completeness tests
action risk tests
basic frontend smoke
```

不要等平台化后才建立 eval。没有 eval 的 Agent 产品只能 demo，不能进入企业场景。

---

## 10. Code Agent 使用方式

Code Agent 适合提升工程速度，但不能替代产品边界和评测。

### 10.1 推荐分工

| Agent 类型 | 职责 |
|---|---|
| Product Architect Agent | 检查抽象是否过度平台化或写死行业逻辑 |
| Contract Agent | 维护 Pydantic schema、JSON schema、示例和兼容性测试 |
| Implementation Agent | 实现 API、服务、工具函数和 UI |
| Eval Agent | 补充 golden case、回归测试和失败样本 |
| Security Review Agent | 检查 SQL 安全、权限、敏感数据、工具风险 |
| PR Review Agent | 以代码审查方式发现 bug、回归和缺失测试 |

### 10.2 推荐工具组合

| 用途 | 推荐 |
|---|---|
| 主力异步研发 | Codex |
| IDE 内联补全和小改动 | Cursor / GitHub Copilot |
| 复杂设计或第二意见 | Claude Code |
| 全托管任务试点 | Devin 类工具可小范围验证，不作为主路径 |

### 10.3 Code Agent 守则

1. 不允许无 eval 改动 prompt 或模型。
2. 不允许绕过 Contract 直接拼接 Agent 输出。
3. 不允许直接生成生产 SQL 执行路径，必须经过 SQL Safety。
4. 不允许把首发内容电商逻辑写进 Core。
5. 不允许把高风险业务动作做成默认自动执行。
6. 每个 bug 修复都要尽量沉淀 regression case。

---

## 11. Prompt 与 Skill 设计

不要把产品能力塞进一个超长系统提示词。应拆成版本化 skill。

建议结构：

```text
skills/
  intent_parser/
  metric_resolver/
  sql_planner/
  sql_safety_checker/
  evidence_chain_builder/
  action_proposal_builder/
  policy_reviewer/
  connector_certifier/
  content_commerce_domain/
```

每个 skill 至少包含：

```text
SKILL.md
input_schema.json
output_schema.json
allowed_tools.md
positive_examples.jsonl
negative_examples.jsonl
eval_cases.jsonl
owner.md
```

Prompt 设计原则：

1. Prompt 只负责推理和结构化输出，不负责权限判定。
2. 权限、SQL 安全、风险分级必须由代码和测试执行。
3. Data Agent 只输出结构化 EvidenceChain，不执行业务写操作。
4. Business Agent 只能消费 EvidenceChain，不自由解释指标口径。
5. 没有 EvidenceChain，不允许生成高影响业务建议。
6. 没有 OperationContract，不允许调用 Action Connector。

---

## 12. 云服务与硬件策略

MVP 不建议自购 GPU。第一版优先使用外部模型 API 和客户 BYO Key，把工程精力放在 DataProduct candidate、EvidenceChain、ActionProposal、OperationTrace、KnowledgeAsset candidate、评测、权限和业务生产闭环上。

### 12.1 阶段建议

| 阶段 | 推荐 |
|---|---|
| MVP / 内部试点 | 无 GPU，使用模型 API + 轻量 Model Gateway |
| 企业 Hybrid | SaaS 控制面 + 客户内网 Connector Agent，默认 outbound-only |
| 私有化轻量版 | 24-48GB GPU，用于 embedding、rerank、小模型 |
| 私有化标准版 | 1 张 96GB GPU 或 2 张 48GB GPU |
| 大企业私有推理 | H100 / H200 / Blackwell 等 GPU 集群 + vLLM / Triton |
| 离线强合规 | Air-gapped profile，离线模型、离线 eval、离线升级包 |

### 12.2 云厂商选择

| 客户环境 | 优先选择 |
|---|---|
| Microsoft 生态强 | Azure |
| AWS 数据湖、企业 VPC 成熟 | AWS |
| BigQuery / Vertex AI 生态 | Google Cloud |
| 中国大陆企业 | 阿里云百炼 / PAI、火山方舟等 |
| 客户已有模型合同 | BYO Key / BYO Model 优先 |

原则：

1. 第一版不要同时适配所有云。
2. Model Gateway 必须屏蔽模型供应商差异。
3. 客户 Key 不进入业务代码，不落明文。
4. 每次模型调用记录 tenant、workspace、purpose、model、cost、data classification。
5. 私有模型必须跑 eval 才能进入生产。

---

## 13. MVP 成功标准

第一版至少满足：

1. 20 条 golden query 可稳定运行。
2. 高频问题意图识别和指标命中率达到阶段阈值。
3. 所有正式答案都有 EvidenceChain。
4. SQL 安全校验 100% 拦截写操作和非白名单 schema。
5. 每个行动提案都有证据引用、风险等级、审批建议和 OperationTrace。
6. 失败样本、采纳反馈和业务结果能进入 eval 回归集或 KnowledgeAsset candidate。
7. Trace 能串起：

```text
intent
  -> metric
  -> SQL
  -> result
  -> evidence
  -> proposal
  -> approval
  -> feedback
```

8. 新增一个相似业务问题的交付时间显著低于人工方式。
9. 业务 owner 能看懂证据链并愿意据此做判断。
10. 团队没有被 Temporal、OPA、OpenLineage、MCP Gateway、Marketplace 等平台工程拖住。

---

## 14. 决策检查清单

新增功能进入 MVP 前必须回答：

1. 它是否直接增强“DataProduct candidate + EvidenceChain + Governed Operation + KnowledgeAsset candidate”业务生产闭环？
2. 如果没有它，闭环是否无法验收？
3. 它是 P0、P1 还是 P2？
4. 它是否可以先用轻实现代替？
5. 它是否会引入新的数据出域、写操作或权限风险？
6. 它是否有 eval case？
7. 它是否会把首发行业逻辑写死进 Core？
8. 它是否会让团队提前进入平台化建设？
9. 它是否能被真实业务 owner 感知价值？
10. 它是否服务 EvidenceChain，而不是绕开 EvidenceChain？
11. 它是否补强 AI-ready data foundation 的最小闭环，而不是只增加上层交互或行动包装？

如果答案不清楚，默认不进入 MVP。

---

## 15. 最终判断

AI Native Business Data OS 的长期方向成立，但第一版必须减负。

正确的工程姿势是：

```text
先把可信证据链做成产品心脏
再让 Agent、工作流、治理和生态一圈圈长出来
```

只要 SemanticObject lite、MetricContract、ProviderContract lite、DataProduct candidate、EvidenceChain、SQL Safety、Eval、ActionProposal、Approval lite、OperationTrace 和 KnowledgeAsset candidate 站稳，后续引入 Data Fabric、NoETL、Active Metadata、Temporal、OPA、OpenLineage、MCP Gateway、Domain Pack 和私有化部署才有意义。

---

## 16. NL2SQL 准确率工程：三层SQL生成策略

> 补充来源：深度分析报告 — 技术层补充。

当前方案中 SQL 生成路径是：BusinessIntent → MetricContract → SQLTemplate → 模型生成。这在高频标准问题上效果好，但边缘问题（长尾查询）的处理策略不足。

### 16.1 三层策略

**层1 - 确定性路径（覆盖80%高频问题）**

- Golden Query 直接命中 → 返回预验证SQL，不走模型
- MetricContract + SQLTemplate 参数化填充 → 安全高效
- 策略：每个 MetricContract 默认绑定3-5个经过回归验证的 SQLTemplate
- 优势：零模型调用成本、100%语法安全、响应时间 < 500ms

**层2 - 引导生成路径（覆盖15%中频问题）**

- 模型基于 SemanticObject + MetricContract 生成候选SQL
- sqlglot 语法校验 → SQL Safety 检查 → 参数绑定验证
- 结果需要通过 eval 评分（≥ 0.85）才能返回正式答案
- 优势：覆盖预定义模板之外的合理查询

**层3 - 降级路径（处理5%边缘问题）**

- 明确告知用户"当前问题需要数据团队配置才能回答"
- 自动生成需求工单（含原始问题、已尝试的匹配、建议的新MetricContract草稿）
- 触发 MetricContract 更新流程
- 原则：不用错误答案糊弄用户

### 16.2 层间流转机制

```text
用户问题
  → 层1匹配？→ 是 → 直接返回（< 500ms）
  → 否 → 层2生成？→ 成功且评分 ≥ 0.85 → 返回+自动纳入层1候选
  → 否 → 层3降级 → 生成需求工单 → 通知数据团队
```

### 16.3 关键指标

| 指标 | 目标 |
|---|---|
| 层1命中率 | ≥ 80% |
| 层2通过率 | ≥ 70% |
| 层3降级率 | ≤ 5% |
| 层2→层1自动升级率 | ≥ 30%（连续3次通过层2的问题自动升级） |

---

## 17. Agent Runtime 自研风险与渐进策略

> 补充来源：深度分析报告 — 技术层补充。

当前文档决定自研 Agent Runtime，理由是"避免被外部框架锁死"。判断成立，但风险需要显式建模和分阶段管理。

### 17.1 自研风险清单

| 风险 | 影响 | 概率 |
|---|---|---|
| 工具调用(Tool Use)状态机复杂 | Agent死循环或工具调用失败无恢复 | 高 |
| 上下文管理窗口溢出 | 多轮对话后Agent丢失关键上下文 | 中 |
| 并发Agent调度 | 多用户同时使用时资源竞争 | 中 |
| 失败重试与降级逻辑 | 单点失败导致整个链路不可用 | 高 |
| 结构化输出验证 | 模型输出不符合Contract Schema | 高 |
| 与LangGraph/CrewAI功能差距 | 社区生态缺失（无现成工具、连接器、调试工具） | 中 |

### 17.2 渐进式自研策略

**短期（MVP阶段，0-6个月）**

- 保持产品 Core Runtime 自研，先实现最小可控状态机、工具注册、结构化输出验证、失败重试和 Trace 写入
- LangGraph、CrewAI、OpenAI Agents SDK 等只能用于 spike、benchmark、参考实现研究和测试样本设计
- 不允许把外部 Agent 框架作为 `AgentRuntime`、工具编排、状态管理、权限边界、Agent Memory、Agent Eval 或 Action Governance 的生产依赖
- 关键原则：宁可 MVP 编排能力少，也不能让产品 Core 依赖外部 Agent 框架形成锁定

**中期（6-12个月）**

- 扩展自研 `AgentRuntime`，补齐上下文窗口管理、工具调用恢复、并发执行、可观测性和 Eval 回放
- 外部 `AgentRuntime` 接口保持稳定，客户和上层应用无感知
- 自研重点：业务生产闭环特有逻辑（DataProduct 编译、EvidenceChain 生成、SQL Safety 串联、Contract 验证、Action Governance、OperationTrace、KnowledgeAsset candidate 提取）

**长期（12个月+）**

- 完全自研 Runtime，聚焦本项目独特需求：
  - Contract驱动的Agent编排
  - EvidenceChain完整性强制校验
  - Policy Engine原生集成
  - Trace-by-default可观测性

### 17.3 关键决策点

- 如果自研 Runtime 阻塞 MVP 闭环超过两周，可以批准外部框架 spike 作为对照实验，但不得进入产品 Core
- 如果 spike 发现成熟框架能力有价值，只能把能力沉淀为自研接口、测试用例或设计约束
- 如果自研 Runtime 复杂度持续上升，优先收窄 MVP Agent 自动化范围，而不是引入生产级外部 Agent 框架依赖

---

## 18. 向量存储升级路径

> 补充来源：深度分析报告 — 技术层补充。

当前 pgvector 选型合理（PostgreSQL插件，适合MVP）。随着 KnowledgeAsset 积累，需要提前规划升级路径。

| 阶段 | 方案 | 适用条件 |
|---|---|---|
| **当前(MVP)** | pgvector | 向量数量 < 100万，召回延迟 P95 < 200ms |
| **升级触发1** | 向量数量超过500万 |
| **升级触发2** | 召回延迟 P95 > 200ms，影响用户体验 |
| **升级触发3** | 需要混合检索（向量 + 全文 + 结构化过滤） |
| **候选方案1** | Qdrant（轻量独立部署，Rust实现，性能优秀） |
| **候选方案2** | Weaviate（语义搜索强，内置向量化和混合检索） |
| **原则** | 保持 ProviderContract 抽象，向量存储可替换不侵入Core |

---

## 19. 多模型路由策略

> 补充来源：深度分析报告 — 技术层补充。

Model Gateway 设计提到 BYO Key 和多模型路由，以下是具体的路由策略建议。

### 19.1 按任务类型分模型

| 任务 | 优先级 | 推荐模型 | 路由策略 |
|---|---|---|---|
| 意图解析(BusinessIntent) | 速度 | GPT-4o-mini / Qwen-7B / DeepSeek-V2-Lite | 本地优先，超时切换云端 |
| SQL生成(MetricContract→SQL) | 准确率 | Claude Sonnet / GPT-4o / DeepSeek-V2 | 主模型+备模型双路生成，eval选优 |
| 证据链生成(EvidenceChain) | 推理能力 | Claude Sonnet / GPT-4o | 单模型，要求结构化输出严格校验 |
| ActionProposal风险评估 | 安全 | 大模型 + Policy Engine双重校验 | 模型生成提案，Policy Engine做合规校验 |
| KnowledgeAsset候选提取 | 复利 | 大模型 + 人审 + eval绑定 | 从 EvidenceChain、OperationTrace 和反馈中提取可复用知识资产 |
| 嵌入/召回(pgvector) | 成本 | BCE / BGE / text2vec-large-chinese | 国产嵌入模型优先，成本敏感 |

### 19.2 路由决策矩阵

```text
路由判断流程：
  1. 识别任务类型 → 确定优先级（速度/准确率/成本/安全）
  2. 检查客户 BYO Model 配置 → 优先使用客户指定模型
  3. 检查模型可用性 → 主模型不可用时自动切换备模型
  4. 检查成本预算 → 超过单日预算时降级到低成本模型
  5. 记录路由决策 → 用于事后成本分析和模型效果对比
```

### 19.3 关键原则

- 模型不可锁定：所有模型调用必须通过统一的 `ModelProviderAdapter` 接口
- 客户可控：客户可以在 workspace 级别配置偏好的模型和预算上限
- 可对比：同一任务可以用不同模型生成结果，通过 eval 选出最优
- 降级保护：任何模型不可用时，系统要有降级路径（本地小模型或规则引擎）

---

## 20. 可观测性体系设计

> 补充来源：深度分析报告 — 技术层补充。

当前 Trace lite 覆盖了基本的 Intent→SQL→Evidence 链路，但缺少完整的可观测性体系。

### 20.1 四层可观测

| 层级 | 内容 | 工具 | MVP优先级 |
|---|---|---|---|
| **业务可观测** | 每日 DataProduct candidate 生成量、EvidenceChain 生成量、ActionProposal 采纳率、KnowledgeAsset candidate 通过率、用户活跃趋势 | Grafana + 自建Dashboard | P0 |
| **质量可观测** | Golden Query通过率周趋势、SQL Safety拦截率、语义解析准确率 | Grafana + Eval Reporter | P0 |
| **成本可观测** | 每次EvidenceChain的模型调用成本、Token用量、各模型用量占比 | OpenTelemetry + Grafana | P1 |
| **系统可观测** | API延迟P50/P95/P99、错误率、数据库连接池、内存/CPU | OpenTelemetry + Grafana/Datadog | P0 |

### 20.2 告警机制

| 告警条件 | 严重级别 | 通知对象 |
|---|---|---|
| Golden Query通过率 < 80% | P0-Critical | 工程全员 + CTO |
| SQL Safety拦截率 < 100% | P0-Critical | 安全负责人 + CTO |
| P95响应时间 > 30s | P1-Warning | 工程值班 |
| 单日模型成本超出预算120% | P1-Warning | CTO + 产品负责人 |
| 系统可用率 < 99.5% | P0-Critical | SRE + CTO |

### 20.3 接入建议

- MVP阶段就接入 OpenTelemetry（已在参考资料列表），配合 Grafana 做基础监控大盘
- 这对后续卖给企业客户的"可审计性"也是加分项
- 所有 Trace 数据保留至少90天，企业版可自定义保留期

---

## 21. 开发者体验与API设计策略

> 补充来源：深度分析报告 — 扩展分析维度。

作为瞄准生态和 Marketplace 的产品，开发者体验(DevEx)是第二增长曲线的基石。Domain Pack开发者、Provider开发者、ISV都需要优秀的API体验。

### 21.1 API设计原则

| 原则 | 说明 |
|---|---|
| **Contract-first** | 所有API先定义OpenAPI/Pydantic schema，再实现 |
| **SDK生成** | 从Contract自动生成Python/TypeScript SDK，减少手动维护 |
| **幂等性** | 所有写操作支持幂等key，防止重复提交 |
| **版本化** | API版本化(/v1/)，废弃至少提前6个月通知 |
| **自描述** | 错误消息包含可操作的修复建议，而非仅返回错误码 |
| **速率限制透明** | 在响应头中返回剩余配额和重置时间 |

### 21.2 开发者工具链

| 工具 | 用途 | 优先级 |
|---|---|---|
| **CLI工具** | 创建Domain Pack、本地测试Provider、发布到Marketplace | P1 |
| **本地沙箱** | Docker Compose一键启动OS Core + Mock Provider | P1 |
| **API Playground** | 在线交互式API文档（基于OpenAPI/Swagger） | P0 |
| **Domain Pack模板** | 脚手架生成器，5分钟创建新Pack | P2 |
| **Eval Runner** | 本地运行Golden Query回归测试 | P0 |

### 21.3 文档体系

| 文档 | 内容 | 优先级 |
|---|---|---|
| API Reference | 完整API文档（自动生成） | P0 |
| Provider开发指南 | 如何接入新数据源 | P0 |
| Domain Pack开发指南 | 如何创建行业Domain Pack | P1 |
| Action Connector开发指南 | 如何接入业务系统 | P1 |
| 最佳实践 | 常见场景的推荐实现模式 | P2 |
