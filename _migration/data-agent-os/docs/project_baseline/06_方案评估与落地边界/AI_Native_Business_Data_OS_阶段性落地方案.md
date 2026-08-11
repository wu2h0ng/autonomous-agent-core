# AI Native Business Data OS 阶段性落地方案

## 1. 文档目的

本文将 AI Native Business Data OS 的长期愿景拆成可执行阶段。

它补充以下判断：

1. 当前方案有哪些不足和过度理想化之处。
2. 第一阶段应该收敛到什么边界。
3. 每个阶段应交付什么、不交付什么。
4. 需要哪些业务、数据、技术、安全和组织支撑。
5. 什么时候可以进入下一阶段，什么时候必须停止扩张。

---

## 2. 总体判断

当前方案的长期方向成立，但实施范围过满。

它适合作为 3 到 5 年产品北极星，不适合直接作为第一版研发范围。

第一阶段不应对外销售完整“OS”，也不应试图一次性完成 Data Agent、Business Agent、EvidenceChain、Provider SDK、Action Connector、MCP Gateway、Model Gateway、Hybrid、Private、Marketplace 和完整 KnowledgeAsset 全部能力。但内部架构必须按 Business Data & Agentic Operations OS 设计，避免第一版代码变成不可扩展的问数工具。

更现实的第一阶段目标是：

```text
在一个业务部门中证明：
业务问题
→ 可信数据产品
→ EvidenceChain
→ 业务洞察
→ 行动提案
→ 人工确认
→ 任务或审批流
→ 结果反馈
→ KnowledgeAsset candidate

能够把数据需求交付周期从数天/数周降到小时级，
并让关键建议可以被追踪、复盘、评测和沉淀。
```

---

## 3. 当前方案的主要不足

### 3.1 MVP 承载过重

原方案 Horizon 1 已包含：

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
- reference domain pack。

这些每一个都可以单独成为产品模块。若全部放进 0 到 18 个月目标，会产生三个问题：

1. 平台骨架很多，但客户可感知价值不够尖。
2. 团队被基础设施拖住，难以形成高频使用场景。
3. 销售和交付容易讲不清第一版到底卖什么。

### 3.2 OS 定位过早

“AI Native Business Data OS”适合作为战略定位，但早期客户不会先购买 OS。

客户更容易购买的是：

- 提数变快。
- 口径可信。
- AI 回答可追溯。
- 报表需求减少。
- 异常诊断更快。
- 建议能变成任务或审批。
- 业务复盘有证据。

早期对外表达应避免“替代 BI、替代数仓、企业操作系统”这类高阻力语言。

### 3.3 从 Data Agent 到 Business Agent 的责任跳跃被低估

问数和写业务系统不是同一种风险。

从“回答 ROI 为什么下降”到“暂停广告计划、调整预算、写入 CRM、触发 ERP 变更”，会立刻涉及：

- 权限。
- 审批。
- 职责分离。
- 幂等。
- 回滚。
- 补偿。
- 异常处理。
- 责任归属。
- 审计留存。

因此第一阶段 Business Agent 不应默认直接执行高风险动作，而应优先生成行动提案、审批单、任务和 dry-run 结果。

### 3.4 对企业数据基础的假设偏乐观

EvidenceChain、MetricContract、Semantic Registry 都依赖相对清晰的数据基础。

现实中常见问题包括：

- 表和字段无人负责。
- 指标口径跨部门冲突。
- 历史数据缺失。
- 数据质量规则没有沉淀。
- 权限继承不清。
- 业务系统字段和数据仓库字段不一致。
- 关键口径只存在于人的经验里。

AI 不能自动消除这些组织债。产品必须把数据 owner、指标治理、质量规则和人工 review 纳入流程。

### 3.5 生态接入范围过宽

Provider SDK、Action Connector SDK、MCP Gateway、Model Gateway、Workflow Bridge、BYO Key、BYO Model、BYO Compute 都有价值，但早期同时推进会把团队拖入连接器泥潭。

每个连接器都不仅是 API 调用，还包含：

- 鉴权。
- 字段映射。
- 权限 scope。
- 限流。
- 错误重试。
- 版本兼容。
- 日志和审计。
- 客户侧部署。
- 安全审查。

早期应只做能支撑首发闭环的最小 Provider 和最小 Action。

### 3.6 私有化和 Air-gapped 不应前置

完整私有化不是“把系统打包给客户”。

它需要：

- Helm chart 或 Docker Compose。
- 离线镜像。
- 私有对象存储和数据库适配。
- 客户 IAM、Vault、SIEM 集成。
- license。
- backup / restore。
- upgrade runbook。
- compatibility check。
- 安全扫描。
- 现场故障定位能力。

