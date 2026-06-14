# 产品蓝图与原型定义（Product Blueprint & Prototype）

> 日期：2026-06-06
> Owner：Product Manager Agent（CTO 审批前为 draft）
> 状态：draft，待 CTO 评审
> 任务来源：用户指令「定义产品蓝图和原型；分析以下技术方案」
> 输入方案：`AI Native Business Data OS — 工程实现完全方案 v1.0`（等同归档件 `99_原始输入与来源/AI_Native_Business_Data_OS_工程实现完全方案_20260602.md`）

---

## 0. 阅读前必读：本文档与既有基线的关系

用户提供的「工程实现完全方案 v1.0」**不是新的权威基线**。它与归档件
`工程实现完全方案_20260602.md` 实质同源，已由 CTO 在
[AR-20260602 工程实现完全方案采纳评审](../architecture_reviews/AR-20260602-engineering-implementation-plan-adoption-review.md)
中做出「有条件采纳」裁决。

本文档据此：

1. **不重新打开** AR-20260602 已裁决的边界（见第 1 节冲突清单）。
2. 在已通过的采纳结论之上，**综合出产品蓝图**（第 2-4 节）。
3. **对齐既有原型** [Intent Workspace Prototype V2](./intent-workspace-prototype-v2-requirements.md)，把原型从「单屏静态骨架」扩展为「蓝图驱动的原型范围」（第 5-7 节）。

凡本文档与以下文件冲突，以这些文件为准：`MEMORY.md`、`.agent`、`docs/decisions/ADR-*`、`AR-20260602`、`repo_scaffold/README.md`。

---

## 1. 技术方案分析（按既有采纳分类复核）

沿用 AR-20260602 的四分类口径，对 v1.0 方案逐条复核。**重点是冲突项**——
若按方案原文实施会违反工程铁律。

### 1.1 必须纠偏的冲突项（reject-for-product-core）

| 方案 v1.0 原文 | 冲突的基线 | 正确做法 |
|---|---|---|
| 仓库根目录 `business_data_os/` | 独立项目边界（ADR-0007），现仓库为 `ai-native-business-data-agent-os/` | 用现有仓库根，不回退命名 |
| Agent 框架选 LangGraph（外部包装） | ADR-0006 Agent OS Core 必须 100% 自研 | 自研最小 AgentRuntime；LangGraph 仅作 non-production 参考/benchmark |
| 「所有契约对象必须是 Pydantic 模型，不允许 dict 传递」 | AR-20260602 §3.2：内部 contract 现为 dataclass，迁移需另开 ADR | 对外 API schema 用 Pydantic/JSON Schema；内部 contract 暂保持现状 |
| OS Core 直接出现 `dingtalk/`、`maxcompute/` 等平台模块在 core 视图内 | OS Core 不得 import 领域/平台 SDK（铁律#3、ADR-0006、scaffold §4） | 平台逻辑只存在于 `providers/`、`action_connectors/`，经 Contract 注入 |

> ⚠️ 这些是方案 v1.0 里**最容易被 AI/工程师顺手照抄**的部分，且恰好命中
> 项目历史上的「产品身份降格」根因（见 `MEMORY.md` §11）。蓝图必须显式拦截。

### 1.2 需调整后采纳（adapt-before-adopt）

| 方案项 | 调整 |
|---|---|
| SQLAlchemy + Alembic | 进入持久化里程碑再引入；先补 Persistence ADR，不阻塞当前 Trusted Loop |
| Celery + Redis | 等真实异步/长任务出现再引入；先保留 `AsyncJobRuntime` 边界 |
| Vault / K8s Secret | 企业 Hybrid/私有化阶段目标；MVP 做本地密钥卫生 + 环境变量引用，禁明文持久化 |
| 模型路由表（Qwen/Claude/BGE-M3 固定映射） | 仅作方向参考；最终组合由 Eval、成本、延迟、数据驻留、客户部署共同决定，模型名不写死业务代码 |
| Feature Flags（Unleash/LaunchDarkly） | MVP 用配置型开关；外部特性平台等灰度/付费试点再引入 |
| RLS / 多租户 | 持久化第一天保留 `tenant_id` 字段；完整 RLS 执行放后续里程碑 |
| Monaco Editor | 适合 MetricContract/SQLTemplate 编辑，但非第一版前端阻塞项 |

### 1.3 直接采纳（direct-adopt）

