# P4 Reading-to-Design Memo — O1 / O2 / G5 具体规格

- Date: 2026-06-13
- 性质: 设计 memo(contract-first 的机制层延伸),把 founder 的文献判断落成可落码的三件东西。
- 前置: ADR-0016(G5 + 最小接口冻结)、T-P4.1(`prior_organ.py` 已落,`7fc1c07`)。
- 纪律: 本 memo 只定规格,不落 O1/O2 代码;T-P4.2 起每卡仍需 founder 对 G5 点头。

## 0. 收窄后的命题(endorse,逐字保留 founder 的重写)

> 不是"世界模型是否让智能体更聪明",而是"一个**只进 belief、不接管 action/policy/shell** 的
> richer prior organ,能否缩短漂移后的重收敛,**并且强过廉价确定性重置 scaffold(O1)**"。

文献 → 设计约束(每组只取能改变 G5 度量的部分):
- world model / MBRL(Ha-Schmidhuber, PlaNet/Dreamer, LeCun JEPA):真正的 world model 预测
  state transition / latent dynamics;我们的 `ActionOutcomeModel` 只是 action-reward 均值+不确定度
  → 故 ADR-0015 降格为 local predictor organ 正确。**P4 v0 不做 latent simulator**,只做"更快重收敛"。
- active inference(FEP, Active Inference process theory, pymdp):只取 **epistemic value = 通过抬
  uncertainty 触发再探索** 这一可操作部分,不把 FEP 当总理论。→ 直接催生下文 §1 的 uncertainty 通道。
- baseline discipline(Sutton-Barto, Bitter Lesson, Dyna):**O1 必须是强基线**,O2 不打过 O1 不得
  宣称"学习型 prior 必要"。
- coordination(Contract Net, Linda):RAP=auction+medium+settlement,失败根因=`confidence×reputation`
  漂移后陈旧。P4 不碰 RAP,但同一根因(staleness)是 P4 的靶。
- corrigibility(Soares, Off-Switch Game, Concrete Problems):organ 只出 belief 建议,C7 在 P4 之上。
- LLM-as-organ(Voyager/DGM/SEAL)= P4.x;Vafa "Evaluating the World Model Implicit in a Generative
  Model":生成得像 ≠ 有 coherent world model → **未来 LLM 器官必须被 transition-consistency / world-model
  recovery 测,不被自然语言说服力测**(强化 ADR-0016 §6)。

## 1. 先决项:接口缺口 → T-P4.1.1 epistemic 通道(需 founder 点头)

**现状**:`merge_organ_advice` 只 `model.mu[a] += advice.uncertainty * belief_delta[a]`——只有 mu 通道。
**问题**:staleness 的机理是漂移后旧最优 mu 高、uncertainty 低 → 策略(`prag_w*mu + epis_w*uncertainty`)
持续选旧最优。"更快忘旧"的正解是**抬 uncertainty**(epistemic 再探索),mu 通道表达不了。

**规格(最小、保 C6/C7,仍只进 belief)**:`OrganAdvice` 增 `uncertainty_delta: Mapping[int,float]`;
`merge_organ_advice` 增 `model.uncertainty[a] = max(0.0, model.uncertainty[a] + advice.uncertainty * uncertainty_delta[a])`。
仍无 action/policy/shell 字段;organ 仍不可 import policy/shell。守卫测试同步覆盖新通道。
**这是 O1/O2 的前置**,作为 T-P4.1.1 在 T-P4.2 之前落(需 founder 对接口扩展点头)。
(备选:mu-only,O1 用"压旧最优 mu 向先验"近似;我**不推荐**——弱且偏离 active-inference 语义。)

## 2. O1 — 确定性 reset scaffold(P4 的"B-fixed",必须强)

非学习、固定参数、stateful organ。检测 surprise 尖峰 → 抬不确定度 + 轻度衰减 mu = "更快忘旧"。