Air-gapped 还需要离线模型、离线 embedding、离线 eval pack、离线漏洞库快照和离线升级包签名验证。

这些应作为企业试点后的阶段能力，而不是 MVP 目标。

---

## 4. 阶段性实施原则

### 4.1 场景先于平台

先打穿一个高频业务场景，再抽象平台能力。

建议优先选择：

- 内容电商经营。
- 投放效率诊断。
- 销售运营。
- 财务经营分析。
- 客服运营。

首发场景必须满足：

1. 问题高频。
2. 数据相对可获得。
3. 指标价值可量化。
4. 业务 owner 愿意参与。
5. 行动建议能被验证。

### 4.2 证据先于自动化

第一阶段核心价值是“可信业务生产闭环”，不是“全自动”。

没有 DataProduct candidate 的答案容易退化为一次性问答；没有 EvidenceChain 的回答不能进入业务决策；没有 OperationTrace 的动作不能进入自动执行；没有 KnowledgeAsset candidate 的反馈不能形成长期复利。

### 4.3 行动先提案，后执行

Business Agent 的阶段顺序应是：

```text
建议
→ 行动提案
→ dry-run
→ 审批单或任务
→ 低风险自动执行
→ 高风险受控执行
```

### 4.4 Contract 要先做，但只做最小集

需要 Contract-first，但不要一开始做完整 SDK 和 Marketplace。

第一阶段只定义最小契约：

- BusinessIntent。
- MetricContract。
- ProviderContract。
- DataProduct。
- EvidenceChain。
- ActionProposal。
- ApprovalRecord。
- OperationTrace lite。
- KnowledgeAsset candidate。

### 4.5 Pack 只能从复用中长出来

不要先设计庞大的 DomainPack SDK。

先在一个领域打穿，再迁移到第二个领域。当同一内核能服务两个业务域时，再抽象 DomainPack。

---

## 5. 阶段 0：落地场景和数据准备

建议周期：2 到 4 周。

目标不是写大量代码，而是判断是否具备可落地条件。

### 5.1 关键产物

- 首发业务域选择。
- 30 到 50 个真实业务问题。
- 10 到 20 条 golden query。
- 3 到 5 条 golden business loop。
- 核心指标字典。
- 核心数据源清单。
- 数据 owner 和业务 owner。
- 权限和敏感字段清单。
- 第一版 ROI 计算方式。

### 5.2 验收标准

- 至少 80% 高频问题能映射到已有数据源。
- 核心指标有明确 owner。
- 关键 SQL 可以人工验证。
- 业务方愿意每周参与评测。
- 至少有 1 条行动建议能被真实执行或转成任务。

### 5.3 不做

- 不做通用平台。
- 不做 Marketplace。
- 不做复杂私有化。
- 不做高风险自动执行。
- 不做多行业抽象。

---

## 6. 阶段 1：可信业务生产闭环 MVP

建议周期：1 到 3 个月。

目标是让业务用户可以用自然语言提出业务意图，并获得可复用 DataProduct candidate、带证据链的可信答案、可审批 ActionProposal、可追踪反馈和 KnowledgeAsset candidate。

### 6.1 核心能力

- Intent Intake。
- 指标解析。
- 受控 SQL 生成或模板匹配。
- 权限检查。
- 数据质量基础检查。
- EvidenceChain v1。
- 答案置信度和限制说明。
- golden query 评测。
- 查询历史和用户反馈。

### 6.2 最小技术边界

```text
Business Question
→ BusinessIntent
→ MetricContract
→ SQL Template / Query Plan
→ Query Execution
→ Quality Check
→ EvidenceChain
→ Answer
→ Feedback
```

### 6.3 验收指标

- 高频问题覆盖率达到 60% 到 70%。
- golden query 正确率达到 85% 以上。
- 核心指标口径命中率达到 90% 以上。
- 查询结果可复现。
- 每个正式答案都有 EvidenceChain。
- 用户能指出证据来自哪里。

### 6.4 不做

- 不做通用 Data Product Compiler。
- 不做复杂 Agent 自主规划。
- 不做自动写业务系统。
- 不做客户自定义 Pack。
- 不做 MCP Gateway 全量治理。

---

## 7. 阶段 2：Data Product Compiler v1

建议周期：3 到 6 个月。

目标是从“问答”升级为“可复用数据产品生成”。

### 7.1 核心能力

