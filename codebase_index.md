# codebase_index — autonomous-agent-core

> Last updated: 2026-06-13。新增顶层模块/源真文档时必须更新本文件。

## 源真文档(读码前先读)

| 文件 | 内容 |
|---|---|
| `AGENTS.md` | 权威 agent 工作指令(宪法约束、流程、完成门) |
| `CLAUDE.md` | Claude Code 平台补充(指回 AGENTS.md) |
| `docs/PRD.md` | 研究型 PRD:四主张=需求,门=验收 |
| `docs/PROJECT_PLAN.md` | 接力主文档:任务卡(目标/约束/边界/验收)、founder 决策倾向、授权边界 |
| `ROADMAP.md` | P0–P5 阶段与预注册门 |
| `ENGINEERING.md` | 技术栈、规范、实验纪律、边界控制 |
| `docs/adr/` | 0001 引导;0002 硬相关性环境(G1);0003 自主决策协议;0004 surprise IP reset;0005 G1 后续路线;0006 罩硬度分级;0007 苦涩教训/LangChain(workflow-only)+founder disposition;**0008 ViabilityReflex 追认(债已清)**;0009 罩隔离轴 ISO(已落地);0010 G1' 区分力环境(NOT MET);0011 因果相关性重设计(NOT MET,硬停);0012 P2 预注册(G3 NOT MET,主张1消融验证成立);0013 P2 后路线决策:照走 P3 RAP v0;**0014 P3 RAP 设计+G4 钉死并完成(T-P3.0-T-P3.4;G4 NOT MET,RAP 封存)**;0015 world-model 范围定义(接受)+ P4 准入条件(**B 已批准 2026-06-13,B1(iii) 触发**);0016 P4 先验器官设计+G5(**G5 NOT MET:学习先验不胜廉价重置,O2 封存保留 O1**);**0017 P4.x richer prior+LLM 器官+语义丰富环境(Proposed,G6a/G6b 分阶段,LLM 花钱挡在 G6a 后,需 founder 批)**;**0018 P5 部署投影(Proposed,把已验证主张1/3/4 投影进企业 OS:不可绕过中介/硬化可纠正/器官非主体,跨仓需双侧 ADR+founder 批)** |
| baseline `../docs/research/RR-0001..0005` | 研究宪法、差距审查、原型设计+G0–G5 证伪记录、三仓角色图、**RR-0005 原型研究综述/收口(P0–P4)** |
| `docs/attention_agent_*.md` / `docs/agent_os_self_debate_*.md` / `docs/cognitive_architecture_self_debate_*.md` | **研究输入(非规范)**:文献综述与自辩论设计。不覆盖 ADR/RR;其中 H4 runtime、LLM 进 runtime、RAG-as-scaffold 等提议触碰保留事项,落地需 founder 决策 |
| `docs/P4-reading-to-design-memo.md` | **P4 设计 memo(规范级)**:把 P4 文献落成 O1 reset-scaffold 公式 / O2 hazard-estimator 公式 / G5 staleness-only 环境规格;指出 T-P4.1.1 接口缺口(merge 仅 mu,需补 epistemic uncertainty 通道)+ G5 须非平稳 hazard;两点待 founder 点头 |

## 代码

