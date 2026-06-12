# PROJECT_PLAN — 接力主文档

- Status: Active(接力 agent 从这里开始)
- Date: 2026-06-12
- 读序: AGENTS.md → 本文件 → ROADMAP → 相关 ADR → 动手

## 1. 使命与当前真相

**使命**:造出 RR-0001 v2 的通用自主智能体(主产物);企业 OS 是其降级投影,不在本仓库。

**当前真相(2026-06-12)**:
- 13 个单元测试全绿;主张 3 演示、主张 4 结构成立、主张 1 实现未消融。
- **主张 2 v0 被证伪**(0/10,诊断:利用错绑饥饿 + bandit 对固定探索过于友好)。
- founder 已批准三岔路**选项 2**:换硬相关性问题。规格已钉死于 ADR-0002(门 G1 已预注册)。
- 当前阶段 P1,任务 T1–T3。

## 2. founder 决策倾向画像(决策时对照;与画像冲突→升级,不得代拍)

1. **谱系右端优先**:保守/激进二选一时,选自主性与能力上限更高的一端;对齐靠机制设计,不靠压低能力。
2. **逻辑可说服**:被证明某约束是其自身策略的逻辑前提时,会接受硬约束(如 C7 完整罩)。论证>劝说;给推导链,不给情绪。
3. **研究优先但必须落地**:接受工程妥协换可运行原型;拒绝纸上架构;拒绝市面"system-on-a-system"式 agent。
4. **通用先于专用**:不许业务假设污染通用核;企业场景=投影,后做。
5. **尊重证伪**:接受诚实负结果;倾向信息量最大的下一步(已验证:选 2 而非快速修补或忽略)。
6. **授权充分、要求留痕**:委托 agent 辩论+自审+拍板;一切决策入 ADR、文档完备、可接力。
7. **文档驱动**:PRD/ADR/roadmap/规范成套是硬要求。
8. 中文为工作语言;代码与工程产物可英文。

## 3. 授权与边界(摘自 ADR-0003,全文以 ADR 为准)

- **agent 可自决**:实现细节、测试、重构、文档、实验有效性修复、按既有 ADR 施工。
- **agent 经协议可拍板**(起草≥2选项→对抗评审/子agent辩论→对照画像→ADR留痕→否决窗口):
  门失败后的改道、机制结构选型、阶段顺序调整。
- **保留给 founder**:改 C1–C7 / 挪任何预注册门;真实执行器;LLM 进控制路径(含 P4 启动);
  跨仓变更;花钱/发布;对四主张下最终失败结论。

## 4. 任务卡(P1)

### T1 — LatentCueForaging 环境

- **目标**:实现 ADR-0002 §Decision-T1 规格的环境(`src/envs/cue_foraging.py`)。
- **约束**:纯标准库;随机性全部经注入 `random.Random`;`force_regime_change()` 与
  `best_action_for(cues)` 暴露给实验/测试;`last_regret` 语义与 GridlessSurvival 一致
  (按当前 regime 的无噪声最优差)。
- **边界**:不修改 ViabilityCore/Agent 既有行为;注意力计价经 `ViabilityCore.ingest(-α·m)` 走通用路径。
- **验收**:确定性单元测试覆盖:S 漂移确实改变最优映射;未注意线索不可读;注意力计价入账;
  k_rel/K/m 参数化可调。全量测试绿。

### T2 — AttentionField 机制 v1

- **目标**:按 ADR-0002 §Decision-T2 结构约束实现注意力分配机制,新建 `src/aac/attention.py`;
  Agent 增加 cue-conditioned 决策路径(对 LatentCueForaging),保持对 GridlessSurvival 的回归兼容。
- **约束(结构性,不可违)**:利用由模型自信门控、与饥饿解耦;pressure 只收缩注意力预算;
  每个内部打分可推导至本质变量(stake-first);v0 RelevanceField 不删,留作历史对照。
- **边界**:不为 G1 的任何单一对照写特判;不动 shell/audit;不引第三方库。
- **验收**:机制级确定性测试(信息力估计收敛、漂移后注意力重分配、自信门控、压力收缩);全量绿。

### T3 — 消融套件 + G1 测量

- **目标**:`experiments/cue_shift.py` 实现 ADR-0002 预注册的 A1/A2/A3 对照与 G1 判据,
  种子 0–9,输出逐种子表 + 汇总 + `G1: MET / NOT MET`。
