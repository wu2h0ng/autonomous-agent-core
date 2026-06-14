# AI Native Business Data OS 生态接入、安全算力与组织范式

> 日期：2026-05-31
> 定位：补充 `AI Native Business Data OS 技术 PRD 与架构设计`，说明企业级生态接入、网络通信、安全合规、MCP/工具协议、BYO AI Key/模型/算力、本地 Agent/工作流互操作，以及公司自身研发组织和工作范式。

---

## 1. 核心判断

AI Native Business Data OS 不能被设计成“我们替客户解决所有技术问题”的封闭平台。企业已经有自己的云、网络、安全体系、身份系统、AI API Key、本地模型、MCP 工具、本地 Agent、RPA、工作流平台、BI、数仓、CRM、ERP 和审批系统。

产品应该提供的是一个 **可信业务数据操作层**：

```text
BusinessIntent
  -> Data Agent
  -> EvidenceChain
  -> Business Agent
  -> Governed Operation
  -> Customer-owned systems and workflows
  -> Feedback
```

因此架构原则是：

1. OS Core 只定义契约、运行时、治理和审计，不强行接管客户基础设施。
2. 数据、模型、工具、算力、工作流、业务系统都通过可替换 Adapter/Provider/Connector 接入。
3. 客户可以使用自己的 AI API Key、本地模型、本地 Agent、MCP Server、云工作流和安全体系。
4. 我们提供统一的接入标准、风险控制、可观测性、评测和 Marketplace 规则。
5. 平台的长期护城河不是“全都自己做”，而是让第三方和客户自己的生态安全接入。

---

## 2. 平台边界：我们提供什么，不提供什么

### 2.1 我们提供

| 能力 | 说明 |
|---|---|
| OS Core | BusinessIntent、Semantic Runtime、Data Product Compiler、EvidenceChain、Business Agent Runtime、PolicyEngine、EvaluationRuntime |
| Provider SDK | 数据库、文件、SaaS API、浏览器采集、事件流等数据读取契约 |
| Action Connector SDK | CRM、ERP、广告、客服、审批、工单等业务动作契约 |
| MCP Gateway | MCP Server 的注册、鉴权、作用域、审计、策略和沙箱代理 |
| Model Gateway | 多模型路由、客户 BYO Key、本地模型、云模型、预算和策略控制 |
| Workflow Bridge | Temporal、Airflow、Dagster、n8n、Power Automate、企业自研流程引擎互操作 |
| Security/Governance | RBAC/ABAC、审计、审批、DLP、OperationTrace、Eval gates、策略执行 |
| Marketplace Rules | Provider、Action Connector、Domain Pack、Business Agent Pack、Eval Pack 的认证规则 |

### 2.2 我们不承诺替客户完成

| 不承诺范围 | 正确产品边界 |
|---|---|
| 改造客户所有历史系统 | 通过 Provider/Connector 接入，优先不替换 |
| 统一所有云厂商和安全工具 | 提供标准接口和参考集成 |
| 承担客户所有模型成本 | 支持 BYO Key、BYO Model、BYO Compute |
| 管理客户全部私有网络 | 提供连接器、网关、部署拓扑和安全建议 |
| 取代客户审批和责任体系 | 接入其 IAM、审批流和审计体系 |
| 对第三方 MCP 工具无限信任 | 通过 MCP Gateway 做认证、授权、沙箱、审计和风险分级 |

---

## 3. 总体生态架构

```text
┌─────────────────────────────────────────────────────────────┐
│                         OS Workspace                         │
│  intent, evidence, data product, operation trace, approvals   │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│                         OS Core                              │
│  Intent Runtime | Semantic Runtime | Data Product Compiler    │
│  Business Agent Runtime | PolicyEngine | EvaluationRuntime    │
└───────────────┬──────────────┬──────────────┬───────────────┘
                │              │              │
┌───────────────▼───┐ ┌────────▼────────┐ ┌───▼────────────────┐
│ Data Access Plane │ │ Tool/MCP Plane   │ │ Business Action    │
│ Provider SDK      │ │ MCP Gateway      │ │ Plane              │
└───────────────┬───┘ └────────┬────────┘ └───┬────────────────┘
                │              │              │
┌───────────────▼──────────────▼──────────────▼────────────────┐
│                 Customer-owned systems and ecosystem          │
│ warehouse, files, SaaS, local agents, MCP servers, workflows, │
│ cloud AI products, approval systems, CRM, ERP, ads, support   │
└──────────────────────────────────────────────────────────────┘
```

