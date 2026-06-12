# ADR-0004: AttentionField v1.1 — Surprise-triggered IP Reset

- Status: Accepted(再诊断,ADR-0003 协议流程,2026-06-12)
- Date: 2026-06-12
- Supersedes: ADR-0002 §Decision-T2(AttentionField v1 → v1.1,结构修订)

## Context

G1 实验(ADR-0002 §G1 结果)NOT MET。诊断定位到**注意力粘性陷阱**:
- `select_attention()` 纯确定性 top-m 排序;未被注意的线索 IP 永不更新。
- regime shift 后,旧 IP 锁定在旧相关线索上 → 新相关线索永远不在注意力窗口内
  → 恶性循环。
- 信息论分析表明 m=3 在 60 步 regime 内理论观测预算充足(每线索 ~15 次),
  但前提是注意力有效覆盖相关线索。**瓶颈不在学习率,在注意力分配。**

## 选项评审(ADR-0003 协议 §1-2)

| | A: Surprise IP reset | B: Adaptive LR | C: 混合 A+B |
|---|---|---|---|
| 解决粘性 | ✅ 直击根因 | ❌ 不治本 | ✅ |
| 参数风险 | 中(单参数可锚定) | 低 | 高(两参数) |
| 特判嫌疑 | 低 | 最低 | 最高 |

**最强反方论证**(对抗评审):
- A 风险:假阳性 reset 销毁有效 IP;冷启动后稳定排序偏向低 index。
- B 致命:unattended cues 永不更新,lr 再高无用。
- C 风险:n_eff≈1.5 的方差灾难 + 参数过拟合。

## Decision: 选项 A + 两项修正

### 修正 1: 动态阈值(防假阳性)

在 `AttentionField` 增加 surprise 滑动窗口,reset 触发条件:
`surprise > μ + 2.5 * max(σ, noise_floor)`。noise_floor=0.3(环境噪声下界)。
最少需 5 个样本才触发;两次 reset 间隔 ≥ 15 步(cooldown)。

### 修正 2: Reset 后短暂均匀窗口(防冷启动偏向)

reset 后 K/m 步(默认 4 步)内,`select_attention` 返回均匀轮转覆盖
(类似 A3),确保全部 K 个线索被观测一次。之后切回 IP-based 选择。

### 机制不变的部分(T2 结构约束依然成立)

- 相关性 = 注意力分配(IP 估计,top-m 选择)。
- 利用由模型自信门控,与饥饿解耦。
- pressure 只收缩注意力预算。

## G1 重跑预注册(G1-r)

**门判据与 ADR-0002 完全相同,一字不改**(不挪门柱)。
环境参数、对照体定义、种子范围均不变。
如 G1-r 仍 NOT MET → 诚实结论:IP 机制在该参数空间信息论不足,
走 ADR-0003 选项 2(升级问题难度)或选项 3(建议 founder 降级主张 2)。

## Consequences

- `AttentionField` v1 → v1.1(`on_surprise()` 新方法 + `select_attention` 修正)。
- `experiments/cue_shift.py` 增加 `on_surprise()` 调用。
- v1 代码可通过不设 surprise 输入完全回归(v1.1 向后兼容)。

## G1-r 实验结果(2026-06-12)

**G1-r: NOT MET**(诚实负结果)。

| 判据 | v1 结果 | v1.1 结果 |
|---|---|---|
| 1a regret vs A1 | 7/10 | **7/10** ✅ |
| 1a recovery vs A1 | 3/10 | 3/10 ❌ |
| 1b regret vs A3 | 5/10 | **6/10** |
| 1b recovery vs A3 | 3/10 | 3/10 ❌ |
| 2 budget > A2 | PASS | **PASS** ✅ |

**诊断观察**:
- IP reset 打破了注意力粘性陷阱(regret vs A3: 5→6/10)。
- 但 recovery 瓶颈在**世界模型重收敛**而非注意力分配:
  ActionOutcomeModel(lr=0.3)需 ~10 步收敛新映射,而 reset 后的 4 步均匀窗口
  仅提供观测,世界模型 mu 值仍基于旧 regime 的 EMA。
- 生存优势压倒性:modulated 1182 vs A1 482 vs A3 567。
- 代谢必要性确认:modulated budget 61.55 >> A2 38.01。

**下一步**:结构修订权已用。按 ADR-0002 协议走三选一,
记新 ADR(ADR-0005)。
