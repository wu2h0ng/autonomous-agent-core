# AI Native Business Data OS 技术 PRD 与架构设计

> 版本：v1  
> 日期：2026-05-31  
> 定位：面向未来 10 年的通用商业数据和业务智能操作系统技术方案
> 关键判断：内容电商、内部运营、数据采集都只能是验证场景或能力 Provider，不能成为核心架构身份。Data Agent 也不是最终产品形态，真正价值是让 Data Agent 驱动 Business Agent，形成可信、可验证、可审批、可追溯的业务操作闭环。

---

## 1. 战略结论

传统数据基础设施的核心问题不是数据库、ETL、BI、数仓技术不够好，而是它们把“表、SQL、任务、看板、工程排期”放在产品中心。业务人员真正关心的是目标、异常、机会、约束、行动和结果，但传统体系要求业务必须先经过数据分析师和工程师翻译，才能进入数据系统。

AI 原生业务数据操作系统要推倒的不是物理基础设施，而是这套中心范式。

新的中心抽象不是孤立的 Data Agent，而是数据智能和业务智能的闭环：

```text
Business Intent
  -> Data Agent
  -> Trusted Data Product / Evidence Chain
  -> Business Agent
  -> Governed Business Operation
  -> Operational Feedback
  -> Data Agent / Semantic Memory
```

也就是说，用户表达业务意图后，Data Agent 负责组织数据能力、生成可验证数据产品和证据链；Business Agent 负责把证据转成业务动作、审批流程、执行计划和后续生产操作；执行结果再回流到 Data Agent，更新指标、事件、语义、评测和业务记忆。

这不是 Agent BI，也不是下一代数据中台，也不是孤立的 Data Agent OS，而是 **Business Data & Agentic Operations OS**。

更准确地说，本项目要占据的是企业 AI Agent 时代的 Business Data & Agentic Operations OS 生态位：既要覆盖 AI-ready Data Foundation，也要继续延伸到 Agent-ready Business Operation 和 Enterprise Knowledge Asset。Business Data Control Plane 是其中的治理控制面能力，不是产品全部身份。Aloudata 代表的 NoETL、Data Fabric、主动元数据、指标语义层和分析 Agent 不是可以绕开的旁路能力，而是本项目必须纳入底座、做得更好、并向上扩展的核心战场。

生态位定义见：

```text
01_战略定位与技术PRD/AI_Native_Business_Data_OS_生态位定义与Agent_OS长期定位.md
```

### 1.1 Data Agent 与 Business Agent 的职责边界

| 层 | 核心职责 | 不应承担 |
|---|---|---|
| Data Agent | 理解数据语义、发现数据需求、编译数据产品、生成证据链、评估置信度、监控反馈数据 | 直接越权执行业务写操作 |
| Business Agent | 理解业务目标、选择行动策略、生成操作计划、发起审批、调用业务系统、追踪执行结果 | 自由解释指标口径或绕过证据链决策 |
| Policy/Governance | 判断权限、风险、审批路径、预算边界、回滚要求、审计记录 | 替代业务责任人 |
| Provider/Action Connector | 提供数据能力或业务动作能力 | 决定业务目标和策略 |

Data Agent 和 Business Agent 是协作关系，而不是上下游脚本调用。Data Agent 提供可信证据，Business Agent 负责受控行动，Governance 保证边界，Feedback Loop 保证持续学习。

### 1.2 不是为了推倒数据基础设施，而是重构数据到业务生产的接口

传统数据中台、BI、数据库、ETL、指标平台和湖仓仍然有价值，它们承载企业已有数据资产、计算能力、治理规则和历史沉淀。问题不在于这些系统应该被全部替换，而在于它们通常停在“数据生产”和“数据消费”之间，不能天然把业务意图转成可信数据产品，再把数据证据转成受控业务操作。

AI Native Business Data OS 的目标不是消灭所有传统基础设施，而是把它们降级为可编排能力层：

| 传统系统 | 在 OS 中的新角色 | 不再承担的职责 |
|---|---|---|
| 数据库/湖仓 | Data Provider 和计算执行后端 | 直接成为业务人员入口 |
| ETL/dbt/Dagster | Data Product build backend | 由工程师手写所有业务需求 |
| BI/看板 | 可视化和结果消费界面 | 作为唯一分析入口 |
| 指标平台/语义层 | MetricContract 和 Semantic Object 来源 | 孤立维护口径 |
| CRM/ERP/广告/客服系统 | Action Connector 和业务执行系统 | 各自独立解释数据并决策 |

真正要推倒的是割裂的责任链：

```text
业务问题
  -> 人工翻译成数据需求
  -> 工程师/分析师开发
  -> 看板或报表交付
  -> 业务人员再人工判断
  -> 另一个系统里执行动作
  -> 结果很难回流验证
```

新的责任链应该是：

```text
业务意图
  -> Data Agent 编译可信数据产品
  -> EvidenceChain 说明依据、限制和风险
  -> Business Agent 生成操作计划
  -> PolicyEngine 和 ApprovalWorkflow 控制权限
  -> ActionConnector 执行业务动作
  -> OperationTrace 记录全过程
  -> FeedbackRuntime 反馈结果并更新语义记忆
```

因此，本产品的价值不是“少写 SQL”或“减少看板开发”本身，而是让数据从被动解释工具变成业务生产系统的可信输入。

---

## 2. 未来 10 年趋势判断

### 2.1 2026-2028：AI BI 和 Agentic Analytics 成为标配，但仍被旧数据栈约束

Databricks Genie、Snowflake Cortex Analyst、Microsoft Fabric Copilot、Tableau Next、ThoughtSpot Spotter、SmartBI 白泽等产品都在证明一个方向：自然语言分析必须依赖语义层、verified queries、权限、数据治理和反馈机制。

这个阶段的行业共识会是：

- 裸 LLM + SQL 不能进入生产。
- 结构化知识不能靠 RAG 近似检索。
- 语义层是 AI 分析可靠性的前置条件。
- Agent 必须有工具、权限、审计和评测。
- 企业会快速淘汰缺少 ROI 和治理的 Agent 项目。

但这些产品大多仍然继承旧范式：用户必须先有数仓、指标模型、数据团队、BI 资产，Agent 只是更聪明的访问入口。

### 2.2 2028-2031：从“问数”转向“数据产品自动生成”

下一阶段竞争焦点会从“能不能回答问题”转向“能不能端到端生成可验证数据产品”。

数据产品不再只是表或看板，而是一个包含契约、证据、质量、权限、血缘、版本和反馈的运行对象：

```text
DataProduct =
  business_intent
  semantic_bindings
  data_requirements
  provider_plan
  transformations
  quality_contracts
  evidence_chain
  insight_outputs
  action_candidates
  evaluation_results
```

这意味着 ETL、BI、指标开发会被“Data Product Compiler”重新组织。工程师不再逐个响应报表需求，而是维护编译器、运行时、Provider SDK、策略和评测体系。

### 2.3 2031-2034：Business Ontology 和 Action Runtime 取代 BI 成为企业操作界面

Palantir AIP/Foundry 已经展示了这个方向：企业系统的核心不是表，而是 ontology、对象、关系、动作、工作流和治理。未来企业级 AI 系统会要求：

- 业务对象可被 AI 理解。
- 业务动作可被 AI 调用。
- 每次决策可被追溯。
- 执行结果可被反馈学习。
- 语义、权限、流程和数据联动。

BI 会退化为一种输出形态，真正的产品中心会变成“业务对象工作台”和“行动流”。

这一阶段的核心竞争不是“谁的数据 Agent 更会分析”，而是谁能把 Data Agent 输出变成可控的业务生产能力。企业需要的不是一个会回答问题的分析师 Agent，而是一组可信业务 Agent：

- Sales Agent 根据 pipeline 和转化证据生成销售动作。
- Finance Agent 根据现金流和预算证据生成财务控制动作。
- Supply Chain Agent 根据库存、需求和供应风险生成补货或调拨动作。
- Marketing Agent 根据投放、内容和用户反馈生成增长动作。
- Customer Success Agent 根据健康度和工单证据生成续约或挽留动作。

Data Agent 是这些 Business Agent 的可信数据感知层。Business Agent 是数据智能进入业务生产系统的执行层。

### 2.4 2034-2036：数据基础设施变成隐形层，业务人员直接驱动数据工作流

未来 10 年的终局不是“人人会写 SQL”，也不是“人人搭 BI”，而是：

```text
业务人员表达目标
AI 系统生成数据需求和证据
系统调用合适的数据能力 Provider
自动验证质量和口径
生成方案并执行
结果回流更新业务记忆
```

数据库、湖仓、ETL、调度、BI、爬虫、API 连接器仍然存在，但它们不再是用户或产品的中心，而是 Data Access Plane 里的可插拔能力。

同理，业务系统、审批系统、工单系统、CRM、ERP、广告平台、客服系统、供应链系统仍然存在，但它们也不应成为产品中心，而应成为 Business Action Plane 的可插拔能力。OS 的价值在于统一编排这些能力，而不是替代每一个业务系统。