关键设计：

- Data Access Plane 只负责读数据或产生数据快照。
- Business Action Plane 只负责受控业务写操作。
- Tool/MCP Plane 只负责工具能力接入，不绕过 PolicyEngine。
- Model/Compute Plane 负责模型调用和算力调度，不把模型供应商写死在业务逻辑里。
- Workflow Bridge 负责与客户已有流程系统协作，不强迫客户迁移。

---

## 4. 网络通信与部署拓扑

### 4.1 标准拓扑

| 拓扑 | 适用客户 | 通信方式 | 风险控制 |
|---|---|---|---|
| SaaS hosted | 中小企业、非敏感数据 | 客户系统开放 API 或 OAuth 授权 | API allowlist、OAuth scope、tenant isolation |
| Hybrid connector | 企业内部系统多、不能开放入站 | 客户内网部署 Connector，主动出站到 OS | outbound-only、mTLS、短期 token、连接器审计 |
| Private deployment | 数据不出域、强合规 | OS 部署在客户 VPC/机房 | 客户 IAM、私有对象存储、内部网络策略 |
| Air-gapped deployment | 金融、政企、高敏场景 | 离线包、离线模型、离线评测 | 离线授权、离线日志导出、人工升级 |
| Local desktop/agent bridge | 本地工具、浏览器、桌面数据 | Local Agent 只绑定 localhost | origin validation、local approval、最小权限 |

### 4.2 推荐网络原则

1. 默认不要求客户内网开放入站端口。
2. SaaS 到客户内网优先使用客户侧 Connector 主动出站。
3. 所有远程 Connector 使用 mTLS、短期凭证和租户级隔离。
4. 高风险 Action Connector 必须走客户审批系统或客户网关。
5. 所有外发 AI 请求必须经过 Model Gateway，记录模型、用途、数据分类、成本和响应摘要。
6. 本地 MCP/Agent 服务必须默认绑定 `127.0.0.1`，不能默认监听 `0.0.0.0`。
7. 所有 HTTP 工具服务必须校验 `Origin`、认证状态、租户和 scope。
8. 企业客户必须支持代理、私有 DNS、证书轮换、出站 allowlist 和审计日志转发。

### 4.3 网络组件

| 组件 | 职责 |
|---|---|
| Connector Agent | 部署在客户网络内，负责数据和动作连接 |
| Secure Tunnel | 出站长连接或轮询任务通道，不暴露客户内网 |
| API Gateway | 统一外部 API、租户、限流、鉴权 |
| MCP Gateway | 统一 MCP Server 注册、授权、策略、审计 |
| Model Gateway | 统一模型调用、BYO Key、预算、DLP、路由 |
| Event Gateway | 统一 webhook、事件回调、异步反馈 |
| Audit Sink | 日志导出到客户 SIEM、对象存储或审计平台 |

---

## 5. MCP 与工具生态接入

### 5.1 MCP 的定位

MCP 是工具和上下文接入协议，不是治理系统本身。产品里应把 MCP 放在 Tool/MCP Plane，而不是让 Business Agent 直接信任任意 MCP Server。

MCP 当前关键事实：

- MCP 采用 client-host-server 架构。
- 标准传输包含 `stdio` 和 Streamable HTTP。
- MCP 使用 JSON-RPC 消息。
- HTTP 传输需要关注 Origin 校验、localhost 绑定和认证。
- HTTP 授权规格围绕 OAuth 2.1、Bearer Token、resource indicator、PKCE、短期 token 等安全机制。

### 5.2 MCP Gateway

```text
MCP Client/Host
  -> MCP Gateway
  -> PolicyEngine
  -> Tool Registry
  -> Approved MCP Server
  -> Tool Result Sanitizer
  -> OperationTrace / ToolTrace
```

MCP Gateway 必须提供：

| 能力 | 说明 |
|---|---|
| Server Registry | 注册 MCP Server、版本、owner、来源、能力 |
| Capability Manifest | tools/resources/prompts 的结构化描述和风险等级 |
| Authorization Broker | OAuth、API Key、客户 IAM、短期 token |
| Scope Mapping | MCP tool scope 到 OS 权限和 OperationContract |
| Tool Sandbox | 限制文件、网络、命令、环境变量、执行时间 |
| Prompt/Result Sanitizer | 检测工具描述、资源内容、返回值中的注入和敏感信息 |
| Approval Gate | 高风险工具调用进入审批 |
| Provenance | 记录工具来源、版本、参数、输出摘要和证据链 |
| Kill Switch | 出现异常时禁用特定 server/tool/version |

