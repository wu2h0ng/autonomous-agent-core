# 工程标准、风险控制与交付 SOP

> 日期：2026-06-01  
> 适用范围：AI Native Business Data OS 第一阶段研发、试点和交付  
> 目标：确保产品不是 demo 型 Agent，而是可审计、可评测、可回归、可控风险的企业软件。

## 1. 工程原则

1. Contract-first：所有关键对象先定义 schema，再实现 Agent、API 和 UI。
2. Evidence-first：没有 EvidenceChain 的正式答案不得进入业务决策。
3. Eval-first：没有 eval 的 Agent、prompt、模型或 SQL 改动不得进入生产。
4. Safety-by-code：权限、SQL 安全、风险分级必须由代码和测试执行，不能只靠 prompt。
5. Trace-by-default：所有端到端链路必须有 trace id。
6. Human-in-control：R4/R5 高风险业务动作只允许提案和审批，不默认自动执行。
7. Core isolation：行业逻辑、平台 SDK、采集细节不得写死进 Core。
8. Small surface：MVP 只接首发闭环必要 Provider 和 Action。

## 2. PR 标准

每个 PR 必须回答：

1. 改动属于 Core、Provider、Action、Eval、UI 还是 Docs？
2. 是否改变 Contract？
3. 是否新增或修改 golden case？
4. 是否影响 SQL Safety？
5. 是否影响 EvidenceChain 完整性？
6. 是否引入新的工具、模型、连接器或数据出域？
7. 是否影响风险分级或审批路径？
8. 是否有 Trace 可回放？

PR 不满足以下条件不得合并：

- CI 通过。
- schema tests 通过。
- 相关 eval 通过。
- 安全相关改动经过 reviewer 批准。
- Agent/prompt 改动有回归对比。
- 代码未绕过 Contract 直接拼接结构化输出。

## 3. Contract 标准

核心 Contract 必须具备：

- JSON/Pydantic schema。
- 字段说明。
- 正例和反例。
- 版本号。
- owner。
- schema compatibility test。
- 示例 payload。

Contract 变更分级：

| 类型 | 示例 | 要求 |
|---|---|---|
| Patch | 新增可选字段 | schema test + release note |
| Minor | 新增对象或非破坏性枚举 | eval 回归 + 文档更新 |
| Major | 删除字段、改语义、改必填 | CTO review + migration plan |

## 4. SQL Safety 标准

所有生产查询必须经过 SQL Safety Checker。

强制规则：

1. 只允许 `SELECT`。
2. 禁止 `INSERT`、`UPDATE`、`DELETE`、`TRUNCATE`、`DROP`、`ALTER`、`CREATE`。
3. 只允许白名单 schema。
4. 必须参数绑定，禁止字符串拼接。
5. 必须有时间范围或 LIMIT。
6. 必须限制最大返回行数。
7. 除法必须有 `NULLIF` 或等价除零保护。
8. 敏感字段必须脱敏或拒绝。
9. 每次执行记录 user、tenant、workspace、trace id、SQL template id、参数和结果摘要。

SQL Safety 测试至少覆盖：

- 写操作拦截。
- 多语句拦截。
- 非白名单 schema 拦截。
- 缺少限制条件拦截。
- 字符串拼接风险。
- 注入样本。
- 敏感字段访问。
- 大结果集风险。

## 5. EvidenceChain 标准

EvidenceChain 是正式答案的最低可信单元。

必填内容：

- business question。
- BusinessIntent。
- MetricContract。
- data source / table / field。
- QueryPlan / SQLTemplate。
- query parameters。
- SQL Safety result。
- permission scope。
- QueryResult summary。
- quality check result。
- conclusion。
- confidence。
- limitations。
- related ActionProposal。
- trace id。

EvidenceChain 检查：

| 检查项 | 规则 |
|---|---|
| 完整性 | 必填字段全部存在 |
| 一致性 | 结论引用的数据必须来自本链路 |
| 可复现 | QueryPlan 和参数可回放 |
| 权限 | 不展示用户无权访问的证据 |
| 限制 | 数据缺失、延迟、口径风险必须显式说明 |

## 6. Agent 和 Prompt 标准

Agent 只能通过工具和 Contract 工作。

禁止事项：

1. 禁止 Agent 直接持有生产数据库超级权限。
2. 禁止 Agent 生成 SQL 后绕过 SQL Safety 执行。
3. 禁止 Agent 自由解释指标口径，必须引用 MetricContract。
4. 禁止 Agent 输出无 schema 的关键业务结论。
5. 禁止 Agent 在没有 EvidenceChain 时生成高影响业务建议。
6. 禁止 Agent 对 R4/R5 动作默认自动执行。
7. 禁止 prompt 承担权限判定、审批判定和数据脱敏职责。