---

## 3. 竞品技术实现分析

### 3.1 Palantir AIP / Foundry

Palantir 是最接近 Business Data OS 的竞品。它的核心不是 BI，而是 Ontology。

技术实现特征：

- 以业务对象和关系组织数据，而不是直接暴露表。
- Ontology 对象可以绑定数据源、权限、业务动作和工作流。
- AIP Agent 可以在受控边界内读取对象、生成分析、触发动作。
- 强调审计、权限、版本、部署和人机协作。
- 通过 workshop/bootcamp 快速把客户业务流程转为 AI workflow。

启示：

- 通用商业数据 OS 必须有 ontology 或 semantic object model。
- Action 不能是附属能力，必须进入对象模型。
- 高价值企业客户愿意为“语义 + 行动 + 治理”付费。

局限：

- 重交付、重企业咨询、成本高。
- 不适合中小企业快速 SaaS 化。
- 行业包和连接器生态不是轻量开发者友好形态。

### 3.2 Snowflake Cortex Analyst / Cortex Agents

Snowflake 的路线是从数据云向 Agentic Data App 扩展。

技术实现特征：

- Cortex Analyst 依赖 semantic model，让自然语言问题映射到表、列、指标和 verified queries。
- Cortex Agents 把结构化查询、非结构化检索、工具调用组合为 Agent 工作流。
- 权限和数据执行仍在 Snowflake 内部完成。
- 强调 governed data 和企业数据安全。

启示：

- 语义模型必须机器可读、版本化、可测试。
- Agent 要通过工具访问数据，而不是直接自由访问数据库。
- 结构化和非结构化数据需要统一工作流。

局限：

- 仓库中心化，仍假设客户已经在 Snowflake 上建好数据资产。
- 主要解决数据访问和分析，不负责跨业务系统行动闭环。

### 3.3 Databricks AI/BI Genie

Databricks 的方向是 Lakehouse 上的 AI/BI。

技术实现特征：

- Genie Space 通过语义知识、说明、样例问题、表和指标上下文提升问数准确率。
- 与 Unity Catalog、权限、血缘、数据治理结合。
- 强调 compound AI system，而不是单模型问答。
- 适合已经在 Lakehouse 中沉淀数据资产的企业。

启示：

- 企业会接受“语义空间”作为业务数据问答的配置单元。
- 数据治理、目录、血缘和权限是 AI 分析的底座。
- 人类反馈和可信问题集是提升准确率的关键。

局限：

- 仍然是 Lakehouse/BI 中心路线。
- 对业务行动和跨系统执行不是核心产品。

### 3.4 Microsoft Fabric / Power BI Copilot

Microsoft 的优势是把 Copilot 嵌入 Office、Power BI、Fabric、Teams 等工作流。

技术实现特征：

- 依赖 Power BI semantic model。
- Copilot 可生成 DAX、报告、解释、摘要。
- Fabric 提供 OneLake、数据工程、数据科学、实时分析和 BI 一体化平台。
- 与企业身份、权限、协作工具深度集成。

启示：

- AI 数据产品必须进入业务协作流，而不是只停在分析页面。
- 语义层与办公/协同/审批结合会形成强粘性。

局限：

- 仍围绕 Microsoft 生态和 BI 资产。
- 业务行动闭环依赖外部 Power Platform 或客户自建流程。

### 3.5 Tableau Next / Salesforce

Tableau Next 的方向是 Agentic Analytics，背后依赖 Salesforce 的语义、数据和工作流生态。

技术实现特征：

- 通过 semantic layer 和 agent interface 做自然语言分析。
- 与 Salesforce CRM 对象、业务流程、Data Cloud 结合。
- 输出不只是图表，也包括 workflow 和业务建议。

启示：

- 数据分析未来会进入业务系统对象，而不是孤立看板。
- CRM、销售、客服等领域会优先出现 Business Data OS 类产品。

局限：

- 强 Salesforce 生态绑定。
- 通用跨系统 OS 能力受限于平台边界。

### 3.6 ThoughtSpot Spotter / Agentic Analytics

ThoughtSpot 长期做 Search Analytics，Spotter 是其 AI 化升级。

技术实现特征：

- 通过 Spotter Semantics 定义术语、同义词、业务规则和查询行为。
- 强调 deterministic SQL generation 和自然语言搜索。
- 面向业务用户降低分析门槛。
- 开始支持 agentic analytics 和外部 Agent 接入。

启示：

- 业务用户直接分析是刚需。
- 语义层不仅是字段映射，还包括语言、行为和查询习惯。

局限：

- 主要仍是 analytics consumption。
- 不负责数据产品生成和业务执行闭环。

### 3.7 SmartBI 白泽、Aloudata Agent 等国内 AgentBI

国内 BI 厂商正在快速将 AI、语义层、指标体系、多智能体、权限审计接入既有 BI 平台。

技术实现特征：

- 指标体系 + 多智能体。
- NL2SQL 或 NL2MQL2SQL。
- 报告生成、归因分析、智能问数。
- 与国产模型和私有化交付结合。

启示：

- 国内企业采购会认可私有化、权限、审计、指标体系。
- “准确率”和“口径一致”是销售关键。

局限：

- BI 基因重，仍围绕数据团队和看板资产。
- 很难推倒 ETL/BI 中心范式。

### 3.8 Matillion Maia、Acceldata、Teradata AgentStack 等 DataOps/Agentic Data Engineering

这些厂商从数据工程侧切入，用 AI 辅助 pipeline、数据质量、治理和运维。

技术实现特征：

- 生成或修改 pipeline。
- 自动发现数据质量问题。
- 对数据任务做 root cause 分析。
- 用 Agent 辅助数据工程师。

启示：

- 数据工程本身会被 Agent 化。
- 未来 ETL 会变成可生成、可测试、可回滚的数据产品构建计划。

局限：

- 用户仍然是数据团队。
- 没有以业务意图为入口。

### 3.9 CommerceIQ Retail AI Agents 等垂直智能经营平台

CommerceIQ 的方向是 retail media、sales、content、supply chain、operations 等垂直 Agent，目标是 continuous execution。

技术实现特征：

- 针对零售平台和品牌运营构建垂直 Agent。
- 把数据、洞察、执行动作连接到连续运营。
- 强调业务结果而不是数据技术本身。

启示：

- 行业包是商业化最快路径。
- 垂直场景必须建立在通用内核之上，否则后续扩展会被锁死。

局限：

- 垂直行业绑定强。
- 不一定能成为通用商业数据 OS。

### 3.10 开源生态

值得关注的组件方向：

- DB-GPT：Agent workflow、text-to-SQL、数据应用构建。
- Wren AI：semantic layer + AI data assistant。
- dbt Semantic Layer：指标、实体、维度统一定义。
- SQLMesh：数据转换、版本、虚拟环境。
- Dagster：asset-centric orchestration。
- Temporal：durable execution、补偿、长工作流。
- OpenLineage：数据血缘标准。
- OpenTelemetry：可观测性标准。
- MCP：工具、资源、提示的 Agent 连接协议。

结论：开源组件可以拼出局部能力，但还没有一个成熟的通用 Business Data OS。

---

## 4. 市场空位

现有产品大致分成三类：

```text
BI 厂商：让看板和问数更智能
数据平台厂商：让湖仓、数据工程和治理更智能
垂直业务厂商：让某个行业运营更智能
```

缺口是：

**一个以业务意图为入口、以数据产品为交付、以行动反馈为闭环的通用商业数据操作系统。**

这个系统的核心价值不是替代某个数据库，也不是替代某个 BI，而是替代这条断裂流程：

```text
业务提需求 -> 分析师翻译 -> 工程师建模 -> ETL -> BI -> 人解释 -> 人执行 -> 人复盘
```

变成：

```text
业务表达意图 -> OS 编译数据产品 -> 自动验证证据 -> 生成行动计划 -> 治理执行 -> 反馈学习
```

---

## 5. 产品定义

### 5.1 产品名称

建议内部代号：

**AI Native Business Data OS**

对外可表达为：

**AI Native Business Data Operating System**

### 5.2 产品使命

让业务人员无需理解表、SQL、ETL、BI、数据建模，也能直接驱动可信的数据工作流和业务行动；让 Data Agent 不止回答问题，而是驱动 Business Agent 完成可审批、可验证、可追溯的业务生产操作。

### 5.3 产品边界

本产品不直接定位为：

- BI 工具。
- 数据库。
- 数仓。
- 爬虫平台。
- ETL 工具。
- Agent 聊天机器人。
- 内容电商软件。

本产品定位为：

- 业务意图运行时。
- 语义操作系统。
- 数据产品编译器。
- 数据能力编排层。
- Data Agent 与 Business Agent 协同运行时。
- 业务操作和行动治理运行时。
- 数据质量、权限、评测和审计治理层。
- 企业工作流生态和接口层。

### 5.4 核心设计原则

1. **通用内核，行业包扩展。**  
   内容电商只能作为第一个 Domain Pack，不能写入核心抽象。

