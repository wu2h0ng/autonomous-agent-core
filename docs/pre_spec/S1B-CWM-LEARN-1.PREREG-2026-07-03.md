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

## 6. RESULT v1 = INVALID(2026-07-03,泄漏,由作者对抗审计抓出)

v1 机械报 MET(LearnedCWM recall 1.000 vs STAT 0.867,δ+0.133,p=0.002,permute 负控制塌 chance)。**但对抗审计发现泄漏 → INVALID(按 §4 INVALID 分支):** LearnedCWM 特征含**被干预节点 X 自身的值**,do(X) 钳住 X → 模型对**每一对**(X,T)都能从 X 的钳位值检测"这是 do(X) 样本"。诊断:祖先对 AUC 0.988(15/15 过 0.60)**且非祖先对 AUC 0.852(17/17 也过 0.60)**——模型全判"祖先",recall 1.0 是"全判祖先"产物,检测的是**干预**不是**祖先**。permute 负控制只证"非记忆",没证"是祖先信号"——是错的控制。recall-only 冻结判据太松,抓不到 all-ancestor。STAT 无此泄漏(边际只在真祖先时移动,0.867 诚实)。**如实记 INVALID,不 claim MET。**

## 7. v2 RE-SPEC(收严,先冻结预测再跑;非 spec-shopping:剔特征+改判别,更难非更易)
- **特征剔除**:LearnedCWM 特征剔除**被干预节点 X 自身**(及 target T)——只用 mediators;这样"检测干预"的捷径被封,只有 X→T 有真机制路径时,mediators 才带 do(X) 签名。
- **判据改判别(非 recall)**:两臂都对全部 (X,T) 对打分(STAT=边际效应量;CWM=剔 X 后的 held-out AUC),算**判别 AUC** = 各自的分数把真祖先排在非祖先之上的能力。**MET**:CWM 判别 AUC 显著 > STAT 判别 AUC(δ≥0.05,10 seeds 配对 p<0.05)。**NULL**:TIE 或不显著 → 保留统计实现。
- **v2 冻结预测**:泄漏封死后,**预期 NULL**(承 RR-0038 + Sachs 边际强传播;剔除 X 后学习模型难超边际)。若仍 MET = 真捕到 mediated 结构,是"智能在自建模型上"的真证据。

## 8. RESULT v2 = NULL(2026-07-03,泄漏封死后,诚实)

剔除被干预节点 X 自身 + 改测判别 AUC 后:**STAT 判别 AUC 0.831 vs LearnedCWM 0.772,delta −0.059,10/10 seeds STAT 全胜(p=0.002)→ NULL**(且我们的学习模型实际**更差**)。与 v2 冻结预测(NULL)一致。

**净裁决(CWM-LEARN-1 = NULL):** 在 Sachs 规模,我们自建的最小学习型 CWM(多变量 logistic 机制签名)**没有统计基线之外的能力增量,反而更差**。边际效应量法在强传播的 Sachs 网络上近饱和,最小学习模型难超。**保留统计实现**(现 verifier),不 rescue。

**对 founder steer("智能要在我们自己的模型上")的诚实含义:** 今天可 demonstrable 的能力仍是 (a) 借来的 LLM 器官,(b) CWM = 统计**方法**(非学习结构)。**我们自建的学习模型此刻尚无可证的学习智能增量。** 这不是"我们的模型不能智能",而是"最小版在此规模/数据上 ties-or-loses";让它真正超统计 = phase-2 研究程序(更富机制结构/更难数据/更好表示),即 H-P2 准入门 S5-3 **未满足**,phase-2 继续不排期。**这正是本门要诚实回答的问题:phase-2 的"规划大脑"今天还没有脑。**

**方法学胜利(承 SD4 线纪律):** v1 机械 MET → 作者对抗审计抓出"检测干预非祖先"的泄漏 → v2 收严 → NULL。author≠adjudicator + 对着冻结 NULL 预测跑 + 收严非放松,防住了一次高危假阳性(founder 最易被此误导之处)。
