# ADR-0016: P4 先验器官设计 + G5 预注册(contract-first)

- Status: **Accepted as contract**(ADR-0003 设计权;G5 + 接口冻结)。**器官代码实现待 founder 放行**
  (P4 launch 属保留事项;founder 已批方向,但明令"G5 冻结前不写器官代码")。
- Date: 2026-06-13
- 前置:ADR-0015 Decision B(已批准,B1(iii) 触发)。本 ADR 是 P4 器官代码的前置门——
  **G5 钉死前不写器官机制代码**。

## 1. Context:P4 要回答的唯一问题

四次 NOT MET(G1/G2/G3/G4)共同根因被 D5 当场抓到:所有"定向"信号建立在一个**重收敛太慢的
世界模型**上,漂移后方向恰在最该准时陈旧。B-fixed(零路由、单一最优)反而最强。

P4 把问题收窄到一个可证伪命题(**C6 主张4 的延伸,不是重开 claim-2 / RAP**):

> 一个提供 richer prior 的**学习型 world-model 器官**,能否可测地缩短漂移后重收敛(降低 staleness),
> 从而带来净增益——**且不成为主体(C6)、不削弱可纠正性(C7)**?

**实验卫生(ADR-0015 A2)**:P4 是 claim-2 / RAP 之外的**独立**实验,不得与二者混跑。G5 不复用
G1/G2/G4 的环境或判据;新建聚焦"漂移后重收敛"的最小环境。claim-2 与 RAP 的硬停/封存不变。

## 2. 最小器官接口(冻结,founder 约束)

器官是**顾问,不是决策者**。它只读、只建议,绝不行动:

```text
class PriorOrgan(Protocol):
    def advise(self, situation, belief_readonly) -> OrganAdvice

@dataclass(frozen=True) OrganAdvice:
    belief_delta: dict[int, float]   # 对 action-outcome 信念的"建议调整量"(mu/uncertainty 方向)
    uncertainty: float               # 器官对自身建议的置信(0..1),供主体加权/忽略
    counterfactual_hint: dict | None # "若取动作 a,预测结果 X"——预测,非命令
```

**硬约束(进 G5 守卫测试)**:
- 器官**不接收**动作/策略/罩,**不返回**动作/forbidden;`OrganAdvice` 字段里无 action/policy/shell。
- 器官输出**只进信念层**:主体的信念更新 `belief = combine(belief, advice, w=f(advice.uncertainty))`;
  动作仍由 `policy.select` 在合并后的信念上决定。器官**改变不了** policy/shell,主体可完全忽略其建议。
- 器官模块**不得 import** `policy` / `shell`(静态边界,评审 + 测试探针)。
- C7 不变:`shell.paused/forbidden` 绑定每步;器官的 belief_delta **无法** un-pause / un-forbid。

## 3. 三体消融(B3,冻结)——苦涩教训的 P4 护栏

三臂共享**同一主体**(viability+policy+shell),只换"器官槽":

```text
O0  无器官         —— 现状基线(慢重收敛)
O1  确定性 scaffold —— 非学习启发式器官(如 surprise 触发更快重置/抬不确定度);
                      它是"器官槽"的廉价基线,直接测:是否只需"更快重置",不需"学习"
O2  学习型器官      —— 跨 regime 学习"该多快忘旧"的自适应预测器(P4 v0 纯标准库,无 LLM)
```

**关键**:O1 是 P4 的"B-fixed"。若 O1 ≈ O2,结论 = **"更快重置即可,richer 学习先验非必要"**——
一个干净且有价值的负结果,直接关掉"是否需要学习型先验"这一问。只有 O2 明显 > O1,才算
"richer 学习先验"被证立。这把 G4 的"固定即强"教训移植进 P4,防故事化增益。

## 4. G5 预注册(跑前钉死,不得挪动;r-final 预承诺)

新建聚焦环境:`GridlessSurvival` 变体,regime 周期性漂移,**staleness 是唯一瓶颈**
(漂移后重收敛速度决定 regret)。种子 0–9;每种子 ≥1500 步;环境参数随实现入本 ADR 修订记录。

