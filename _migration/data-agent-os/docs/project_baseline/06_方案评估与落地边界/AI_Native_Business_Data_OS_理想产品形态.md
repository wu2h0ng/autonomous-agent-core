# AI Native Business Data OS 理想产品形态

## 1. 文档目的

本文描述 AI Native Business Data OS 的理想产品形态，也就是长期北极星。

它回答三个问题：

1. 如果产品最终成立，它应该改变企业里的哪条工作链路？
2. 理想状态下，用户、数据、Agent、业务动作和知识资产之间应该如何协同？
3. 哪些能力属于长期产品形态，不能被误读为第一版必须一次性交付？

本文不定义 MVP 范围。阶段性落地范围请见：

`06_方案评估与落地边界/AI_Native_Business_Data_OS_阶段性落地方案.md`

---

## 2. 一句话定义

**AI Native Business Data OS 是把业务意图编译成可信数据产品，并驱动可治理、可追踪、可反馈业务 Agent 工作流的企业操作层。**

它不是为了替换数据库、数仓、BI、ETL、CRM、ERP 或审批系统，而是在这些系统之上建立一条新的责任链：

```text
业务目标
→ 数据需求
→ 可信数据产品
→ 证据链
→ 业务洞察
→ 行动提案
→ 审批和执行
→ 结果反馈
→ 企业知识资产
```

这条链路的核心价值不是“AI 会聊天”，而是让企业从“报表和人肉推进”升级为“意图、证据、动作、反馈一体化”。

---

## 3. 理想产品承诺

理想状态下，产品对企业客户的承诺是：

1. 业务人员不需要理解表、SQL、ETL 和 BI 建模，也能提出可执行的数据问题。
2. 每个关键答案都能追溯到指标口径、查询逻辑、数据来源、质量检查和权限上下文。
3. 每个重要洞察都能转化为行动候选、审批单、业务任务或系统动作。
4. 每个业务动作都有风险分级、审批、执行记录、回滚或补偿策略。
5. 每次分析、审批、执行和复盘都会沉淀为可治理的企业知识资产。
6. 企业已有的数据源、业务系统、模型、Agent、MCP 工具和工作流可以通过契约接入，而不是被强制替换。

---

## 4. 理想用户体验

### 4.1 从业务目标进入，而不是从报表进入

用户不再说：

```text
帮我做一张本周 ROI 按平台拆解的看板。
```

而是说：

```text
为什么本周投放效率下降？哪些计划需要处理？如果要恢复到目标 ROI，建议怎么做？
```

系统应该自动完成：

1. 识别业务意图。
2. 解析目标指标和时间窗口。
3. 绑定指标口径和权限。
4. 发现可用数据源。
5. 生成查询或数据产品计划。
6. 校验质量和口径冲突。
7. 形成 EvidenceChain。
8. 输出结论、置信度、限制和行动候选。

### 4.2 从洞察自然进入业务动作

用户看到的不是孤立建议：

```text
建议暂停计划 A。
```

而是一个可治理行动提案：

```text
行动候选：暂停计划 A 24 小时
原因：近 3 日 ROI 低于基线 58%，消耗占比 21%，转化率未同步改善
风险等级：中
审批人：投放负责人
执行方式：广告平台 Action Connector
回滚策略：恢复原预算和状态
观察窗口：24 小时
反馈指标：ROI、GMV、消耗、转化率
```

### 4.3 从一次性回答变成组织记忆

每次闭环结束后，系统应该沉淀：

- 这次问题的 BusinessIntent。
- 使用的数据产品和 SQL。
- 指标口径和质量结果。
- 关键证据和业务解释。
- 人工审批意见。
- 实际执行结果。
- 复盘结论。
- 可复用 SOP、规则或异常案例。

这些内容不应只留在聊天记录或日志里，而应进入 KnowledgeAsset registry，并带有 owner、version、classification、policy、eval score 和过期复审机制。

---

## 5. 理想产品组成

### 5.1 Intent Workspace

