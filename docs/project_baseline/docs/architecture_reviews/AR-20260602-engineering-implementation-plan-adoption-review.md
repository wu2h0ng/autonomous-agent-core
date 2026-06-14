# AR-20260602 工程实现完全方案采纳评审

> 日期：2026-06-02
> 评审人：CTO
> 状态：有条件采纳
> 来源：`99_原始输入与来源/AI_Native_Business_Data_OS_工程实现完全方案_20260602.md`

## 1. CTO 结论

这份工程实现方案有较高参考价值，但它本身不是新的项目权威基线。

它必须先经过现有架构决策过滤：

1. `ai-native-business-data-agent-os/` 仍然是唯一产品实现根目录。
2. Agent OS Core 必须保持自研。
3. 外部 Agent 框架只能用于研究、benchmark、非生产 spike 和测试样本设计。
4. `ai-agent-engineering-workflow/` 是辅助产品开发的工程化工作流，不是产品运行时。
5. FaSoLa 只作为 Customer-0、Reference Domain Pack 和 Connector 来源材料。

本方案可以作为 API、持久化、Eval、可观测性、前端和交付节奏的实施细节参考。凡是与 ADR-0006、ADR-0007、ADR-0008 或“产品运行时/辅助工作流分离”边界冲突的内容，不采纳。

## 2. 不可谈判边界

| 边界 | CTO 裁决 |
|---|---|
| 产品根目录 | 使用 `ai-native-business-data-agent-os/`，不把产品仓库改回 `business_data_os/`。 |
| 产品身份 | 使用 `AI Native Business Data Agent OS`；除归档原文外，不回退到旧的 `Business Data OS` 产品表述。 |
| Agent Runtime | 产品 Core Runtime 必须自研。LangGraph、CrewAI、AutoGen、OpenAI Agents SDK、OpenHands、Goose、Aider、Cline 等只能作为参考。 |
| 辅助工作流 | `ai-agent-engineering-workflow/` 是研发辅助系统，`ai-native-business-data-agent-os/` 不得 import 它。 |
| 领域逻辑 | OS Core 不得 import 内容电商、FaSoLa、MaxCompute、钉钉或任何具体客户/平台 SDK。 |
| 高风险动作 | R4/R5 业务动作必须人工审批，MVP 不允许自动执行。 |
| 隐私计算/区块链 | MVP 只保留接口字段和本地可验证审计哈希链能力，不引入外部区块链、TEE、联邦学习或多方安全计算依赖。 |

## 3. 采纳矩阵

### 3.1 直接采纳

| 领域 | 采纳决策 | 原因 |
|---|---|---|
| 后端 API | Python 3.11+、FastAPI、OpenAPI、Pydantic schema layer | 符合 contract-first API 和 AI/data 工程生态。 |
| 契约暴露 | 对外 API schema 应类型化，并兼容 JSON Schema / OpenAPI | 支撑前端、SDK、Eval 和外部集成方。 |
| 持久化方向 | PostgreSQL 16、JSONB、UUID、tenant/workspace 字段、pgvector 轻量语义检索 | 与 MVP 和后续多租户演进一致。 |
| SQL Safety | sqlglot-first 解析、SELECT-only、schema allowlist、危险模式检测、参数校验、limit policy | 与当前代码方向一致。 |
| Eval Gate | Golden Query Eval、SQL Safety 回归、EvidenceChain 完整性、延迟和阈值报告 | 防止 AI 开发表面完成、实际不可用。 |
| 可观测性 | Trace-by-default，后续接 OpenTelemetry | EvidenceChain 和 OperationTrace 必须可回放。 |
| 前端方向 | Next.js + TypeScript + 分阶段 Intent Workspace | 符合前端架构评审和 contract-driven UI。 |
| Model Gateway | BYO Key 引用、模型路由、token/cost 归因、默认不记录原始 prompt | 满足企业级成本、安全和审计治理。 |
| 本地交付 | Docker Compose 本地开发、GitHub Actions CI | 适合小团队快速落地并保留工程化边界。 |

### 3.2 调整后采纳

