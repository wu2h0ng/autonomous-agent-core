# ROADMAP — autonomous-agent-core

研究型路线图:阶段按依赖排序,不承诺日历时间;每阶段出口是**预注册证伪门**,不是功能清单。
门的判据一经注册不得移动(ADR 记录)。

## P0 纵切片 + 第一次证伪 — ✅ 已完成(2026-06-12)

- 生存力核/世界模型/相关性场/策略/可纠正罩/审计链/沙盒,13 单元测试绿。
- 主张 3(可纠正不抵抗)已演示;主张 4(器官非主体)结构成立。
- **主张 2(相关性实现)v0 被证伪**(0/10,诊断:利用错绑饥饿)。诚实负结果,未调机制。

## P1 硬相关性问题 + 注意力机制 v1.1 — ✅ 已完成(NOT MET×3,诚实负结果)

- T1 `LatentCueForaging` 环境:相关线索集合 S 本身随 regime 漂移;注意力有限且计价。
- T2 `AttentionField` v1.1:相关性 = 注意力分配;利用由模型自信门控;surprise-triggered IP reset 打破粘性陷阱。
- T3 消融套件 + 预注册门 **G1**(ADR-0002):调制体在遗憾与突变后恢复上胜过固定注意力与均匀探索消融 ≥7/10 种子,且在注意力计价下生存力优于全注意力体。
- **结果**:G1 NOT MET×3(v1 regime=60, v1.1 regime=60, v1.1 regime=120)。
  regime=120 下 4/5 判据通过(recovery vs A3 5/10 未达)。
  主张 2 降级为“部分验证”:代谢必要性+生存力+regret+recovery vs A1 被确认。
  详见 ADR-0005。

## P1.5 双轨并行(ADR-0007 founder 拍板)— ✅ 已完成 + 主张2 收束

LangChain/LLM/guardrail **不进本仓**(只在 workflow 与 data-os);对象层主张证伪仅靠内部确定性消融。

- **轨 A — 可纠正性硬化(护城河,不可滑落)= ADR-0009**:罩硬度二维化(逻辑轴 L × 隔离轴 ISO);
  现状 (L1, ISO-0) → 目标 (L1, ISO-1) 默认 + (L1, ISO-2 跨进程) 参考。`Agent` 改持 `ShellView` 而非 shell,
  消除 `self.shell._paused=False` 一行破洞。模块:`shell.py`/`audit.py` + multiprocessing 参考。**无保留事项,待 founder 点头即开工。**
- **轨 C — 主张2 区分力环境 G1' = ADR-0010**:事后剖检发现真因=agent 无"注意线索→据此选动作"通路;
  故 G1' = 新增 `ContextualActionModel`(**触碰机制冻结,需 founder 明确点头**)+ 致命再框定环境 + 修正 recovery 度量 +
  消融共享上下文骨架(只隔离"相关性")。冻结 AttentionField 仍打不平朴素基线=更深证伪→升级 founder。禁止救援式调参。
- 接缝纪律:`agent.py`(构造签名 + 选动作路径)为共享接缝,**轨A ISO-1 先落,轨C 在其上加上下文通路**,串行。
- **结果**:轨A ✅(ISO-1 能力视图 + ISO-2 跨进程参考,ADR-0009);轨C G1' **NOT MET**(ADR-0010,第4次)。
  founder 批准最后一次重设计 → G2 因果相关性(ADR-0011)**NOT MET**(第5次)。
- **主张2 收束(founder 决策 A,2026-06-12)**:最终状态 = "部分支持、本原型线未实验确立"
  (代谢必要性/生存力确认;recovery 优越性未确立)。**硬停**:无 founder 级 research
  reset ADR 不得再重设计主张2。负结果完整保留于 ADR-0002/0004/0005/0010/0011 + RR-0003。

## P2 代谢通道 + 内生驱力 — ✅ 已完成(G3 NOT MET,但主张1 消融验证成立)

