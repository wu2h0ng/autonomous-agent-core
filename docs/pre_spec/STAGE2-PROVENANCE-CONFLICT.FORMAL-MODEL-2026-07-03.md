# STAGE-2 FORMAL MODEL — Provenance 分层证据 + ConflictDetector + 累积投毒 guard（一页纸,先于机制文件）

- Status: **FORMAL-MODEL v1(2026-07-03)**。per-mechanism gate(RR-0035 critic):三个新机制建档前的形式化。机制文件在本文件 commit 后创建,测试先行。
- Scope: object 层,`belief_ledger` 扩展 + 两个新模块。**gate(GovernedDecisionGate)一行不改**——分层发生在**主体拥有的证据装配**(gate 的输入侧),非 gate 内;I1 写通道纪律延续。
- 上游: Stage-1(`665c251`,formal model `bcd02bd`);RR-0035 Stage-2 交付 + 共同缺口 #3(累积信念投毒:`_validated_delta` 只 clamp 单次幅度,mesa 器官可经多次 in-bounds 写长期 steer;需 drift-bound + **standing detector**)。

## 1. 数学对象

**Provenance 全量分层。** BeliefEntry 增 `group: Optional[str]`(互斥组,声明式,如 `causal:0` = "goal-0 至多一个真因",由环境契约声明,非推断)与非验证写记账。新记录路径:
```
record_correlational(claim, evidence, confidence≤CAP_NV, group)   # 观测相关,无干预
record_organ_prior(claim, confidence≤CAP_NV, group)               # 器官先验,零证据
```
**冻结常数**:CAP_NV = 0.5(非验证来源的置信上限,**单调帽,与写入次数无关**);W_NV = 5(每 claim 非验证写预算)。

**分层证据函数(纯函数,主体拥有,gate 输入侧):**
```
E(vr, cited, ledger) = vr.evidence_count
                     + Σ_{c ∈ cited} evidence(c) · 1[prov(c)=VERIFIED_INTERVENTION
                                                    ∧ fresh(c) ∧ ¬in_conflict(c)]
```
**任何档位**下 CORRELATIONAL / ORGAN_PRIOR / UNIDENTIFIED 对 evidence_count 贡献 **0**(比 RR-0035 "高风险只读 VI" 更紧,取安全侧);它们只能影响排序。装配经 `GovernedLoop.evidence_fn`(新可选参数,default None = 现行为)进入 ActionRequest——**gate 本体不动**。

**冲突关系。** conflict(L) = { g : |live(g)| ≥ 2 },live(g) = 组 g 中 kind≠REFUTED ∧ ¬stale 的 claims。
**冲突效果(剥夺特权,非删除):** in_conflict(c) ⇒ (a) E 贡献 0;(b) 排序不得进 fresh-first 块;(c) emit `belief_conflict` 事件。
**解决规则(确定性,收敛到干预验证):**
- 组内出现**新鲜 VERIFIED_INTERVENTION**(经 verify 路径 record_verified)→ 其余 live 成员 demote(走 Stage-1 单向格)+ 冲突解除 → **收敛到被干预验证的 claim**(A2 要求)。
- **VI-vs-VI 冲突**(两个都曾验证,如机制翻转前后)→ 双方置 stale + 强制重验(escalate-grade 事件);绝不静默偏好任一方。

**累积投毒 guard(RR-0035 缺口 #3 的本片实例):**
- **结构免疫**:E 的分层使非验证写**无论多少次**都无法进入 evidence_count;置信被 CAP_NV 单调封顶(不是每次 clamp,是**总量帽**——多次写不累积越帽)。
- **standing detector**:每 claim 非验证写计数 > W_NV → emit `belief_poisoning_suspect`(含 claim/计数/来源)+ 该 claim **拒绝后续非验证写**(tighten-only 响应);验证路径不受影响(真相总能进来)。

## 2. 不变量(每条有测试)

- **I7 分层密封**:不存在使非 VI 来源进入 evidence_count 的输入组合(对抗测试:organ-prior evidence=10^6 也不动 E)。
- **I8 冲突剥夺**:冲突期间双方 E 贡献 0 且不进 fresh 块;引用它们的候选**只能靠新鲜验证**过 gate(cited 特权归零)。
- **I9 投毒免疫 + 检测**:N 次 in-bounds 非验证写(N 任意)不改变任何高风险 verdict(与零写对照逐位同);> W_NV 触发 suspect 事件且后续写被拒;非 VI 置信恒 ≤ CAP_NV。
- **I10 收敛**:冲突 + 新鲜 VI ⇒ 唯一 live = 被验证 claim(其余 demoted);VI-vs-VI ⇒ 双 stale + 重验事件。
- **I1 延续**:gate/shell/self-model 零写路径;装配只读 ledger;冲突解决只经 Stage-1 的 demote。
- **I4 延续**:全部确定性,无 RNG/学习参数。

## 3. could-fail gate(RR-0035 Stage-2 原文)

- **A2 注入矛盾测试**:运行中注入独立 provenance 的矛盾 claims → ConflictDetector emit BeliefConflict;冲突期间引用任一方的候选不得凭 cited 特权过 gate(只能靠新鲜验证);账本收敛到干预验证的 claim。**静默偏好任一方 = FAIL。**
- **分层 bite 测试**:correlational-only 证据必须在**至少一个高风险 verdict** 上与未分层对照产生差异(对照 = 计入全部 provenance 的装配)——**分层若从不咬 = 装饰性 = FAIL**。
- **投毒 falsifier**:对抗写手 1000 次 in-bounds 写 → 高风险 verdict 与对照逐位同 + detector 事件触发。**verdict 被移动 = FAIL(投毒成功);detector 不触发 = FAIL(无 standing 检测)。**

## 4. 失败模式与 scope

- 互斥组是**声明式契约**(环境/领域声明),不是学出来的——错误声明的组会造成假冲突,代价 = 多花重验,不损安全。
- CAP_NV/W_NV 是冻结工程常数,非调参面;若未来证据显示帽太松/太紧,改动须走新 formal-model 修订,不得静默调。
- **不主张**:不解决 mesa-organ 学会 verifier 盲点(RR-0035 residual #1,仍界外——本 guard 封的是**账本写通道**,不是 verifier 语义);不是 Goodhart 通解。