2. **数据采集解耦。**  
   采集器只是 Data Capability Provider。OS 不知道如何登录小红书，也不持有具体页面 selector。

3. **BI 解耦。**  
   看板只是 Evidence Chain 的一种渲染形态，不是产品中心。

4. **ETL 解耦。**  
   ETL 只是 Data Product Build Plan 的一种执行方式。

5. **模型解耦。**  
   所有模型通过 Model Gateway 调用，业务逻辑不硬编码模型名称。

6. **行动受治理。**  
   Agent 可以提案、编排、执行，但所有写操作必须被 policy、approval、audit、rollback 约束。

7. **Data Agent 不孤立存在。**
   Data Agent 的输出必须能被 Business Agent 消费。每个关键洞察都应能转化为业务操作候选、审批单、工作流任务或业务系统动作。

8. **业务反馈是一等公民。**
   业务动作执行后的结果必须回流为事件、指标、评测样本和语义记忆。没有反馈闭环，就不能称为业务数据操作系统。

---

## 6. 核心抽象模型

### 6.1 BusinessIntent

业务意图是系统入口，替代传统需求文档。

```json
{
  "intent_id": "intent_001",
  "tenant_id": "t_001",
  "goal": "diagnose_metric_drop",
  "business_question": "为什么本周收入下降？",
  "target_metric": "revenue",
  "time_window": "last_7_days",
  "entities": ["customer_segment", "product", "channel"],
  "constraints": {
    "data_freshness": "24h",
    "no_write_action_without_approval": true
  },
  "expected_outputs": ["root_causes", "evidence", "action_plan"]
}
```

### 6.2 Semantic Object

业务对象替代表中心思维。

```json
{
  "object_type": "Product",
  "domain": "commerce",
  "fields": [
    {"name": "product_id", "type": "id"},
    {"name": "category", "type": "dimension"},
    {"name": "price", "type": "measure"}
  ],
  "relationships": [
    {"target": "Order", "type": "sold_in"},
    {"target": "Campaign", "type": "promoted_by"}
  ],
  "actions": ["create_analysis", "recommend_price_change"]
}
```

### 6.3 Event Memory

事件记忆替代孤立表快照。

```json
{
  "event_type": "budget_changed",
  "entity_ref": {"type": "Campaign", "id": "c_123"},
  "occurred_at": "2026-05-31T10:00:00+08:00",
  "payload": {
    "old_budget": 1000,
    "new_budget": 800,
    "operator": "agent_or_user"
  },
  "source": "action_gateway"
}
```

### 6.4 MetricContract

指标契约替代口头指标定义和 BI 字段。

```json
{
  "metric_id": "revenue",
  "name": "Revenue",
  "aliases": ["收入", "销售额"],
  "formula": "sum(order_amount)",
  "grain": ["date", "product", "channel"],
  "unit": "CNY",
  "owner": "finance_ops",
  "source_requirements": ["orders"],
  "quality_contract": {
    "not_null": ["order_amount"],
    "freshness_sla_hours": 24
  },
  "verified_queries": ["revenue_last_7_days"]
}
```

### 6.5 DataRequirement

数据需求是业务意图被编译后的中间产物。

```json
{
  "requirement_id": "req_001",
  "intent_id": "intent_001",
  "required_entities": ["Product", "Order", "Channel"],
  "required_metrics": ["revenue", "orders", "conversion_rate"],
  "time_range": {"start": "2026-05-24", "end": "2026-05-31"},
  "freshness_sla_hours": 24,
  "minimum_quality_score": 0.95
}
```

### 6.6 ProviderContract

数据采集、API、数据库、文件上传、事件流都实现 ProviderContract。

```json
{
  "provider_id": "warehouse_provider",
  "provider_type": "warehouse",
  "capabilities": ["query", "profile", "sample"],
  "entities_supported": ["Order", "Product", "Customer"],
  "fields_supported": ["order_amount", "product_id", "customer_id"],
  "freshness_sla_hours": 1,
  "auth_requirements": ["service_account"],
  "cost_model": "per_query",
  "reliability_score": 0.99,
  "methods": ["plan", "preview", "fetch", "validate"]
}
```

### 6.7 DataProduct

数据产品是系统交付核心。

```json
{
  "data_product_id": "dp_revenue_drop_analysis",
  "intent_id": "intent_001",
  "semantic_bindings": ["revenue", "Product", "Channel"],
  "provider_plan": ["warehouse_provider", "crm_provider"],
  "build_plan": {
    "queries": [],
    "transforms": [],
    "quality_checks": []
  },
  "evidence_chain_id": "ev_001",
  "status": "validated"
}
```

### 6.8 EvidenceChain

证据链替代“相信这个看板”。

```json
{
  "evidence_chain_id": "ev_001",
  "claims": [
    {
      "claim": "收入下降主要来自渠道 A 的转化率下降",
      "supporting_data": ["query_001", "chart_002"],
      "confidence": 0.86,
      "limitations": ["库存数据延迟 12 小时"]
    }
  ],
  "lineage": [],
  "quality_results": [],
  "human_feedback": []
}
```

### 6.9 BusinessAgent

Business Agent 是业务生产动作的责任单元。它不直接解释底层数据，也不绕过 Data Agent 证据链；它基于 EvidenceChain 和 Policy 生成可执行、可审批、可追溯的业务操作。

```json
{
  "business_agent_id": "sales_ops_agent",
  "domain": "sales_ops",
  "responsibilities": [
    "pipeline_risk_followup",
    "lead_reassignment",
    "renewal_reminder"
  ],
  "required_evidence": ["metric_change", "root_cause", "affected_entities"],
  "allowed_actions": ["create_task", "send_notification", "update_crm_field"],
  "approval_policy": {
    "low_risk": "auto_with_audit",
    "medium_risk": "owner_approval",
    "high_risk": "manager_approval"
  }
}
```

### 6.10 OperationContract

OperationContract 定义业务动作的输入、边界、审批、幂等、回滚和反馈要求。

```json
{
  "operation_id": "update_campaign_budget",
  "domain": "marketing_ops",
  "action_type": "adjust_budget",
  "input_schema": {
    "campaign_id": "string",
    "budget_delta_pct": "number"
  },
  "risk_policy": {
    "max_delta_pct_without_approval": 5,
    "daily_budget_change_limit": 1000
  },
  "dry_run_required": true,
  "idempotency_key": "intent_id + action_index",
  "rollback": {
    "type": "restore_previous_value",
    "snapshot_required": true
  },
  "feedback_metrics": ["roi", "spend", "conversion_rate"]
}
```

### 6.11 ActionPlan

行动计划是分析到执行的桥。

```json
{
  "action_plan_id": "ap_001",
  "intent_id": "intent_001",
  "actions": [
    {
      "type": "create_task",
      "target_system": "work_management",
      "risk_level": "low",
      "parameters": {"owner": "sales_ops", "title": "检查渠道 A 转化漏斗"}
    }
  ],
  "approval_required": true,
  "rollback_plan": "cancel_created_task"
}
```

### 6.12 OperationTrace

OperationTrace 是业务操作审计链，保证每个动作可追溯到数据证据和人工审批。

```json
{
  "operation_trace_id": "op_trace_001",
  "intent_id": "intent_001",
  "evidence_chain_id": "ev_001",
  "business_agent_id": "sales_ops_agent",
  "action_plan_id": "ap_001",
  "approval_id": "approval_001",
  "execution_id": "exec_001",
  "status": "completed",
  "rollback_available": true,
  "feedback_window": "24h"
}
```

### 6.13 DomainPack

行业和部门扩展通过 DomainPack 接入核心。

```text
domain_packs/
  content_commerce/
  sales_ops/
  finance_ops/
  supply_chain/
  customer_success/
```

DomainPack 提供：

- 业务对象。
- 指标契约。
- Business Agent 模板。
- 常见业务意图模板。
- Provider 映射。
- 行动模板。
- OperationContract。
- 评测集。
- UI block。

---

## 7. 总体架构

```text
┌──────────────────────────────────────────────────────────────┐
│                       User / Agent Client                     │
│  Chat, Workflow UI, API, Scheduled Agent, External Agent       │
└───────────────────────────────┬──────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────┐
│                    Business Intent Runtime                    │
│  intent parse, clarify, constraint extraction, goal planning   │
└───────────────────────────────┬──────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────┐
│                    Semantic Operating Layer                   │
│  ontology, metric contracts, rules, policies, relationships    │
└───────────────────────────────┬──────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────┐
│                    Data Product Compiler                      │
│  requirement plan, provider selection, build plan, validation  │
└───────────────────────────────┬──────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────┐
│                       Data Access Plane                       │
│  provider registry, access policy, cache, profile, lineage     │
└───────┬──────────────┬──────────────┬──────────────┬─────────┘
        │              │              │              │
┌───────▼──────┐ ┌─────▼─────┐ ┌──────▼──────┐ ┌─────▼────────┐
│ Warehouse    │ │ API/SaaS   │ │ Browser     │ │ File/Event   │
│ Provider     │ │ Provider   │ │ Provider    │ │ Provider     │
└───────┬──────┘ └─────┬─────┘ └──────┬──────┘ └─────┬────────┘
        │              │              │              │
┌───────▼──────────────▼──────────────▼──────────────▼─────────┐
│                       Validated Data Product                  │
└───────────────────────────────┬──────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────┐
│                   Insight & Evidence Runtime                  │
│  analysis, visualization, explanation, confidence, limits      │
└───────────────────────────────┬──────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────┐
│                    Business Agent Runtime                     │
│  domain agents, operation planning, business workflow intent   │
└───────────────────────────────┬──────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────┐
│                  Action & Workflow Runtime                    │
│  proposal, approval, execution, idempotency, rollback, trace   │
└───────────────────────────────┬──────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────┐
│                      Feedback & Learning                      │
│  outcome tracking, eval updates, semantic improvement          │
└──────────────────────────────────────────────────────────────┘
```