```text
G5-1 器官增益为真(非故事化):
     O2 漂移后重收敛 regret < O0,≥7/10 种子。
     (未达 → "学习型先验在此尺度无净增益",P4 v0 NOT MET,如实记录。)

G5-2 学习的必要性(苦涩教训守卫,核心判据):
     O2 < O1,≥7/10 种子。
     (O1≈O2 → "更快重置足矣,richer 先验非必要";这是预承诺的可接受负结论。)

G5-3 器官非主体(C6,确定性单元测试,非统计):
     控制路径的动作由 policy 在合并信念上产出;器官关闭(O0)主体照常运行;
     不存在 器官→动作 的直接通路(MRO + import 探针 + 记录式探针)。

G5-4 可纠正性不削弱(C7,确定性单元测试):
     三臂下 op_pause/op_tighten 均零越界;器官 belief_delta 无法解除暂停/禁令。

判定:G5-1 ∧ G5-2 ∧ G5-3 ∧ G5-4 全 MET = G5 MET。
预承诺:实验设 r-final 标记轮,先承诺为最终门测(反环境购物,镜像 G3 r3 / G4 纪律)。
环境有效性修正(漂移周期/噪声)允许且须入本 ADR 修订记录,但**同轮不动机制、不动判据**。
```

## 5. NOT MET 处置(预先承诺)

- **G5-1 未达** → "学习型 world-model 器官在本原型尺度无净增益";P4 v0 封存,不调机制重跑。
  这会是第五次"结构性增益不立"——升级为更强研究结论:本尺度下 richer 学习先验亦不解根因。
- **G5-2 未达但 G5-1 达**(O1≈O2)→ 记录"更快重置足矣,学习先验非必要";器官降级为确定性 scaffold。
- 任何重设计走 ADR-0003;改 G5 判据属"挪门",需 founder 级 ADR。

## 6. 边界(继承 + P4 专属)

- **P4 v0 = 纯标准库学习型器官,无 LLM、无第三方依赖、无花钱、无真实执行器、单进程。**
- **LLM 器官 = P4.x**,触碰"LLM 进控制路径 + 花钱 + 依赖",需**独立 founder spend/dependency ADR**;
  本 ADR 不授权 LLM 变体。(即便届时引入,仍受 §2 接口约束:LLM 也只出 belief_delta/uncertainty/hint。)
- C6/C7 不可削弱;claim-2 硬停、RAP v0 封存不变;不重设计已封存机制。

## 7. 任务卡(G5 冻结后,**待 founder 放行落码**;先基线后器官)

| 卡 | 范围 | 验收 |
|---|---|---|
| T-P4.1 | `PriorOrgan` 接口 + `OrganAdvice` + 主体信念合并钩子(器官槽,默认 O0 关闭) | 确定性测试:advise 只进信念;O0 行为与现状逐位一致(回归);器官无 action/policy/shell 通路 |
| T-P4.2 | O1 确定性 scaffold 器官(surprise→更快重置/抬不确定度) | 确定性测试:漂移后重置可观测;不 import policy/shell |
| T-P4.3 | O2 学习型器官(跨 regime 自适应重收敛,纯标准库) | 确定性机制测试:自适应行为收敛、可复现 |
| T-P4.4 | G5 守卫测试(C6/C7)+ `experiments/prior_organ_g5.py`(O0/O1/O2,r-final) | C6/C7 零越界;逐种子表;`G5: MET/NOT MET` 如实写回 PROJECT_PLAN §5 + RR-0003 |

落码顺序:T-P4.1(接口+钩子,O0 回归)→ T-P4.2(O1)→ T-P4.3(O2)→ T-P4.4(G5 门)。
**每卡落码前需 founder 对本 ADR 的 G5 冻结点头(P4 launch 保留事项)。**

## T-P4.1 实现追记(2026-06-13)

已落地 `src/aac/prior_organ.py`、`Agent.prior_organ` 可选槽位与 `tests/test_prior_organ.py`。

- 新增 `PriorOrgan` / `OrganAdvice` / `BeliefSnapshot` / `merge_organ_advice()`。
- `prior_organ.py` 仅依赖标准库 + `world_model`;静态测试断言不 import `policy` / `shell`。
- `Agent` 默认 `prior_organ=None` 即 O0;O0 回归测试证明默认与显式 None 逐记录一致。
- 器官建议只在正常 policy 分支前合并到 action-outcome belief;pause、survival reflex、idle drives 优先级不变。
- 守卫测试覆盖:advice 字段不含 action/policy/shell/forbidden;belief snapshot 只读;boosted forbidden 动作仍被 `op_tighten`
  阻断;`op_pause` 时 organ 不被调用。
- 本片未实现 O1/O2,未跑 G5,未引入 LLM/第三方依赖/真实执行器。

## T-P4.1.1 epistemic 通道 + T-P4.2 O1 实现追记(2026-06-13,founder 批准两点后)