### 5.3 MCP 风险模型

| 风险 | 示例 | 控制 |
|---|---|---|
| Tool poisoning | 工具描述或资源内容诱导模型泄密 | 工具描述审查、签名、工具结果隔离 |
| Excessive agency | MCP 工具允许删除文件、发邮件、改预算 | scope、审批、dry-run、OperationContract |
| Sensitive disclosure | 工具返回 PII、商业机密或 token | DLP、字段脱敏、输出过滤 |
| Supply chain | 第三方 MCP Server 更新后行为改变 | 版本 pin、签名、SBOM、准入测试 |
| Local network exposure | 本地 MCP 监听所有网卡 | 默认 localhost、Origin 校验、认证 |
| Credential leakage | token 写入日志或 query string | secret redaction、header only、短期 token |
| Cross-tenant confusion | 多租户工具上下文混淆 | tenant-bound token、session isolation |

### 5.4 MCP 与 Action Connector 的边界

MCP tool 可以作为工具接入，但只要会改变业务系统状态，就必须升级为 Action Connector 或绑定 OperationContract。

```text
Read-only MCP tool
  -> ToolTrace

Business write MCP tool
  -> OperationContract
  -> PolicyEngine
  -> ApprovalWorkflow
  -> ActionRuntime
  -> OperationTrace
```

这能避免 MCP 变成绕过治理的后门。

---

## 6. BYO Key、BYO Model、BYO Compute

### 6.1 客户自有 AI API Key

客户常见诉求：

- 已经购买 OpenAI、Azure OpenAI、DashScope、火山、百度、腾讯、Anthropic、Gemini 等模型服务。
- 不希望模型调用费用通过我方转售。
- 希望数据只发往指定区域或指定供应商。
- 希望不同部门使用不同模型或预算。

设计：

```text
Customer Key
  -> Customer Vault or OS Secret Broker
  -> Model Gateway
  -> PolicyEngine checks data class, model class, region, budget
  -> Model Provider Adapter
  -> InvocationTrace
```

要求：

1. 不在业务表中保存明文 key。
2. 支持客户自有 Vault、KMS、环境变量、Kubernetes Secret。
3. 每次调用记录 provider、model、tenant、workspace、purpose、cost、token、data classification。
4. 支持模型级数据出域策略。
5. 支持 key rotation、budget limit、department quota。
6. 支持客户选择“只用本地模型”“只用中国区模型”“禁止训练用途”等策略。

### 6.2 客户本地模型

| 场景 | 推荐方案 |
|---|---|
| 开发和离线 demo | Ollama 或轻量 vLLM |
| 企业私有推理 | vLLM + Kubernetes + GPU node pool |
| 多模型路由 | Model Gateway + queue + policy |
| 高并发低延迟 | vLLM/TensorRT-LLM/Triton 类推理服务 |
| 文档/语义检索 | embedding/rerank 本地服务 + pgvector/向量库 |

原则：

- 我们不承诺替客户调优所有模型。
- 我们提供模型适配器、评测集、路由策略和最低运行基线。
- 私有模型必须通过 EvaluationRuntime 才能进入生产。
- 高风险业务动作不能只依赖本地模型输出，必须有规则、证据和审批。

### 6.3 算力接入方式

| 算力来源 | 接入方式 |
|---|---|
| 我方 SaaS GPU Pool | 多租户队列、配额、成本控制 |
| 客户云上 GPU | Kubernetes、私有 Model Gateway、VPC 内访问 |
| 客户本地 GPU | Private deployment、离线镜像、健康检查 |
| 第三方 AI API | BYO Key + Model Provider Adapter |
| CPU-only | 云模型 + 本地编排 + 小模型工具任务 |

### 6.4 硬件 Profile

| Profile | 适用 | 建议 |
|---|---|---|
| P0 SaaS API-only | 客户用外部模型 API | 无 GPU，重点在安全、审计、限流 |
| P1 Private light | 只做本地 embedding、小模型、规则 | 24-48GB GPU，128-256GB RAM |
| P2 Private standard | 中型企业私有模型和多 Agent | 1x 96GB GPU 或 2x 48GB GPU，256-512GB RAM |
| P3 Enterprise | 多部门、多模型、高并发 | 2-4x 96GB GPU，512GB-1TB RAM，对象存储和独立向量库 |
| P4 Regulated offline | 离线安全域 | 离线模型、离线许可证、离线评测和补丁流程 |