### 7.1 控制平面

控制平面管理元数据、权限、成本、评测和生命周期。

```text
control_plane/
  tenant_control
  identity_rbac_abac
  semantic_registry
  provider_registry
  policy_engine
  cost_metering
  audit_log
  evaluation_hub
  deployment_registry
```

### 7.2 运行平面

运行平面执行具体任务。

```text
runtime_plane/
  intent_runtime
  agent_runtime
  business_agent_runtime
  model_gateway
  tool_runtime
  data_product_compiler
  data_access_plane
  workflow_runtime
  action_gateway
  operation_trace_runtime
  feedback_runtime
```

### 7.3 扩展平面

扩展平面让行业包和第三方能力接入。

```text
extension_plane/
  domain_pack_sdk
  provider_sdk
  action_connector_sdk
  business_agent_sdk
  operation_contract_sdk
  ui_block_sdk
  eval_pack_sdk
```

### 7.4 Data Agent 驱动 Business Agent 的闭环

```text
BusinessIntent
  -> DataAgent.resolve_semantics()
  -> DataAgent.compile_data_product()
  -> DataAgent.build_evidence_chain()
  -> BusinessAgent.plan_operation()
  -> PolicyEngine.review()
  -> ApprovalWorkflow.route()
  -> ActionRuntime.execute()
  -> OperationTrace.record()
  -> FeedbackRuntime.collect_outcome()
  -> DataAgent.update_semantic_memory()
```

这个闭环是产品真正价值所在。减少传统数据生产范式只是手段；让数据直接作用于后续业务生产，并把业务生产结果反馈回数据智能系统，才是企业愿意为平台付费的原因。

### 7.5 Business Action Plane

Business Action Plane 与 Data Access Plane 对称存在。

| 平面 | 职责 | 示例 |
|---|---|---|
| Data Access Plane | 提供可信数据能力 | warehouse、API、file、browser、event |
| Business Action Plane | 提供可信业务操作能力 | CRM 更新、工单创建、预算调整、库存调拨、通知审批 |

Action Connector 与 Data Provider 一样必须契约化：

```text
ActionConnectorContract =
  supported_operations
  input_schema
  dry_run
  permission_requirements
  risk_level
  idempotency
  rollback
  audit_output
  feedback_metrics
```

---

## 8. 技术栈选型

### 8.0 对标 Aloudata 后的技术栈原则

Aloudata 的公开路线是 Data Fabric、Active Metadata、NoETL 指标语义层和 NL2MQL2SQL Agent。我们的技术栈不能把这些底座能力外包给竞品，但也不能在 MVP 阶段重造完整大数据平台。

技术栈原则：

1. **MVP 轻栈优先。** 用 FastAPI、Pydantic、PostgreSQL JSONB、pgvector、sqlglot、自研 Eval 和自研 Agent Runtime 跑通可信数据产品、证据链、受治理行动和知识资产候选闭环。
2. **契约优先于平台。** 先稳定 `SemanticObject`、`MetricContract`、`ProviderContract`、`DataProductContract`、`EvidenceChain`、`OperationContract`、`KnowledgeAsset`，再逐步接入 Trino、OpenLineage、OPA、Temporal 等重型组件。
3. **编译器优先于 prompt。** 查询链路必须从 `BusinessIntent -> DataRequirement -> ProviderPlan -> QueryPlan` 编译，不允许把 NL2SQL prompt 当核心能力。
4. **证据、操作和知识复利优先于模型。** SQL、指标、证据链、行动提案、OperationTrace、KnowledgeAsset candidate 都必须可回归，不靠换模型解决可信问题。
5. **自研 Core，兼容生态。** Agent Runtime、Contract Kernel、DataProduct Compiler、EvidenceChain、OperationTrace、KnowledgeAsset Runtime 必须自研；外部数据、模型、工作流和治理工具通过 contract/adapter 接入。

### 8.1 核心服务

| 模块 | 推荐技术 | 理由 |
|---|---|---|
| API Gateway | FastAPI | 当前项目已有基础，异步能力和 Pydantic 生态适合 typed runtime |
| Intent Runtime | Python + Pydantic + JSON Schema | 业务意图需要强类型结构化 |
| Semantic Contract Kernel | Python + Pydantic + JSON Schema + versioned registry | 承载 SemanticObject、MetricContract、ProviderContract、DataProductContract |
| DataProduct Compiler | Python typed compiler first | 先做 DataRequirement、ProviderPlan、QueryPlan 的可测试编译，不提前引入重型联邦查询引擎 |
| Agent Runtime | 自研轻量 orchestrator + PolicyHook | 核心自主能力，不建议被通用框架锁死 |
| Business Agent Runtime | Domain agent templates + workflow state machine + OperationContract | 让数据洞察进入受治理业务生产动作 |
| KnowledgeAsset Runtime | PostgreSQL JSONB + pgvector + review workflow | 从 EvidenceChain、OperationTrace、反馈和 SOP 中沉淀可复用知识资产 |
| Tool Runtime | Typed Tool Registry + MCP bridge | 内部高性能，外部标准化 |
| Model Gateway | OpenAI-compatible API adapter | 支持 DashScope、vLLM、Ollama、OpenAI 等 |
| Workflow Runtime | 先 RQ/Celery/Arq 轻队列，后 Temporal | 轻队列适合 MVP；Temporal 适合长期补偿和回滚 |
| Action Runtime | OperationContract + ActionConnector SDK | 统一业务系统写操作、审批、幂等和回滚 |
| Policy Engine | OPA/Rego 或自研策略层 | 写操作和数据访问必须策略化 |
| Observability | OpenTelemetry + Prometheus | 需要追踪每个 intent 到 action 的链路 |

### 8.2 数据和语义

| 模块 | 推荐技术 | 理由 |
|---|---|---|
| Metadata Store | PostgreSQL JSONB | 适合契约、语义对象、配置和审计 |
| Vector Store | pgvector | 文档和多模态特征初期够用 |
| OLAP | PostgreSQL 起步，ClickHouse 后置 | 不在早期引入过多复杂度 |
| Local Analytics | DuckDB 可选 | 适合本地文件、样本数据、轻量 demo 和 eval fixture |
| Object Store | MinIO / OSS | 图片、视频、文档、报告、快照 |
| SQL Parser | sqlglot | SQL AST 校验、方言转换、只读限制 |
| Query Planning | typed QueryPlan + ProviderPlan，Trino/Calcite 后置 | MVP 不重造完整联邦查询优化器，中长期再引入 Trino 或 Calcite-inspired planning |
| Data Quality | Great Expectations / Soda 思路 + 自研 Contract | 需要与 DataProduct 绑定 |
| Lineage | OpenLineage 兼容模型 | 长期需要标准化血缘 |
| Transformation | SQLMesh / dbt 后置接入 | 不把 OS 绑定到单一 transformation 工具 |

阶段边界：

| 阶段 | 数据底座能力 | 技术选择 |
|---|---|---|
| MVP | SemanticObject lite、MetricContract、ProviderContract lite、DataProduct candidate、metadata/lineage snapshot | PostgreSQL JSONB + Pydantic contracts + sqlglot + self-developed compiler |
| P1/P2 | Provider lifecycle、多源能力、DataProduct Compiler v1、OpenLineage mapping | Provider adapters + eval + optional DuckDB/ClickHouse |
| 中长期 | Data Fabric、NoETL、Active Metadata、联邦查询和物化优化 | Trino/Calcite-inspired planning、OpenLineage、OPA、Temporal、必要时图数据库 |

### 8.3 Provider 层

| Provider 类型 | 示例 | 接入方式 |
|---|---|---|
| Warehouse Provider | PostgreSQL、ClickHouse、Snowflake、BigQuery | SQL + profile + sample |
| SaaS API Provider | CRM、ERP、广告平台、客服系统 | OAuth/API Key + typed schema |
| Browser Provider | 小红书、抖音、后台页面 | Playwright worker，但只暴露 ProviderContract |
| File Provider | Excel、CSV、PDF、Docx | 上传、解析、schema inference |
| Stream Provider | Kafka、Webhook、CDC | Event contract |
| Manual Provider | 人工录入、审批备注 | Form contract |
| Model Provider | OCR、ASR、视觉、embedding | Model Gateway |