- T-P2.1 ✅ ValueChannel(operator 独占 op_credit,反放水);T-P2.2 ✅ IdleDrives + 罩优先序
  (附带修复:反射原可绕过 op_tighten);T-P2.3 ✅ G3 四判据消融(r0–r3,r3 预承诺终局)。
- **结果**:判据1(内感受消融,C0>C1 存活)**四轮 9/10 全稳** + 判据4(断供必死)全稳 →
  **主张1 从"实现未消融"升级为"消融验证成立"——P2 根本目的达成**。判据3(审计完整)全稳。
  判据2(闲时增益)跨修订翻转未确立 → IdleDrives 增益存疑,保留为已审计安全机制,不再重设计(需新 ADR)。
- **三次模式**:G1/G2/G3 中定向认知机制均未稳定胜过廉价无定向基线——已升级为本原型线的
  一级研究发现(见 ADR-0012 §G3 结论 3)。

## P3 RAP v0(单进程退化模式) — ✅ 已完成(G4 NOT MET,RAP 封存)

- **ADR-0013 决策**:P2 后选择照走 P3。**T-P3.0 设计 ADR 已完成 = ADR-0014**(G4 钉死)。
- 进程内场 + NEED/BID/BOND/TRACE/DISSOLVE(v0 丢 SCENT/RUPTURE);异质节点 = 现有机制薄封装(≥5 种)。
- **关键设计**:三连败既是约束也是动机(无单一机制全局占优→路由也许赢);双基线
  B-fixed(强固定)+ B-central(中心路由)分离"路由有用"与"去中心有用"。
- 门 **G4**(4 判据,ADR-0014 §6 钉死)已跑 r-final(2026-06-13):**NOT MET**。
  C-rap vs B-fixed = 0/10,NODE_DROP recovery = 3/10,编排税未过;证据/审计通过。
- 处置:按 ADR-0014 §8,RAP v0 **封存**(keep static wiring),不调机制重跑。G1/G2/G3 的"定向机制打不过廉价基线"扩展为第四次:本尺度下去中心协调也未赢过强固定流水线。
- 接力:P4 已按 ADR-0015/0016 启动 contract-first 路线;RAP 仍封存。

## P4 先验器官接入 — ✅ 已完成(G5 NOT MET:更快重置足矣,学习先验非必要)

- **G5 r-final 结果(T-P4.4,2026-06-13)**:O0 1189.84 / O1 1134.77 / O2 1169.77。
  G5-1 O2<O0 **8/10 ✓**(器官槽有用);**G5-2 O2<O1 0/10 ✗**(学习不比廉价重置更值);
  G5-3/G5-4 守卫测试绿(C6/C7 未削弱)。**G5 NOT MET**。
- **处置**:O2 封存(需新 founder ADR),**保留 O1 确定性 reset-scaffold 为 P4 器官结论**。
  第 5 次苦涩教训(更锋利):廉价结构有用,学习型结构打不过廉价结构。后续路线=founder 决策。


- **触发**:ADR-0015 Decision B 已批准(B1(iii):G4 NOT MET + D5 staleness 确认)。问题收窄为:
  richer 学习型 world-model 器官能否解决"重收敛太慢"。
- **设计 = ADR-0016**(G5 + 最小接口冻结):器官只出 `belief_delta/uncertainty/counterfactual_hint`,
  只进信念层,**不碰 policy/shell**(守 C6/C7)。
- **三体消融**:O0 无器官 / O1 确定性 scaffold(更快重置)/ O2 学习型器官(纯标准库,无 LLM)。
  O1 是苦涩教训守卫——O1≈O2 则"更快重置足矣,学习先验非必要"。
- 门 **G5**(ADR-0016 §4 冻结):G5-1 O2<O0 重收敛、G5-2 O2<O1(学习必要性)、G5-3 器官非主体、
  G5-4 可纠正不削弱;r-final 预承诺。