用户表达业务目标、查看分析路径、确认证据链、审批行动提案、追踪执行结果的统一工作区。

它不是传统 Dashboard 首页，也不是单纯 Chat UI。它更像业务工作台：

- 当前业务问题。
- 数据证据。
- 指标解释。
- 行动候选。
- 审批状态。
- 执行反馈。
- 相关知识资产。

### 5.2 Semantic Operating Layer

企业语义层不只是 Metric Layer，而是业务实体、指标、规则、流程、权限和行动语义的统一运行时。

核心对象包括：

- BusinessIntent。
- Semantic Object。
- MetricContract。
- DataRequirement。
- DataProduct。
- EvidenceChain。
- OperationContract。
- OperationTrace。
- KnowledgeAsset。

### 5.3 Data Product Compiler

Data Product Compiler 是理想产品的核心引擎。

它将业务意图编译为可验证的数据产品，而不是只让大模型直接生成答案。

典型流程：

```text
Parse Intent
→ Resolve Semantics
→ Plan Data Requirements
→ Select Providers
→ Generate Build Plan
→ Validate Plan
→ Materialize or Virtualize
→ Build EvidenceChain
→ Generate Insight and Action Candidates
→ Feedback
```

### 5.4 EvidenceChain Runtime

EvidenceChain 是企业信任的基础载体。

它至少需要包含：

- 用户原始问题和解析后的意图。
- 指标口径。
- 数据源和表字段。
- 查询计划或 SQL。
- 权限检查结果。
- 数据质量检查结果。
- 血缘和时间窗口。
- 分析过程。
- 结论置信度。
- 限制和不确定性。

没有 EvidenceChain 的回答只能算 AI 建议，不能进入企业决策链路。

### 5.5 Business Agent Runtime

Business Agent 不应绕过 Data Agent 自行解释数据。它消费 EvidenceChain，并将可信洞察转化为可审批、可追踪、可反馈的业务行动。

它的职责包括：

- 生成行动候选。
- 识别风险等级。
- 匹配审批路径。
- 生成 OperationContract。
- 调用 Action Connector 或外部 Workflow。
- 写入 OperationTrace。
- 收集执行反馈。

### 5.6 Action Governance Plane

所有写操作都必须经过治理层。

关键能力包括：

- risk level。
- dry-run。
- approval。
- separation of duties。
- idempotency。
- rollback 或 compensation。
- audit。
- policy gate。
- execution trace。

理想状态不是让 Agent 无限自动化，而是让 Agent 的行动能力被企业责任体系接住。

### 5.7 Knowledge Asset Plane

企业知识资产层沉淀长期护城河。

知识资产包括：

- 指标口径和术语。
- 业务实体和关系。
- 数据产品、SQL、质量契约和血缘。
- EvidenceChain。
- 操作 SOP。
- 人工审批理由。
- 异常案例。
- OperationTrace。
- 复盘结论。
- golden intent、golden query、eval pack。

### 5.8 Ecosystem Gateway

理想产品必须接入企业已有生态，而不是替换一切。

关键网关包括：

- Provider Gateway：数据库、文件、SaaS API、事件流、浏览器采集。
- Action Gateway：CRM、ERP、广告、客服、工单、审批。
- MCP Gateway：第三方工具和本地工具治理。
- Model Gateway：BYO Key、BYO Model、BYO Compute、多模型路由。
- Workflow Bridge：Temporal、Airflow、Dagster、n8n、Power Automate、客户自研流程。

---

## 6. 理想商业形态

长期商业化不应直接卖“替代 BI”或“替代数仓”。

更合理的表达是：

```text
我们不替换你的数据库、数仓、BI、CRM、ERP。
我们在它们之上建立业务意图到可信数据产品和可治理行动闭环的操作层。
```

理想收入结构可以来自：

- Core workspace。
- Data Product Compiler。
- EvidenceChain 和审计留存。
- Provider / Action Connector。
- Domain Pack。
- Business Agent Pack。
- Eval Pack。
- BYO Model / BYO Key 治理。
- Hybrid / Private deployment。
- KnowledgeAsset registry。
- Marketplace 和认证生态。

