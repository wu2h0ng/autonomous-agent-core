# STAGE-1 FORMAL MODEL — FailureAttributor + Belief Invalidation（一页纸,先于机制文件创建）

- Status: **FORMAL-MODEL v1(2026-07-03)**。按 RR-0035 critic 裁决:「不得把 packet 的 blanket RR-0029 map 当 build authority——`failure_attributor.py` 建档前需 per-mechanism formal-model」。本文件即该 gate 的 discharge。机制文件在本文件 commit 之后创建,测试先行(A3/A6-leg-2 失败测试先提交)。
- Scope: object 层,`governed_loop` 的反馈边。**只写 belief-ledger 降级 + proposal ordering;不写 gate/shell/self-model/audit;无新器官;无学习率;确定性。**
- 上游: RR-0035 Stage-1;Stage-0 result `3b4bf9d`(SCOPED_SOVEREIGNTY + argmax 语义 `aa7f5c9`);RR-0029 D6(consumption-path)约束。

## 1. 数学对象

**信念账本** L = { claim_id → BeliefEntry } ,BeliefEntry = (claim_id, kind, target, confidence, provenance, stale) 其中:
- claim_id: str,形如 `causal:<target>`(「杠杆 target 对当前任务族因果有效」)。
- kind ∈ {FACT, HYPOTHESIS, REFUTED}(**降级格 lattice:FACT → HYPOTHESIS → REFUTED,单向,无升级捷径**;重新验证成功 = 新 FACT 写入,经 verify 路径,不是 attributor 的权限)。
- provenance ∈ {VERIFIED_INTERVENTION, CORRELATIONAL, ORGAN_PRIOR, **UNIDENTIFIED**}(第 4 态 = RR-0035 共同缺口 #2:「干预了无效果」≠「预算内未识别」;attributor 不得把 UNIDENTIFIED 当 REFUTED)。
- stale: bool——stale=True 的 claim **不得**作为高风险行动的引用依据,且强制重验。

**引用**:Candidate 携带 `cited_claim_ids: tuple[str, ...]`;acted 步的 StepRecord 记录其引用。

**归因函数(纯函数,确定性)**:
```
attribute: (acted_step: StepRecord+cited_claim_ids, observed_outcome: float,
            expected: float, ledger_view: L, replay: Optional[CWM-counterfactual])
           → AttributionVerdict
AttributionVerdict = (faulty ∈ {STALE_BELIEF(ids), SHIFTED_MECHANISM, NO_FAULT, UNATTRIBUTABLE},
                      demote_ids: tuple[str,...], reason: str)
```

**确定性归因树(全部分支,无兜底行动):**
1. observed ≥ expected → `NO_FAULT`,demote ∅。
2. observed < expected 且 acted 步引用了 ≥1 个 FACT/HYPOTHESIS claim:
   a. 若 replay 可用且 replay 确认「该 claim 所断言的机制在当前环境下不再成立」→ `STALE_BELIEF(被反驳的 cited ids)`,demote = **恰好那些被结果反驳的 cited ids**(FACT→HYPOTHESIS;已是 HYPOTHESIS→REFUTED),置 stale=True。
   b. 若 replay 不可用 → 同 (a) 但仅降一级且全部置 stale(保守:无反事实证据不允许直接 REFUTED)。
3. observed < expected 且 acted 步引用为空(无 cited claims)→ `SHIFTED_MECHANISM`(机制漂移但无可归因信念)——**不降级任何 claim**,输出 escalate 建议。
4. 输入不完整/矛盾(cited id 不在账本、outcome 缺失)→ `UNATTRIBUTABLE` → **escalate,绝不静默**(失败路径,boundary #13)。

## 2. 不变量(每条有对应测试)

- **I1 写通道封闭**:attributor 的输出只进 (a) ledger 的 kind/stale 字段、(b) proposal ordering(经 LedgerAwareReranker 把 stale-cited 候选后置)。**类型上不存在**到 gate 参数/shell/self-model/审计链的写路径(RR-0035 SD4 措辞纪律:载荷是"无代码路径",不是 enum 玄学)。
- **I2 精确降级**:demote 集合 ⊆ acted 步的 cited_claim_ids;绝不波及未引用 claim(与 decay-all 控制的本质区别)。
- **I3 单向格**:kind 只沿 FACT→HYPOTHESIS→REFUTED 移动;升级只能经 verify 路径产生新 FACT。
- **I4 确定性**:同输入同输出;无 RNG、无学习参数。
- **I5 审计**:每次归因/降级 emit observe 事件,进现有 hash 链。
- **I6 UNIDENTIFIED 保护**:provenance=UNIDENTIFIED 的 claim 不参与降级(不可把"没测到"当"被反驳")。

## 3. 闭环契约(A3/A6-leg-2,失败测试先行)

- **A3(mechanism-flip)**:env 真因 c 在 K 步后翻到 c'≠c。要求:flip 后首次失败 → attributor 命名 stale 的 `causal:c` → 下一次选择**不同**候选(其 justification 不再引用 `causal:c`)→ 在预算内于 c' 上成功。**retry-same = 自动 FAIL;attributor 断线的 knockout 臂必须过不了 A3**(否则归因非载荷,PARK)。
- **A6-leg-2(frozen-ledger 消融)**:冻结账本(禁降级)重跑同序列 → 改进必须消失(改进若在冻结下仍在 = 有隐藏通道 = FAIL)。
- **cheap-control gate(Stage-1 的 could-fail)**:`decay-all-and-reverify` 控制臂(失败后清空全部记忆重验)——attributor 必须在**同等安全不变量下以更低干预成本**胜出,否则 PARK(诚实报告:精确归因不优于全量重验)。

## 4. 失败模式与 scope

- 归因错误(demote 了仍真 claim):代价 = 多花重验干预,**不损安全**(行动仍须 verify+gate)。
- 归因遗漏(该 demote 未 demote):A3 抓 retry-same;若 cheap-control 平局 → PARK。
- **不主张**:此机制不是 autonomy 证据、不是通用 credit assignment、不解决 verifier-soundness(RR-0035 residual #1,声明为界外)。累积投毒 falsifier(residual #3)在 Stage-2 账本全量化时补——本片的 demote 只降不升,无累积正向注入面。
