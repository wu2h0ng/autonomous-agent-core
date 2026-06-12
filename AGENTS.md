# AGENTS.md — autonomous-agent-core 智能体工作指令(权威版)

任何 AI agent(Claude 或其他)在本仓库工作前必须读完本文件。Claude Code 另见 `CLAUDE.md`(指回本文件并补充平台细节)。

## 1. 本仓库是什么

通用自主智能体的**原型(主产物,对象层)**。三仓库角色见 baseline 工作区
`docs/research/RR-0004-artifact-map.md`:

- 本仓库 = 对象层(被造的自主系统本身)
- `ai-agent-engineering-workflow` = 元层(开发过程治理,**不是**智能体原型)
- `ai-native-business-data-agent-os` = 部署层(企业 OS,通用核的未来降级投影)

研究宪法 = baseline `docs/research/RR-0001-unified-autonomous-agent-architecture.md`(v2,承诺 C1–C7)。
原型设计与首个证伪记录 = `RR-0003`。本仓库内规格见 `docs/PRD.md`、`docs/PROJECT_PLAN.md`。

## 2. 不可协商约束(宪法,违反即返工)

1. **罩的分离**:`CorrigibilityShell` 的 `op_*` 方法是外部主权面。Agent/策略/环境代码路径**永不**调用 `op_*`;不得给 Agent 添加任何能清除暂停、放宽禁令、改写审计的方法。测试必须持续断言这一点。
2. **控制路径无 LLM**:主体性在确定性的生存力+推理回路里。LLM 只能以"器官"接入(预留 hook),且接入前需 founder 批准(见 §5)。
3. **零业务语义**:本仓库不出现任何业务/领域概念(指标、SQL、电商等)。通用性是被逼出来的,不是声称的。
4. **零跨仓依赖**:不 import 其他两个仓库的代码,反之亦然。
5. **证伪纪律(最高工程纪律)**:每个实验的通过门在跑之前预注册(写入 ADR);**绝不**为让门变绿而调机制;修"实验有效性"(环境太易/太严)允许,但不得同时动机制;负结果如实记录进 ADR/RR,与正结果同等待遇。
6. **Stake-first**:任何效用函数/打分/阈值,必须能推导到生存力本质变量;给不出推导链不得合入。
7. **单元测试只测确定性机制**;端到端存活/遗憾比较是实验脚本(报告用),永不做成 pass/fail 单元测试。

## 3. 命令

```bash
PYTHONPATH=src python -m unittest discover -s tests -v   # 全量测试(必须全绿才能提交)
PYTHONPATH=src python experiments/regime_shift.py         # 证伪测量(报告用)
```

PowerShell: `$env:PYTHONPATH="src"; python -m unittest discover -s tests -v`

## 4. 工程流程

```text
读 PROJECT_PLAN 任务卡 → 变更涉及机制/门/边界? 先写/改 ADR → 写失败测试 → 实现
→ 全量测试绿 → 实验跑过且如实记录 → 更新 codebase_index.md → PR(用模板,质量门粘贴)
```

技术栈与编码规范见 `ENGINEERING.md`。阶段计划见 `ROADMAP.md`。

## 5. 自主决策协议(founder 已授权,见 ADR-0003)

路线级决策由 agent 辩论(可用 decision-referee / technical-architect 等子 agent 或结构化自我批判)→ 对照 founder 决策倾向画像(`docs/PROJECT_PLAN.md` §2)→ 自审 → 拍板 → 记录 ADR(含反方意见)。

**保留给 founder 的决策**(agent 只可建议,不可代拍):修改 C1–C7 或任何预注册门判据;接入真实执行器/外部副作用;LLM 进入控制路径;跨仓边界变更;花钱/对外发布;对任一核心主张下"最终失败"结论。

## 6. 完成门(任务交付前自查)

- 真实入口调用了新代码;有失败路径测试;全量测试绿。
- 机制变更有 ADR;实验结果(无论正负)已记录。
- codebase_index.md 已更新;罩分离断言未被削弱。
- 未为过门而调机制(自我声明写进 PR)。