- DataRequirement 生成。
- ProviderContract 最小版。
- DataProduct schema。
- Query Plan / Transform Plan。
- 数据质量契约。
- 数据产品版本。
- EvidenceChain v2。
- DataProduct catalog。
- Evaluation dashboard。

### 7.2 验收指标

- 高频数据需求不需要工程师每次手写 SQL。
- 至少 10 个 DataProduct 可复用。
- 数据产品有 owner、version、lineage、quality status。
- 关键结果可以从 EvidenceChain 回放。
- 新增一个相似问题的交付时间低于人工方式 50%。

### 7.3 不做

- 不做任意复杂 ETL 自动生成。
- 不承诺取代 dbt、Airflow、Dagster。
- 不做跨全部数据源自动发现。
- 不做业务动作自动执行。

---

## 8. 阶段 3：提案型 Business Agent

建议周期：6 到 9 个月。

目标是把可信洞察转化为行动提案、审批单和任务流。

### 8.1 核心能力

- ActionProposal。
- OperationContract lite。
- 风险等级。
- dry-run。
- 审批路径配置。
- 任务或工单生成。
- OperationTrace lite。
- 执行反馈采集。

### 8.2 行动边界

第一版 Business Agent 可以：

- 生成建议。
- 生成审批单。
- 创建任务。
- 推送通知。
- 生成变更计划。
- 对低风险动作执行 dry-run。

第一版 Business Agent 不应默认：

- 直接调整广告预算。
- 直接暂停高价值投放计划。
- 直接修改 ERP、财务或库存系统。
- 直接变更客户数据。
- 绕过审批流执行写操作。

### 8.3 验收指标

- 至少 3 条 golden business loop 跑通。
- 行动提案采纳率可统计。
- 每个行动提案都有证据链引用。
- 每个审批或任务都有 OperationTrace。
- 执行结果能回流到反馈表或事件表。

---

## 9. 阶段 4：Domain Pack 产品化

建议周期：9 到 12 个月。

目标是把首发场景从项目实现抽象为可复用包。

### 9.1 核心能力

- Domain Pack manifest。
- 领域指标模板。
- 领域业务问题模板。
- golden query pack。
- golden business loop pack。
- Provider mapping。
- Action proposal template。
- Eval pack。

### 9.2 进入条件

- 首发领域已经有稳定复用。
- 至少一个第二业务域开始接入。
- 内核中没有写死首发行业对象。
- 领域差异可以通过配置、模板和映射表达。

### 9.3 验收指标

- 第二个业务域的接入周期明显短于第一个。
- 至少 50% 内核能力可复用。
- 新 domain pack 不需要改 OS Core。
- 评测样本能随 pack 发布。

---

## 10. 阶段 5：企业试点和 Hybrid 支持

建议周期：12 到 18 个月。

目标是支持真实企业客户试点，但仍避免进入无限定制。

### 10.1 核心能力

- Tenant / Workspace / User / Role。
- OIDC 登录。
- 基础 RBAC。
- Connector Agent。
- BYO Key 最小治理。
- Audit export。
- SaaS + Hybrid deployment profile。
- 基础 quota 和 cost tracking。
- 客户侧部署 runbook。

### 10.2 验收指标

- 一个外部客户或准客户完成试点。
- 客户数据无需完全出内网即可完成核心闭环。
- 审计日志可以导出。
- 客户 key 不进入业务代码。
- 试点交付内容可以沉淀为通用 Contract、Connector 或 Pack。

### 10.3 不做

- 不做完整 Air-gapped。
- 不做所有云厂商适配。
- 不做复杂 Marketplace。
- 不做完全自助开发者生态。

---

## 11. 阶段 6：平台化和生态化

建议周期：18 到 36 个月。

目标是从部门级产品升级为多场景商业平台。

### 11.1 核心能力

- 多租户控制面。
- Provider SDK。
- Action Connector SDK。
- Business Agent Pack。
- Eval Pack。
- Model Gateway 完整能力。
- MCP Gateway。
- Workflow Bridge。
- Marketplace beta。
- Private deployment template。
- 高级权限和审计。

### 11.2 进入条件

- 至少两个业务域证明可复用。
- 至少一个企业客户愿意为治理和部署能力付费。
- 核心闭环指标稳定。
- 交付不再依赖大量一次性代码。

---

## 12. 实现边界

### 12.1 第一阶段必须守住的边界

- 只承诺一个首发业务域。
- 只接入必要数据源。
- 只做必要指标。
- 只做可验证答案。
- 所有正式答案都要 EvidenceChain。
- 业务动作先做提案和审批。
- 所有写操作默认人工确认。
- 所有新增能力都要进入 eval。

### 12.2 第一阶段明确不承诺

