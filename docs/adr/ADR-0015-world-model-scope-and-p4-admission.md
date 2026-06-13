# ADR-0015: World-model 范围定义 + P4 准入条件

- Status: **A 部分接受**(范围/实验卫生,ADR-0003 设计权)/ **B 提案待 founder 批准**(P4 准入触碰保留事项)
- Date: 2026-06-12
- 触发: 研究复盘(world-model 路线定位)+ 三连败模式(G1/G2/G3)+ P3 进行中,需在 T-P3.4/P4 之前钉死边界,防 scope creep 与 G4 误读。

## Context

- `world_model` 当前是 `ActionOutcomeModel`:bandit-like 局部动作-回报预测器(均值 + 不确定度),
  不支持可组合状态转移、反事实滚动、多步信用分配、可校验因果。它是**器官**,主体仍是
  viability+policy+shell 确定性闭环(RR-0001 C6)。
- 一级研究发现:定向认知不稳定胜过廉价无定向基线,G1/G2/G3 三现(ADR-0012 §G3 结论3)。
- P3 在测的是 C5(协调价值),与"单器官智能上限"正交。
- 风险:把 world-model 偷渡成"已验证的 directed cognition 突破";P3 期间引入学习型器官污染 G4 对 C5 的测量。

## Decision A(接受,ADR-0003 设计权内)

- **A1 官方范围**:`world_model` = "local action-outcome predictor organ"。**不是** planner、
  **不是** belief graph、**不是** rich simulator。任何把它升格为主体或"已证突破"的表述无效。
- **A2 实验卫生防火墙**:P3 期间,**禁止**在同一实验里混入下列任意两者以上:claim-2 reopen、
  P4 organ gain、RAP coordination gain。**G4 只判 coordination value**。
  正式记录(防误读):**"P3 的判决对象是 coordination value,不是 single-organ intelligence ceiling。"**
- **A3 分层定位**:world-model 是 RAP 中某类 bidder/node 的**局部能力**,**不是** RAP 的前提条件、
  也不是其下游"放大器"。代码已如此(`rap_nodes` 薄封装)。

## Decision B(提案,**P4 触碰保留事项,需 founder 批准后方可治理 P4 启动**)

- **B1 P4 准入条件(满足其一)**:
  - (i) G4 NOT MET **且**失败归因显示**路由已接近上限**(各弱器官甜区已被穷尽,加器官种类无增益);或
  - (ii) G4 MET **但**残余 error mass 主要集中在 perceptual ambiguity / latent-state inference;或
  - (iii) **【本 ADR 新增,接 ADR-0014 §D5 诊断】** G4 NOT MET **且** D5 预注册诊断确认
    **声誉/世界模型重收敛过慢(staleness)是主因**——此时 richer priors 有理由直接补根因
    (更快重收敛 → 路由信号不再陈旧),属**正向** P4 信号,与 (i) 的"路由本身封顶"明确区分。
  - **反面排除**:"感觉缺先验"这种直觉**不构成**准入条件。
- **B2 最小 P4 接口(先注册接口,不先注册模型类型)**:P4 器官只可产出
  `belief_delta / uncertainty / counterfactual_hint`;**禁止**直接改 policy 或 shell。守住 C6/C7。
- **B3 强制 P4 消融**:至少三体对比 —— 无器官 / 非学习型 deterministic scaffold / 学习型 world-model 或 LLM 器官。
  否则 P4 会重演 P1/P2 的故事化增益。
- **B4** P4 启动本身仍 founder-reserved(不变);本 ADR 只**预注册门**,不开门。

## Consequences

- world-model 范围与 G4 解读被钉死,防 scope creep 与"路线总成败"误读。
- P4 有了可证伪的准入门 + 守 C6/C7 的接口约束 + 防故事化的消融要求。
- B1(iii) 把 P4 准入与 ADR-0014 §D5 的 staleness 诊断显式挂钩:G4 失败的**原因**决定 P4 是否该开,
  而非 G4 的成败本身。
- **待办**:founder 批准 Decision B(或修订),之后它方可治理 P4 启动。在批准前,B 仅为研究记录。