FastAPI + Pydantic API 层、PostgreSQL 16/JSONB/UUID/pgvector 方向、
**sqlglot-first SQL 四层安全**、**Eval Gate 阈值门控**、Trace-by-default（后接
OpenTelemetry）、Next.js + TS 分阶段 Workspace、Model Gateway 的 BYO Key /
成本归因 / 默认不记录 prompt、Docker Compose + GitHub Actions 本地交付。

这些与现有代码方向一致，构成蓝图的工程底座。

### 1.4 延后（defer-until-triggered）

Kubernetes 生产部署、Sentry、Vault、特性平台、全量 Provider 集合
（MaxCompute/ClickHouse/MySQL）、完整 RLS/RBAC、Domain Pack Marketplace。
触发条件见 AR-20260602 §3.4。

### 1.5 方案 v1.0 的真正价值

剔除冲突项后，方案 v1.0 对蓝图的**净贡献**是三件具体工程资产：

1. **SQL 四层安全的可执行规格**（语法解析→语句白名单→危险模式→资源限制注入）。
2. **Eval Gate 的阈值表与 CI 门控形态**（exact_match/metric_coverage/evidence_chain_rate/safety_pass_rate/p95）。
3. **三维可观测性**（业务/质量/成本）与 EvidenceChain、OperationTrace 的 span 结构。

蓝图把这三项纳入「不可绕过的工程控制层」。

---

## 2. 产品蓝图（Blueprint）

### 2.1 一句话定义

AI Native Business Data Agent OS 是面向企业 AI Agent 时代的**业务生产操作系统**：
它同时重构数据工程范式和业务生产范式，把**企业业务意图**编译为
**可信数据产品**、**EvidenceChain**、**受治理业务行动**、**反馈学习**和
**企业知识资产**。它不是“只做治理控制面”的薄管道，也不是中间件包装
（铁律#15）；EvidenceChain 是信任基础，DataProduct Compiler + Governed
Operation + KnowledgeAsset 闭环才是产品灵魂。

### 2.2 北极星与价值断言

- **北极星指标**：用户自主提问数 / 周（参照客户≥10 次/周为 MVP 达标线）。
- **价值断言**：提数变快、口径可信、AI 回答可追溯、异常诊断更快、建议能变成审批、复盘有证据。
- **对外语言纪律**：早期不说「替代 BI / 替代数仓 / 企业操作系统」（`MEMORY.md` §8.2）。

### 2.3 能力地图（Capability Map）

```text
┌─────────────────────────────────────────────────────────────┐
│ L0 入口      Intent Workspace UI / API / Scheduled / 外部 Agent │
├─────────────────────────────────────────────────────────────┤
│ L1 意图      Intent Runtime  （NL → 结构化 BusinessIntent）      │
│ L2 语义      Semantic Runtime（SemanticObject / MetricContract） │
│ L3 编译      DataProduct Compiler（Requirement→ProviderPlan→QueryPlan）│
│ L4 取数      Query Runtime + Providers（经 ProviderContract）     │
│ L5 安全      ★ SQL Safety（四层，100% 不可绕过）                  │
│ L6 证据      ★ EvidenceChain Builder（不可选，ADR-003）          │
│ L7 行动      ActionProposal → Approval → ActionConnector        │
│ L8 治理      ★ OperationTrace / Policy / Risk(R1-R5)            │
│ L9 反馈      Feedback Runtime → KnowledgeAsset / Semantic Memory │
├─────────────────────────────────────────────────────────────┤
│ 横切（不可绕过）  Eval Gate ｜ Trace ｜ Model Gateway ｜ Tenant 隔离 │
└─────────────────────────────────────────────────────────────┘
```

★ = 四条信任支柱（SQL Safety / EvidenceChain / Eval / Trace），任何 PR 不得绕过（铁律#2）。

### 2.4 核心链路（MVP 业务生产闭环）

```text
BusinessIntent
  → SemanticObject lite → MetricContract → ProviderContract lite
  → DataProduct candidate → QueryPlan → SQL Safety → QueryResult
  → EvidenceChain → ActionProposal → Approval lite → Feedback / Trace
  → KnowledgeAsset candidate
```

**MVP 边界（lite ≠ stub，铁律#16）**：每个链路节点至少有一个非 stub 真实实现；
R4/R5 高风险动作只生成提案，不自动执行（铁律#4、ADR-004）。