- 不承诺自动理解所有表。
- 不承诺自动解决所有指标冲突。
- 不承诺跨行业通用。
- 不承诺全自动业务执行。
- 不承诺替代 BI、数仓、ETL。
- 不承诺完整私有化。
- 不承诺 Marketplace。
- 不承诺客户自行开发复杂 Pack。

---

## 13. 必要支撑

### 13.1 业务支撑

- 一个强 owner 的首发业务域。
- 每周业务评测会。
- 明确的业务指标和目标。
- 可执行或可验证的行动建议。
- 对失败案例的复盘机制。

### 13.2 数据支撑

- 核心数据源访问权限。
- 指标字典。
- 表字段说明。
- 数据质量规则。
- golden SQL。
- 历史异常样本。
- 业务口径 owner。

### 13.3 技术支撑

- Query execution sandbox。
- SQL 安全校验。
- MetricContract。
- EvidenceChain 存储。
- Evaluation harness。
- Trace 和日志。
- 基础权限系统。
- Connector runtime。

### 13.4 安全支撑

- 最小权限。
- 敏感字段分类。
- 数据脱敏。
- 操作分级。
- 审批流。
- 审计日志。
- 凭证隔离。

### 13.5 组织支撑

最小团队建议：

- Product owner。
- Domain expert。
- Data engineer。
- Backend / platform engineer。
- AI / agent engineer。
- Frontend engineer。
- Security / governance reviewer。
- Solution engineer。

---

## 14. 阶段推进门槛

每进入下一阶段前，必须回答：

1. 当前阶段是否有可量化业务收益？
2. 关键答案是否都能追溯证据？
3. golden query 正确率是否达标？
4. 业务用户是否持续使用？
5. 行动建议是否被采纳或验证？
6. 失败案例是否进入 eval？
7. 新增能力是否沉淀为 Contract、DataProduct、Pack 或 Eval？
8. 是否出现了大量一次性定制代码？
9. 安全和权限是否仍可解释？
10. 团队是否有能力运维当前复杂度？

如果这些问题没有答案，不应继续扩展平台范围。

---

## 15. 最现实的产品路径

建议路径如下：

```text
BusinessIntent
→ 可信数据产品
→ 证据链工作台
→ 行动提案
→ 审批和任务
→ 反馈闭环
→ 知识资产候选
→ 领域包
→ 第二业务域复制
→ 企业级治理
→ 生态和平台化
```

这个路径保留了 AI Native Business Data OS 的长期方向，但避免第一版被 OS 愿景压垮。

---

## 16. 核心结论

方案不是不现实，而是不能按终局形态一次性实现。

正确方式是：

1. 用理想产品形态统一长期方向。
2. 用阶段性落地方案约束短期边界。
3. 用 EvidenceChain 和 eval 建立信任。
4. 用行动提案替代过早自动执行。
5. 用一个业务域打穿闭环，再抽象为 Pack。
6. 用客户真实反馈推动平台化，而不是凭空建设平台。

---

## 17. 冷启动：数据引导（Data Onboarding）路径

> 补充来源：深度分析报告 — 产品层补充。

当前方案假设企业有指标 owner 和 MetricContract，但对于新客户，这是巨大的摩擦点。需要设计渐进式的数据引导路径。

### 17.1 冷启动三阶段

**阶段0 - 数据探索模式（Day 1-7）**

目标：让客户在零配置情况下看到产品价值。

- 提供"数据发现"工具：自动扫描已接入的数据源，识别表结构、字段名、数据类型
- 生成"指标候选清单"：基于字段名模式匹配和数据分布特征，自动推荐候选指标（如包含"amount/金额"字段自动推荐为收入类指标）
- 用户只需"一键确认"或"一键忽略"，不需要预先填写复杂的 MetricContract 配置表单
- 关键体验：接入数据源后5分钟内看到第一条 EvidenceChain

**阶段1 - 引导建模模式（Day 7-30）**

目标：基于真实使用行为，沉淀高质量 MetricContract。

- 基于用户真实查询历史，自动推荐 MetricContract 草稿（SQL模板、参数、owner）
- "一键确认"式指标口径沉淀：系统推荐 → 用户确认/修改 → 自动纳入 MetricContract 注册表
- 关键体验：用户每次问问题都在帮助系统变得更懂业务

**阶段2 - 自运转模式（Month 1+）**

目标：指标口径通过使用自动完善，新问题自动匹配历史 DataProduct。

- 指标口径通过使用频率和反馈自动调整优先级和置信度
- 新问题自动匹配历史 DataProduct，命中率持续提升
- 指标变更自动触发依赖分析和影响通知
- 关键体验：数据团队从"配置者"变成"审核者"

