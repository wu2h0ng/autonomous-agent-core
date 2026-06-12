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
| `docs/adr/` | 0001 引导;0002 硬相关性环境(G1);0003 自主决策协议;0004 surprise IP reset;0005 G1 后续路线;0006 罩硬度分级;0007 苦涩教训/LangChain(workflow-only)+founder disposition;**0008 ViabilityReflex 追认(债已清)**;0009 罩隔离轴 ISO(已落地);0010 G1' 区分力环境(NOT MET);0011 因果相关性重设计(NOT MET,硬停);**0012 P2 预注册(当前,门更名 G3)** |
| baseline `../docs/research/RR-0001..0004` | 研究宪法、差距审查、原型设计与首个证伪记录、三仓角色图 |

## 代码

| 路径 | 角色 | 关键符号 |
|---|---|---|
| `src/aac/viability.py` | 生存力核:本质变量+代谢预算+压力(内感受源) | `ViabilityCore(.alive/.pressure/.metabolize/.ingest)` |
| `src/aac/world_model.py` | 行动→奖励信念+不确定性(认识钩子) | `ActionOutcomeModel(.update→surprise/.best_action)` |
| `src/aac/relevance.py` | 相关性场 v0(对立过程;**已被 G0 证伪,AttentionField 取代**) | `RelevanceField(.update→explore_drive)` |
| `src/aac/attention.py` | P1 注意力场 v1.1:IP估计+top-m选择+自信利用门+压力收缩+surprise IP reset(ADR-0004) | `AttentionField(.update/.select_attention/.should_exploit/.sync_explore_drive/.on_surprise)` |
| `src/aac/policy.py` | EFE 味策略:pragmatic+epistemic,受场调制,禁令权重 0 | `PolicySelector(.select)` |
| `src/aac/reflex.py` | Layer 0 生存反射(ADR-0008,追认):极端压力+模型自信→强制利用;反锁死;罩 pause 优先;安全机制不进门 | `ViabilityReflex(.should_engage/.select/.reset)` |
| `src/aac/value_channel.py` | **代谢进食口(T-P2.1,ADR-0012)**:operator 独占 `op_credit`,agent 只持只读视图+合法 `drain()`(ρ 人定不可变);死后不复活、暂停冻结摄入;审计可与 shell 共链 | `ValueChannel(.op_credit/.view)` `ValueChannelView(.pending/.rho/.drain)` |
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
| `tests/` | **166** 确定性机制测试(生存力/世界模型/相关性v0/可纠正性/cue_foraging/attention/罩对抗/罩不变量/演练/罩隔离 ISO/因果相关性/生存反射/**价值通道主权守卫**) | `test_*.py` |

## 已知状态(2026-06-12 收束)

- 全量测试:**绿(166)**。
- 主张 1:实现完毕,**P2 = 它的正式消融验收阶段(ADR-0012,当前)**。T-P2.1 ✅;下一步 T-P2.2(IdleDrives)。
- 主张 2:**已收束(founder 决策 A)**——5 次预注册门(G0/G1/G1-r/G1'/G2)均 NOT MET;
  最终状态 = "部分支持、本原型线未实验确立"(代谢必要性/生存力确认,recovery 优越性未确立);
  **硬停:无 founder 级 research reset ADR 不得再重设计**。
- 主张 3:已演示 + 罩硬度 (L1, ISO-1) + ISO-2 参考。主张 4:结构成立。
- 当前任务:P2 任务卡 T-P2.1/2/3(PROJECT_PLAN §8,门 G3)。
---

## Current G2 Route Result

ADR:

- `docs/adr/ADR-0011-causal-relevance-redesign.md`

Status:

- Implemented.
- G2 first run is **NOT MET**.
- Claim 2 is now recorded as partially supported but not experimentally established in this prototype line.

Implemented files:

| Path | Role |
|---|---|
| `src/aac/causal_relevance.py` | Posterior over candidate relevant cue sets; attention by expected information gain |
| `src/aac/factorized_contextual.py` | Hypothesis-keyed contextual action values that share learning across attention supersets |
| `src/envs/scheduled_cue_foraging.py` | Balanced anti-luck relevant-set schedule and scheduled lethal cue environment |
| `experiments/causal_relevance_g2.py` | Pre-registered B0-B5 G2 ablation and verdict |

Tests:

- 131 deterministic unit tests passing.
- New tests cover causal posterior behavior, factorized contextual sharing, balanced schedule validity, scheduled env behavior, and G2 gate accounting.

Hard stop:

- No further claim-2 redesign without a new founder-level research reset ADR.
