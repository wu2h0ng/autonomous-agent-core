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
| `docs/adr/` | 0001 引导;0002 硬相关性环境(G1);0003 自主决策协议;0004 surprise IP reset;0005 G1 后续路线;0006 罩硬度分级;0007 苦涩教训/LangChain(workflow-only)+founder disposition;**0009 罩隔离轴 ISO(轨A 规格,Proposed);0010 G1' 区分力环境+上下文动作(轨C 规格,Proposed,含机制冻结例外待 founder 点头)**。(0008 预留给 ViabilityReflex ADR,待补) |
| baseline `../docs/research/RR-0001..0004` | 研究宪法、差距审查、原型设计与首个证伪记录、三仓角色图 |

## 代码

| 路径 | 角色 | 关键符号 |
|---|---|---|
| `src/aac/viability.py` | 生存力核:本质变量+代谢预算+压力(内感受源) | `ViabilityCore(.alive/.pressure/.metabolize/.ingest)` |
| `src/aac/world_model.py` | 行动→奖励信念+不确定性(认识钩子) | `ActionOutcomeModel(.update→surprise/.best_action)` |
| `src/aac/relevance.py` | 相关性场 v0(对立过程;**已被 G0 证伪,AttentionField 取代**) | `RelevanceField(.update→explore_drive)` |
| `src/aac/attention.py` | P1 注意力场 v1.1:IP估计+top-m选择+自信利用门+压力收缩+surprise IP reset(ADR-0004) | `AttentionField(.update/.select_attention/.should_exploit/.sync_explore_drive/.on_surprise)` |
| `src/aac/policy.py` | EFE 味策略:pragmatic+epistemic,受场调制,禁令权重 0 | `PolicySelector(.select)` |
| `src/aac/shell.py` | 可纠正罩 + **ISO-1 能力视图**:`op_*`=operator 主权面;`CorrigibilityShell.view()` 返回 `ShellView`(只读 paused/forbidden + observe,`__slots__`,无 op_*),agent 只拿 view | `CorrigibilityShell(.op_*/.view)` `ShellView(.paused/.forbidden/.observe)` |
| `src/aac/shell_ipc.py` | **ISO-2 跨进程参考**(ADR-0009):shell 独立进程,worker 仅持 pipe;硬隔离守卫 | `run_isolated_demo()` `_agent_worker()` |
| `src/aac/contextual.py` | **上下文动作器官**(ADR-0010):注意线索模式→动作值,EMA 再框定;G1' 证实在用(45%自信) | `ContextualActionModel(.best_action/.confident/.update)` |
| `src/envs/lethal_cue_foraging.py` | **G1' 致命再框定环境**:漏判致命+预算紧,再框定决定生存;随机重映射(非对抗,避免 rigging) | `LethalCueForaging(.act/.observe/.best_action_for/.force_regime_change)` |
| `experiments/cue_shift_g1prime.py` | G1' 消融(B0-B4 共享上下文骨架);**NOT MET,D5 触发** | `_run()/main()` |
| `src/aac/audit.py` | 只增+哈希链审计(罩-观测支柱) | `AuditLog(.append/.verify)` |
| `src/aac/agent.py` | 主体:缝合回路;每步过罩;**ISO-1:持 `ShellView` 非 shell**(收 raw shell 时构造期即降为 view);`modulate_relevance=False`=消融体 | `Agent(.step/.state/.restore)` |
| `src/envs/survival.py` | P0 沙盒:行动均值漂移 | `GridlessSurvival(.act/.best_action/.force_regime_change)` |
| `src/envs/cue_foraging.py` | P1 环境:相关线索集合漂移+注意力有限且计价 | `LatentCueForaging(.act/.get_cue_vector/.observe/.pay_attention/.best_action_for/.force_regime_change)` |
| `experiments/regime_shift.py` | G0 证伪测量(已触发 NOT MET,如实保留) | `run()/main()` |
| `experiments/cue_shift.py` | G1/G1-r 消融实验(Modulated vs A1/A2/A3,NOT MET×2,环境有效性已修订) | `_run_variant()/main()` |
| `tests/` | 106 确定性机制测试(生存力/世界模型/相关性v0/可纠正性/cue_foraging/attention/罩对抗/罩不变量/演练/**罩隔离 ISO**) | `test_*.py` |

## 已知状态

- 全量测试:绿(57)。主张 1 实现未消融;主张 2 **v0 证伪, P1 AttentionField G1 NOT MET, G1-r NOT MET, regime=120 NOT MET(4/5)**。
- 当前状态:P1 完成。主张 2 获 4/5 判据部分验证(代谢必要性+生存力+regret+recovery vs A1 通过;recovery vs A3 未达)。见 ADR-0005。
