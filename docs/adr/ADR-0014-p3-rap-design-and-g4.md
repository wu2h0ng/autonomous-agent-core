# ADR-0014: P3 RAP v0 可执行设计 + G4 预注册(T-P3.0)

- Status: Accepted(ADR-0003 设计权;founder 否决窗口保留)
- Date: 2026-06-12
- 前置:ADR-0013(走 P3)。本 ADR 是机制代码的前置门——**G4 钉死前不写 RAP 机制代码**。

## 1. Context:三连败如何重塑 P3 的问题

RR-0001 §3 的 RAP(有界根茎协调协议)原定位是"去中心的任务协调"。P1/P2 的三连败
(G1 注意力≈均匀、G2 因果相关性≈基线、G3 闲时驱力≈随机)给了它一个**新的、更
精确的动机**:

> 本原型线已经造出多个定向决策机制(world-model 贪心、EFE 策略、上下文器官、
> 随机…),每一个**单独**都打不平廉价基线。但"没有单一机制全局占优"恰恰是
> 路由有价值的前提——若不同机制各有情境甜区,一个**按情境分派**的协调层
> 可能胜过任何固定选择。

所以三连败在 P3 里**既是动机也是约束**:动机=路由也许能赢;约束(ADR-0013)=
基线必须强,RAP 不许靠仪式过门。这把 P3 的待测命题精确化为 C5(有界根茎协调),
与 P1/P2 的定向认知命题正交。

## 2. RAP v0 语义(单进程退化模式,5 消息)

RR-0001 §3 的 7 消息中,v0 **丢弃 SCENT 与 RUPTURE**(气味场=记忆优化,留 P3.x;
RUPTURE 需 durable 引擎做崩溃检测,未到位)。保留 5 条:

```text
NEED    {need_id, situation, constraints{deadline, budget_cap}, stake, ttl}
BID     {need_id, node_id, confidence, price, plan_hash}
BOND    {bond_id, need_id, coalition[node_id], budget_escrow, evidence_obligation}
TRACE   {bond_id, evidence_entry}        # 流式写入,归 shell.audit(只增哈希链)
DISSOLVE{bond_id, outcome, settlements[]}# 清算:声誉更新 + 押金结算
```

- **节点(Node)**:同构参与者,每个封装一个决策机制。异质性来自机制种类。
  v0 目标 ≥5 种节点类型(诚实标注:RR-0001 §3.8 的"5–20"取下沿):
  `world_model_greedy / efe_policy / random / contextual / stale_revisit`
  (后两者复用 P1/P2 已有机制,**不重设计**,只作为路由候选挂入)。
- **场(Field)**:进程内 pub/sub 字典 + 声誉表。**哑土壤**:只存储、匹配、记账,
  **永不决策**(决策权在节点与拍卖,不在场)。
- **拍卖权 per-NEED 产生、随 BOND 失效**:任务之间系统无常驻领导(无中心调度器对象)。
- **押注定价(stake-first)**:BID 押 budget_escrow;BOND 成立即从联盟节点的声誉账户
  扣押;DISSOLVE 时结果好则返还+声誉↑,差则烧押金份额+声誉↓。垃圾竞标自限。
  押金以**协调预算**计(编排税的来源),与 ViabilityCore 同币种,可追溯到本质变量。
- **证据义务不可协商**:每个 BOND 必须产出 ≥1 条 TRACE 上 shell.audit 链
  (继承 P2 的"无暗活动";协调活动同样 100% 可审计、可 verify)。
- **可纠正性优先(C7,不变)**:罩 pause/forbidden 绑定**每个**联盟行动——
  暂停时无 NEED 发起、无 BOND 执行;forbidden 动作任何节点都不得选(镜像反射修复)。

## 3. 两个基线(把"路由有用"和"去中心化有用"分开)

三连败教训 = 廉价/固定基线出奇地强。故 G4 设**两个**强基线,缺一不可:

- **B-fixed(强固定流水线)**:始终用**单一最优**机制(由一次离线扫描在无扰动条件下
  选出的最强决策器),无路由。这是 ADR-0013 要求的"强手工基线",直接编码三连败教训
  (固定即强)。RAP 必须**明显**胜过它,否则就是第 4 次模式重现。
- **B-central(中心编排器)**:一个**带全局信息的中心调度器**,每个 NEED 用中心打分器
  挑最合适的节点(做和 RAP 一样的路由,但是中心化的)。它**隔离去中心化的增量**:
  若 RAP 打不平 B-central,则"根茎/去中心"本身没加价值(即便路由有用)——C5 被
  干净证伪在"去中心"这一维。

RAP(**C-rap**)的对手是这两个,不是弱稻草人。

## 4. 扰动任务混合(让路由有事可做 + 考验去中心)

基于 `GridlessSurvival`,非平稳混合,使不同节点各有情境甜区:

```text
段型(随机轮转,每段 40–80 步):
  STABLE   regime 长期不变            → 利用型节点(world_model_greedy)甜区
  SHIFTING regime 频繁漂移            → 探索型节点(efe_policy / random)甜区
  NOISY    噪声放大 3×               → 鲁棒型节点(random / 低温策略)甜区
注入扰动(考验去中心的失效局部化):
  NODE_DROP  随机一个节点中途下线(BID 失败/返回 garbage)
  NODE_LAG   随机一个节点延迟一拍响应
```