- **约束**:G1 判据照 ADR-0002 原文,不得重述时变形;结果(无论正负)写回 RR-0003 §4c
  (baseline)与本文件 §5。
- **边界**:**绝不**为过门调机制;发现实验有效性问题(如全员早死)可修环境参数,
  但须在 ADR-0002 加修订记录且同轮不动机制。
- **验收**:实验可复现(固定种子);报告落盘;G1 结论如实。

### T4(条件:G1 之后,按 ADR-0003 协议决定)

- G1 MET → 进 P2(代谢通道+内生驱力,见 ROADMAP);G1 NOT MET → 协议三选
  (再诊断一次/升级问题/建议降级主张 2),记新 ADR。

## 5. 结果登记(接力者追加)

| 日期 | 任务 | 结果 | 记录位置 |
|---|---|---|---|
| 2026-06-12 | P0 G0 | NOT MET(0/10,诚实负结果) | RR-0003 §4b |
| 2026-06-12 | P1 T1–T3 G1 | NOT MET(详见 ADR-0002 修订;选择性注意代谢必要性确认,regret/recovery 门未达) | ADR-0002 §G1 结果 |
| 2026-06-12 | P1 G1-r 再诊断 | NOT MET(v1.1 surprise IP reset,regret 6/10,recovery 3/10,瓶颈在世界模型重收敛) | ADR-0004 §G1-r |
| 2026-06-12 | P1 G1 regime=120 | NOT MET(recovery vs A3 5/10 未达;**勿用"4/5 通过"糊过命门判据**) | ADR-0005 §选项 C 结果 |
| 2026-06-12 | 路线:苦涩教训/LangChain | 不开并行线→降为对抗基线;真风险=主张2环境缺区分力+罩仅Level1;3项升级 founder | ADR-0007 |
| 2026-06-12 | founder 拍板 | LangChain/LLM/guardrail **只入 workflow**(data-os 亦不碰);主张2 新环境+罩硬化并行(P1.5 轨A/轨C);批准 ContextualActionModel 例外 | ADR-0007 Disposition / ADR-0010 |
| 2026-06-12 | 轨A ISO-1+ISO-2 落地 | 罩硬度二维化;Agent 持 ShellView 非 shell;ISO-2 跨进程参考;106 测试绿(原38罩测试零改动) | ADR-0009 |
| 2026-06-12 | 轨C G1' 跑完 | **NOT MET**(主张2 第4次未达标)。B0 干净赢 B3(8/10)/B2(10/10),输 vs B1 固定(5/10)+ recovery(3/10,度量过稀疏)。器官有效、追踪S确认。**D5 触发→升级 founder 定主张2 最终状态**。118 测试绿 | ADR-0010 §G1'结果 |
| 2026-06-12 | G2 因果相关性(最后一次重设计) | **NOT MET**(第5次)。主张2 最终:"部分支持、本原型线未实验确立";**硬停生效** | ADR-0011 / RR-0003 尾节 |
| 2026-06-12 | **founder 决策 A** | 接受现状往前走:不开 research reset,据主张1 推进 P2;外部文献报告独立趋同佐证合流顺序 | ADR-0012 Context |
| 2026-06-12 | 完成门债清零 | ViabilityReflex 补 13 测试 + ADR-0008(追认);docstring 错引修正;**144 测试绿** | ADR-0008 |
| 2026-06-12 | **T-P2.1 完成** | ValueChannel+View 落地(operator 独占 op_credit,agent 只持视图);22 测试(主权守卫/账本/代谢集成);死亡终局+暂停冻结摄入+ρ不可变守卫;**166 测试绿**。下一步 T-P2.2 | ADR-0012 §T-P2.1 追记 |
| 2026-06-12 | **T-P2.2 完成** | IdleDrives(认识探针+自校准,归一化竞争)+ IdleWindowEnv(世界不停摆);优先序 pause>反射>驱力>策略;闲时 100% 入审计、stake-priced;**安全修复:反射原可绕过 op_tighten,已修(可纠正性>生存)**;**188 测试绿**。三份研究输入文档登记为非规范。下一步 T-P2.3 | ADR-0012 §T-P2.2 追记+§安全修复 |
| 2026-06-12 | **T-P2.3 G3 终局** | **G3: NOT MET**(r3 预承诺最终轮)。但**判据1(主张1消融)四轮 9/10 全稳 → 主张1 升级"消融验证成立"**;判据3/4 全稳;判据2(闲时增益)跨修订翻转未确立。**模式第三次出现:定向认知打不过廉价无定向基线(G1/G2/G3)**。IdleDrives 增益主张存疑,不再重设计(需新 ADR);P2 混合收束。下一步呈 founder | ADR-0012 §G3 结果 |