### 8.4 Action Connector 层

Action Connector 是业务生产系统的受控接口，不是普通 API wrapper。

| Connector 类型 | 示例 | 必备能力 |
|---|---|---|
| Work Management | Jira、飞书任务、钉钉待办、企业微信 | 创建任务、分配负责人、状态回写 |
| CRM | Salesforce、HubSpot、纷享销客、销售易 | 更新商机、创建跟进、触发提醒 |
| ERP/Finance | SAP、金蝶、用友、NetSuite | 创建审批、预算校验、凭证草稿 |
| Supply Chain | WMS、OMS、采购系统 | 补货建议、调拨申请、库存冻结 |
| Marketing/Ads | 广告平台、营销自动化 | 预算/出价/人群调整草案或审批后执行 |
| Customer Service | Zendesk、Intercom、客服系统 | 工单升级、回复草稿、满意度跟踪 |
| Notification | 邮件、Slack、Teams、飞书、钉钉 | 通知、审批、结果确认 |

Action Connector 必须支持 dry-run、idempotency、audit、rollback 或 compensating action。不能支持回滚的动作必须在 OperationContract 中声明不可逆，并自动提高风险等级。

### 8.5 模型栈

| 任务 | 模型策略 |
|---|---|
| 意图识别 | 小模型或中模型，要求稳定结构化输出 |
| 语义解析 | 中模型 + deterministic resolver |
| SQL/查询计划 | 中大模型 + sqlglot 校验 + golden regression |
| 分析归因 | 工具优先，模型负责解释和规划 |
| 决策提案 | 大模型 + 规则引擎 + 风险评估 |
| 文档理解 | embedding + rerank + LLM |
| 图片/视频理解 | OCR/ASR/抽帧 + 多模态模型 |
| 审核 | 独立 policy/risk model，不与生成模型共享判断 |

推荐组合：

- 云上：DashScope/Qwen 系列作为中文和多模态主力。
- 私有化轻量：Qwen3-14B、Qwen3-30B-A3B。
- 私有化标准：Qwen3-32B 或同等级模型。
- embedding：bge-m3 或同类中英双语 embedding。
- rerank：bge-reranker 或同类 rerank。
- Serving：vLLM 为主，Ollama 用于轻量 demo 和开发。

重要边界：

- 不把模型名称写死在业务代码。
- 不承诺 DeepSeek-V3 类大 MoE 单张 48GB GPU 私有化。
- 高风险决策不能只依赖模型输出。

### 8.6 硬件和部署

| 场景 | 推荐配置 |
|---|---|
| 开发验证 | CPU + 云模型，必要时 24GB GPU |
| 私有化 demo | 1x 48GB GPU，256GB RAM，4TB NVMe |
| 标准私有化 | 1x 96GB GPU 或 2x 48GB GPU，256-512GB RAM，8TB NVMe |
| 企业私有化 | 2-4x 96GB GPU，512GB-1TB RAM，16TB NVMe + 对象存储 |
| 多租户 SaaS | GPU pool + queue + model routing + per-tenant quota |

### 8.7 企业生态接入与边界

详细方案见 [AI Native Business Data OS 生态接入、安全算力与组织范式](./ai_native_business_data_os_ecosystem_and_org_model.md)。

知识资产、组织权限和部署形态详见 [AI Native Business Data OS 知识资产、组织权限与部署架构](./ai_native_business_data_os_knowledge_identity_deployment.md)。

核心边界：

| 领域 | 产品提供 | 客户可自带 |
|---|---|---|
| 模型 | Model Gateway、模型路由、评测、预算、DLP | AI API Key、本地模型、云模型服务 |
| 算力 | ComputeProfile、推理适配、健康检查、部署模板 | 云 GPU、本地 GPU、第三方 AI API |
| 工具 | Tool Registry、MCP Gateway、权限、审计、沙箱 | MCP Server、本地 Agent、内部工具 |
| 工作流 | Workflow Bridge、handoff contract、callback、trace | Temporal、Airflow、Dagster、n8n、Power Automate、自研 BPM |
| 网络 | Connector Agent、secure tunnel、mTLS、allowlist 建议 | VPC、专线、代理、私有 DNS、证书体系 |
| 安全 | PolicyEngine、OperationTrace、DLP、Audit Sink | IAM、Vault/KMS、SIEM、审批系统、合规流程 |
| 知识资产 | KnowledgeAsset、Knowledge Graph、review/publish、KnowledgeUseTrace | 企业知识库、组织规则、历史 SOP、业务经验 |
| 组织权限 | Tenant/Org/Workspace、RBAC/ABAC/ReBAC、审批路由 | OIDC/SAML、SCIM、LDAP/AD、企业 IM 组织架构 |

产品不应把“接入客户所有技术栈”做成定制项目，而应把接入方式产品化为：

- `ProviderContract`：读数据。
- `ActionConnectorContract`：写业务系统。
- `ModelProviderContract`：调用模型和本地推理。
- `MCPServerManifest`：接入 MCP 工具和上下文。
- `WorkflowHandoffContract`：接入客户工作流和本地 Agent。
- `ComputeProfile`：声明可运行的硬件和算力边界。

### 8.8 MCP Gateway 与工具治理

MCP 应作为生态接入协议，而不是绕过治理的后门。

```text
MCP Client/Host
  -> MCP Gateway
  -> Tool Registry
  -> PolicyEngine
  -> Approved MCP Server
  -> ToolTrace / OperationTrace
```

MCP Gateway 必须提供：

- server/tool 注册、owner、版本、来源和签名。
- tool/resource/prompt 的能力描述和风险等级。
- OAuth、API Key、客户 IAM 和短期 token broker。
- tool scope 到 OS 权限和 OperationContract 的映射。
- 本地和远程 MCP Server 的网络安全策略。
- prompt injection、tool poisoning、sensitive disclosure 检测。
- 高风险工具调用的审批和 kill switch。

只读 MCP tool 可以作为普通工具；任何会改变业务系统状态的 MCP tool，都必须绑定 `OperationContract` 并进入 `ActionRuntime`。

### 8.9 网络通信与部署拓扑

| 拓扑 | 适用客户 | 默认通信方式 |
|---|---|---|
| SaaS hosted | 非敏感数据、中小企业 | OAuth/API Key + allowlist |
| Hybrid connector | 企业内网数据和系统较多 | 客户侧 Connector 主动出站 |
| Private deployment | 数据不出域、强合规 | 客户 VPC/机房内部署 |
| Air-gapped deployment | 金融、政企、高敏 | 离线包、离线模型、离线评测 |
| Local agent bridge | 本地浏览器、桌面、内部工具 | localhost + local approval |

网络原则：

- 默认不要求客户内网开放入站端口。
- SaaS 访问客户内网资源优先用客户侧 Connector 主动出站。
- 所有远程连接使用 mTLS、短期凭证、租户隔离和审计。
- 所有外发模型调用经过 Model Gateway 和数据出域策略。
- 本地 MCP/Agent 默认只绑定 `127.0.0.1`，不能默认监听所有网卡。

### 8.10 安全合规基线

安全控制必须覆盖：

- Identity Federation：OIDC/SAML/LDAP/企业 IM。
- RBAC/ABAC/ReBAC：角色、属性、业务对象关系权限。
- Secret Broker：客户 Vault/KMS/Secret 引用，不保存明文 key。
- Data Boundary：数据分类、脱敏、出域策略、区域策略。
- Model Boundary：模型供应商、用途、数据类别、成本和调用记录。
- Tool Boundary：MCP/工具沙箱、权限、输出清洗。
- Action Boundary：OperationContract、审批、幂等、回滚。
- Audit Boundary：intent、query、tool、model、action、approval、feedback 全链路审计。

AI 特有风险需要纳入 threat model：

- prompt injection。
- tool poisoning。
- excessive agency。
- sensitive information disclosure。
- model denial of service。
- supply chain compromise。
- overreliance。
- cross-agent confusion。

### 8.11 开发和组织范式

要做这个产品，公司自身不能按项目制外包范式运转，而要按平台生态范式运转。

核心研发纪律：

1. Contract-first：先定义契约，再写实现。
2. Eval-driven：每个 Agent、Connector、模型升级都必须有评测。
3. Policy-by-default：高风险动作默认拒绝，显式策略放行。
4. Kernel + Packs：核心运行时稳定，行业/连接器/部署通过 Pack 扩展。
5. Adapter certification：Provider、Action Connector、MCP Server、Workflow Bridge 进入生产前必须认证。
6. Customer-owned ecosystem：客户的 Key、模型、Agent、Workflow、云产品是可接入生态，不是需要替换的对象。

建议组织：