硬件建议必须以 `ComputeProfile` 表达，不写死供应商：

```json
{
  "profile": "P2_private_standard",
  "gpu_memory_gb": 96,
  "min_ram_gb": 256,
  "storage": "8TB NVMe + object storage",
  "supported_modes": ["local_llm", "embedding", "rerank", "batch_analysis"],
  "not_suitable_for": ["large_moe_training", "high_concurrency_video_understanding"]
}
```

---

## 7. 客户自有 Agent、Workflow、Cloud AI 产品接入

### 7.1 Agent Handoff Contract

客户可能已经有本地 Agent、云 Agent、RPA 或部门自动化脚本。本项目不应要求全部重写，而应通过 Handoff Contract 协作。

```json
{
  "handoff_id": "handoff_001",
  "source": "business_data_os_agent",
  "target": "customer_local_agent",
  "intent": {},
  "evidence_chain_id": "ev_001",
  "allowed_actions": [],
  "approval_required": true,
  "callback_url": "https://...",
  "expected_feedback_schema": {}
}
```

要求：

- handoff 必须带 EvidenceChain。
- target agent 必须声明能力、权限和 owner。
- 回调必须包含 action status、business metrics、error、trace。
- 未注册或未认证 Agent 不允许接收高风险任务。

### 7.2 Workflow Bridge

适配对象：

- Temporal。
- Airflow。
- Dagster。
- n8n。
- Power Automate。
- Zapier。
- 企业自研 BPM/审批流。
- 云厂商 AI workflow。

桥接方式：

| 模式 | 用法 |
|---|---|
| Trigger | OS 触发客户工作流 |
| Callback | 工作流完成后回写结果 |
| Human approval | 调用客户审批系统 |
| External task | 客户系统拉取待办并执行 |
| Event subscription | 客户事件驱动 OS 更新语义和反馈 |

关键约束：

- 所有触发必须 idempotent。
- 所有外部 workflow run 必须进入 OperationTrace。
- 不可回滚 workflow 必须在 OperationContract 标注。
- 工作流失败要有 compensation plan。

### 7.3 Cloud ecosystem adapter

企业常用云生态不应被 OS 内核硬编码：

```text
CloudAIAdapter =
  identity integration
  model endpoint
  data boundary policy
  workflow trigger
  event callback
  cost and quota report
  audit export
```

可优先支持：

- Azure OpenAI / Azure AI Foundry / Microsoft Fabric / Power Platform。
- AWS Bedrock / SageMaker / Glue / Step Functions。
- Google Vertex AI / BigQuery / Workflows。
- 阿里云 DashScope / MaxCompute / DataWorks。
- 火山方舟 / VeDI / ByteHouse。
- 腾讯云 TI / TDSQL / 数据连接器。

---

## 8. 安全合规架构

知识资产、组织权限和部署形态的详细设计见 [AI Native Business Data OS 知识资产、组织权限与部署架构](./ai_native_business_data_os_knowledge_identity_deployment.md)。

### 8.1 安全原则

| 原则 | 落地方式 |
|---|---|
| Zero Trust | 每次工具、模型、数据、动作调用都鉴权 |
| Least Privilege | Provider、Connector、MCP tool 只给最小 scope |
| Policy by Default | 默认拒绝高风险写操作和敏感数据出域 |
| Evidence before Action | 没有 EvidenceChain 不允许 Business Agent 执行动作 |
| Human Accountability | 高风险动作必须有人类 owner 和审批 |
| Audit Everything | intent、query、tool、model、action、approval、feedback 全链路审计 |
| Tenant Isolation | tenant、workspace、project、connector、secret 全隔离 |
| Reversible if Possible | 可回滚优先，不可回滚动作升级风险等级 |

### 8.2 控制面

```text
Identity
  -> RBAC/ABAC/ReBAC
  -> PolicyEngine
  -> Data Boundary
  -> Tool Boundary
  -> Model Boundary
  -> Action Boundary
  -> Audit and Evidence
```

关键模块：

- Identity Federation：OIDC/SAML/LDAP/企业微信/飞书/钉钉。
- RBAC/ABAC/ReBAC：角色、属性、业务对象关系权限。
- Secret Broker：Vault/KMS/Secret 引用，不泄露明文。
- DLP：PII、财务、合同、客户数据识别和脱敏。
- Data Residency：数据区域、模型区域、日志区域策略。
- PolicyEngine：访问、模型、工具、动作统一策略。
- Audit Sink：对接 SIEM、对象存储、审计系统。
- Incident Response：工具禁用、key revoke、connector quarantine。