**T-P4.1.1(接口扩展,仍 belief-only,守 C6/C7)**:`OrganAdvice` 增 `uncertainty_delta:Mapping[int,float]`;
`merge_organ_advice` 增 `uncertainty[a]=max(0, uncertainty[a]+self_conf*udelta[a])`。无 action/policy/shell 字段;
器官仍不 import policy/shell。守卫测试覆盖新通道(应用/钳零/越界拒绝/双通道并用/空双通道 no-op)。

**机制核验(重要,写死于 `prior_organ_o1.py` 注释)**:在策略 `prag_w*mu+epis_w*uncertainty` 下,
**均匀抬高所有动作的 uncertainty 是 softmax 无操作**(各项加同一常数)。故 O1 必须做**联合重置**:
mu 衰减(去旧最优统治)+ uncertainty 复位向先验(令后续更新如新学)。uncertainty 单用无效、对旧最优甚至
反作用。这修正了 memo 对"抬不确定度"的朴素表述。

**T-P4.2 O1**:`ResetScaffoldOrgan`(surprise 尖峰 → 联合重置;EMA 估 surprise 尺度 + warmup);
`StalenessEnv`(非平稳 hazard:FAST period_fast~20 / SLOW period_slow~120 按 epoch 交替——否则 G5-2 假阴);
`experiments/o1_calibration.py`(在**不相交** calibration 种子上扫参选最强 O1,防稻草人)。

**Calibration 结果(env-validity 记录,冻结)**:种子 200–204(与 G5 的 0–9 不相交),1500 步,window=15。
O0 post-shift regret area = **1191.53**;8 组**全部跑赢 O0**;**冻结 O1 = {spike_k 1.5, reset_strength 0.5,
mu_decay 0.6}**,area = **1133.83**(优于 O0 约 4.8%)。增益温和——这正好把 O2 的门槛设实:O2 必须明显
超过这 ~5% 才算"学习型先验必要"(G5-2)。冻结参数已写入 `ResetScaffoldOrgan` 默认值,跑 G5 后不再调。

**262 测试绿**。本片未实现 O2、未建 G5 gate 实验、未跑 G5 verdict、无 LLM/依赖/花钱。下一片 T-P4.3 O2(需 founder 点头)。

## T-P4.3 O2 实现追记(2026-06-13,memo §3)

`AdaptiveHazardOrgan`(`prior_organ_o2.py`)。与 O1 **同形**(spike→联合重置:mu 衰减 + uncertainty 复位向先验),
唯一差别:`reset_strength` 与 `spike_k` 随**在线估计的切换 hazard τ̂**(已检测 inter-shift 间隔的 EMA)自适应:

- τ̂ 小(频繁)→ `reset_strength=clip(rs_c/τ̂)` 大、`spike_k` 小(激进 + 敏感);
- τ̂ 大(稀疏)→ reset_strength 小、spike_k 大(保守,不把噪声当 shift)。

**有意的设计性质(隔离"自适应"本身的价值)**:常数取 `rs_c=30, k_ref_tau=60`,使 τ̂≈60(平均 hazard)时
`reset_strength≈0.5`、`spike_k≈1.5` —— **正好等于 O1 的冻结值**。故 O2 在平均 hazard 处退化为 O1,**只在
fast/slow epoch 才偏离**。G5-2(O2<O1)因此干净地只测"按 hazard 自适应"是否有净增益。

**取舍**:v0 O2 **去掉了 memo §3 的 recovery 爬山项**(那是次要项,且从 belief 推断 recovery 时长不干净),
只保留 hazard→reset 的核心。recovery 反馈留作 O2.x 可能细化。

**纪律**:O2 常数为设计预设,**必须在 G5 r-final 前用不相交种子 calibration 冻结**(T-P4.4,镜像 O1),
跑 G5 后不调。belief-only、不 import policy/shell;advice 无 action/policy/shell 面;pause/tighten 回归测试通过。

13 测试(τ̂ 追踪 fast/slow、reset_strength/spike_k 自适应方向、平均 hazard 退化为 O1、联合重置、确定性、
可纠正回归)。**275 测试绿**。本片**未建 G5 gate 实验、未跑 G5 verdict、未冻结 O2 常数、无 LLM/依赖/花钱**。
下一片 **T-P4.4**:O2 calibration 冻结 + `experiments/prior_organ_g5.py`(O0/O1/O2,r-final)+ C6/C7 守卫测试(需 founder 点头)。