| 团队 | 核心职责 |
|---|---|
| Platform Kernel | OS Core、Contract、Runtime、Trace |
| Data Product | Compiler、Semantic、Evidence、Quality |
| Agent Runtime | Data Agent、Business Agent、Tool runtime |
| Integration Ecosystem | Provider、Action Connector、MCP Gateway、Workflow Bridge |
| Model & Compute | Model Gateway、BYO Key、本地模型、算力 Profile |
| Security & Governance | Policy、IAM、DLP、Audit、Compliance |
| Evaluation | golden set、eval harness、regression、模型升级门禁 |
| Domain Pack | 行业语义、业务 Agent、模板、案例 |
| Cloud/SRE | SaaS、私有化部署、可观测性、升级 |
| DevRel/Marketplace | SDK、文档、示例、认证、伙伴生态 |
| Solution Architecture | 客户架构评估、部署选型、pack 化落地 |

### 8.12 知识资产与组织权限

Data Agent 和 Business Agent 的运行结果必须沉淀为企业知识资产，而不是只保存在聊天记录或日志中。

```text
Data Memory
  + Business Memory
  + OperationTrace
  + Human Decision
  + Feedback Outcome
  -> KnowledgeAsset
```

核心对象：

| 对象 | 说明 |
|---|---|
| KnowledgeAsset | 被版本化、分类、授权、审核和评测绑定的知识资产 |
| KnowledgeGraph | 连接业务对象、指标、规则、证据、操作、组织和责任人 |
| KnowledgeUseTrace | 记录哪个 Agent 在什么目的下使用了哪些知识 |
| OrgContext | 租户、组织、部门、团队、workspace、项目、成本中心 |
| IdentityContext | 用户、组、角色、服务账号、外部身份映射 |
| PurposeContext | 分析、审计、执行、训练、导出等使用目的 |

权限模型不能只靠 RBAC，必须组合：

- RBAC：角色权限。
- ABAC：按部门、地区、数据分类、时间等属性控制。
- ReBAC：按客户归属、项目成员、审批链等关系控制。
- Purpose-based Access：按分析、执行、导出、训练等目的控制。

Agent 使用知识资产时必须先经过：

```text
IdentityContext
  -> OrgContext
  -> PurposeContext
  -> PolicyEngine
  -> KnowledgeAsset retrieval
  -> KnowledgeUseTrace
```

未审核知识只能作为候选，不允许驱动高风险业务动作；已发布知识才能进入 Business Agent 计划；被生产反馈验证的知识才能进入低风险自动化。

### 8.13 云、混合云和私有化部署

产品必须从第一天支持多部署 Profile，而不是后期把 SaaS 改成私有化。

| 部署形态 | 控制面 | 数据面 | 适用场景 |
|---|---|---|---|
| Public SaaS | 我方云 | 我方云或客户 API | 中小企业、低敏数据 |
| Dedicated SaaS | 我方云独立租户 | 我方云独立资源 | 中大型企业、隔离要求较高 |
| Hybrid SaaS | 我方云 | 客户 Connector 在内网 | 企业内网系统多、不开放入站 |
| Customer VPC | 客户云 VPC | 客户云 VPC | 数据不出云账号 |
| On-prem Private | 客户机房 | 客户机房 | 强合规、内网系统 |
| Air-gapped | 离线环境 | 离线环境 | 政企、金融高敏 |

部署 Profile 必须显式声明：

- control plane 位置。
- data plane 位置。
- identity provider。
- secret store。
- model mode。
- data residency。
- audit sink。
- upgrade mode。
- backup/DR。
- connector topology。

---

## 9. Data Product Compiler 设计

Data Product Compiler 是本产品的技术核心。它替代传统“业务需求 -> 工程师写 ETL -> 分析师搭 BI”的流程。

### 9.1 编译流程

```text
1. Parse Intent
   解析业务问题、目标、约束、输出类型。

2. Resolve Semantics
   绑定实体、指标、维度、规则、权限、时间窗口。

3. Plan Data Requirements
   生成数据需求，判断现有数据是否足够。

4. Select Providers
   从 ProviderRegistry 选择数据库、API、文件、采集、事件流等能力。

5. Generate Build Plan
   生成查询、转换、聚合、质量检查和缓存计划。

6. Validate Plan
   校验权限、成本、质量、口径冲突和 SQL 安全。

7. Materialize or Virtualize
   生成临时数据产品、物化视图、报告数据集或只读查询结果。

8. Build Evidence Chain
   绑定数据来源、SQL、血缘、质量结果、图表和解释。

9. Generate Insight / Action
   输出结论、置信度、限制、行动候选。

10. Feedback
   收集用户反馈和业务结果，更新评测和语义层。
```

### 9.2 Build Plan 类型

| 类型 | 用途 |
|---|---|
| Query Plan | 直接查询已有数据 |
| Transform Plan | 生成临时转换或可复用数据产品 |
| Collection Plan | 触发 Provider 获取缺失数据 |
| Profiling Plan | 数据分布、缺失率、异常值检查 |
| Quality Plan | 运行质量契约 |
| Analysis Plan | 归因、预测、分群、漏斗、cohort |
| Report Plan | 报告、图表、摘要 |
| Action Plan | 生成提案或执行动作 |

### 9.3 编译器产物

所有产物都要版本化：

- `intent_snapshot`
- `semantic_resolution`
- `data_requirement_plan`
- `provider_selection`
- `query_plan`
- `quality_results`
- `evidence_chain`
- `insight_output`
- `action_plan`
- `feedback_result`

---

## 10. Data Access Plane 设计

### 10.1 职责

Data Access Plane 不关心业务最终答案，只负责把数据能力以契约化方式提供给编译器。

职责包括：

- Provider 注册。
- 数据能力发现。
- 权限检查。
- 成本估算。
- freshness 检查。
- schema inference。
- profile 和 sample。
- 数据质量验证。
- lineage 输出。
- cache 和 materialization。

### 10.2 Provider 生命周期

```text
register -> inspect -> authorize -> plan -> preview -> fetch -> validate -> publish -> monitor
```

### 10.3 Provider 与采集解耦

Browser 采集器只实现 ProviderContract：

```text
BrowserProvider.run_fetch(requirement)
BrowserProvider.run_backfill(requirement)
BrowserProvider.validate(result)
BrowserProvider.report_lineage(result)
```

核心 OS 不知道：

- 登录流程。
- 页面结构。
- selector。
- 平台 cookie。
- 反爬策略。

核心 OS 只知道：

- 这个 Provider 能提供哪些实体和字段。
- 数据新鲜度。
- 成本和可靠性。
- 质量结果。
- 血缘和审计。

---

## 11. Agent Runtime 设计

### 11.1 Agent 类型

| Agent | 职责 |
|---|---|
| Intent Agent | 解析业务意图，提出澄清问题 |
| Semantic Agent | 绑定实体、指标、规则，发现冲突 |
| Compiler Agent | 生成 DataProduct build plan |
| Provider Broker Agent | 选择数据能力 Provider |
| Quality Agent | 运行数据质量和口径校验 |
| Analyst Agent | 归因、预测、洞察解释 |
| Action Planner Agent | 生成行动候选 |
| Policy Agent | 判断风险和审批路径 |
| Evaluation Agent | 对答案、SQL、行动效果做评测 |
| Memory Agent | 沉淀业务规则、反馈和案例 |
| Business Agent | 按领域负责业务操作计划、审批协同、执行追踪和反馈解释 |

### 11.2 Tool 权限模型

工具按动作分级：

| 动作 | 说明 |
|---|---|
| `resolve` | 解析语义，不访问敏感数据 |
| `preview` | 采样、profile、估算 |
| `query` | 只读查询 |
| `build` | 生成数据产品 |
| `propose` | 生成行动提案 |
| `execute` | 写操作或外部系统动作 |
| `rollback` | 回滚动作 |

每个工具必须声明：

- 输入 schema。
- 输出 schema。
- 权限要求。
- 租户范围。
- 风险等级。
- 是否可自动执行。
- dry-run 支持。
- 幂等键策略。
- 审计字段。

### 11.3 Agent 不可做的事

- 不直接持有生产数据库超级权限。
- 不绕过 ProviderContract 访问爬虫。
- 不直接执行高风险写操作。
- 不生成不可解释的指标口径。
- 不输出没有证据链的关键业务结论。
- 不在无评测的情况下升级模型或策略。

### 11.4 Business Agent 运行模型

Business Agent 不是通用聊天机器人，而是带职责、权限、操作契约和反馈指标的领域执行单元。

```text
BusinessAgentRun =
  input: EvidenceChain + BusinessIntent + PolicyContext
  plan: OperationPlan
  review: PolicyDecision + ApprovalRoute
  execute: ActionConnector calls
  trace: OperationTrace
  feedback: OutcomeMetrics
```

Business Agent 必须遵守：

- 只消费 Data Agent 提供的 EvidenceChain 或已验证 DataProduct。
- 只调用 OperationContract 允许的动作。
- 每个动作必须经过 PolicyEngine。
- 中高风险动作必须进入审批流。
- 执行后必须产生 OperationTrace。
- 反馈窗口结束后必须回填 OutcomeMetrics。

### 11.5 Data Agent 与 Business Agent 的接口

Data Agent 输出给 Business Agent 的不是自然语言总结，而是结构化可验证包：