### 8.3 AI 与 Agent 特有威胁

| 威胁 | 对应控制 |
|---|---|
| Prompt injection | 上下文隔离、工具输出标记、指令优先级、结果清洗 |
| Tool poisoning | MCP/工具注册审核、签名、版本 pin、工具描述评测 |
| Excessive agency | OperationContract、审批、限额、dry-run |
| Sensitive information disclosure | DLP、最小上下文、模型出域策略、输出过滤 |
| Model denial of service | 限流、队列、预算、输入长度控制 |
| Supply chain compromise | SBOM、依赖扫描、签名镜像、connector certification |
| Overreliance | EvidenceChain、human approval、Eval gate |
| Cross-agent confusion | Agent identity、session isolation、trace binding |

### 8.4 合规映射

| 框架 | 产品映射 |
|---|---|
| NIST AI RMF / GenAI Profile | Govern、Map、Measure、Manage；AI 风险和生成式 AI 风险控制 |
| OWASP Top 10 for LLM Applications | prompt injection、sensitive disclosure、supply chain、excessive agency 等控制 |
| OWASP Agentic Applications / Skills | autonomous workflow、agent skill 和 tool 层风险控制 |
| SOC 2 / ISO 27001 | 访问控制、变更、审计、供应链、事件响应 |
| ISO/IEC 42001 | AI 管理体系和模型治理 |
| GDPR / PIPL | 数据最小化、出域、删除、可解释、数据主体权利 |
| 等保 / 行业合规 | 私有化部署、日志留存、权限分级、网络边界 |

---

## 9. 开发范式

### 9.1 Contract-first

所有生态能力先定义契约，再写实现：

```text
ProviderContract
ActionConnectorContract
ModelProviderContract
MCPServerManifest
WorkflowHandoffContract
BusinessAgentContract
OperationContract
EvalPackContract
```

工程要求：

- Contract 版本化。
- Contract 有 schema、examples、compatibility tests。
- 实现不能绕过 Contract 直接 import 第三方 SDK。
- 每个 connector 都必须有 mock server 和 golden tests。

### 9.2 Eval-driven development

每个新能力必须回答：

1. 业务意图能否稳定解析？
2. 数据查询是否正确？
3. EvidenceChain 是否完整？
4. Tool/MCP 调用是否有权限和审计？
5. Business Agent 是否遵守 OperationContract？
6. 高风险动作是否进入审批？
7. 模型替换后结果是否退化？
8. 失败时是否可回滚或补偿？

CI 需要包含：

- unit tests。
- contract tests。
- connector sandbox tests。
- golden intent regression。
- model output eval。
- policy tests。
- security tests。
- migration tests。

### 9.3 Platform kernel + packs

研发结构必须避免“项目制功能堆叠”：

```text
Kernel:
  intent, semantic, data product, evidence, policy, eval, trace

Packs:
  provider pack
  action connector pack
  domain pack
  business agent pack
  eval pack
  deployment pack
```

Kernel 追求稳定，Packs 追求快速扩展。商业化复制依赖 Pack，而不是每个客户写一套定制代码。

### 9.4 Adapter certification

所有生态接入进入生产前必须认证：

| 阶段 | 检查 |
|---|---|
| Register | owner、source、version、license、data scope |
| Static Review | schema、权限、危险动作、依赖 |
| Sandbox Test | mock 数据、错误、超时、重试 |
| Security Test | secret、注入、越权、日志脱敏 |
| Eval Test | golden intents、action risk cases |
| Production Gate | approval、audit、rollback、SLO |

---

## 10. 企业组织架构

### 10.1 组织原则

做 AI Native Business Data OS 的公司不能按传统“后端、前端、算法、交付”切法运行。产品核心是生态平台，所以组织必须围绕契约、运行时、治理、评测、连接器和行业包构建。

### 10.2 建议团队

