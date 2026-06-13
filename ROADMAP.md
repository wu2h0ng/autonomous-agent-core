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

## P4 先验器官接入 — ◀ 当前(T-P4.1 已完成,下一片 T-P4.2)

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

## P5 降级投影试点 — 跨仓,双侧 ADR

- 验证"企业 OS = 通用核 + autonomy→0 + 域包":在企业仓影子环境复演其 Trusted Loop 行为。
- 出口 = RR-0004 §5 支撑关系闭环;此前企业仓照常独立演进。