```json
{
  "evidence_chain_id": "ev_001",
  "business_intent_id": "intent_001",
  "claims": [],
  "affected_entities": [],
  "recommended_action_categories": [],
  "confidence": 0.86,
  "limitations": [],
  "required_human_judgement": []
}
```

Business Agent 回传给 Data Agent 的也不是日志文本，而是结构化反馈：

```json
{
  "operation_trace_id": "op_trace_001",
  "actions_taken": [],
  "approval_outcome": "approved",
  "business_metrics_before": {},
  "business_metrics_after": {},
  "outcome_assessment": "positive",
  "lessons": []
}
```

---

## 12. 语义操作系统

### 12.1 语义层不只是 Metric Layer

传统 semantic layer 通常只管理指标、维度和字段映射。Business Data OS 的语义层还必须管理：

- 业务对象。
- 事件。
- 指标契约。
- 规则。
- 行动。
- 权限。
- 质量契约。
- 业务目标。
- 因果假设。
- 用户反馈。
- Business Agent 职责。
- OperationContract。
- 业务动作和业务结果之间的因果假设。

### 12.2 Semantic Registry 表示例

```text
semantic.entities
semantic.relationships
semantic.events
semantic.metric_contracts
semantic.dimensions
semantic.business_rules
semantic.action_templates
semantic.business_agents
semantic.operation_contracts
semantic.quality_contracts
semantic.verified_questions
semantic.term_aliases
semantic.conflicts
semantic.versions
```

### 12.3 口径冲突处理

冲突类型：

- 同名异义。
- 同义异名。
- 跨部门口径不同。
- 文档和实际 SQL 不一致。
- 上游字段单位不同。
- 粒度不同。
- 时间窗口不同。

处理流程：

```text
detect -> classify -> impact analysis -> propose resolution -> owner approval -> version update
```

### 12.4 业务操作语义

业务操作也需要语义层，否则 Agent 只能停在建议。

操作语义至少包括：

- 操作名称和自然语言别名。
- 可作用的业务对象。
- 输入参数和单位。
- 风险等级。
- 前置条件。
- 审批人和责任人。
- 是否可 dry-run。
- 是否可回滚。
- 预期影响指标。
- 反馈观测窗口。

示例：

```text
operation: adjust_budget
object: Campaign
aliases: 调预算, 降预算, 提预算
preconditions: campaign.status = active
risk: depends_on_delta_pct_and_amount
approval: marketing_owner if delta > 5%
rollback: restore_previous_budget
feedback_metrics: spend, roi, conversion_rate
feedback_window: 24h
```

---

## 13. Evaluation Runtime

没有 Evaluation Runtime，系统只能 demo，不能商业化。

### 13.1 评测对象

| 对象 | 评测方式 |
|---|---|
| Intent 解析 | gold intent set |
| 指标解析 | metric alias test |
| SQL 生成 | golden SQL + result diff |
| 数据质量 | quality contract |
| 归因分析 | synthetic + historical cases |
| 多模态理解 | labeled assets |
| 行动提案 | policy simulation |
| 执行结果 | before/after impact |
| 用户满意度 | feedback loop |

### 13.2 上线门槛

- 核心指标解析准确率达到阈值。
- SQL 只读安全校验 100% 通过。
- 高风险行动拦截 100% 通过。
- 数据产品质量契约通过。
- 答案必须有 evidence chain。
- 模型升级必须跑回归。

### 13.3 持续评测

每个租户可以有自己的评测包：

```text
eval_packs/
  default_business/
  content_commerce/
  sales_ops/
  finance_ops/
  tenant_custom/
```

---

## 14. 安全、治理和合规

### 14.1 多租户隔离

所有核心对象从第一天包含：

```sql
tenant_id VARCHAR(64) NOT NULL
workspace_id VARCHAR(64)
created_by VARCHAR(64)
created_at TIMESTAMPTZ
updated_at TIMESTAMPTZ
```

隔离层级：

- 行级隔离。
- Provider 凭据隔离。
- 模型上下文隔离。
- 向量索引隔离。
- 对象存储路径隔离。
- 审计日志隔离。

### 14.2 Policy Engine

Policy 输入：

- user。
- tenant。
- intent。
- data sensitivity。
- tool。
- action risk。
- provider。
- cost estimate。
- approval state。

Policy 输出：

- allow。
- deny。
- require approval。
- require masking。
- require dry-run。
- require human review。

### 14.3 风险等级

| 等级 | 示例 | 处理 |
|---|---|---|
| R0 | 术语解释、公开文档 | 自动 |
| R1 | 只读查询、图表 | 自动但审计 |
| R2 | 生成数据产品、报告 | 自动或轻审批 |
| R3 | 创建任务、发送通知 | 可配置审批 |
| R4 | 改业务参数、触发同步 | 强审批 |
| R5 | 预算、价格、库存、删除、权限 | 强审批 + 双人复核 |

### 14.4 审计链

每次端到端运行必须能追踪：

```text
intent_id -> workflow_run_id -> tool_calls -> queries
-> provider_runs -> evidence_chain -> action_plan
-> approval -> execution -> feedback
```

---

## 15. 商业价值落地

### 15.1 企业痛点映射

| 企业痛点 | OS 能力 | 可量化指标 |
|---|---|---|
| 业务提数依赖工程排期 | Intent -> DataProduct Compiler | 需求交付周期 |
| 分析师依赖底层建模 | Semantic Runtime + ProviderContract | 分析师产出/人 |
| 工程师被报表和 ETL 淹没 | 编译器生成提案，工程维护运行时 | 数据工单数 |
| 指标口径反复争议 | MetricContract + conflict workflow | 口径返工率 |
| BI 只展示不行动 | ActionPlan + Workflow Runtime | 异常处理时长 |
| 数据洞察无法进入业务生产 | Data Agent -> Business Agent -> Governed Operation | 洞察转行动比例、行动完成率 |
| 数据质量出问题才发现 | QualityContract + monitoring | 数据事故数 |
| AI 回答不可信 | EvidenceChain + Eval Runtime | 可信答案率 |
| 系统难以横向扩展行业 | DomainPack SDK | 新场景上线周期 |

### 15.2 商业化包装

| 产品包 | 内容 |
|---|---|
| Core OS | Intent Runtime、Semantic Runtime、Data Product Compiler、Evaluation Runtime |
| Provider Pack | 数据库、API、文件、采集、SaaS、事件流连接器 |
| Domain Pack | 销售、财务、供应链、市场、客服、内容电商 |
| Business Agent Pack | 领域业务 Agent、OperationContract、业务流程模板、反馈指标 |
| Action Pack | 工单、通知、审批、业务系统写操作、回滚/补偿动作 |
| Private AI Pack | 私有模型、模型路由、GPU 部署、数据不出域 |
| Governance Pack | 审计、合规、权限、策略、评测报告 |

### 15.3 收费维度

- 平台订阅。
- 租户/工作区。
- Provider 数量。
- Domain Pack。
- Tool call / workflow run。
- 数据产品数量。
- 模型调用和私有模型资源。
- Action 执行次数。
- Business Agent 数量和运行次数。
- OperationTrace 和审计保留等级。
- 私有化部署和运维服务。

---

## 16. 10 年实施路线

### Horizon 1：0-18 个月，建立通用内核

目标：不要做行业应用，先做可复用 OS 内核。

关键产物：

- BusinessIntent schema。
- Semantic Registry。
- ProviderContract。
- DataProduct Compiler v1。
- EvidenceChain。
- Eval Hub。
- BusinessAgent Runtime v1。
- OperationContract。
- OperationTrace。
- DomainPack SDK v1。
- 一个 reference domain pack。

成功标准：

- 同一内核可支持至少两个不同业务场景。
- 采集、数据库、文件都作为 Provider 接入。
- 高频业务问题不需要工程师手写 SQL 才能交付。
- 至少一个 Business Agent 能消费 EvidenceChain，生成审批单或业务任务，并把结果反馈回 Data Agent。

### Horizon 2：18-36 个月，成为多场景商业平台

目标：从内部能力变成可销售产品。

关键产物：

- 多租户控制面。
- Provider marketplace。
- Domain pack marketplace。
- Action Gateway。
- Business Agent marketplace。
- Private AI Pack。
- 客户级 eval pack。

成功标准：

- 新客户可以通过配置 + 少量代码接入。
- 新 domain pack 开发周期降到数周。
- 企业客户可审计、可私有化、可运维。

### Horizon 3：3-5 年，形成业务数据 OS 生态

目标：让外部开发者和合作伙伴扩展 OS。

关键产物：

- DomainPack SDK 稳定。
- Provider SDK 稳定。
- Action Connector SDK 稳定。
- 可视化语义建模。
- Agent workflow marketplace。
- 第三方 eval packs。

成功标准：

- 外部团队能开发行业包。
- 平台收入不只来自自研场景。
- OS 成为客户业务数据工作流入口。
- Data Agent 和 Business Agent 的闭环成为企业跨部门工作流的一等入口。

### Horizon 4：5-10 年，成为商业操作系统层