### 2.5 核心契约（蓝图级，权威字段以 contracts 包为准）

| 契约 | 角色 | 关键不变量 |
|---|---|---|
| `BusinessIntent` | 系统入口，替代需求文档 | 必带 tenant、goal、约束 |
| `MetricContract` | 口径单一真相 | 必带 owner、formula、verified、version |
| `ProviderContract` | 数据能力契约 | OS Core 不知登录/selector/SQL 细节 |
| `EvidenceChain` | 核心输出 | 每个结论含 confidence + limitations + 可点击溯源 SQL |
| `ActionProposal` | 行动候选 | 必引用 EvidenceChain；带 risk(R1-R5) |
| `OperationContract` | 写动作边界 | dry-run / 幂等 / 回滚或补偿（不可逆→自动升级风险） |
| `OperationTrace` | 审计链 | proposed→approved→executed→observed 状态机 |

### 2.6 技术栈结论（蓝图采用版）

- 后端：Python 3.11+ / FastAPI / 对外 Pydantic schema（内部 contract 暂 dataclass）。
- 前端：Next.js 14 App Router / TypeScript strict / Tailwind / shadcn/ui / TanStack Query / SSE。
- 数据：PostgreSQL 16 + JSONB + pgvector（持久化里程碑前不落库 schema）。
- SQL 安全：sqlglot-first 自建 checker。
- Agent Runtime：**自研最小版**（外部框架仅参考）。
- 语言边界（ADR-0010）：Python 拥有 OS Core/Trusted Loop；TypeScript 拥有 Workspace UI/CLI/Tooling；Java 留给企业 Connector/重型 SQL Planner/私有化适配。

---

## 3. 工程控制层（蓝图不可协商部分）

从方案 v1.0 净化采纳，作为蓝图的硬约束：

1. **SQL 四层安全**：语法解析(sqlglot) → SELECT-only 白名单 → 危险模式检测 → 资源限制注入（LIMIT/timeout）。safety_pass_rate 必须 = 1.0。
2. **Eval Gate**：Golden Query Eval 进 CI；阈值不达标 PR 阻塞（exact_match≥0.85、metric_coverage≥0.90、evidence_chain_rate=1.0、safety_pass_rate=1.0、p95≤15s）。
3. **Trace-by-default**：每个 intent→action 链路可回放；后接 OpenTelemetry。
4. **三维可观测**：业务（EvidenceChain 成功率/Intent 准确率/采纳率/北极星）、质量（Golden 通过率/失败分类/拦截率/延迟）、成本（每链路模型成本/租户 token/任务分布）。
5. **先写测试再实现**（铁律#17）：测试失败须可证明与实现缺失直接相关，常量返回不得通过。

---

## 4. 实施阶段（与既有 Stage 对齐）

| Stage | 蓝图交付 | 周期 |
|---|---|---|
| Stage 0 | 落地场景 + 数据准备（ProviderContract、5 个核心 MetricContract） | 2-4 周 |
| Stage 1 | 可信业务生产闭环 MVP（DataProduct candidate + EvidenceChain + 受治理行动 + 知识资产候选） | 1-3 月 |
| Stage 2 | DataProduct Compiler v1（多源、QueryPlan 强化） | 3-6 月 |
| Stage 3 | 提案型 Business Agent（ActionProposal + 钉钉审批 + OperationTrace） | 6-9 月 |
| Stage 4 | Domain Pack 产品化（content_commerce 抽象） | 9-12 月 |

PR 跟踪口径沿用 `MEMORY.md` §8.6。注意：截至 2026-06-06，PR-02/03/06 已被 CLI/API、治理门、OperationTrace、Feedback/KnowledgeAsset 等实现部分推进，PR-05 处于 SQL Safety 加固收口中；不能再按“PR-02→07 全部待启动”理解。

---

## 5. 原型定义（Prototype）

原型分两条线，互为印证：**(A) UI 原型**（人机控制面）与
**(B) 链路原型**（首个可运行 Trusted Loop 切片）。

### 5.1 原型目标

让业务负责人/运营经理在一个工作台上回答四个问题：

1. 系统理解了什么问题？
2. 答案为什么可信？
3. 提了什么行动？
4. 什么需要审批或更多证据？

原型**不是** BI 看板、聊天页或营销页，而是**可信业务数据工作的人类控制面**。

### 5.2 (A) UI 原型——以 Intent Workspace V2 为基线扩展