| 团队 | 职责 | 关键产出 |
|---|---|---|
| Platform Kernel Team | OS Core、Runtime、Contract、Trace | 稳定 API、SDK、运行时 |
| Data Product Team | Compiler、Semantic、Evidence、Quality | 数据产品生成和证据链 |
| Agent Runtime Team | Data Agent、Business Agent、Tool runtime | Agent 编排和状态机 |
| Integration Ecosystem Team | Provider、Action Connector、MCP Gateway、Workflow Bridge | 生态接入和认证 |
| Model & Compute Team | Model Gateway、BYO Key、本地模型、算力 Profile | 模型路由、成本、私有化模型 |
| Security & Governance Team | Policy、IAM、DLP、Audit、Compliance | 安全控制和合规材料 |
| Evaluation Team | golden set、eval harness、regression、模型升级评估 | 质量门禁 |
| Domain Pack Team | 行业语义、业务 Agent、模板、案例 | 可复制业务包 |
| Cloud/SRE Team | SaaS、私有化部署、可观测性、升级 | 稳定运行和交付基线 |
| Developer Relations / Marketplace Team | SDK、文档、示例、认证、伙伴生态 | 第三方开发者生态 |
| Solution Architecture Team | 客户架构评估、部署选型、成功路径 | 低定制高复用交付 |

### 10.3 工作流

```text
Business requirement
  -> Contract design
  -> Threat model
  -> Eval design
  -> Reference implementation
  -> Sandbox certification
  -> Pack packaging
  -> Documentation
  -> Marketplace or customer rollout
  -> Feedback to Contract and Eval
```

关键制度：

- 任何 connector 或 agent 不允许没有 threat model 就上线。
- 任何高风险动作不允许没有 OperationContract。
- 任何模型替换不允许没有 eval report。
- 任何客户定制必须判断能否沉淀为 Pack。
- 解决方案团队不能长期维护 fork，要推动核心和 pack 化。

### 10.4 角色分工

| 角色 | 关注点 |
|---|---|
| Product Architect | 产品抽象是否保持通用 |
| Platform Engineer | 运行时、SDK、接口稳定 |
| AI Engineer | 模型、prompt、工具调用、评测 |
| Data Engineer | 数据产品、质量、血缘 |
| Security Engineer | threat model、policy、DLP、audit |
| Integration Engineer | Provider、Connector、MCP、Workflow |
| Domain Architect | 行业语义和业务流程 |
| SRE | 部署、监控、升级、成本 |
| Solution Architect | 客户落地、边界判断、pack 化 |
| DevRel | 文档、示例、认证、伙伴生态 |

---

## 11. 商业化阶段的技术组织演进

### 阶段 1：内部 reference implementation

目标：

- 跑通一个内部业务域。
- 证明 Data Agent -> Business Agent -> OperationTrace -> Feedback。
- 所有能力都按 Contract 写，避免写成内容电商专用系统。

组织重点：

- 小型平台内核团队。
- 一个 Domain Pack 小组。
- 一个 Integration 小组。
- 安全和评测必须从第一天进入流程。

### 阶段 2：私有化试点

目标：

- 支持客户 BYO Key、本地 Connector、私有部署。
- 输出部署拓扑、网络白皮书、安全白皮书。
- 建立 adapter certification 流程。

组织重点：

- Solution Architecture 介入，但不做无限定制。
- Integration Ecosystem Team 成为核心生产力。
- Security & Governance Team 输出合规材料。

### 阶段 3：SaaS + Hybrid 平台

目标：

- 多租户、配额、计费、Marketplace。
- Connector/Pack 可以半自助接入。
- 客户能自己接入模型、工具、工作流。

组织重点：

- DevRel 和 Marketplace Team 建立生态。
- Cloud/SRE 建立高可用和成本治理。
- Evaluation Team 建立平台级质量门禁。

### 阶段 4：生态平台

目标：

- 第三方开发 Provider、Action Connector、Business Agent Pack。
- 客户内部团队可以扩展自己的业务 Agent。
- AI Native Business Data OS 成为业务数据和业务 Agent 的控制平面。

组织重点：

- 伙伴生态、认证和开发者体验成为产品核心。
- 核心团队聚焦 Contract、Runtime、Governance、Eval。
- 行业团队通过 Pack 扩展，而不是项目交付扩展。

---

## 12. 对当前 Monorepo 的新增落地映射

建议在已有 `business_data_os/` 架构之外，增加：

```text
business_data_os/
  integration_hub/
    provider_registry/
    action_registry/
    mcp_registry/
    workflow_registry/
  mcp_gateway/
    server_registry/
    auth_broker/
    tool_sandbox/
    tool_trace/
  model_gateway/
    provider_adapters/
    byo_key_broker/
    budget_guard/
    data_boundary_policy/
  network_plane/
    connector_agent/
    secure_tunnel/
    callback_gateway/
  security_governance/
    iam/
    dlp/
    audit_sink/
    policy_tests/
  compute_profiles/
    profiles/
    health_checks/
    deployment_templates/

connectors/
  providers/
  actions/
  mcp_servers/
  workflow_bridges/

packs/
  domain_packs/
  business_agent_packs/
  eval_packs/
  deployment_packs/
```

