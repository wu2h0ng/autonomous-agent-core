# ADR-0017: P4.x — richer prior(含 LLM 器官)+ 语义丰富环境 设计 + G6 预注册

- Status: **Proposed**(触碰保留事项:LLM 进控制路径作器官 + 花钱 + 第三方依赖 + env reset;**需 founder 批准方可落码**)
- Date: 2026-06-13
- 前置:RR-0005 §3 中心发现 + §6;ADR-0016(G5 NOT MET,器官接口与三体消融)。
- 纪律:contract-first。**G6 钉死前不写器官/环境机制代码;LLM 变体在 founder 未批 spend/dependency 前不接。**

## 1. Context:G5 的边界把"是否上 LLM"变成了"环境是否有结构"

G5 NOT MET 限定于**无语义结构的合成沙盒**——learned prior 无处发力(RR-0005 §3)。所以 P4.x 的命题不是
"LLM 让 agent 更聪明",而是:

> 在一个**有可迁移结构**的环境里,一个**只进 belief、不碰 policy/shell** 的 richer prior(先非 LLM 学习型,
> 后 LLM)能否可测地胜过廉价确定性重置 —— 且器官非主体(C6)、可纠正不削弱(C7)?

## 2. 关键设计:环境必须有"可迁移结构"

`StalenessEnv` 刻意无结构,这正是 G5 假阴的来源。P4.x 新环境(`structured_*`)必须让**先验能跨 regime 迁移**:
例如各 regime 共享一个隐组合结构 / 观测携带可泛化特征,使"已学到结构的先验"能在漂移后**比从零重学更快**
预测新 regime。**若环境无此性质,P4.x 无意义**(会重演 G5)。环境规格落 T-P4.x.1 时入本 ADR。

## 3. 三/四体消融(继承苦涩教训守卫)

共享同一主体,只换器官槽:**O0 无 / O1 廉价重置 / O2 学习型(纯标准库)/ O3 LLM 器官**。
O1/O2 是 LLM 必须打过的廉价/非 LLM 基线(防"LLM magic"故事化)。

## 4. 分阶段(把花钱挡在一道廉价证伪门之后)

- **T-P4.x.1**:`structured_*` 环境(可迁移结构)。
- **T-P4.x.2 + 门 G6a(无 LLM,不花钱)**:O2(学习型先验)在结构环境上胜 O0 **且** 胜 O1,≥7/10。
  - **G6a NOT MET → 不上 LLM**(若连学习型先验在有结构环境都打不过廉价重置,LLM 几乎必然也不行,省钱)。
- **T-P4.x.3 + 门 G6b(LLM 器官,需 founder spend/dependency ADR)**:仅当 G6a MET 才启动。
  O3 LLM 器官在同环境胜 O2,≥7/10。

## 5. G6 判据(预注册,跑前钉死)

```text
G6a O2 < O0 且 O2 < O1(结构环境上,学习型先验终于胜廉价),≥7/10 种子;r-final 预承诺。
G6b（条件 G6a MET）O3(LLM 器官) < O2,≥7/10。
G6-C6 器官非主体:LLM/学习器官仅出 belief_delta/uncertainty/counterfactual_hint;不碰 policy/shell(确定性测试)。
G6-C7 可纠正不削弱:pause/tighten 零越界(确定性测试)。
**Vafa 约束(LLM 专属)**:O3 以 world-model recovery / transition-consistency 评判,**不以自然语言说服力评判**。
```

## 6. 边界 / 保留事项

- **LLM 器官 = 花钱 + 第三方依赖 + LLM 进控制路径(作器官)= 三项保留事项**,需独立 founder spend/dependency ADR。
- env reset(换环境框架)也属研究路线重大变更,本 ADR 即其载体,**需 founder 批准生效**。
- C6/C7 永不削弱;claim-2/RAP/O2(旧 staleness 上的)硬停不变——P4.x 是新环境上的新实验,不是重开旧门。
- 非 LLM 的 T-P4.x.1/2(G6a)若 founder 单独放行,可先于 LLM 决策推进(它不花钱、不引依赖)。

## 7. NOT MET 处置(预先承诺)

- G6a NOT MET → "即便有结构,学习型先验仍不胜廉价重置";richer-prior 路线在本原型尺度封存,不上 LLM。
- G6a MET、G6b NOT MET → "LLM 不比廉价学习型先验更值";记录,LLM 器官不纳入。
- 任何重设计走 ADR-0003;改 G6 判据需 founder 级 ADR。

## T-P4.x.1/2 + G6a 结果(2026-06-13,agent 自决执行,无 LLM/无花钱)

founder 授权"自己拍板直接执行";我选了**零保留事项**的部分(结构环境 + 学习型器官 + G6a),
不碰 LLM/花钱/跨仓。

落地:`src/envs/structured_regime.py`(`StructuredRegimeEnv`:K 个**复现**的隐 regime 库 = 可迁移结构;
通过 `situation()` 暴露 last_action/last_reward 供 belief-only 器官读观测)、`src/aac/prior_organ_library.py`
(`RegimeLibraryOrgan`:从观测学 regime 原型,漂移后识别复现 regime 并把已知值注入 belief_delta;
只输出 belief 建议,不碰 policy/shell)、`experiments/structured_g6a.py`、`tests/test_structured_regime.py`。

O2 calibration(不相交种子 200–204):8 组全胜 O1;冻结 **{match_threshold 0.5, inject_weight 0.85}**。

**G6a r-final(种子 0–9,2000 步):** O0 **1384.8** / O1(廉价重置)**1332.0** / O2(学习型)**1269.3**。

| 判据 | 结果 |
|---|---|
| O2 < O0 | **10/10 ✓** |
| O2 < O1 | **9/10 ✓** |
| C6/C7 守卫 | tests 绿 |

**→ G6a MET。**

**这是本原型线第一次"学习型/richer 先验胜过廉价基线"。** 它**经验性地证实了 RR-0005 的论点**:G5(器官)
的失败不是"学习无用",而是**环境无结构可学**;一旦给出有可迁移结构(复现 regime 库)的环境,学习型器官
通过"识别复现 regime → 跳到已知值"显著快于廉价重置。中心发现因此被精确化:**不是"聪明输给廉价",
而是"聪明需要可被利用的结构"。**

**处置(ADR-0017 §4):G6a MET → G6b(LLM 器官)现在有理由考虑。但 G6b 触碰花钱 + 第三方依赖 + LLM
进控制路径(作器官)= 三项保留事项,我不在 autopilot 上启动——升级给 founder 决策。** 292 测试绿,
未引入 LLM/依赖/花钱。