Prompt / Skill 变更必须：

- 标明 owner。
- 有输入输出 schema。
- 有正反例。
- 有 eval cases。
- 有模型版本和参数记录。
- 跑回归对比。

## 7. 风险分级

| 等级 | 示例 | MVP 处理 |
|---|---|---|
| R0 | 术语解释、公开信息 | 自动 |
| R1 | 只读查询、图表 | 自动但审计 |
| R2 | 报告、数据产品候选 | 自动或轻审批 |
| R3 | 创建任务、发送通知 | 可配置审批 |
| R4 | 改业务参数、触发外部同步 | 只提案，强审批 |
| R5 | 预算、价格、库存、删除、权限 | 只提案，双人复核，MVP 不自动执行 |

任何功能如果可能触达 R4/R5，必须经过 CTO 或安全 reviewer 审查。

## 8. 权限和凭证标准

凭证规则：

- 禁止明文存储 API key。
- 客户 Key 不进入业务代码。
- 模型调用只通过 Model Gateway。
- Provider 凭证按 tenant/workspace 隔离。
- 服务账号必须有最小权限。
- 日志不得输出密钥、token、cookie、完整敏感 payload。

权限检查必须考虑：

- user。
- tenant。
- workspace。
- role。
- data classification。
- purpose。
- tool/action risk。
- approval state。

## 9. Eval 标准

MVP 必须具备以下评测：

| 评测 | 覆盖 |
|---|---|
| Intent eval | 问题 -> expected intent |
| Metric eval | 别名、口径、owner 命中 |
| SQL eval | 模板匹配、结果 diff |
| SQL Safety eval | 危险 SQL、越权 schema、缺限制 |
| Evidence eval | 必填字段、证据引用一致 |
| Action eval | 风险等级、审批建议、证据引用 |
| Regression eval | bug fix、prompt/model 变更 |

规则：

- 每次修复一个业务错误，尽量新增一个 regression case。
- 模型、prompt、skill、SQL 模板变更必须跑相关 eval。
- eval 结果必须进入 release review。

## 10. CI / Release Gate

CI 最小集：

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

Release Gate：

- P0 tests 通过。
- golden query 正确率不下降。
- SQL Safety 100% 通过。
- EvidenceChain completeness 100% 通过。
- R4/R5 自动执行路径不存在。
- release note 写明新增能力、风险和回滚方式。

## 11. 事故处理 SOP

事故分级：

| 等级 | 示例 | 响应 |
|---|---|---|
| S1 | 数据泄露、越权访问、错误写操作 | 立即冻结相关功能，CTO/Security 介入 |
| S2 | 错误业务结论进入正式决策 | 下线相关能力，补 eval，出复盘 |
| S3 | golden query 回归失败 | 阻断发布，修复后重跑 |
| S4 | UI/体验问题不影响可信链路 | 进入普通缺陷队列 |

事故复盘必须包含：

- trace id。
- 影响范围。
- 根因。
- 是否缺少 Contract / eval / safety check。
- 修复项。
- 新增 regression case。
- 防复发措施。

## 12. Code Agent 使用标准

Code Agent 可以用于实现、测试、文档、review，但必须遵守：

1. 不允许无 eval 改动 prompt 或模型。
2. 不允许绕过 Contract 直接拼接 Agent 输出。
3. 不允许直接生成生产 SQL 执行路径，必须经过 SQL Safety。
4. 不允许把首发行业逻辑写进 Core。
5. 不允许把高风险业务动作做成默认自动执行。
6. 每个 bug 修复都要尽量沉淀 regression case。

Code Agent 产物必须由人类 reviewer 对核心边界负责。

## 13. 交付文档标准

每次对业务或 CEO 演示前，必须准备：

- 本次可跑通的业务问题。
- EvidenceChain 示例。
- ActionProposal 示例。
- eval 报告。
- 已知限制。
- 不承诺事项。
- 风险和下一步。

对客户或准客户交付前，必须额外准备：

- 数据源清单。
- 权限和敏感字段清单。
- 部署边界。
- 审计日志样例。
- 失败和回滚说明。

## 14. 不得突破的红线

1. 不得在没有 EvidenceChain 的情况下输出正式经营结论。
2. 不得在没有 SQL Safety 的情况下执行生产查询。
3. 不得在没有审批的情况下执行 R4/R5 动作。
4. 不得把客户凭证明文写入代码、日志或配置。
5. 不得为了 demo 绕过权限、审计和 eval。
6. 不得用“后面补测试”作为 Agent 能力上线理由。
7. 不得在 Core 中写死内容电商或具体平台逻辑。
8. 不得向 CEO 或客户承诺 MVP 不包含的能力。

---

## 15. 技术债务管理机制