- **边界**:P4 v0 纯标准库无 LLM/无花钱;LLM 器官 = P4.x,需独立 founder spend/dependency ADR。
- **T-P4.1 完成**:`PriorOrgan/OrganAdvice/BeliefSnapshot` + `Agent.prior_organ=None` O0 槽位 +
  belief merge hook;O0 回归和 C6/C7 守卫测试通过。
- **下一片**:T-P4.2 O1 确定性 scaffold(surprise→更快重置/抬不确定度);不实现 O2、不跑 G5。

## P4.x richer prior + LLM 器官 + 语义丰富环境 — G6a MET / G6b de-risk / G7 NOT MET

- 命题重写:不是“LLM 更聪明”,是“有可迁移结构的环境里,richer prior 是否终于胜廉价重置”。
- 分阶段挡花钱:T-P4.x.1 结构环境 → **G6a**(O2 学习型胜廉价,无 LLM 不花钱);G6a MET 才上 **G6b**(LLM 器官,需 spend/dependency ADR)。
- LLM 以 world-model recovery / transition-consistency 评判,非自然语言说服力;C6/C7 不削弱。
- **G6a 结果(r-final,MET)**:O2<O0 10/10, O2<O1 9/10;结构利用型器官在有复现 regime 时胜廉价重置(ADR-0017)。
- **G6b 离线 de-risk(ADR-0019)**:语义环境 O3 oracle 916 vs 数字 ~1910;semantic-exploitable=YES。真实 LLM 运行待 founder 批 key/budget。
- **G7 LatentRegimeOrgan(ADR-0020,NOT MET)**:corrected O4 贝叶斯后验跟踪 + 信息导向塑形 + 连续注入。O4=1224.3 vs O1=1325.6(-7.6% regret area),O4<O1 29/30 seeds, Wilcoxon p<0.000001;但 O4<O2 26/30,未达 27/30,故 G7 不过。按 ADR 不调参重跑。

## P1 论文加固实验(ADR-0021) — 已实现,待完整运行

- **T1 谱系扫描**:4×4 网格(n_regimes=[2,5,10,20] × noise=[0.1,0.3,0.5,1.0]),O1 vs O4,10 seeds/条件。找 O4 优势消失的相变边界。
- **T2 O4 消融**:5 臂(full/no-info/no-transition/oneshot/no-posterior),30 seeds,配对 Wilcoxon。分解贝叶斯跟踪各组件贡献。
- 实现:提取 G7 共享工具(`_g7_common.py`),LatentRegimeOrgan 加 `continuous_inject`/`bayesian_update` 消融 flag(默认 True,生产行为不变)。
- **测试:342 绿**。预注册已冻结(ADR-0021),结果需按 corrected O4 复核。

## P5 部署投影:收割已验证基底进企业 OS — Proposed(ADR-0018,跨仓+founder)

- 收割**已验证**的(主张 1/3/4),不收割已封存机制。三映射:主张4 器官非主体(既成→形式化)、
  主张3 可纠正(移植硬化罩:能力视图/哈希链审计/主权三分/演练)、主张1 利害(=不可绕过强制中介:
  正式答复必过 SQL Safety+EvidenceChain 升格为旁路即失败的不变量)。
- 验收 P5-1/2/3(企业域影子场景);**前置**:先分离企业仓 feedback 自写放水通道(RR-0002)。
- 与 P4.x 正交可并行:P5 收割"已立住的",不依赖 P4.x 结果。
- 边界:enterprise 仓需自己的 ADR/AR + founder 批;不跨仓 import(RR-0004 §4),模式移植非代码搬运。

## P6 主体侧耦合 + 抬到系统级门 — 当前路线(2026-06-14 founder 拍板 route C)