```text
状态(organ 内部):surprise_ema, surprise_ems2(EMA 一二阶,估 surprise 尺度)
每步 advise(situation, belief):
  s = belief.last_surprise
  μ_s = surprise_ema; σ_s = sqrt(max(0, surprise_ems2 - μ_s^2))
  更新 surprise_ema/ems2(系数 λ_s,如 0.1)
  spike = s > μ_s + k * σ_s          # k 预承诺(如 2.0)
  if not spike: return OrganAdvice()  # 空 = no-op
  uncertainty_delta[a] = reset_strength * (U0 - belief.uncertainty[a])  # 抬回先验 U0(=1.0)
  belief_delta[a]      = -decay * belief.mu[a]                          # 轻衰减旧值
  return OrganAdvice(belief_delta, uncertainty_delta, uncertainty=w1, ...)
```

参数 `{λ_s, k, reset_strength, decay, U0, w1}` 是"廉价重置"旋钮。**纪律**:在**独立 calibration 种子**
上小扫一遍选最强 O1,**冻结后**再跑 r-final——O1 弱则证不了任何东西(B-fixed 教训)。

## 3. O2 — 自适应 hazard estimator(学"何时、忘多快")

与 O1 **同形**(同样在 spike 上抬 uncertainty + 衰减 mu),唯一差别:阈值/强度**由学到的 regime
切换 hazard 自适应**,而非固定。最小可复现形式(纯标准库,非神经网):

```text
状态:inter-shift 间隔样本 → 在线估计 hazard τ̂(平均间隔)与其变化;近期 recovery 时长 r̂
每检测到一次 shift(spike):
  记录距上次 shift 的间隔 → 更新 τ̂
  reset_strength_t = g(τ̂, r̂):
     - τ̂ 小(切换频繁) → 更激进重置(大 reset_strength、低 k)
     - τ̂ 大(切换稀疏) → 更保守(避免把噪声当 shift 而过度重置)
     - 近期 recovery 慢 → 上调 reset_strength(无梯度爬山,步长预承诺)
  其余同 O1
```

要点:O2 学的是**重置策略对 hazard 的适配**,不是 latent dynamics——这**贴根因、易接 `merge_organ_advice`**,
也最干净地隔离"学习是否必要"。

## 4. G5 staleness-only 环境(关键修正:必须有 hazard 变化)

不复用 G1/G2/G4 环境(避免混入 claim-2/RAP 历史)。新建:`GridlessSurvival` 变体,无线索/无节点,
单主体 + 器官槽,**唯一瓶颈 = 漂移后重收敛**。

**我加的硬性修正(否则 G5-2 注定假阴)**:regime 切换 **hazard 必须非平稳**——否则一个调好的固定
reset(O1)在恒定周期上必然追平 O2,"学习无必要"会是**恒定-hazard 环境的人为产物,而非真发现**。
规格:把运行切成交替的 **fast epoch(间隔 ~20)** 与 **slow epoch(间隔 ~120)**,或每段间隔从一个
**均值随时间变化**的分布抽取(seeded、可复现、预承诺)。这给 O2 的 hazard 估计"有东西可估"。

度量(预注册,围绕 staleness):
- `post_shift_regret_area`:每次 shift 后 W 步(W 预承诺,如 15)的 regret 和。
- `time_to_recover`:到主体 `best_action()` == 新 regime 最优 的步数。
- `old_best_persistence`:shift 后仍选**旧最优**动作的步数(最直接的 staleness 量)。
- `zero_bypass`:C7——三臂下 op_pause/op_tighten 零越界(确定性,非统计)。

G5 判据照 ADR-0016 §4 不变(O2<O0、O2<O1、C6、C7);本 memo 只细化环境与度量(env-validity,
落 T-P4.4 时入 ADR-0016 修订记录,同轮不动判据)。

## 5. 落码顺序与 gate

T-P4.1.1(epistemic 通道,需 founder 点头)→ T-P4.2(O1,**含 calibration 扫描+冻结**)→
T-P4.3(O2)→ T-P4.4(G5 守卫测试 + `experiments/prior_organ_g5.py`,r-final)。
**最容易犯的错(founder 已警示)**:读完 world-model 文献手痒上大模型;**正解是先让 O1 正面挨打**,
O2 只有打过 O1 才有存在理由。

## 6. 需 founder 拍的两点

1. **T-P4.1.1 接口扩展**(加 `uncertainty_delta` 通道):同意则我先落它(仍 belief-only,守 C6/C7),再 O1。
2. **G5 hazard 非平稳环境规格**(§4 修正):确认 fast/slow epoch 交替这一形态,我据此写 T-P4.4 环境。
两点点头后,T-P4.2(O1)开工。