关键规则：

- `mcp_gateway/` 是唯一允许直接对接 MCP Server 的入口。
- `model_gateway/` 是唯一允许直接使用客户 AI Key 的入口。
- `network_plane/connector_agent` 是 SaaS 访问客户内网资源的默认方式。
- `connectors/` 只能依赖 SDK 和 Contract，不能依赖 OS Core 内部实现。
- `packs/` 不能修改 Kernel；只能声明契约、模板、评测和映射。

---

## 13. 决策检查清单

每次新增生态能力前必须回答：

1. 这是 Provider、Action Connector、MCP Tool、Workflow Bridge、Model Adapter，还是 Domain Pack？
2. 是否需要读数据、写业务系统，还是只调用模型？
3. 是否有 Contract、schema、owner、version、risk level？
4. 是否需要客户 BYO Key、BYO Model、BYO Compute？
5. 是否涉及敏感数据出域？
6. 是否有最小权限 scope？
7. 是否需要审批、dry-run、幂等、回滚？
8. 是否能接入客户 IAM、Vault、SIEM、审批流？
9. 是否可在 SaaS、Hybrid、Private、Air-gapped 中至少一种拓扑运行？
10. 是否有 eval 和安全测试？
11. 是否可沉淀为 Pack，而不是一次性项目代码？
12. 如果第三方实现出问题，是否可以禁用、隔离、回滚、追责？

---

## 13. 组织变革管理：产品采用不只是技术问题

> 补充来源：深度分析报告 — 组织变革管理维度。

引入 AI Native Business Data OS 不只是部署一套软件，而是改变企业内数据使用、分析和决策的组织方式。这个维度是当前文档体系中最显著的缺失之一。

### 13.1 角色再定义

产品引入后，企业内现有角色的工作性质将发生变化：

| 现有角色 | 当前职责 | 未来职责 | 价值升级 |
|---|---|---|---|
| **数据分析师** | 写SQL、做报表、回答业务问题 | MetricContract Owner + Eval Curator（定义指标口径、维护Golden Query、审核AI答案质量） | 从"取数工具人"升级为"知识资产管理者" |
| **数据工程师** | 维护ETL、建表、管数据管道 | Provider Contract Owner + DataProduct Runtime维护者 | 从"管道工"升级为"数据能力平台建设者" |
| **业务负责人** | 看报表、凭经验决策 | ActionProposal审批人 + EvidenceChain最终责任人 | 从"经验驱动"到"证据驱动决策" |
| **IT/数据治理** | 管权限、做合规 | PolicyEngine配置者 + 审计追溯者 | 从"守门员"升级为"AI治理架构师" |

### 13.2 变革四阶段

```text
阶段1 - 试用期（0-3个月）：AI辅助，人工复核所有答案
  - 产品定位："AI帮你整理数据证据，你来做判断"
  - 用户行为：看到EvidenceChain后会进行二次确认
  - 组织支持：数据团队需要在旁解答疑问

阶段2 - 协作期（3-6个月）：AI生成，人工抽查+关键问题复核
  - 产品定位："日常问题交给AI，关键决策人工复核"
  - 用户行为：对常规问题信任AI答案，异常问题主动复核
  - 组织支持：建立"关键问题清单"，定义哪些问题必须人工复核

阶段3 - 信任期（6-12个月）：AI主导，人工只审批高风险动作
  - 产品定位："AI负责分析和提案，人负责审批和执行"
  - 用户行为：日常分析完全信任AI，聚焦审批ActionProposal
  - 组织支持：建立审批SOP和风险分级机制

阶段4 - 自主期（12个月+）：AI常规决策，人工专注异常和策略性问题
  - 产品定位："AI处理常规业务，人聚焦战略和创新"
  - 用户行为：只在异常告警时介入，日常运行自动化
  - 组织支持：建立异常升级路径和定期策略复盘机制
```

### 13.3 变革阻力与应对

| 阻力来源 | 表现 | 应对策略 |
|---|---|---|
| **数据分析师** | 担心被替代，消极配合MetricContract建设 | 明确角色升级路径：从"写SQL"到"知识资产管理"（更高价值、更难替代） |
| **业务负责人** | 不信任AI分析结果，拒绝采纳ActionProposal | EvidenceChain透明化："你可以不信任AI，但可以自己验证数据证据" |
| **IT部门** | 担心安全和合规风险 | 早期提供完整的审计日志、权限模型和安全白皮书 |
| **中层管理者** | 担心决策权被稀释 | 定位产品为"决策辅助工具"而非"决策替代工具"，审批权始终在人 |