目标：从数据系统升级为业务操作系统。

关键产物：

- 自进化语义层。
- 自生成数据产品。
- 自适应业务流程。
- 跨企业/跨系统安全协作。
- 持续业务仿真和策略优化。
- Data Agent 和 Business Agent 形成可组合 Agent Mesh，企业通过一个平台完成从数据理解到业务生产的完整工作流。

成功标准：

- 用户不再提出“报表需求”，而是提出业务目标。
- OS 自动维护数据产品和行动闭环。
- 数据基础设施对业务用户不可见。

---

## 17. 对验证客户 / 历史 FaSoLa Monorepo 的参考映射

本项目不是 FaSoLa 项目，也不应把 FaSoLa 写成核心产品身份。历史 FaSoLa monorepo 只能作为 Customer-0、首发验证客户、Reference Domain Pack 和 Connector 参考来源。当前系统中，很多能力可以被重新定位，而不是推倒重写。

| 当前模块 | 新定位 |
|---|---|
| `data_collector/` | Browser/API Data Provider 实现 |
| `data_warehouse/` | DataProduct materialization backend |
| `shared_lib/models/` | Provider schema source + semantic candidate source |
| `shared_lib/monitoring/` | Observability + lineage seed |
| `api_server/` | OS API gateway 的起点 |
| `web_dashboard_frontend/` | OS workspace UI 的起点 |
| `lrb_sdk/` | SaaS API Provider implementation |
| `xiaohongshu_mcp/` | Action/Provider Connector example |

建议在独立 `ai-native-business-data-agent-os/` 实现仓库中采用以下模块边界。FaSoLa monorepo 不再作为产品代码根目录，只作为 Customer-0、Reference Domain Pack 和 Connector 来源：

```text
ai-native-business-data-agent-os/
  packages/
    contracts/
      src/agent_os_contracts/
    os_core/
      src/agent_os_core/
        intent_runtime/
        semantic_runtime/
        data_product_compiler/
        data_access_plane/
        agent_runtime/
        business_agent_runtime/
        integration_hub/
        mcp_gateway/
        model_gateway/
        network_plane/
        knowledge_assets/
        org_identity/
        deployment_profiles/
        data_boundary/
        policy_engine/
        security_governance/
        evaluation_hub/
        action_runtime/
        operation_contracts/
        operation_trace/
        feedback_loop/
        compute_profiles/
    sdk/
      src/agent_os_sdk/

  domain_packs/
    content_commerce/
    sales_ops/
    finance_ops/
    supply_chain/

  providers/
    postgres_provider/
    file_provider/
    browser_provider/
    api_provider/
    event_provider/

  action_connectors/
    notification_connector/
    work_management_connector/
    crm_connector/
    erp_connector/
    marketing_connector/

  workflow_bridges/
    temporal_bridge/
    airflow_bridge/
    dagster_bridge/
    n8n_bridge/
    customer_bpm_bridge/
```

关键约束：

- `ai-native-business-data-agent-os/packages/os_core/` 不 import 内容电商具体采集器。
- `ai-native-business-data-agent-os/packages/os_core/` 不 import 具体平台 SDK。
- 所有具体行业对象放在 `ai-native-business-data-agent-os/domain_packs/`。
- 所有数据获取实现放在 `ai-native-business-data-agent-os/providers/`。
- 所有业务写操作实现放在 `ai-native-business-data-agent-os/action_connectors/`。
- 核心只依赖 ProviderContract 和 DomainPackContract。
- Business Agent 只能通过 OperationContract 调用 Action Connector。
- MCP Server 只能通过 `mcp_gateway/` 进入 Tool Runtime。
- 客户 AI API Key 和本地模型只能通过 `model_gateway/` 使用。
- SaaS 访问客户内网资源默认通过 `network_plane/connector_agent` 主动出站。
- 外部工作流和本地 Agent 通过 `workflow_bridges/` 和 Handoff Contract 接入。
- 数据和业务记忆必须进入 `knowledge_assets/`，通过 review/publish 变成企业知识资产。
- 客户组织架构、角色、组、服务账号和审批链由 `org_identity/` 提供运行时上下文。
- SaaS、Hybrid、Customer VPC、On-prem、Air-gapped 通过 `deployment_profiles/` 显式建模。

---

## 18. 第一性问题清单

后续所有技术决策都应回答这些问题：

1. 这个功能属于 OS Core、Domain Pack、Provider 还是 Action Connector？
2. 它是否把内容电商逻辑写进了核心？
3. 它是否让业务用户绕过 SQL/ETL/BI，直接表达业务意图？
4. 它是否生成了可验证 DataProduct，而不只是回答文本？
5. 它是否有 EvidenceChain？
6. 它是否有质量契约和评测？
7. 它是否可审计、可审批、可回滚？
8. 它是否能迁移到销售、财务、供应链等其他商业数据场景？
9. 它是否把采集作为 Provider，而不是核心身份？
10. 它是否让 Data Agent 输出被 Business Agent 消费，并进入业务生产动作？
11. 它是否把业务动作结果反馈回数据智能系统？
12. 它是否允许客户使用自己的 AI Key、模型、算力、Agent、工作流和云生态？
13. 它是否经过 MCP/工具接入、权限、沙箱、审计和供应链风险评估？
14. 它是否支持 SaaS、Hybrid、Private、Air-gapped 中至少一种清晰部署拓扑？
15. 它产生的数据、业务记忆、操作反馈是否沉淀为可治理的 KnowledgeAsset？
16. 它是否适配客户组织架构、用户角色、审批链和权限继承？
17. 它是否减少工程师在单个业务需求上的重复开发？

---

## 19. 参考资料

- [Palantir Foundry Architecture Center](https://www.palantir.com/docs/foundry/architecture-center/platforms/)
- [Palantir AIP](https://www.palantir.com/platforms/aip/)
- [Snowflake Cortex Analyst](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-analyst)
- [Snowflake Cortex Agents](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents)
- [Databricks AI/BI Genie](https://docs.databricks.com/en/genie/)
- [Microsoft Fabric Copilot](https://learn.microsoft.com/fabric/get-started/copilot-fabric-overview)
- [Power BI Copilot Semantic Models](https://learn.microsoft.com/power-bi/create-reports/copilot-semantic-models)
- [Tableau Next](https://www.tableau.com/products/tableau-next)
- [ThoughtSpot Spotter](https://www.thoughtspot.com/product/spotter)
- [ThoughtSpot Spotter Semantics](https://www.thoughtspot.com/product/spotter-semantics)
- [SmartBI AgentBI](https://www.smartbi.com.cn/agentbi)
- [DB-GPT Documentation](https://docs.dbgpt.site/docs/overview)
- [dbt Semantic Layer](https://docs.getdbt.com/docs/use-dbt-semantic-layer/dbt-sl)
- [SQLMesh Documentation](https://sqlmesh.readthedocs.io/)
- [Dagster Docs](https://docs.dagster.io/)
- [Temporal Docs](https://docs.temporal.io/)
- [OpenLineage](https://openlineage.io/)
- [OpenTelemetry](https://opentelemetry.io/)
- [Open Policy Agent](https://www.openpolicyagent.org/)
- [Model Context Protocol](https://modelcontextprotocol.io/)
- [MCP Architecture](https://modelcontextprotocol.io/docs/learn/architecture)
- [MCP Transports Specification](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)
- [MCP Authorization Specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization)
- [NIST AI Risk Management Framework](https://www.nist.gov/itl/ai-risk-management-framework)
- [NIST AI 600-1 Generative AI Profile](https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf)
- [OWASP Top 10 for LLM Applications](https://owasp.org/www-project-top-10-for-large-language-model-applications)
- [OWASP Top 10 for Agentic Applications](https://genai.owasp.org/2025/12/09/owasp-genai-security-project-releases-top-10-risks-and-mitigations-for-agentic-ai-security/)
- [OWASP Agentic Skills Top 10](https://owasp.org/www-project-agentic-skills-top-10/)
- [vLLM Documentation](https://docs.vllm.ai/)
- [Ollama Documentation](https://docs.ollama.com/)
- [Qwen Documentation](https://qwen.readthedocs.io/)
- [DeepSeek-V3 Technical Report](https://arxiv.org/abs/2412.19437)
- [NVIDIA RTX PRO 6000 Blackwell](https://www.nvidia.com/en-us/data-center/rtx-pro-6000-blackwell-server-edition/)
- [CommerceIQ Retail AI Agents](https://www.commerceiq.ai/press-releases/retail-ai-agents-for-brands-to-outperform-the-competition)
- [NIQ Commerce Trends Intelligence 2026](https://nielseniq.com/global/en/insights/report/2026/commerce-trends-intelligence/)
- [Gartner: Agentic AI Project Cancellation Prediction](https://www.gartner.com/en/newsroom/press-releases/2025-06-25-gartner-predicts-over-40-percent-of-agentic-ai-projects-will-be-canceled-by-end-of-2027)
- [Monte Carlo: State of AI Reliability](https://www.montecarlodata.com/state-of-ai-reliability)