现状基线（已 CTO 批准）：`apps/workspace/prototype/index.html`，F0 静态骨架，
桌面优先，含 7 个模块 + 3 个失败态，AC-01~AC-11 全 Pass。

本蓝图在其上定义 **F1 原型范围**（仍可先以静态 mock 表达，再接 typed API）：

| 模块 | F0 现状 | F1 扩展 |
|---|---|---|
| Business Context | 静态 | 实时意图解析回显（"我理解您在问 ROI…"）+ 推荐问题冷启动 |
| Trusted Answer | 静态 | 结论 + 置信度分级 + eval 覆盖 + 阻断问题数（绑定真实 EvidenceChain 字段） |
| EvidenceChain | 静态 | 每个数字可点击 → 展开来源 SQL / Provider / 质量检查 / limitations |
| Action Governance | 静态 | ActionProposal 仅显示为「提案 / 审批草稿」，带 R1-R5 与观察窗口 |
| Governance Status | 静态 | evidence id / SQL safety / approval / feedback / gap note |
| Trace | 静态 | 有序执行步骤 + trace id（可回放占位） |
| Failure States | 3 态 | loaded / SQL blocked / insufficient evidence + loading/empty 态 |

**渲染纪律**：图表（Recharts）只是 EvidenceChain 的一种渲染形态，不是产品中心；
EvidenceChain 不得被折叠藏在通用答案卡之后。

### 5.3 (B) 链路原型——首个可运行切片

对应 `repo_scaffold` §5「First Implementation Slice」，CLI 已可跑通：

```text
BusinessIntent → SemanticObject lite → MetricContract → ProviderContract lite
→ DataProduct candidate → SQLTemplate/QueryPlan → SQL Safety
→ QueryResult → EvidenceChain → ActionProposal → Approval lite
→ Feedback/Trace → KnowledgeAsset candidate
```

原型数据源用 file/mock provider + DuckDB（仅 eval/fixture），不连生产数据。

### 5.4 原型功能范围

**P0**

- 三个黄金问题：GMV 异常、ROI 诊断、日报扫描。
- 三个状态：loaded、SQL blocked、insufficient evidence。
- EvidenceChain 可见且可溯源；ActionProposal 仅提案/审批草稿；trace id 可见。

**P1**

- backend contract 稳定后接入 typed API；empty/loading 态；更完整 feedback 事件模型；CI 中加 UI smoke test。

**P2**

- 可观测 dashboard；KnowledgeAsset registry 视图；跨流程历史；移动端运营流。

### 5.5 Non-Goals（原型阶段）

- 不接生产数据、不在 F0/F1 接 live API（除非 typed contract 稳定）。
- 不在 Core import domain-pack 业务逻辑。
- 不直接执行 R4/R5 业务动作。
- 不为原型新增后端契约字段（字段以 contracts 包为准）。

---

## 6. 原型验收标准

继承 V2 的 AC-01~AC-11（已 Pass），新增 F1 项：

| ID | 标准 |
|---|---|
| AC-12 | EvidenceChain 中任一数字可点击展开其来源 SQL 与 Provider |
| AC-13 | 置信度分级（high/medium/low/uncertain）可见且来自 EvidenceChain 字段 |
| AC-14 | SQL blocked 态展示被拦截的安全层与原因 |
| AC-15 | ActionProposal 显示 R1-R5 风险等级与审批要求，且引用 evidence id |
| AC-16 | 链路原型 CLI 端到端可运行并产出非 stub EvidenceChain（铁律#16 验证） |

---

## 7. 工程交接

- UI 原型入口：`ai-native-business-data-agent-os/apps/workspace/prototype/index.html`
- 链路原型入口：`python -m agent_os_api.cli --question "GMV" --start-date … --end-date … --limit 100`
- 验证截图目录：`output/playwright/`
- 下一步：F1 仍保持静态/CLI；前端脚手架建立后再拆 React/Next 组件边界；typed contract 与后端测试稳定前不接 live API。

---

## 8. 给 CTO 的待决问题

1. 本蓝图是否可作为 `docs/product/` 下的**产品蓝图 source-of-truth**（而非仅 draft）？
2. F1 原型是否在「前端脚手架 PR-07」内一并推进，还是单独切 PR？
3. 内部 contract 由 dataclass 迁移 Pydantic 是否现在开 ADR（关系到方案 v1.0 §2.2 的最终落地）？