### 13.4 变革成功的度量

| 指标 | 目标（12个月） |
|---|---|
| 数据分析师从写SQL转向MetricContract管理的比例 | ≥ 50% |
| 业务负责人自主使用产品频率 | ≥ 每周3次 |
| ActionProposal被严肃对待（审批或驳回）的比例 | ≥ 70% |
| 员工对"AI不会取代我的工作"的认同度 | ≥ 60% |

---

## 14. 成本模型与单位经济学深度分析

> 补充来源：深度分析报告 — 扩展分析维度。

### 14.1 成本构成

| 成本类别 | 子项 | 占收入比例（基准场景） | 趋势 |
|---|---|---|---|
| **模型调用成本** | LLM API调用（意图解析+SQL生成+证据链+ActionProposal） | 10-15% | 随模型降价下降 |
| **基础设施成本** | 云服务器、数据库、存储、网络 | 8-12% | 随规模下降（规模效应） |
| **研发成本** | 工程师薪资、工具、培训 | 25-35% | 随产品成熟度下降 |
| **客户成功成本** | CSM薪资、客户培训、实施支持 | 10-15% | 先升后降（自助化提升） |
| **销售与市场** | 销售薪资、市场活动、内容营销 | 15-25% | 随品牌建立下降 |
| **管理与合规** | 法务、合规、审计、保险 | 5-8% | 随规模上升 |

### 14.2 单位经济模型（单客户，Professional版）

| 项目 | 金额 | 说明 |
|---|---|---|
| 年合同价值(ACV) | ¥98,000 | Professional版年费 |
| 模型调用成本/年 | -¥9,800 | 假设每次EvidenceChain ¥0.3, 月均2,700次 |
| 基础设施成本/年 | -¥8,000 | 云资源摊销 |
| 客户成功成本/年 | -¥12,000 | CSM服务成本均摊 |
| **客户毛利/年** | **¥68,200** | 毛利率 ≈ 70% |
| 获客成本(CAC) | ¥35,000 | 销售+市场费用摊销 |
| CAC回收期 | 6.2个月 | CAC / (月毛利) |
| LTV（3年） | ¥204,600 | 3年毛利合计 |
| LTV/CAC | 5.8x | 健康水平（目标 > 3x） |

### 14.3 降本路径

| 策略 | 预期效果 | 实施时机 |
|---|---|---|
| 模型缓存（相同问题30分钟内复用结果） | 降低模型成本20-30% | MVP阶段 |
| 层1确定性路径命中率提升 | 降低模型成本15-20% | 随Golden Query积累自然提升 |
| 国产模型替代（Qwen/DeepSeek替代GPT-4o） | 降低模型成本40-60% | 阶段2（模型路由成熟后） |
| 多租户基础设施共享 | 降低基础设施成本30-50% | 阶段2（客户数 > 10） |
| 客户自助onboarding | 降低客户成功成本50% | 阶段3（产品成熟后） |

### 14.4 盈利路径

```text
Year 1: 亏损（研发投入 > 收入）
  目标：验证产品-市场匹配，建立参照案例

Year 2: 接近盈亏平衡
  目标：ARR覆盖研发+基础设施+模型成本
  条件：≥ 15个Professional客户或等效ARR

Year 3: 盈利
  目标：正向经营利润，支撑自增长
  条件：≥ 40个客户，NRR > 110%
```

---

## 15. 参考资料

- [Model Context Protocol Architecture](https://modelcontextprotocol.io/docs/learn/architecture)
- [MCP Transports Specification](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)
- [MCP Authorization Specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization)
- [NIST AI Risk Management Framework](https://www.nist.gov/itl/ai-risk-management-framework)
- [NIST AI 600-1 Generative AI Profile](https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf)
- [OWASP Top 10 for LLM Applications](https://owasp.org/www-project-top-10-for-large-language-model-applications)
- [OWASP Top 10 for Agentic Applications](https://genai.owasp.org/2025/12/09/owasp-genai-security-project-releases-top-10-risks-and-mitigations-for-agentic-ai-security/)
- [OWASP Agentic Skills Top 10](https://owasp.org/www-project-agentic-skills-top-10/)
