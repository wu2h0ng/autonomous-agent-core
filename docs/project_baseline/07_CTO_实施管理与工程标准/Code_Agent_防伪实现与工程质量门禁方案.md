# Code Agent 防伪实现与工程质量门禁方案

> 日期：2026-06-01  
> 角色视角：CTO  
> 适用范围：AI Native Business Data Agent OS 全部 AI 辅助开发任务  
> 目标：降低 Code Agent 因根因定位弱、伪实现、局部修补、缺少全局架构意识导致的返工和质量风险。

## 1. 问题判断

Code Agent 不是稳定的资深工程师。它更像一个速度很快但需要强约束的执行单元。

常见失控模式：

1. 根因定位不足：只修表面报错，不追踪调用链、状态来源、数据契约和失败路径。
2. 伪实现：新增空类、硬编码成功、假 adapter、mock-only runtime、文档写完但代码没接入。
3. 实现未调用：代码存在，但没有被 API、CLI、Trusted Loop、任务编排或测试路径触发。
4. 自证测试：测试输入 expected，代码直接返回 expected，测试通过但没有验证真实能力。
5. 类型和产量定义混乱：字段含义、单位、状态枚举、返回结构、错误码没有 contract 约束。
6. 局部正确、全局破坏：只看当前文件，不理解架构边界、上下游模块和非功能要求。
7. 多轮 review 才收敛：第一次输出没有按软件工程流程完成设计、实现、验证和总结。

结论：不能依赖 Agent 自觉。必须把质量要求变成流程、contract、测试、CI、review checklist 和项目记忆。

## 2. 外部最佳实践吸收

### 2.1 GitHub Copilot Coding Agent

GitHub 的实践重点是让 coding agent 能在自己的开发环境里构建、测试和验证变更；PR 仍需要 review，尤其是关键和敏感代码。

可吸收规则：

- 每个 Agent 任务必须能运行项目认可的 build/test/lint 命令。
- PR 描述必须写清任务、改动、验证结果和剩余风险。
- 复杂 review comment 应批量提交，避免 Agent 在碎片化指令下反复局部修补。
- Agent PR 不允许自动合入核心分支。

### 2.2 Cursor Rules

Cursor 官方建议把项目规则保存在 `.cursor/rules`，版本化、按代码库作用域管理，并保持规则聚焦在命令、模式和权威样例上。

可吸收规则：

- 规则必须短、准、可执行，不写泛泛价值观。
- 每条规则尽量指向项目内的 contract、测试命令、架构文档或参考实现。
- 规则需要随代码演进维护；过期规则会误导 Agent。
- 不同任务类型使用不同规则：架构、后端、SQL Safety、eval、前端、review 分离。

### 2.3 OpenAI Agent / Codex / Evals

OpenAI 文档强调 agent 工作流需要工具、guardrails、evals、trace grading 和可复现评估。

可吸收规则：

- 关键 Agent 能力必须有 eval 数据集，不只靠一次人工试跑。
- 复杂 Agent 输出必须保留 trace，便于复盘为何做出某个代码修改。
- 可复用工作流沉淀为 Skill，而不是每次靠临场 prompt。
- 对 shell / tool 执行设置白名单、审批和沙箱。

### 2.4 aider Repo Map

aider 的 repo map 思路是用仓库级索引帮助 Agent 理解全局代码结构、符号和模块关系。

可吸收规则：

- 本项目 `code_index.md` 必须作为 Agent 全局索引入口。
- 新增模块必须登记 owner、purpose、entry points、contracts、tests、security notes。
- Agent 改跨模块代码前，必须先读 `code_index.md` 和目标模块邻近测试。

### 2.5 开源 Skills / Skills Registry

SkillsMD、EvoSkill、Agent-Skills 等开源实践说明：可复用 skill 应该包含说明、资源、脚本、验证材料，并可以从失败轨迹中迭代。

可吸收规则：