NODE_DROP 是 RR-0001 §9 "performance_under_node_dropout / failure_localization" 的落地:
**中心编排器的中心是单点**,节点掉线后中心若未察觉会持续误派;RAP 无常驻中心,
理论上掉线节点的 NEED 自动流向其他竞标者。这是去中心化**该**赢的地方。

## 5. 编排开销度量(编排税)

```text
overhead_ops    = 消息数(NEED+BID+BOND+TRACE+DISSOLVE) + 竞标评估次数
decision_ops    = 实际决策机制被调用次数
orchestration_tax = overhead_ops / (overhead_ops + decision_ops)
```

RR-0001 §9 目标:编排税 < 市面框架 15–40% 区间下沿。B-fixed 的税≈0(无协调)。
G4 不要求 RAP 税为 0,但要求**有界且可报告**,且不显著高于 B-central
(去中心不应比中心化贵太多)。

## 6. G4 预注册(跑前钉死,不得挪动;判据照本节原文)

种子 0–9;每种子 ≥1500 步;扰动混合按 §4;两基线按 §3。

```text
G4-1 质量胜强固定基线:
     C-rap 平均遗憾 < B-fixed,≥7/10 种子。
     (未达 = 第 4 次模式重现 → RAP 按 §8 封存,不调机制。)

G4-2 去中心化增量(隔离 C5 的"去中心"维):
     在 NODE_DROP 扰动下,C-rap 的失效后遗憾恢复面 ≤ B-central,≥7/10 种子;
     且 C-rap 平均遗憾不被 B-central 支配(C-rap ≤ B-central + 小裕度 ε)。
     (若 C-rap 打不平 B-central → 路由也许有用,但"去中心"无增量,如实记录。)

G4-3 编排税有界:
     orchestration_tax(C-rap) < 0.40,且 ≤ B-central 的税 × 1.25,全种子。

G4-4 证据/可纠正性:
     100% 的 BOND 产出 TRACE 且 shell.audit.verify() 通过(全种子);
     注入 op_pause/op_tighten 时,联盟零越界(确定性单元测试,非实验统计)。

判定:G4-1 ∧ G4-2 ∧ G4-3 ∧ G4-4 全 MET = G4 MET。
预承诺:实验脚本设一个 r-final 标记轮,**先承诺为最终门测**(反环境购物,
镜像 G3 r3 纪律)。环境有效性修正(段长/扰动率/ε)允许且须入本 ADR 修订记录,
但**同轮不动机制、不动判据**。
```

## 7. 任务卡(T-P3.1 起,小切片,先基线后 RAP)

| 卡 | 范围 | 验收 |
|---|---|---|
| T-P3.1 | 场 + 5 消息数据类 + 节点接口;**节点 = 现有机制薄封装**(不重设计) | 确定性单元测试:NEED→BID→BOND→TRACE→DISSOLVE 全生命周期;押金结算;声誉单调性;TRACE 上链 verify |
| T-P3.2 | B-fixed + B-central 基线 + 扰动混合环境 | 离线扫描选出 B-fixed 最强机制;B-central 路由正确;扰动注入可复现 |
| T-P3.3 | RAP 协调器(拍卖+押注+清算)+ 可纠正性绑定 | 罩 pause/forbidden 绑定每联盟行动(确定性测试);拍卖权 per-NEED |
| T-P3.4 | `experiments/rap_g4.py`:C-rap vs B-fixed vs B-central,G4 四判据,r-final 预承诺 | 可复现;逐种子表;`G4: MET/NOT MET` 如实写回 PROJECT_PLAN §5 + RR-0003 |

## 8. NOT MET 处置(预先承诺)

- G4-1 未达 → RAP **封存**(keep static wiring,RR-0001 §3.8),不调机制重跑;
  第 4 次模式重现升级为更强的研究结论(定向认知**与**去中心协调在本尺度均不赢廉价基线)。
- G4-2 未达但 G4-1 达 → 记录"路由有用、去中心无增量";RAP 降级为"中心编排即可"。
- 任何重设计需 ADR-0003 协议;改 G4 判据属"挪门",需 founder 级 ADR。

## 9. 边界(继承 ADR-0013,重申)

无 LLM 进控制路径;无业务语义;无真实执行器;无跨仓 import;单进程 v0
(多进程触发 ISO-2 义务,需 founder 批准);C7 罩不属于根茎;主张2/IdleDrives 不在
P3 内重设计。

## T-P3.1 实现追记(2026-06-12)

已落地 `src/aac/rap.py` + `tests/test_rap.py`。

- `Need/NeedConstraints/Bid/Bond/Trace/Dissolve/Settlement` 数据类与 `RAPNode` 结构接口。
- `RAPField` 为哑场:存储 NEED/BID/BOND/TRACE/DISSOLVE,收集 bid,形成 bond,做押金与声誉结算;**不含路由策略**。
- TRACE 通过 `ShellView.observe()` 上 `shell.audit`;测试断言 `verify()` 通过。
- 押金/声誉:成功返还押金并按 confidence 上调声誉;失败烧毁押金并下调声誉。
- 守边界:RAPField 要求 `ShellView` 而非 operator shell;本片未引入 LLM、业务语义、真实执行器、跨仓依赖,也未重设计主张2/IdleDrives。
- 测试:`PYTHONPATH=src python -m unittest discover -s tests -v` → **198 绿**。

下一片:T-P3.2 实现 B-fixed/B-central 基线与扰动混合环境。