| 方案项 | 调整后裁决 |
|---|---|
| “所有契约对象必须是 Pydantic 模型” | 对外 API schema 应使用 Pydantic 或生成 JSON Schema；内部 contract 可继续使用 dataclass，是否迁移需另开 ADR。 |
| SQLAlchemy + Alembic | 持久化阶段采纳；当前 Trusted Loop 骨架不被数据库 schema 工作阻塞。 |
| Celery + Redis | 等异步 Eval、数据刷新、长任务确实出现后再引入；先保留 `AsyncJobRuntime` 边界。 |
| Vault / K8s Secret | 企业 Hybrid / 私有化阶段目标；MVP 先做本地密钥卫生、环境变量引用和禁止明文持久化。 |
| Feature Flags | MVP 先用配置型开关；Unleash / LaunchDarkly 等到租户灰度、实验或付费试点需要时再引入。 |
| 模型路由表 | 作为方向参考；最终模型组合必须由 Eval、成本、延迟、数据驻留和客户部署约束共同决定。 |
| RLS 和多租户 | 引入持久化时从第一天保留字段；完整 RLS 执行放到后续持久化里程碑。 |
| Monaco Editor | 适合 MetricContract / SQLTemplate 管理界面，但不是第一版前端骨架阻塞项。 |

### 3.3 产品 Core 明确拒绝

| 拒绝项 | 原因 |
|---|---|
| LangGraph 作为产品 Core Agent Framework | 与 ADR-0006 冲突，只允许非生产 spike / benchmark / 参考研究。 |
| `business_data_os/` 作为实现根目录 | 与独立项目边界和现有仓库命名冲突。 |
| 外部 Agent 框架接管 Core 状态管理 | 会削弱自研 Agent OS 技术护城河并形成锁定。 |
| OS Core 直接 import 平台 SDK | 破坏 ProviderContract / OperationContract 边界。 |
| 原始工程实现方案直接成为权威文档 | 原始文件只是归档来源；只有采纳评审、ADR 和 source-of-truth 文档生效。 |

### 3.4 延后处理

| 延后项 | 重新评审触发条件 |
|---|---|
| Kubernetes 生产部署 | 第一个真实客户 / Hybrid 部署或生产硬化阶段。 |
| Sentry | 用户可用 MVP 进入持续外部测试后。 |
| Vault | 企业 BYO Key 或客户私有化部署需求出现后。 |
| LaunchDarkly / Unleash | 真实租户灰度、实验或付费试点需要后。 |
| MaxCompute、ClickHouse、MySQL Provider 全量集合 | Customer-0 和首个付费试点的数据源优先级决定。 |
| 完整 RLS / RBAC | 持久化、Auth、Tenant Model 和 Admin UI 稳定后。 |
| Domain Pack SDK / Marketplace | 第二个可复用领域包验证成功后。 |

## 4. 对现有基线的变更

1. 修正 MVP 技术选型文档中的残留冲突：不得再把 LangGraph 描述为 MVP 内部实现方案。
2. 当前产品 Runtime 骨架继续保持自研。
3. 后续 API surface 稳定后，再评审是否将内部 contracts 从 dataclass 迁移到 Pydantic。
4. 引入 SQLAlchemy、Alembic 和 PostgreSQL 表结构前，必须先补持久化 ADR。
5. 前端继续按 `AR-20260601-frontend-workspace-architecture.md` 分阶段推进。
6. 辅助工程化工作流继续与产品代码分离。

## 5. Agent 执行规则

任何 Agent 使用归档工程实现方案前，必须先把建议分类到四类之一：

```text
direct-adopt
adapt-before-adopt
reject-for-product-core
defer-until-triggered
```

任何 Agent 不得引用归档原文覆盖以下边界：

```text
ADR-0006 Agent OS Core self-developed boundary
ADR-0007 independent project boundary
ADR-0008 privacy computing and verifiable audit boundary
AI_Agent engineering workflow/product runtime separation
```

任何被采纳的代码实现仍必须通过 Engineering Reality Gates：

```text
entry point
typed contract/schema
failure mode
integration path
test/eval that fails if bypassed
trace/evidence impact
boundary check
```

## 6. 下一步工程影响

这份方案加强了下一阶段实施顺序：

1. 产品代码继续在 `ai-native-business-data-agent-os/` 推进。
2. 优先稳定 API schema 和前端 contract mocks。
3. 在扩大 NL2SQL 自动化前，先补 Eval 阈值报告。
4. 持久化必须等待 Persistence ADR 和 schema review。
5. 外部基础设施必须有具体里程碑触发，不能因为方案里出现就提前引入。

近期代码库不应因为这份实现方案就引入 LangGraph、Celery、SQLAlchemy、Vault 或具体平台 SDK。
