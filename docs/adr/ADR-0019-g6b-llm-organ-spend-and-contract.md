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

## 5. 待 founder(保留事项)

- **是否现在花钱跑 G6b**:我的诚实建议——**先建语义环境**(本身是一块实在的工作),否则在数字环境上
  跑 LLM 是浪费。语义环境就位 + 你给 key/budget 后,真实运行只差接一个 backend adapter(几十行)。
- key/budget/选型(provider+model snapshot)由你定;本仓不碰你的钱与密钥。

## 6. NOT MET 处置(预承诺)

- G6b NOT MET → "LLM 不比纯标准库学习器官更值";记录,不纳入 LLM 器官。
- 任何重设计走 ADR-0003;改 G6b 判据需 founder 级 ADR。