- Skill 不是提示词片段，而是“任务说明 + 输入输出 + 可运行命令 + 质量门禁 + 反例”。
- 每个高频失败模式都要沉淀成 skill 或 checklist。
- Skill 必须可评测；不能只看描述是否漂亮。
- 外部 skill 只能参考，不能直接作为本产品 Agent OS Core runtime。

## 3. 本项目强制工程门禁

### 3.1 Implementation Reality Gate

任何 Agent 声称“实现完成”前，必须回答：

| 检查项 | 必须回答 |
|---|---|
| Entry Point | 哪个 API、CLI、class、runtime、workflow 或测试真实调用了新代码？ |
| Contract | 消费或产出哪个 dataclass / schema / API contract？ |
| Invocation | 新代码是否被主流程调用？如果没有，是否标记为 staged seam？ |
| Failure Path | 非法输入、不安全 SQL、未知 metric、未知 provider、权限不足时如何失败？ |
| Test Validity | 如果实现返回常量、跳过 parser、跳过 SQL Safety、跳过 EvidenceChain，测试会不会失败？ |
| Type Safety | 字段单位、状态枚举、可空性、错误码是否明确？ |
| Boundary | OS Core 是否仍然不依赖 domain pack、provider 实现和外部 Agent 框架？ |
| Traceability | 是否记录 Trace / Evidence / OperationTrace / Feedback？ |

未满足任一项，不允许标记完成。

### 3.2 Bug Root Cause Gate

修 bug 必须按以下顺序输出和执行：

```text
Symptom
  -> Reproduction
  -> Suspected call path
  -> Actual root cause
  -> Minimal fix
  -> Regression test
  -> Risk scan
```

禁止只根据报错文本直接改最后一行。

必须至少检查：

- 入口参数是否正确。
- Contract 是否被误用。
- 上游是否传错字段、单位、枚举或状态。
- 下游是否吞错、默认成功或 fallback 过宽。
- 测试是否覆盖失败路径。
- 是否存在同类 bug 的第二处。

### 3.3 No Pseudo Implementation Gate

以下情况直接判定为伪实现：

- 只有 class/function，没有被任何真实入口调用。
- adapter 返回固定成功值。
- provider/connector 不校验 contract。
- eval case 把 expected 传给 runtime，再断言 runtime 返回 expected。
- 测试只验证对象能创建，不验证行为。
- 异常被 broad `except` 吞掉。
- TODO 伪装成实现。
- 文档说支持，但代码没有入口、测试、错误处理或 trace。

### 3.4 Type and Contract Gate

新增字段或状态必须回答：

- 字段含义是什么？
- 单位是什么？
- 生命周期状态有哪些？
- 是否允许为空？
- 由谁生产？
- 谁消费？
- 错误码是什么？
- 是否进入 Evidence / Trace / Eval？

核心 contract 改动必须增加或更新：

- contract unit test
- trusted loop test
- eval golden case
- code_index entry
- ADR 或 architecture review，视风险决定

### 3.5 Global Awareness Gate

跨模块任务必须先读：

```text
code_index.md
ai-native-business-data-agent-os/AGENTS.md
目标模块代码
目标模块测试
相邻上下游模块
```

Agent 输出 summary 必须说明：

- 读了哪些上下文。
- 改动影响哪些模块。
- 哪些模块明确没有改。
- 是否存在未处理的 staged seam。

## 4. Agent 分级授权

| Agent 能力等级 | 允许任务 | 禁止任务 | 必须门禁 |
|---|---|---|---|
| L1 文档/局部测试 Agent | 文档整理、测试补充、局部样例 | contract、runtime、SQL Safety、权限 | ruff + tests |
| L2 局部实现 Agent | 单模块小功能、明确 bugfix | 跨模块重构、架构决策 | Reality Gate + regression test |
| L3 模块 owner Agent | 模块内架构、contract 实现、eval | 产品边界变更、Core runtime 依赖变更 | Architecture Brief + CTO review |
| L4 架构 Agent | 架构方案、ADR、模块边界 | 直接落生产代码 | CTO approval |
| L5 CTO Gate | 审批、风险接受、合并决策 | 无 | 全部门禁 |

