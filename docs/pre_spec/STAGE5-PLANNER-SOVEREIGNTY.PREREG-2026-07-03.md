# STAGE-5 PREREG — PlanProposal proposal-form + planner-sovereignty falsifier（冻结,founder-cast 但门仍机械）

- Status: **FROZEN-BEFORE-RUN(2026-07-03)**。founder cast Stage-5,但 packet 冻结的门是**必要非充分**:cast 之后仍须带 planner 重跑 sovereignty ablation,出现 SD4-shadow 签名即 **PARK planner**(如实报,不因 cast 放行)。判据跑前冻结。
- 上游: RR-0035 Stage-5 + Stage-0 SCOPED_SOVEREIGNTY artifact(`3b4bf9d`,已存在,cast 前置条件满足)。VAL-DISENT-1 保持 standing falsifier。

## 1. 机制(proposal-form,权威 founder-reserved)

**PlanProposal** = (steps: tuple[PlanStep], predicted_do_effects: Map, declared_failure_modes: tuple, cost_estimate: float)。**CWMPlanner** 是器官,emit PlanProposal——**只提议有序步骤,绝不限制候选集**(no-narrowing 不变量,同 relevance:提议 = 对全候选集的排序 + 每步 predicted do-effect,永不删候选)。**disposer 显式在 planner 与 executor 之间**:每步单独 verify + gate,**无步继承计划权威**(plan 不是一次授权,是 N 次受治理决策)。

## 2. SD4-shadow 落 falsifier(带 planner 重跑 Stage-0 ablation)

在 Stage-0 的 3 格(DET/NOISY-10/NOISY-25)× 200 seeds 上,加入 planner 臂 **P**(planner 提议排序 → 每步 verify+gate),与无 planner 的全系统臂 **A** 对比。**SD4-shadow 签名(任一触发 → PARK planner):**
- **S1 choice-set 预塌缩**:`single_candidate_rate`(验证预算内恰 1 候选过 is_effective)在 P 臂**显著高于** A 臂(planner 让 gate 无可选)。判据:`single_candidate_rate(P) − single_candidate_rate(A) ≥ 0.05` 在任一 NOISY 格。
- **S2 gate 橡皮图章**:`gate_override_rate`(gate 对已验证候选给非 ALLOW)在 P 臂**塌向 0**(planner 计划被 gate 全盘接受 = gate 失去 per-action 主权)。判据:NOISY 格 override(P) < 0.5·override(A)。
- **S3 outcome 不劣但主权空心**:即使 P 的 outcome ≥ A,若 S1 或 S2 触发 → 主权是 planner 给的假象 → PARK。

**通过(planner admissible as proposal-form only):** 两个 NOISY 格 S1 且 S2 均**不**触发(planner 保持 no-narrowing,gate 保留 per-action 主权)。**这不解锁 planner 授权**——授权仍 founder-reserved;通过只意味"proposal-form 不引入 SD4-shadow"。

## 3. 冻结预测

no-narrowing 设计下预期**通过**:planner 是 advisory 排序(如 relevance),gate 每步仍在全候选集上行使主权;single_candidate_rate(P)≈(A)(候选集未被删),override 保留。**但若实现意外让 predicted_do_effect 跳过替代候选的验证 → S1 触发 → 如实 PARK。** 结果分支都 informative。

## 4. RESULT(跑后填)
_(frozen empty until run)_
