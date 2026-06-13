# ADR-0019: G6b — LLM 器官 spend/dependency 契约 + 语义环境前提

- Status: **Accepted as contract**(founder 2026-06-13 "都做" 批准 G6b 方向);**实际付费运行待 founder 提供
  key + budget cap,且需语义环境就位**。
- Date: 2026-06-13
- 前置:ADR-0017(G6a MET:有结构时学习型先验胜廉价)。本 ADR 把 LLM 引入限定为 belief-only 器官,
  并把花钱挡在两道前提之后。

## 1. Context:G6a 已答核心问题,G6b 只问一个更窄的问题

G6a 已证"有可利用结构时,richer 学习先验值回成本"。G6b 问的更窄:**LLM 作为更 richer 的先验,
能否胜过纯标准库学习器官(O2)?** 这只有在 LLM 的**预训练知识有可迁移落点**时才可能。

**关键前提(agent 取证):当前 `StructuredRegimeEnv` 是数字 regime 库,无语义/语言结构——LLM 的广博先验
无处发力。在它上面跑付费 LLM 会烧钱证明 LLM≈O2。** 故 G6b **要求语义丰富环境**(文本/符号结构,
使预训练知识可迁移)。这是"聪明需要可利用结构"在更高一层:**LLM 需要语义结构,不只是统计复现。**

## 2. 契约(冻结)

- **LLM = belief-only 器官**:同 C6/C7 接口。LLM 原始输出**不可信**——器官 parser **只**抽取
  `belief_delta{int:float}` 与 `uncertainty∈[0,1]`,**丢弃一切其它字段**(action/policy/shell/forbidden 等)。
  即 **LLM 无论怎么乱来,都只能微调 belief,绝不能行动或碰罩**。
- **确定性可复现**(项目不变量):pin 模型快照 + `temperature=0` + **响应缓存/录制回放**,使 r-final 复现。
- **依赖隔离**:LLM adapter 为 optional extra,**core 仍纯标准库零依赖**;不引入即不可用,但不污染基底。
- **花钱有界**:budget cap 经 env 变量;key 经 env;**本仓不存 key**。
- **评判**(Vafa 约束):G6b 以 world-model recovery / transition-consistency 评判,**非自然语言说服力**。

## 3. G6b 门(预注册,跑前钉死)

```text
前提-1 语义环境就位(text/symbolic 可迁移结构)。
前提-2 founder 提供 key + budget cap。
G6b   O3(LLM 器官) < O2(纯标准库学习器官),≥7/10 种子;r-final 预承诺。
G6b-C6/C7 LLM 器官仅 belief-only(确定性测试:恶意响应被中和);pause/tighten 零越界。
```

## 4. 本片已落地(离线、零花钱、零依赖)

`src/aac/prior_organ_llm.py`:`LLMPriorOrgan`(strict parser:只收 belief_delta/uncertainty,丢弃其它)+
`LLMBackend` Protocol + `DeterministicStubBackend`(离线确定性)。守卫测试证明:**恶意 backend 返回
action/pause/forbidden 一律被中和,只剩 belief 微调**;不 import policy/shell;pause/tighten 回归通过。
**未引入真实 LLM、依赖、网络、花钱。**

## 4b. 前提-1 已就位 + 离线 de-risk(2026-06-13,founder "你先建语义环境")

**语义环境已建并验证可被语义知识利用——付费前先证它值得跑。**

- `src/envs/semantic_regime.py`:`SemanticRegimeEnv`。每个 regime = 一个语义类别
  (bird/vehicle/fruit/tool/fish);动作带**文字标签**;最优 = 标签属当前类别的那个。**每次漂移
  重随机标签↔位置**,故 position/recurrence 不携带信号——数字/位置学习器只能逐 regime 试错重学,
  唯有**读懂词义**(sparrow∈bird)的器官能零样本命中。这正是 LLM 预训练知识该发力、数字学习器发不了力处。
- `src/aac/semantic_oracle.py`:`SemanticOracleBackend` = **离线零花钱的语义 LLM 替身**(自带完美词知识=
  同一 TAXONOMY,从 prompt 读标签,与真 LLM 同路径)。它是**上界**("若器官懂词,环境会不会奖励它"),
  **不是 G6b 结论**;其输出经**同一 untrusted strict parser**,权限不高于任何 backend。
- `experiments/semantic_g6b_offline.py` 结果(seeds 0-9,steps 2000,post-shift regret area,越低越好):
  **O0 1960.0 / O1 1948.0 / O2 1910.0 / O3(oracle) 916.4**;**O3<O0 10/10、O3<O2 10/10**。
  三个数字器官(O0/O1/O2)互相难分=**确认数字/位置学习在此环境无效**;语义器官腰斩 regret。
  **结论:环境确为 semantic-exploitable → 真实 LLM 运行值得做。**(残余 ~30% regret = 策略探索,各臂共有,公平。)
- 仍**未**调用/未花钱/未引依赖;`ruff check` + 309 测试绿(新增 `tests/test_semantic_regime.py`)。
- **判据边界(诚实):** oracle 是完美知识上界,证的是"环境奖励语义",**不是**"真 LLM 的实际知识够用"——
  后者正是 §3 前提-2 的付费 r-final。oracle 不可冒充 LLM 结论。

## 5. 待 founder(保留事项)

- **前提-1(语义环境)已就位**(§4b),且离线已证它 semantic-exploitable。**现在只差前提-2:你给
  key + budget cap**,真实运行只剩接一个 backend adapter(实现 `LLMBackend.propose`,pin 模型+temp0+缓存,
  几十行)替换 `SemanticOracleBackend`,跑 §3 的 r-final 门。
- key/budget/选型(provider+model snapshot)由你定;本仓不碰你的钱与密钥。
- 我的诚实建议:跑前确认 budget cap 与缓存就绪(确定性可复现);oracle 已表明环境奖励语义,值得这次花钱。

## 6. NOT MET 处置(预承诺)

- G6b NOT MET → "LLM 不比纯标准库学习器官更值";记录,不纳入 LLM 器官。
- 任何重设计走 ADR-0003;改 G6b 判据需 founder 级 ADR。
