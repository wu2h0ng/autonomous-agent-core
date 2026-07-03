# S1B / CWM-LEARN-1 PREREG — 学习型 CWM 器官 vs 同预算统计基线（冻结,founder cast freeze/run 2026-07-03）

- Status: **FROZEN-BEFORE-RUN**。founder cast freeze/run(2026-07-03)。判据/split/阈值跑前冻结;跑后只写 §RESULT,不调机制(AGENTS.md §2.5)。
- 上游: RR-0038 PART B;founder steer 2026-07-03 "智能要在我们自己搭的模型上"——本门检验**我们自建的学习模型是否有统计基线之外的能力增量**。
- 边界: object 层;verify-only 消费(Stage-5 已证 proposal-form 惰性);学习**离线**(ADR-0033 L0-L3),运行时冻结,**不引 online 推断进控制路径**(RR-0026 §5.1)。capability-under-governance。

## 1. 问题
现 CWM = 边际效应量检验(标准化均值差;Sachs 干预 recall 0.905 = 方法学验证,非学习结构)。CWM-LEARN-1 问:**一个学习的 mechanism 模型**(从干预数据拟合、用多变量结构)在 held-out 干预上能否**显著超过**同预算的边际效应量基线?

## 2. 机制(两臂,同数据同预算,fair)
真 Sachs:PROTEINS(11)、INTERVENABLE={Mek,PIP2,Akt,PKA,PKC}、GT DAG(17 边)、干预数据 5401 行。对每个 target T,判每个 intervenable X 是否 T 的因果祖先(GT ancestry)。
- **STAT(基线)**:X 的干预样本 vs 观测基线,T 的**标准化均值差**;≥τ_stat → 判 ancestor。=现 SachsInterventionVerifier 逻辑。
- **LearnedCWM(我们的模型)**:对 (X,T),在 **train split** 上拟合一个 logistic 分类器 = P(sample∈do(X) | 全部非 T 蛋白的值),即学习"干预 X 的机制签名";held-out split 上的判别 AUC ≥τ_cwm → 判 ancestor。**多变量**(用 mediators),对比 STAT 的单变量边际——这是"建模机制"相对"测边际"的增量。
- **公平**:两臂同 train/test split、同干预样本预算;LearnedCWM 只多用了"更多特征"(这正是学习模型的意义);无臂拿对方没有的数据。

## 3. 冻结 split + 阈值
- split:每 (X) 的干预样本按 `Random(seed)` shuffle,前 60% train / 后 40% test;seed ∈ {0..9}(10 seeds,报均值±std)。
- 阈值:τ_stat = 0.3(标准化均值差,承现 verifier);τ_cwm = 0.60(held-out AUC,>0.5 才有判别力,0.60 保守)。**跑前冻结,不为通过调。**
- δ(增量显著阈)= LearnedCWM recall − STAT recall ≥ **0.05** 且配对 sign-test p<0.05(跨 10 seeds × 7 targets)。

## 4. 冻结判据
- **MET**:LearnedCWM held-out ancestry recall 显著 > STAT(δ≥0.05,p<0.05),且 confound-controlled(负控制:随机 permute 干预标签 → LearnedCWM 判别力塌到 ~chance,证信号真);→ **我们的学习模型有增量**,S5-3 准入门满足度提升。
- **NULL(诚实,预期)**:TIE 或不显著 → **保留统计实现,不 rescue**;记"学习型 CWM 在 Sachs 规模无增量"——**NULL 是可发表基线,精确回答'phase-2 规划大脑今天有没有脑':没有→ H-P2 准入门 S5-3 不满足,phase-2 继续不排期**。
- **INVALID**:负控制未塌(判别力来自泄漏)/ split 不公 → 修 spec 重跑。

## 5. 预测(冻结,可打脸)
承 RR-0038 + Sachs 方法学结论:**预期 NULL**(边际效应量已近饱和于强传播的 Sachs 网络,多变量学习难在此规模超它)。**若 MET = 真惊喜**:说明我们的模型捕到了边际测漏掉的机制结构,是"智能在自建模型上"的第一份真证据。两分支都 informative。

## 6. RESULT(跑后填)
_(frozen empty until run)_