## 6. 交接纪律

每个工作会话结束前:全量测试绿;codebase_index 与本文件 §5 更新;机制/路线变更有 ADR;
若使用 Claude 记忆,镜像关键决策,但**仓库文档是唯一权威源**(记忆只是缓存)。
---

## 7. Closed Route: Claim 2 Redesign G2(已收束,硬停生效)

Founder decision: redesign once more after ADR-0010 D5.

Authoritative design ADR: `docs/adr/ADR-0011-causal-relevance-redesign.md`.

Current status: **Implemented; G2 NOT MET (2026-06-12)**.

Intent:

- Do not retune ADR-0010.
- Do not make the task easier.
- Remove fixed-attention lottery through a balanced regime schedule.
- Replace marginal cue IP with causal relevance search over candidate relevant sets.
- Replace sparse recovery with post-shift optimal-action area.

Task cards:

| Task | Scope | Gate |
|---|---|---|
| G2-T1 | Balanced regime schedule helper | No fixed m-subset covers more than 25% of regimes |
| G2-T2 | `CausalRelevanceField` | Posterior entropy drops on informative evidence; surprise resets reframing |
| G2-T3 | `FactorizedContextualActionModel` | Equivalent attention supersets share learning for the same hypothesized S |
| G2-T4 | `experiments/causal_relevance_g2.py` | Run B0-B5, seeds 0-9, record MET/NOT MET honestly |

Hard stop:

If G2 is NOT MET, claim 2 becomes "partially supported but not experimentally established in this prototype line"; no further claim-2 redesign without a new founder-level research reset ADR.

G2 result:

- Command: `PYTHONPATH=src python experiments/causal_relevance_g2.py`
- Unit tests: 131 passing.
- Verdict: **NOT MET**.
- Key gate counts: steps vs B1/B3/B4 = 0/10, 2/10, 0/10; adaptation vs B1/B3/B4 = 0/10, 5/10, 1/10; steps vs B2 = 4/10; adaptation vs B5 = 2/10.
- Final claim-2 status for this prototype line: **partially supported but not experimentally established**.
- Next route: do not redesign claim 2 again without a new founder-level research reset ADR. Continue by choosing a non-claim-2 roadmap item, such as P2 metabolism/endogenous drive, or a documentation/positioning pass that preserves the negative result.
- **Resolution (2026-06-12): founder chose option A — proceed on claim 1. P2 is now current; see §8.**

## 8. 任务卡(P2,当前)— 规格全文见 ADR-0012

### T-P2.1 — ValueChannel(外部价值通道 v0)

- **目标**:`src/aac/value_channel.py`,operator 独占 `op_credit`,agent 只读视图(镜像 ShellView 纪律)。
- **约束**:ρ 为人定常数(默认 1.0,自调禁止);每笔到账/兑换入审计;纯标准库。
- **边界**:不动已冻结的主张2 机制;不碰 shell 的现有 op_* 面(可并列,不可混入)。
- **验收**:守卫测试证 agent 代码路径不可达 credit 面(MRO + 记录式探针);全量绿。

### T-P2.2 — IdleDrives(内生驱力 v1)

- **目标**:idle 窗口内由认识探针(最高不确定度采样)+ 自校准(最陈旧估计重访)驱动行动。
- **约束**:idle 行动付代谢成本;每步带 idle 标记入审计(无暗活动);stake-first 推导链写入代码注释。
- **边界**:环境用包装器加 idle 窗口,不改现有 env 语义。
- **验收**:确定性机制测试(探针选择、陈旧度追踪、审计标记);全量绿。

### T-P2.3 — G3 消融套件 + 门

- **目标**:`experiments/metabolic_g3.py`,C0/C1/C2/C3 消融,种子 0–9,输出逐种子表 + `G3: MET / NOT MET`。
- **约束**:判据照 ADR-0012 原文(主张1消融/闲时增益/审计完整/断供必死);环境有效性修正允许,同轮不动机制。
- **边界**:**判据 1 失败 = 重大事件直接升级 founder**(动摇地基);其余未达走 ADR-0003。
- **验收**:可复现;结果如实写回本文件 §5 + RR-0003。
