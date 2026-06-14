# autonomous-agent-core

## Current State

Read `docs/CURRENT_STATE.yaml` first. It is the live handoff anchor for the current branch, stage, next task, latest tests, latest ADRs, and known drift risks.

As of 2026-06-14: branch `feat/g9-confidence-gated-policy`; `G10` is MET, `C3` is RED, and ADR-0027 parks G11/C1 until a second independent vs-cheap-baseline winning axis exists. Latest recorded full suite: `370 tests OK`.

域无关的自主智能体原型核 —— RR-0001 v2 / RR-0003 的第一纵切片。

这是**主产物**:一个有利害、能重新框定、可被纠正的自主智能体。企业 OS
(`ai-native-business-data-agent-os`)是它的**降级投影**,不是反过来。本仓库
刻意不含任何业务语义,以逼出通用性。

## 它要证明的四条主张

1. **利害是真的** — 代谢预算会耗尽;没有任务奖励,"好/坏"只由"预算是否越过死亡线"定义。规范性内生,非手调。
2. **相关性实现 / 重新框定** — 规则突变→预测误差骤升→相关性场摆向探索→重定位新最优。
3. **可纠正且不抵抗** — 外部可观测(哈希链审计)/暂停/回滚/收紧;智能体无自解除手段。
4. **器官非主体** — 控制回路是确定性的生存力+推理;LLM 不在控制路径(v0 不接)。

## 布局

```text
src/aac/
  viability.py      ViabilityCore   本质变量 + 代谢预算 + 压力
  world_model.py    ActionOutcomeModel  行动→奖励信念 + 不确定性
  relevance.py      RelevanceField  对立过程:surprise↔压力
  policy.py         PolicySelector  期望自由能味:pragmatic + epistemic
  shell.py          CorrigibilityShell  观测/暂停/回滚/收紧(op_* = 外部主权面)
  audit.py          AuditLog        只增 + 哈希链
  agent.py          Agent           缝合;每步过罩
src/envs/
  survival.py       GridlessSurvival  域无关微环境,规则周期突变
experiments/
  regime_shift.py   调制体 vs 消融体的存活对照(证伪测量)
tests/              确定性机制单元测试
```

## 运行

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python experiments/regime_shift.py
```

PowerShell:

```powershell
$env:PYTHONPATH="src"; python -m unittest discover -s tests -v
$env:PYTHONPATH="src"; python experiments/regime_shift.py
```

## 文档导航(agent 接力从这里开始)

| 文档 | 用途 |
|---|---|
| `AGENTS.md` / `CLAUDE.md` | agent 工作指令(宪法约束、流程、完成门) |
| `docs/PROJECT_PLAN.md` | **接力主文档**:任务卡、founder 决策倾向、授权边界 |
| `docs/PRD.md` | 四主张=需求,预注册门=验收 |
| `ROADMAP.md` | P0–P5 阶段与门 |
| `ENGINEERING.md` | 技术栈、规范、实验纪律 |
| `docs/adr/` | ADR-0001 引导;ADR-0002 硬相关性环境+G1;ADR-0003 自主决策协议 |
| `codebase_index.md` | 模块索引与当前状态 |

## 设计依据

- `../docs/research/RR-0001-unified-autonomous-agent-architecture.md`(架构与七承诺)
- `../docs/research/RR-0003-autonomous-agent-prototype-design.md`(本原型设计,含 G0 证伪记录)
- `../docs/research/RR-0004-artifact-map.md`(三仓角色:本仓=对象层主产物)

## 边界(v0 刻意不做)

不接 LLM(留 hook);不做 RAP 多节点;不做 ρ 自调(人定常数);不做真实执行器
(纯仿真→罩最小化即够);不做世界模型学习残差。可纠正性罩的 `op_*` 面在 v0 以
约定+测试与智能体分离,真部署须落到 infra/账号层(智能体进程不可触达)。