---

## 7. 理想护城河

真正的长期护城河不是某个聊天界面，而是以下资产的复合：

1. **业务意图到数据产品的编译能力。**
2. **可信证据链和评测体系。**
3. **可治理业务动作运行时。**
4. **跨客户、跨行业可复用的 Domain Pack。**
5. **Provider 和 Action Connector 生态。**
6. **企业知识资产沉淀。**
7. **权限、审计、审批和部署能力带来的企业信任。**

---

## 8. 理想形态的必要支撑

理想形态成立，需要以下支撑条件：

### 8.1 数据支撑

- 核心数据源稳定可访问。
- 指标 owner 明确。
- 指标口径可版本化。
- 字段含义可解释。
- 质量规则可执行。
- 历史样本可用于评测。

### 8.2 业务支撑

- 有明确首发业务域。
- 有业务 owner 参与评审。
- 行动建议可以被验证。
- 业务动作有真实反馈指标。
- 组织愿意把 SOP 和审批理由资产化。

### 8.3 技术支撑

- Contract-first 的 Provider、Action、Model、Workflow 抽象。
- Evaluation Runtime。
- Policy Engine。
- Audit and trace。
- Connector runtime。
- Model Gateway。
- 可观测性和成本治理。

### 8.4 安全合规支撑

- IAM / OIDC / SCIM 集成。
- RBAC、ABAC、ReBAC 组合权限。
- 数据分类和目的访问控制。
- 敏感字段脱敏。
- 审批和职责分离。
- 审计导出到客户 SIEM。

### 8.5 组织支撑

- Platform Kernel。
- Data Product。
- Agent Runtime。
- Integration Ecosystem。
- Security & Governance。
- Evaluation。
- Domain Pack。
- Cloud / SRE。
- Solution Architecture。

---

## 9. 不能误读为第一版承诺

理想形态不能被误读为：

- 第一版就支持所有行业。
- 第一版就自动接入所有企业系统。
- 第一版就可以直接执行高风险写操作。
- 第一版就支持完整私有化和 Air-gapped。
- 第一版就有 Marketplace。
- 第一版就允许客户低成本自建 Pack。
- 第一版就能自动解决客户所有历史数据问题。

理想形态是北极星，不是初始交付清单。

---

## 10. 核心判断

AI Native Business Data OS 的理想形态是成立的，因为企业真正缺的不是更多报表，而是从业务意图到数据证据、业务动作、执行反馈和知识资产之间的连续责任链。

但理想形态必须通过阶段性产品收敛来实现。第一阶段应证明一个部门级闭环，而不是直接建设完整 OS。

---

## 11. 用户旅程：从激活到锁定

> 补充来源：深度分析报告 — 产品层补充。

理想产品形态需要落地到用户可感知的旅程。以下是期望的用户生命周期：

### 11.1 四阶段用户旅程

**Day 1（激活）：用户第一次提出问题并获得可信答案**
- 输入：一条自然语言业务问题（如"最近7天GMV是多少"）
- 输出：一个带有 EvidenceChain 的答案（数据来源、SQL、质量检查、置信度）
- 关键体验：用户第一次看到答案的"为什么可信"，而非仅仅"是什么"
- 成功标准：用户点击展开 EvidenceChain 查看细节

**Week 1（习惯）：用户建立日常使用习惯**
- 从"试试看"到"每天打开"
- 关键驱动：每次提问能得到一致、可复现的答案
- 辅助驱动：系统记住用户常用的指标和数据范围，减少重复配置
- 成功标准：用户每周自主使用 ≥ 3次

**Month 1（价值）：用户衡量产品带来的具体价值**
- 可感知变化：原来需要找数据分析师的简单问题现在自己就能得到答案
- 可量化变化：提数周期从 X天 降到 Y小时
- 关键驱动：第一次被业务同事问"你这个数据从哪来的"时，能直接分享 EvidenceChain
- 成功标准：用户向至少1位同事推荐产品

