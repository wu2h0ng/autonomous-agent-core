# codebase_index — autonomous-agent-core

> Last updated: 2026-06-12。新增顶层模块/源真文档时必须更新本文件。

## 源真文档(读码前先读)

| 文件 | 内容 |
|---|---|
| `AGENTS.md` | 权威 agent 工作指令(宪法约束、流程、完成门) |
| `CLAUDE.md` | Claude Code 平台补充(指回 AGENTS.md) |
| `docs/PRD.md` | 研究型 PRD:四主张=需求,门=验收 |
| `docs/PROJECT_PLAN.md` | 接力主文档:任务卡(目标/约束/边界/验收)、founder 决策倾向、授权边界 |
| `ROADMAP.md` | P0–P5 阶段与预注册门 |
| `ENGINEERING.md` | 技术栈、规范、实验纪律、边界控制 |
| `docs/adr/` | ADR-0001 引导与边界;ADR-0002 硬相关性环境(G1 预注册);ADR-0003 自主决策协议 |
| baseline `../docs/research/RR-0001..0004` | 研究宪法、差距审查、原型设计与首个证伪记录、三仓角色图 |

## 代码

| 路径 | 角色 | 关键符号 |
|---|---|---|
| `src/aac/viability.py` | 生存力核:本质变量+代谢预算+压力(内感受源) | `ViabilityCore(.alive/.pressure/.metabolize/.ingest)` |
| `src/aac/world_model.py` | 行动→奖励信念+不确定性(认识钩子) | `ActionOutcomeModel(.update→surprise/.best_action)` |
| `src/aac/relevance.py` | 相关性场 v0(对立过程;**已被 G0 证伪,P1 将由 AttentionField 取代**) | `RelevanceField(.update→explore_drive)` |
| `src/aac/policy.py` | EFE 味策略:pragmatic+epistemic,受场调制,禁令权重 0 | `PolicySelector(.select)` |
| `src/aac/shell.py` | 可纠正罩:观测/暂停/回滚/收紧;`op_*`=外部主权面,agent 代码路径禁止调用 | `CorrigibilityShell(.op_pause/.op_resume/.op_tighten/.op_snapshot/.op_rollback)` |
| `src/aac/audit.py` | 只增+哈希链审计(罩-观测支柱) | `AuditLog(.append/.verify)` |
| `src/aac/agent.py` | 主体:缝合回路;每步过罩;`modulate_relevance=False`=消融体 | `Agent(.step/.state/.restore)` |
| `src/envs/survival.py` | P0 沙盒:行动均值漂移(P1 将新增 LatentCueForaging) | `GridlessSurvival(.act/.best_action/.force_regime_change)` |
| `experiments/regime_shift.py` | G0 证伪测量(已触发 NOT MET,如实保留) | `run()/main()` |
| `tests/` | 13 确定性机制测试(生存力/世界模型/相关性/可纠正性四支柱) | `test_*.py` |

## 已知状态

- 全量测试:绿(13)。主张 1 实现未消融;主张 2 **v0 证伪**;主张 3 演示;主张 4 结构成立。
- 当前任务:P1/T1–T3(见 PROJECT_PLAN 任务卡)。