## 5. Review Checklist

Code Review Agent 必须优先找：

1. 新代码是否真实接入主流程。
2. 是否存在硬编码、假成功、mock-only 逻辑。
3. 测试是否能防止绕过真实实现。
4. contract 字段是否定义清楚。
5. 是否破坏 OS Core 边界。
6. 是否有失败路径。
7. 是否记录 trace/evidence。
8. 是否存在同类问题未一起修。
9. 是否引入外部 runtime 依赖。
10. 是否更新 `code_index.md` 和相关 docs。

Review 结论必须分为：

```text
Blocker: 不修不能合并
High: 合并前应修
Medium: 当前 PR 可修或下个 PR 跟进
Low: 风格/可维护性建议
```

## 6. 推荐 Skill 体系

本项目应优先自建这些 skill：

| Skill | 用途 | 核心输出 |
|---|---|---|
| bug-root-cause-analysis | 防止表面修 bug | 复现、调用链、根因、回归测试 |
| implementation-reality-check | 防伪实现 | 入口、contract、失败路径、测试有效性 |
| contract-first-development | 防字段和类型漂移 | schema、单位、状态、生产者/消费者 |
| trusted-loop-change | 防绕过核心链路 | Intent、Semantic、Provider、SQL Safety、Evidence、Trace |
| eval-case-authoring | 防自证测试 | golden case、负例、绕过检测 |
| architecture-boundary-review | 防 OS Core 污染 | dependency scan、module boundary report |
| pr-review-high-risk | 防低质量合并 | blocker/high/medium/low findings |
| project-memory-update | 防重复踩坑 | ADR、code_index、AGENTS、经验沉淀 |

每个 skill 必须包含：

```text
Purpose
When to use
Inputs
Procedure
Required commands
Completion checklist
Bad examples
Output format
```

## 7. CI 与自动化门禁

第一阶段必须执行：

```text
python -m ruff check --no-cache .
python -m ruff format --check --no-cache .
python -m unittest discover -s tests -p "test_*.py"
```

第二阶段增加：

```text
pyright / mypy
pytest coverage threshold
contract compatibility check
import boundary check
eval regression suite
dead-code / unused public module scan
```

第三阶段增加：

```text
mutation testing for critical logic
trace completeness grading
security scan
dependency policy scan
Agent output quality scorecard
```

## 8. 落地策略

短期立即执行：

1. `.agent` 与 `ai-native-business-data-agent-os/AGENTS.md` 已加入防伪实现门禁。
2. 所有新任务 summary 必须回答 Reality Gate。
3. Review Agent 默认按防伪 checklist 审查。
4. 任何 “新增模块” 必须有真实 entry point 或明确标记 staged seam。

中期执行：

1. 建立 `.codex/skills/` 或项目级 `skills/` 目录。
2. 把高频失败模式沉淀为本项目自研 skill。
3. 为每个 skill 建 eval，比较 with-skill 与 baseline。
4. 建立 Agent 质量排行榜：一次通过率、返工率、bug 引入率、token 成本。

长期执行：

1. 建立 self-improving skill loop，但只从 reviewed failure 中学习。
2. 建立架构边界自动扫描。
3. 建立 Agent PR 自动打分，但合并权仍在人类 owner。

## 9. CTO 结论

本项目可以全面使用 Code Agent，但必须把 Agent 当作受控执行单元，而不是自治工程师。

真正的工程护城河不是“使用更强模型”，而是：

```text
清晰 contract
  + 可执行 architecture boundary
  + 防伪实现门禁
  + 失败路径测试
  + eval regression
  + trace/evidence
  + human review
  + 项目记忆
```

只要这些门禁保持严格，即使 Agent 能力参差不齐，也会被流程纠偏；反过来，如果门禁缺失，最强模型也会制造看似完成、实际不可用的工程债。