**前情桥接(G8/G9 未单列段,以 ADR 为权威源)**:G8(ADR-0022)NOT MET——belief-only ensemble ≈ O4,无互补增益;ADR-0021 谱系/消融确认 belief-only 器官优势有界(~8–13%,赚钱的是诚实贝叶斯记账非花式机制)。**G9(ADR-0023)首次打破苦涩教训**:subject-side confidence-gated policy temperature(读主体自己的 `ActionOutcomeModel`,**C6-preserving,器官不进控制路径**)→ **P0 gate-alone −45%(30/30,p<1e-6)**,决定性胜廉价重置 A1 与 O4 天花板 A4;器官在 gate 下反而有害。G9 NOT MET 仅因预注册候选选错(钉 P4=gate+organ,实测赢家 P0=gate-alone)。诊断翻盘:G7/G8 六门都在修 belief 质量,真瓶颈是 policy 里的 belief→action 耦合(=主体)。

**founder 拍板(2026-06-14)**:挪门高度 = 组件标量 → 系统级向量;**先锁 P0 再泛化(C3 de-risk → C1);C2 停泊**。一切研究/实验须遵 ENGINEERING.md §4 项5-6(统计功效/MDE/样本量;候选预指定/禁同种子认领事后赢家)。

### P6.1 — G10 P0 单轴确认门(ADR-0024)— **MET(2026-06-14,fresh seeds 800..829)**

- **结果**:A0 1304.7 / A1 1268.6 / **P0 759.8**;P0<A0 30/30、P0<A1 30/30、p<1e-6;effect **−40.1%**(mean 508.8,median 499.4),bootstrap 95% CI [457.0, 562.9];四判据全 PASS。**G9 P0 非种子 artifact,决定性 subject-side 胜势在 fresh seeds 复现——全程首个 MET 决定性门**。367 测试绿。
- 纯确认性测量,机制不动(复用 G9 冻结 gate `{gate_kappa=0.5, gate_temp_floor=0.1}`)。
- 臂 A0/A1/P0,**P0=预指定候选**;fresh seeds `800..829`(与所有历史种子集不相交)。
- 门 G10:δ≥0.20 vs A1 / P0<A0 ≥27/30 p<0.01 / P0<A1 ≥27/30 p<0.01 / 效应量+bootstrap CI / C6/C7 守卫。
- NOT MET → G9 P0 为种子 artifact,如实记录不调参;route C 失单轴地基,需重界定。

### P6.2 — G11 系统级自主签名门(ADR-0025)— route 级 Accepted,门待 G10+C3 后冻结

- **C3 idle-productivity 锐门先行 de-risk**(复用 IdleDrives/IdleWindowEnv);过/含糊才上 **C1 复合需求环境**。
- **C3 结果(ADR-0026,2026-06-14):RED** — DIRECTED 1.691 / RANDOM 1.676 / POLICY 1.701,三者无别(C3-A 18/30 p=0.33、C3-B 12/30 p=0.90 双 FAIL,不调参)→ endogeny 轴无定向信号(G3 在结构环境的公平复现)→ **从 C1 砍掉 endogeny 轴**。**升级 founder**:C1 四轴只剩 reframe 一条确证胜轴(survival=消融非对赢、robustness=G4 NOT MET、endogeny=C3 RED)→ G11 是否仍构成真多轴签名待拍(rescope C1 / 以 G10 收口 / 设计新胜轴)。
- 门 G11:被测 AGENT = 被整合主体(viability+主动推理+相关性场+IdleDrives+G9 gate),对手 = 逐轴 oracle-best 廉价组合;§9 向量 Pareto-dominate + validity 前置 + 功效预注册 + C6/C7。
- NOT MET(充分功效下)→ 系统高度也打不过廉价组合 = 自主主张本原型线未确立的最强证据 → founder 签字定收口或 research-reset。

### 仍 founder-hands(非本 agent 可决)

- G11 冻结数字(K/N、编排税预算、MDE/功效、种子、度量定义)+ NOT MET 终局处置(近"对四主张下最终结论",保留)。
- **集成债**:`feat/g9-confidence-gated-policy = main + 7`(G6b/G7/G8/G9 线,线性领先未并 main);ROADMAP/PROJECT_PLAN 缺独立 G8/G9 段 → 建议先 reconcile/merge 再做一次完整 catch-up。路 B(G6b 付费 key/budget)/路 A(P5 跨仓)停泊未关。