> 补充来源：深度分析报告 — 组织层补充。

阶段性落地方案对"不做什么"定义清晰，但缺少技术债务的主动管理机制。

### 15.1 债务分类

| 类型 | 定义 | 示例 | 处理策略 |
|---|---|---|---|
| **战略性债务** | 主动选择"先留接口，后续实现" | Agent Runtime先实现最小自研状态机，LangGraph仅做非生产spike | 记录在ADR中，明确还清时间和触发条件 |
| **意外债务** | 因时间压力或信息不足产生的妥协 | 硬编码的SQL模板、未抽象的Provider逻辑 | 必须在2个sprint内修复或记录 |
| **腐化债务** | 因环境变化而形成的过时设计 | 依赖的库已废弃、API版本过旧 | 每季度评估一次，排入路线图 |

### 15.2 债务账本机制

每个"先留接口，后续实现"的决策：

1. 必须记录在 ADR 中（标注为"deferred decision"）
2. 必须明确：当前简单实现、理想目标实现、触发还债的条件、预期还债时间
3. 每季度做一次"技术债务盘点"：
   - 盘点所有 open deferred decisions
   - 评估是否有债务已经到期需要还清
   - 评估是否有债务累积到影响产品质量或开发效率
   - 将"到期债务"排入下季度路线图

### 15.3 债务度量

| 指标 | 含义 | 警戒线 |
|---|---|---|
| 债务ADR数量 | 未关闭的deferred decision ADR数 | > 10条需关注 |
| 债务年龄 | 最老的未还债务的存续时间 | > 6个月需评估 |
| 债务影响 | 因债务导致的bug/事故数量 | > 3次/季度需优先还债 |

---

## 16. 关键风险补充

> 补充来源：深度分析报告 — 风险补充。

当前文档的风险矩阵偏技术化。以下是四个需要CEO/CTO共同关注的战略级风险：

### 16.1 风险1：大模型能力跃升导致产品被替代

**描述**：如果 GPT-5 / Claude 4 直接支持企业级 Text-to-Action，部分产品价值会被压缩。

**影响**：如果大模型直接内建了语义理解+可信推理+行动执行能力，产品的差异化会被侵蚀。

**应对**：
- 确保护城河在 EvidenceChain 可信度、企业知识资产沉淀和 Governed Action，而不在模型能力本身
- 模型越是聪明，企业越是需要可信治理能力来约束、验证和追踪模型行为
- EvidenceChain的设计哲学（"你可信，但我要能验证"）天然防御模型能力跃升

### 16.2 风险2：中国AI模型监管

**描述**：国内AI模型需要取得相应资质（《生成式人工智能服务管理暂行办法》），企业客户可能要求使用已备案的国内模型。

**影响**：如核心能力依赖未备案模型或境外模型API，可能面临合规审查。

**应对**：
- Model Gateway 优先支持 Qwen、Baichuan、DeepSeek、ChatGLM 等已备案国内模型
- 保持模型无关架构，确保任何模型可插拔
- 关注 AI 法规变化，特别是面向企业客户的生成式AI使用规定

### 16.3 风险3：Prompt Injection 攻击

**描述**：通过数据内容注入恶意指令，操控Agent行为。这是Agentic系统特有的威胁类别。

**影响**：恶意构造的数据内容可导致Agent生成错误分析、泄露信息或触发未授权操作。

**应对**：
- 所有用户输入和外部数据在进入Prompt前必须经过清洗和转义
- Policy Engine 对所有ActionProposal做独立校验（不依赖模型输出做安全判断）
- 定期渗透测试，参照 OWASP Top 10 for LLM 和 Agentic Applications
- 敏感操作（R4/R5）必须人工审批，不依赖模型判断

### 16.4 风险4：首发场景失败

**描述**：如果 FaSoLa 作为 Customer-0 在验证期间产品无法满足需求。

**影响**：影响团队士气、投资人信心、后续客户获取的可信度。

**应对**：
- 在 Customer-0 之外提前接触2-3个备用验证客户，保持多线并行
- 与 FaSoLa 明确约定验证范围和成功标准（避免范围蔓延）
- 每周做产品回顾，每月做客户健康度评估
- 如果 FaSoLa 验证不理想但备用客户验证成功，果断切换首发案例

### 16.5 风险监控节奏

| 风险 | 监控频率 | 负责人 | 升级条件 |
|---|---|---|---|
| 模型跃升替代 | 每季度 | CTO | 大模型发布直接竞品能力 |
| AI模型监管 | 每月 | CTO+合规 | 新法规出台或执法案例 |
| Prompt Injection | 每次发版 | 安全负责人 | 发现新攻击向量 |
| 首发场景失败 | 每周 | CEO+CTO | 连续4周未达阶段目标 |