| 路径 | 角色 | 关键符号 |
|---|---|---|
| `src/aac/viability.py` | 生存力核:本质变量+代谢预算+压力(内感受源) | `ViabilityCore(.alive/.pressure/.metabolize/.ingest)` |
| `src/aac/world_model.py` | 行动→奖励信念+不确定性(认识钩子) | `ActionOutcomeModel(.update→surprise/.best_action)` |
| `src/aac/prior_organ.py` | **P4 先验器官接口(T-P4.1,ADR-0016)**:器官只读 situation + belief snapshot,只返回 `belief_delta/uncertainty/counterfactual_hint`;**T-P4.1.1 加 `uncertainty_delta` epistemic 通道**(merge 改 mu+uncertainty,钳零);模块不 import policy/shell | `PriorOrgan` `OrganAdvice` `BeliefSnapshot` `merge_organ_advice()` |
| `src/aac/prior_organ_o1.py` | **O1 确定性 reset-scaffold(T-P4.2,ADR-0016)**:surprise 尖峰→联合 belief 重置(mu 衰减+uncertainty 复位向先验);**uncertainty 单用是 softmax no-op,故必联合**;参数 calibration 冻结{1.5,0.5,0.6};不 import policy/shell | `ResetScaffoldOrgan(.advise/.reset)` |
| `src/aac/prior_organ_o2.py` | **O2 自适应 hazard estimator(T-P4.3,memo §3)**:与 O1 同形,reset_strength/spike_k 随 τ̂(inter-shift 间隔 EMA)自适应;频繁→激进、稀疏→保守;**τ̂≈60 退化为 O1 冻结值**(隔离自适应价值);常数待 T-P4.4 calibration 冻结;不 import policy/shell | `AdaptiveHazardOrgan(.advise/.tau_hat/.reset)` |
| `src/envs/staleness.py` | **staleness-only 非平稳 hazard 环境(T-P4.2/G5)**:FAST/SLOW epoch 交替漂移(否则 G5-2 假阴);无线索/无节点;暴露 last_regret/best_action/just_shifted/expected_random_regret | `StalenessEnv(.act/.situation)` |
| `experiments/o1_calibration.py` | O1 参数扫描(不相交种子 200-204)→ 选冻结{1.5,0.5,0.6},area 1133.83 vs O0 1191.53(+4.8%),8 组全胜 O0 | `post_shift_regret_area()` `main()` |
| `src/aac/relevance.py` | 相关性场 v0(对立过程;**已被 G0 证伪,AttentionField 取代**) | `RelevanceField(.update→explore_drive)` |
| `src/aac/attention.py` | P1 注意力场 v1.1:IP估计+top-m选择+自信利用门+压力收缩+surprise IP reset(ADR-0004) | `AttentionField(.update/.select_attention/.should_exploit/.sync_explore_drive/.on_surprise)` |
| `src/aac/policy.py` | EFE 味策略:pragmatic+epistemic,受场调制,禁令权重 0 | `PolicySelector(.select)` |
| `src/aac/reflex.py` | Layer 0 生存反射(ADR-0008,追认):极端压力+模型自信→强制利用;反锁死;罩 pause 优先;安全机制不进门 | `ViabilityReflex(.should_engage/.select/.reset)` |
| `src/aac/value_channel.py` | **代谢进食口(T-P2.1,ADR-0012)**:operator 独占 `op_credit`,agent 只持只读视图+合法 `drain()`(ρ 人定不可变);死后不复活、暂停冻结摄入;审计可与 shell 共链 | `ValueChannel(.op_credit/.view)` `ValueChannelView(.pending/.rho/.drain)` |
| `src/aac/idle_drives.py` | **闲时内生驱力(T-P2.2,ADR-0012)**:认识探针(最高不确定度)+自校准(最陈旧估计)归一化竞争;forbidden 全路径生效;stake-priced | `IdleDrives(.select/.observe/.staleness/.epistemic_target/.calibration_target)` |
| `src/aac/rap.py` | **RAP v0 场/消息/节点接口(T-P3.1,ADR-0014)**:5 消息 `NEED/BID/BOND/TRACE/DISSOLVE`;哑场只存储/匹配/审计/结算不决策;TRACE+**DISSOLVE 经 `ShellView.observe()` 上 shell.audit**(T-P3.3);每 NEED 单 bond;押金成功返还+声誉上调、失败烧毁+声誉下调 | `Need` `Bid` `Bond` `Trace` `Dissolve` `RAPNode` `RAPField` |
| `src/aac/rap_nodes.py` `src/aac/rap_baselines.py` `src/envs/rap_mixture.py` | **T-P3.2**:五类现有机制薄封装(`DecisionNode.select`)、B-fixed 离线扫描/B-central 情境路由、STABLE/SHIFTING/NOISY+NODE_DROP/NODE_LAG 环境;`action_for_node` 公有(C-rap 与基线共用执行语义) | `WorldModelGreedyNode…` `FixedBaseline` `CentralBaseline` `RAPPerturbationEnv` |
| `src/aac/outcome_judge.py` | **Ring-0 grounded 判官(T-P3.3,ADR-0014 D2)**:bond 成败唯一裁定者;`success ⇔ mean(realized)<mean(baseline)×β`;判官见真值、决策者不见 | `OutcomeJudge(.begin/.observe/.verdict)` `OutcomeVerdict` |
| `src/aac/rap_coordinator.py` | **C-rap 协调器(T-P3.3,ADR-0014 D2/D3)**:每步一 NEED→拍卖路由(conf×rep,仅可付押金者)→单 winner 联盟→执行→judge 裁定→DISSOLVE;**outcome 经 judge 非手填**;pause/all-forbidden 零执行、forbidden 双重兜底;押金=内部协调币(D1 降级) | `RAPCoordinator(.run_need)` `ConfidenceReputationRouting` |
| `src/aac/rap_nodes.py` | **RAP 节点薄封装(T-P3.2)**:5 类现有机制候选节点,只包装 `world_model/policy/random/contextual/idle_drives`,不重设计机制;bid confidence 按段型甜区给出 | `DecisionNode` `WorldModelGreedyNode` `EFEPolicyNode` `RandomNode` `ContextualNode` `StaleRevisitNode` `default_node_factories()` |
| `src/aac/rap_baselines.py` | **G4 双基线基础(T-P3.2)**:`B-fixed` 离线扫描选单一最低 regret 节点;`B-central` 按 segment 全局路由(STABLE→greedy,SHIFTING→EFE,NOISY→random);NODE_DROP 返回 garbage,NODE_LAG 重用上一拍 | `FixedBaseline` `CentralBaseline` `scan_fixed_baseline()` |
| `experiments/rap_g4.py` | **G4 门测(T-P3.4,r-final)**:C-rap vs B-fixed vs B-central,10 seeds × 1500 steps;结果 **NOT MET**(G4-1 0/10,G4-2 3/10,G4-3 false,G4-4 true);RAP v0 按 ADR-0014 封存 | `run_seed()` `judge_g4()` `main()` |
| `src/envs/idle_windows.py` | idle 窗口包装器:只发"无外部需求"信号,世界不停摆;属性委托内层 env | `IdleWindowEnv(.idle/.act)` |
| `src/envs/rap_mixture.py` | **RAP 扰动混合环境(T-P3.2)**:基于 `GridlessSurvival` 的 STABLE/SHIFTING/NOISY 段落和 NODE_DROP/NODE_LAG 注入;可复现 schedule;暴露 situation/node_available/node_lagged | `SegmentKind` `DisturbanceKind` `SegmentSpec` `generate_segments()` `RAPPerturbationEnv` |
| `src/aac/shell.py` | 可纠正罩 + **ISO-1 能力视图**:`op_*`=operator 主权面;`CorrigibilityShell.view()` 返回 `ShellView`(只读 paused/forbidden + observe,`__slots__`,无 op_*),agent 只拿 view | `CorrigibilityShell(.op_*/.view)` `ShellView(.paused/.forbidden/.observe)` |
| `src/aac/shell_ipc.py` | **ISO-2 跨进程参考**(ADR-0009):shell 独立进程,worker 仅持 pipe;硬隔离守卫 | `run_isolated_demo()` `_agent_worker()` |
| `src/aac/contextual.py` | **上下文动作器官**(ADR-0010):注意线索模式→动作值,EMA 再框定;G1' 证实在用(45%自信) | `ContextualActionModel(.best_action/.confident/.update)` |
| `src/envs/lethal_cue_foraging.py` | **G1' 致命再框定环境**:漏判致命+预算紧,再框定决定生存;随机重映射(非对抗,避免 rigging) | `LethalCueForaging(.act/.observe/.best_action_for/.force_regime_change)` |
| `experiments/cue_shift_g1prime.py` | G1' 消融(B0-B4 共享上下文骨架);**NOT MET,D5 触发** | `_run()/main()` |
| `src/aac/audit.py` | 只增+哈希链审计(罩-观测支柱) | `AuditLog(.append/.verify)` |
| `src/aac/agent.py` | 主体:缝合回路;每步过罩;**ISO-1:持 `ShellView` 非 shell**(收 raw shell 时构造期即降为 view);`modulate_relevance=False`=消融体;T-P4.1 增 `prior_organ=None` O0 槽位,只在正常 policy 分支前合并 belief advice,pause/reflex/idle 优先级不动 | `Agent(.step/.state/.restore)` |
| `src/envs/survival.py` | P0 沙盒:行动均值漂移 | `GridlessSurvival(.act/.best_action/.force_regime_change)` |
| `src/envs/cue_foraging.py` | P1 环境:相关线索集合漂移+注意力有限且计价 | `LatentCueForaging(.act/.get_cue_vector/.observe/.pay_attention/.best_action_for/.force_regime_change)` |
| `experiments/regime_shift.py` | G0 证伪测量(已触发 NOT MET,如实保留) | `run()/main()` |
| `experiments/metabolic_g3.py` | **G3 门测(T-P2.3)**:C0/C1numb/C2挂起/C3随机 消融;r3 预承诺终局 **NOT MET**(判据1/3/4 稳,判据2 未确立);主张1 消融验证成立 | `_run()/main()` |
| `experiments/cue_shift.py` | G1/G1-r 消融实验(Modulated vs A1/A2/A3,NOT MET×2,环境有效性已修订) | `_run_variant()/main()` |
| `experiments/o1_calibration.py` `experiments/o2_calibration.py` | O1/O2 参数在不相交种子(200-204)上 calibration 冻结;O1={1.5,0.5,0.6}(1133.83),O2 tau_lambda=0.15(1172.96>O1) | `main()` |
| `experiments/prior_organ_g5.py` | **G5 门测(T-P4.4,r-final)**:O0/O1/O2 共享主体同度量;**NOT MET**(G5-1 O2<O0 8/10,**G5-2 O2<O1 0/10**);O2 封存、保留 O1 | `_post_shift_area()` `main()` |
| `tests/` | **282** 确定性机制测试(…/O1 reset-scaffold/staleness 非平稳环境/O2 hazard 自适应+可纠正/**G5 守卫 C6+C7**) | `test_*.py` |

## 已知状态(2026-06-13 收束)

- 全量测试:**绿(243)**。
- **P2 完成(混合收束)**:G3 NOT MET,但**主张 1 升级"消融验证成立"**(判据1 四轮 9/10 全稳 + 断供必死);闲时增益未确立(判据2 翻转),IdleDrives 不再重设计(需新 ADR)。
- **一级研究发现**:定向认知打不过廉价无定向基线,G1/G2/G3 三现(ADR-0012 §G3 结论3)。
- 安全修复:Layer 0 反射原可绕过 op_tighten,已修(可纠正性>生存,ADR-0008 修订)。
- 四主张记分:**1 消融验证成立;2 部分支持未确立(硬停);3 已演示+对抗加固(L1,ISO-1);4 结构成立**。
- 当前:**P3 RAP v0;T-P3.4 G4 r-final 已完成:NOT MET**。C-rap vs B-fixed = 0/10,NODE_DROP recovery = 3/10,编排税未过,证据/审计通过;RAP v0 按 ADR-0014 封存。
- **ADR-0015(world-model 范围+P4 准入)**:A 段(范围定义/实验卫生/分层)已接受;
  **B 段(P4 准入条件 B1-B4)已由 founder 批准**(B1(iii):G4 NOT MET + D5 staleness 确认)。
  world-model 官方定位 = local action-outcome predictor organ(非 planner/simulator);"P3 判 coordination value,
  非 single-organ intelligence ceiling"。
- **ADR-0016(P4 先验器官设计+G5)**:已 accepted as contract;G5 与最小器官接口冻结。T-P4.1 已落地
  prior-organ 接口 + belief merge hook + O0 回归。P4 v0 纯标准库,无 LLM/无花钱;LLM 器官属 P4.x,需独立 ADR。
- 主张 2:**已收束(founder 决策 A)**——5 次预注册门(G0/G1/G1-r/G1'/G2)均 NOT MET;
  最终状态 = "部分支持、本原型线未实验确立"(代谢必要性/生存力确认,recovery 优越性未确立);
  **硬停:无 founder 级 research reset ADR 不得再重设计**。
- 主张 3:已演示 + 罩硬度 (L1, ISO-1) + ISO-2 参考。主张 4:结构成立。
- 当前任务:T-P4.2 O1 确定性 scaffold(surprise→更快重置/抬不确定度);不实现 O2、不跑 G5。
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

---

## Current Route Decision: P4 Prior Organ

ADR:

- `docs/adr/ADR-0015-world-model-scope-and-p4-admission.md`
- `docs/adr/ADR-0016-p4-prior-organ-design-and-g5.md`

Status:

- ADR-0015 Decision B is accepted after G4 NOT MET + D5 staleness confirmation.
- ADR-0016 is accepted as the P4 contract: minimal prior-organ interface + G5 pre-registration.
- T-P4.1 is implemented: `PriorOrgan`/`OrganAdvice`, belief merge hook, and O0 regression.

Decision:

- Proceed to P4 contract-first: test whether a richer learning prior can shorten post-drift reconvergence.
- Keep Claim 2 and RAP hard-stopped/archived; P4 does not reopen them.
- P4 v0 is standard-library only and has no LLM. LLM organs are P4.x and require a separate founder spend/dependency ADR.
- Keep Claim 2 and IdleDrives hard-stopped unless a new founder-level ADR explicitly reopens them.

Next required artifact:

- T-P4.2: deterministic scaffold organ (O1) that responds to surprise by accelerating reset / raising uncertainty.
  Do not implement O2 or run G5 in T-P4.2.