### 17.2 冷启动成功指标

| 指标 | 目标(Day 7) | 目标(Day 30) |
|---|---|---|
| 数据源接入完成率 | 100% | 100% |
| 自动推荐指标采用率 | ≥ 60% | ≥ 80% |
| MetricContract手动创建比例 | ≤ 40% | ≤ 20% |
| 新问题自动匹配率 | ≥ 30% | ≥ 60% |

---

## 18. 负反馈机制设计

> 补充来源：深度分析报告 — 产品层补充。

当前 FeedbackEvent 定义偏轻量（排除用户点赞点踩），但企业级产品质量需要更丰富的反馈信号。

### 18.1 多层反馈信号

| 信号类型 | 信号来源 | 含义 | 处理方式 |
|---|---|---|---|
| **显式反馈** | 用户主动标记"答案有误" | 质量缺陷 | 立即进入回归评估队列 |
| **隐式反馈-追问** | 用户在同主题下连续追问3次以上 | 初始答案不完整 | 提升该问题类型的语义解析优先级 |
| **隐式反馈-分享** | 用户分享 EvidenceChain 给同事 | 高价值答案 | 自动标记为Golden Query候选 |
| **隐式反馈-采纳** | 用户确认/执行 ActionProposal | 行动建议有效 | 正样本纳入评测集，并生成 KnowledgeAsset candidate |
| **隐式反馈-忽略** | EvidenceChain生成后用户无后续操作 | 低价值或无行动必要性 | 降低该类型问题的主动推送频率 |
| **业务结果反馈** | ActionProposal执行后关联指标变化 | 行动的实际业务影响 | 自动回流更新 MetricContract 置信度，并绑定 OperationTrace |
| **专家复审** | 数据团队主动审核和标注AI答案质量 | 权威质量标签 | 形成高质量训练/评测数据集 |

### 18.2 失败案例升级路径

当错误答案被确认后，需要快速进入防止复发流程：

```text
用户报告错误
  → 自动记录：原始问题、生成SQL、EvidenceChain、用户纠正
  → 自动归类：指标定义错误 / SQL生成错误 / 数据源问题 / 语义理解错误
  → 自动生成 regression test case
  → 加入 Golden Query 反例集（确保不会再次通过）
  → 通知 MetricContract owner 审核
  → 修复后回归测试通过，关闭
```

### 18.3 反馈闭环的度量

| 指标 | 含义 | 目标 |
|---|---|---|
| 错误发现到修复时间 | 从用户报告到回归测试通过 | < 24小时(工作日) |
| 同类错误复发率 | 同一Golden Query在修复后再次失败 | 0% |
| 用户反馈参与率 | 主动提供反馈的用户比例 | ≥ 20% |

---

## 19. MVP退出标准与Pivot触发条件

> 补充来源：深度分析报告 — 风险补充。

### 19.1 MVP成功标准（6个月内必须达到至少3项）

1. 至少1个用户每周自主使用 ≥ 3次
2. Golden Query 覆盖率稳定在 ≥ 70%
3. 至少1个 ActionProposal 被真实采纳并有可追踪的业务结果
4. 至少5个 DataProduct candidate 被复用或进入审核
5. 至少3个 KnowledgeAsset candidate 通过人工复审或进入待发布状态
6. EvidenceChain 生成的答案被业务用户评价为"可信"的比例 ≥ 50%
7. 客户明确表示愿意付费续约

### 19.2 MVP退出红线（触发Pivot评估）

以下任一条件触发Pivot评估：

- 未能让任何一个用户每周自主使用超过3次
- Golden Query 覆盖率无法稳定在70%以上
- 没有一个 ActionProposal 被真实采纳
- 没有任何 DataProduct candidate 被复用
- 没有任何反馈能沉淀为 KnowledgeAsset candidate
- EvidenceChain 生成的答案被业务用户评价为"不可信"超过50%

### 19.3 Pivot方向候选

如果MVP失败，评估以下三个方向：

| 方向 | 描述 | 适用条件 |
|---|---|---|
| **收窄为垂直领域专家工具** | 仅做内容电商领域，深度优化语义层和Domain Pack | 通用语义解析能力不足，但垂直领域效果好 |
| **收窄为数据团队内部工具** | 只服务数据分析师，不做终端业务用户 | 业务用户接受度低，但数据团队认可价值 |
| **转型为API/SDK产品** | 不做终端产品，给其他BI厂商提供EvidenceChain能力 | 产品体验不达预期，但核心技术有竞争力 |