**Month 3（扩展）：使用从个人扩展到团队**
- 关键驱动：团队成员发现同一个问题的答案一致（MetricContract保证）
- 扩展方式：共享 MetricContract、共享 EvidenceChain、共享 Golden Query
- 成功标准：团队内至少3人每周使用

**Year 1（锁定）：知识资产沉淀形成迁移成本**
- 沉淀内容：50+ MetricContract、200+ EvidenceChain、30+ Golden Query、业务特定语义
- 迁移成本：切换工具意味着丢失所有业务口径定义和历史证据
- 成功标准：客户续约决策中"迁移成本"成为关键考量因素

### 11.2 核心 Aha Moment 候选

Aha Moment 是用户第一次感受到产品不可替代性的时刻。三个候选：

| 候选 | 场景 | 体验差异 | 优先级 |
|---|---|---|---|
| **查看EvidenceChain** | 用户第一次看到答案背后的完整证据链（数据来源、SQL、质量检查） | 相比裸 ChatBI：从"信不信由你"到"你可以自己验证" | P0 |
| **ActionProposal被采纳** | 用户第一次把AI生成的行动建议转化为真实业务动作并看到结果 | 相比所有分析工具：从"看完就完了"到"看完能做事" | P1 |
| **发现可复用DataProduct** | 数据团队看到某个重复性问题自动变成了可复用的数据产品 | 相比传统BI：从"每次都重新做"到"一次配置，自动复用" | P0 |

建议在MVP阶段重点设计和验证前两个 Aha Moment。

---

## 12. 产品指标体系（North Star & Guardrail Metrics）

> 补充来源：深度分析报告 — 产品层补充。

当前文档有业务验收指标，但缺少完整的产品指标树来指导日常决策。

### 12.1 产品指标树

| 层级 | 指标 | 定义 | 目标(MVP 6个月) |
|---|---|---|---|
| **北极星** | 每周活跃业务问题数（带EvidenceChain） | 一周内通过系统生成的完整EvidenceChain数量 | ≥ 20(单客户) |
| **引导指标** | Intent → EvidenceChain 完成率 | 用户提出的业务问题中成功生成完整EvidenceChain的比例 | ≥ 85% |
| **引导指标** | ActionProposal 采纳率 | 生成的行动提案中被用户确认或执行的比例 | ≥ 20% |
| **健康指标** | Golden Query 覆盖率 | 预定义Golden Query集合中被系统正确回答的比例 | ≥ 85% |
| **健康指标** | SQL安全拦截率 | 不安全SQL被正确拦截的比例 | 100% |
| **护栏指标** | 每次EvidenceChain生成成本 | 包含模型调用、数据库查询、语义解析的综合成本 | < ¥0.5 |
| **护栏指标** | P95 响应时间 | 从提问到EvidenceChain展示的端到端时间 | < 15秒 |
| **护栏指标** | 系统可用率 | 核心API可用性 | ≥ 99.5% |

### 12.2 指标看板节奏

| 频率 | 关注指标 | 决策人 |
|---|---|---|
| 每日 | P95响应时间、系统可用率、SQL安全拦截率 | 工程团队 |
| 每周 | 活跃问题数、完成率、采纳率 | 产品经理 |
| 每月 | Golden Query覆盖率、成本趋势 | CTO + 产品负责人 |
| 每季度 | NPS、客户健康度、NRR | CEO + 全员 |

### 12.3 指标驱动的决策框架

- 如果 Intent→EvidenceChain 完成率连续2周 < 80% → 优先修复语义解析和SQL生成
- 如果 ActionProposal 采纳率 < 10% → 优先改进提案质量和相关性
- 如果每次生成成本 > ¥1 → 优先优化模型路由和缓存策略
- 如果 Golden Query 覆盖率下降 > 5% → 进入回归修复模式，禁止新功能开发

