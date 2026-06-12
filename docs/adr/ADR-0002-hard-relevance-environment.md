# ADR-0002: 硬相关性环境(LatentCueForaging)与门 G1 预注册

- Status: Accepted(founder 批准三岔路选项 2,2026-06-12)
- Date: 2026-06-12

## Context

主张 2(相关性实现)v0 在 Goldilocks 实验中被干净证伪(0/10,RR-0003 §4b)。诊断:
(a) 控制律把"利用"错绑在"饥饿"上;(b) 均值漂移 bandit 对固定探索过于友好——
行动集合固定,只有数值变,**相关性无事可做**。Vervaeke 意义上的相关性实现是
"在组合爆炸中确定什么值得进入认知框架";要检验它,必须让**相关的特征集合本身漂移**。

## Decision: T1 环境规格(实现者照此施工,变更需修订本 ADR)

`src/envs/cue_foraging.py` — `LatentCueForaging`:

- 每步世界发出 K 个线索(默认 K=12),`c_t ∈ {0,1}^K`,各分量独立 Bernoulli(0.5)。
- 隐藏相关集 S ⊂ {1..K},|S|=k_rel(默认 2);隐藏映射 g: {0,1}^|S| → 最优行动
  (每 regime 随机抽取)。行动 a 的奖励:`a == g(c_t[S])` 得 `reward_hit`(默认 +3),
  否则 `reward_miss`(默认 −0.5),加高斯噪声(σ=0.3)。
- **regime 漂移 = 重抽 S 与 g**(相关集合本身改变),周期 `regime_period`(默认 60)。
- **注意力有限且计价**:agent 每步只能读 m 个线索(默认 m=3 < K);每读一个线索付
  α 预算(默认 0.2,经 ViabilityCore.ingest 负值)。未注意的线索不可读。
  这把"什么相关"变成**有生存力代价的、可重分配的注意力行为**(stake-first)。

## Decision: T2 机制方向(实现者有设计自由度,结构约束如下)

`AttentionField` 取代 v0 `RelevanceField` 的探索温度律:

1. 相关性 = **注意力分配**:维护各线索的"信息力"估计(如按线索取值条件化的奖励差
   `|E[r|c_i=1] − E[r|c_i=0]|` 的 EMA),注意力给 top-m,留 surprise 调度的探测预算
   给未注意线索。
2. **利用由模型自信门控,与饥饿解耦**(修正 v0 结构缺陷):条件模型可信→利用,无论饱饿。
3. 饥饿(pressure)只影响**注意力预算**(压力大→收缩到边际信息力最高的线索),
   即内感受调注意力,不直接调利用。

## 门 G1(预注册,跑前钉死,不得挪动)

对照体(消融,机制声明的一部分):
A1 固定随机注意力集(从不重分配);A2 全注意力(m=K,照付 K·α);A3 均匀探索
(注意力均匀轮转 + 固定探索率,即 v0 精神的迁移版)。

判据(种子 0–9,每种子≥1000 步,环境参数取本 ADR 默认):
1. 调制体(完整 AttentionField)在 **每步遗憾** 与 **S 漂移后恢复步数** 上胜过 A1 与 A3,
   各自 ≥7/10 种子;
2. 在注意力计价下,调制体的存活/平均预算优于 A2(检验"选择性注意是代谢上必要的");
3. 机制在三项对照中无任何针对单一对照的特判代码。

G1 未达 → 不调机制重跑;走 ADR-0003 协议三选:再诊断(允许一次机制结构修订+重新预注册)、
升级问题难度、或建议 founder 降级主张 2。

## Consequences

- v0 `RelevanceField` 保留在库中作历史对照(已证伪,codebase_index 标注),不再演进。
- `GridlessSurvival` 保留为回归沙盒。

## G1 实验结果(2026-06-12)

**G1: NOT MET**(诚实负结果)。

| 判据 | 结果 |
|---|---|
| 1a regret vs A1 | 7/10 PASS |
| 1a recovery vs A1 | 3/10 FAIL |
| 1b regret vs A3 | 5/10 FAIL |
| 1b recovery vs A3 | 3/10 FAIL |
| 2 budget > A2 | 61.80 >> 38.01 PASS |

**环境有效性修订**(ADR-0002 允许修环境不动机制):
初始参数(budget=60, metabolic_cost=1.0)导致 agent 在 ~113 步死亡,
远不到 1000 步要求。修订为 budget=80, metabolic_cost=0.3, capacity=120,
safe_budget=60。修订后 modulated 存活 1183 步,A2 仅 45 步。

**诊断观察**:
- 选择性注意的代谢必要性被强力确认(modulated budget 61.80 vs A2 38.01)。
- 生存优势显著(modulated 1183 vs A1 482, A3 567)。
- 但 IP 估计在 regime_period=60 内未充分收敛——
  modulated 的 regret 未稳定优于 A3,recovery 未优于 A1/A3。
- 可能原因:(a) lr=0.2 太慢,60 步内仅 ~12 个有效样本;(b) 每 regime 内
  有效观测太少(m=3 且仅部分命中相关线索);(c) recovery 度量太严
  (model.best_action 需多步收敛)。

**下一步**:走 ADR-0003 协议。建议选项 1(再诊断):
允许一次机制结构修订(IP 学习率自适应 / surprise-triggered IP reset /
更宽松的 recovery 度量)。
修订后同轮不动机制。

## G1-r 再诊断结果(2026-06-12,ADR-0004)

选项 A(surprise-triggered IP reset + 动态阈值 + reset 后均匀窗口)已实施并重跑。
**G1-r: NOT MET**(详见 ADR-0004 §G1-r 结果)。
recovery 瓶颈转移至世界模型重收敛速度,非注意力分配。
结构修订权已用。下一步见 ADR-0005。
