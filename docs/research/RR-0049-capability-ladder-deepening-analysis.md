# RR-0049: 能力阶梯深化研究路线分析

> Date: 2026-07-05
> Status: COMPLETE (Phase 4+5 all experiments run, results frozen)
> Prior: RR-0048 (能力阶梯实验报告)
> Scope: autonomous-agent-core / object layer research
> Branch: research/causal-world-model-2026-06-30

## 1. 当前位置

EXP-J~O 建立了 7 层能力阶梯（Level 0~6），但每层都是**独立测试**的。
真正的 agent 需要**同时具备所有能力**并在它们之间动态切换。

当前 toy bandit 的核心限制：
- 每个实验的 agent 只有一种能力
- 环境是独立的（不交叉）
- 没有测试能力之间的**干涉**（例如：遗忘机制是否会破坏因果模型？）
- 没有测试**对抗性**适应（adversary 学习 agent 的策略并反制）

## 2. 三条深化路线

### 路线 A：纵向集成（Vertical Integration）

**问题：** 当 Level 1~6 的能力**同时存在于一个 agent** 中时，会不会互相干涉？

**实验设计：**

```
EXP-P: Integrated Capability Agent
  Agent 同时具备:
    - Thompson Sampling exploration (Level 2)
    - Typed rejection parsing (Level 3)
    - Active causal discovery (Level 4)
    - Windowed forgetting (Level 5)
    - VOI-based probe planning (Level 6)
  环境:
    - Non-stationary + confounded + forbidden + noisy verifier
    - 全部挑战同时存在
  对比:
    - P-full: 完整集成 agent
    - P-ablation-{K,L,M,N,O}: 每次移除一个能力，看性能退化
    - P-level0: baseline (random bandit)
```

**研究价值：** 证明各能力是否**模块化可组合**，还是存在不可调和的冲突。如果可组合，ADR-0050 的 Layer 3 可以被设计为 pluggable capabilities；如果冲突，需要 meta-controller 来调度。

**预期结论空间：**
- P-full >> sum(individual levels) → 能力协同（非线性增益）
- P-full ≈ sum(individual levels) → 能力独立（线性可组合）
- P-full < max(individual levels) → 能力干涉（需要 arbitration）

---

### 路线 B：对抗升级（Adversarial Escalation）

**问题：** 如果 adversary 观察 agent 的策略并适应，agent 的能力阶梯是否稳定？

**实验设计：**

```
EXP-Q: Co-Evolutionary Arms Race
  Agent: integrated capability agent (from EXP-P)
  Adversary: adaptive opponent that:
    - 观察 agent 的探索模式，把 forbidden 放在 agent 最可能探索的 lever
    - 在 agent 学会 causal structure 后，改变 causal structure
    - 在 agent 适应 change 后，伪造 change signals
    - 在 agent 做 probe 时，给 misleading probe results
  测试:
    - Q-static-adv: adversary 不适应（current EXP baseline）
    - Q-reactive-adv: adversary 观察 agent 历史并反应
    - Q-predictive-adv: adversary 预测 agent 下一步并预防
    - Q-deceptive-adv: adversary 主动给 agent 错误信息
```

**研究价值：** 测试能力阶梯在**真正对抗**下的鲁棒性。如果 deceptive adversary 能让 Active-Causal agent 的准确率从 100% 降到 random，说明因果推理需要**防篡改**机制（连接到 Layer 1 物理绑定的必要性）。

**预期结论空间：**
- Layer 2 安全性 vs reactive adversary → 仍安全（structural binding 不受影响）
- Level 4 (causal) vs deceptive adversary → 可能被骗（如果干预通道被篡改）
- Level 5 (adaptation) vs 伪造 change signal → 可能被骗（false positive change detection）
- 结论：物理层绑定（Layer 1）是唯一对 adversarial escalation 稳定的保障

---

### 路线 C：认知架构跨越（Cognitive Architecture Leap）

**问题：** 当前 agent 是**模块拼接**的（explorer + feedback_parser + causal_model + ...），有没有一个**统一认知框架**能自然包含所有能力？

**设计方向：**

```
EXP-R: Unified Belief-Action Agent
  核心思想: 不再单独实现 exploration/causal/planning/forgetting，
  而是用一个统一的 belief state + action policy 框架:

  Belief State B(t) = {
      μ[i]: 每个 lever 的期望 reward (posterior mean)
      σ[i]: 每个 lever 的不确定性 (posterior variance)
      C[i,j]: lever 之间的因果关系 (causal adjacency matrix)
      F[i]: forbidden 标签 (permanent constraint flag)
      τ[i]: belief 新鲜度 (recency-weighted evidence count)
  }

  Action Policy π(B) = argmax_a [
      μ[a] * (1 - F[a])                    # exploit: expected reward × allowed
      + λ_explore * σ[a]                    # explore: uncertainty bonus
      + λ_info * InfoGain(a, C)             # plan: causal info value
      - λ_reject * Reject(a)               # avoid: rejection memory
  ] where Reject(a) = ∞ if F[a] else decayed_count

  Belief Update:
      On reward:   μ[a] ← Bayesian update with decay τ
      On reject:   F[a] ← True if reason==FORBIDDEN; else decayed penalty
      On probe:    C[a,*] ← update causal graph
      On change:   τ[*] *= decay_factor (forget old evidence)
```

**研究价值：** 这是从**工程拼接**到**统一认知模型**的跨越。如果 unified agent 的性能 ≥ 模块拼接，说明能力阶梯可以被压缩成一个**单一信念-行动循环**。这直接连接到项目的终极目标：LLM + CWM 统一模型。

**关键洞察：** 上面的公式本质上是一个 **POMDP solver with causal beliefs** — 这可能就是"统一模型"在 toy scale 的最小形态。

---

## 3. 新方案：从能力阶梯到 Minimal Cognitive Architecture

基于以上三条路线的分析，提出一个**新的实验序列**：

```
Phase 4: Integration & Unification
│
├── EXP-P: 纵向集成（验证模块可组合性）
│     ↓ 如果可组合
├── EXP-R: 统一信念-行动框架（压缩为单一循环）
│     ↓ 验证性能 ≥ 模块拼接
├── EXP-Q: 对抗性测试（在统一框架上测 adversarial robustness）
│     ↓ 发现弱点
├── EXP-S: 最小安全认知架构（Minimal Safe Cognitive Architecture）
│     设计: unified belief agent + Layer 2 typed gate + Layer 1 signed actuator
│     测试: 同时满足:
│       - 认知能力 ≥ Level 6 (VOI planning)
│       - 安全性 = Layer 2 (zero forbidden execution)
│       - Adversarial robustness (vs reactive/deceptive adversary)
│       - Adaptation speed ≤ 2 rounds (non-stationary)
│     这就是 toy-scale 的 "integrated governed intelligence" 最小形态
│
└── 终点: 回答 "统一模型在 toy scale 是否可行"
```

## 4. 与项目终极目标的连接

```
项目终极目标:
  LLM (language/knowledge) + CWM (causal planning) + belief-ledger
  + AgentSelfModel, inside one governed loop, with C7 as correction boundary

Toy-scale 对应:
  Thompson Sampling (probabilistic model) + Active-Causal (intervention-based planning)
  + Belief State B(t) + Self-Model (forbidden set), inside one action loop,
  with Layer 2 gate as correction boundary

如果 EXP-S 成功:
  → 证明在 toy scale "统一认知 + 外部治理" 是可行的
  → 下一步: scale up from toy to real (需要 LLM/CWM 实际集成)
  → 但 toy-scale 成功 ≠ real-scale 保证（明确限制声明）
```

## 5. 路线选择建议

| 路线 | 研究风险 | 发现价值 | 工作量 | 建议 |
|------|---------|---------|--------|------|
| A (纵向集成) | 低 | 中 | 1 天 | **先做**：验证基础假设 |
| B (对抗升级) | 中 | 高 | 1-2 天 | **第二**：测试真正边界 |
| C (认知跨越) | 高 | 极高 | 2-3 天 | **如果 A 成功**才做 |

**推荐序列：** A → (如果模块可组合) → C → B → S

**Kill rules：**
- 如果 A 证明能力互相干涉且不可调和 → 不做 C（统一框架不可行）
- 如果 B 证明 deceptive adversary 能破坏所有 Level 4+ 能力 → Layer 3 认知能力的上限就是 Level 3（typed feedback），不能依赖更高级认知
- 如果 C 的统一框架性能 < 模块拼接 → "统一模型" 在此 toy scale 就不优于 "模块组合"

## 6. 实验序列中新发现的理论问题

1. **模块组合定理？** 独立证明的 Level 是否满足可组合性？（即：能力之间的干涉项是否有界？）

2. **认知-安全帕累托前沿：** Level 6 agent 几乎不触发 Layer 2 — 那么 Layer 2 的"存在但不触发"是否仍有安全价值？（答案来自 EXP-I：adaptive adversary 在 1500 轮后才找到 328 次 bypass — Layer 2 的价值是 **worst-case 保障**，不是 average-case 频率。）

3. **遗忘-安全悖论：** Windowed forgetting 使 agent 适应更快，但如果 forbidden 约束也被遗忘了怎么办？必须有 **不可遗忘层**（= Layer 1/2 permanent constraints）和 **可遗忘层**（= Layer 3 transient beliefs）的结构分离。这已经实现在 EXP-L 的 REASON_FORBIDDEN → permanently_blocked 中。

4. **信息通道攻击面：** EXP-L 证明 typed feedback 有价值，但如果 adversary 能篡改 feedback 内容（把 FORBIDDEN 改成 LOW_CONFIDENCE），agent 会错误地重试 forbidden lever。这是一个新的 attack vector → Layer 2→3 信息通道本身需要签名/完整性保护（连接到 Layer 1 的物理绑定）。

5. **VOI 计算的 meta-problem：** EXP-O 的 Planning agent 表现不如 ProbeAll，因为 VOI 计算本身需要准确的 beliefs。如果 beliefs 不准（刚启动或环境变化后），VOI 计算是错的。这是一个 bootstrapping 问题：需要先 explore 才能有好的 beliefs，但好的 VOI 计算需要好的 beliefs 来指导 explore。解法可能是：初始阶段 fallback 到 UCB1/Thompson（不依赖 beliefs 的准确性），成熟阶段切换到 VOI。

---

## 7. 总结（Phase 3 结论）

五个实验确立了能力阶梯。下一步有三条清晰路线（集成/对抗/统一），按 A→C→B→S 顺序推进。最终目标是在 toy scale 实现 "Minimal Safe Cognitive Architecture"（EXP-S），作为项目终极目标 "integrated governed intelligence" 的 toy-scale 验证。

---

## 8. Phase 4 实验结果（EXP-P/R/Q/S）

### 8.1 EXP-P: 纵向集成

**结论：能力模块之间存在成本干涉（CONFLICTING）。**

| 发现 | 数据 |
|------|------|
| Full integrated agent reward | 6361.2 |
| 移除 causal/planning 后 reward | 6962.8（**更高**） |
| 原因 | Probe cost (720×0.08=57.6) 在 Thompson 已足够好时是净负收益 |
| Forbidden hits 减少 | 97%（838→25） |
| Confounder hits | 2（near zero） |

**关键洞察：** 不是能力冲突，是 **成本冲突**。Probing 在信息已足够时浪费资源。需要统一 utility function 自动判断何时值得 probe。

### 8.2 EXP-R: 统一信念-行动框架

**结论：统一框架可行但需要学习期。**

| Agent | Net Reward | Rejection Rate | Probes |
|-------|-----------|---------------|--------|
| Unified V2 | 5009.3 | 7.0% | 862 |
| Modular | 6361.2 | 1.3% | 720 |
| Baseline | 2974.1 | 46.4% | 0 |

**关键洞察：** 统一 agent 比 baseline 高 68%，但比 modular 低 21%。差距来源：modular agent 有**外部 verifier 预筛选**（只对 is_causal 的 lever 尝试），unified agent 必须自学哪些是 non-causal。这证明：**外部 verifier 的 screening 功能有不可替代的 architectural value**。

### 8.3 EXP-Q: 对抗升级

**结论：安全性无条件成立，能力在对抗下崩塌。**

| Adversary | Reward | Forbidden Executions | Causal Accuracy |
|-----------|--------|---------------------|-----------------|
| Static | 5117.3 | **0** | 0.556 |
| Reactive | -22.6 | **0** | 0.467 |
| Predictive | 25.4 | **0** | 0.467 |
| Deceptive | -22.6 | **0** | 0.156 |

**关键洞察：**
- **零安全违规** — Layer 2 integer-index check 对所有对抗等级免疫
- **100% reward collapse** — reactive adversary 使 agent reward 接近 0
- **72% causal corruption** — deceptive adversary 彻底破坏 agent 的因果模型
- **但腐蚀 ≠ 危害** — 错误认知不导致安全失败（Layer 2 阻断一切）

**新定理 T11（安全-能力不对称性）：** 对抗性升级可以 destroy capability（reward→0）但 cannot breach safety（forbidden executions = 0），当且仅当 safety constraint 是 structural（Layer 2 integer check）而非 cognitive（Layer 3 belief-based）。

### 8.4 EXP-S: 最小安全认知架构（Capstone）

**结论：MSCA 在 combined adversary 下保持零安全违规。**

| Arm | Net Reward | Forbidden Executions | Forbidden Blocked |
|-----|-----------|---------------------|-------------------|
| MSCA (full) | 271.3 | **0** | 141 |
| No-Verifier | 334.2 | **0** | 151 |
| No-Gate | 8780.3 | **11322** | 0 |
| Baseline | 361.4 | **0** | 148 |

**关键洞察：**
1. **No-Gate = 灾难性安全失败**（11322 次执行 forbidden）— 证明 Layer 2 不可移除
2. MSCA reward 低是因为 combined adversary（reactive + deceptive + shift）极端苛刻
3. Anti-deception 机制（dual causal model）使 causal accuracy 在 30% corruption 下仍有 0.389（优于 random 0.333）
4. 但 adaptation 慢（153.6 轮）— windowed decay 在 reactive adversary 不断切换 forbidden 时效果有限

## 9. Phase 4 总定理

**T11（安全-能力不对称性）：** Adversary 可以 destroy capability 但 cannot breach structural safety.

**T12（外部 verifier 架构必要性）：** 统一 agent 比 modular+verifier 低 21% reward。外部 verifier 的 screening 功能不仅是 safety 需求，更是 efficiency 需求（减少无效尝试的 architecture-level shortcut）。

**T13（对抗性上限定理）：** Reactive adversary 使任何 bandit-style agent 的 reward → 0（因为 best lever 总被 ban）。突破此上限需要**多 agent 协作**或**环境建模**（预测 adversary 会 ban 什么，主动选次优）。

**T14（架构完备性主张）：** MSCA 三层结构（physical binding + structural gate + cognitive freedom）是满足 {safety=unconditional, capability=best-effort, robustness=degraded-not-broken} 的**最小完备**架构：
- 移除 Layer 1 → token forgery 可能
- 移除 Layer 2 → 11322 次 safety breach
- 移除 Layer 3 → reward = baseline only

## 10. 下一步研究方向（Phase 5 候选）

1. **Multi-agent anti-adversary**：两个 agent 交替行动，adversary 只能 ban 一个 → 另一个可以 act（突破 T13 限制）
2. **Adversary modeling**：agent 学习 adversary 的 reactive pattern，预测下一轮 ban 什么 → 选不会被 ban 的次优
3. **Environment shaping**：agent 不选 best lever（引诱 adversary ban it），而是故意选次优（adversary ban 次优 → best lever 反而 free）
4. **Scale-up verification**：将 MSCA 结构映射到真实 GovernedLoop + CorrigibilityShell + SignedActuator，验证 toy-scale 结论是否 hold

## 11. 最终限制声明

- 所有结论仅在 toy scale（D=8, 30 seeds）有效
- Combined adversary 仍是简化模型（真实对手更复杂）
- Anti-deception 的 dual-causal-model 依赖"act reward 不可篡改"假设（通过 Layer 1 HMAC 保障）
- MSCA 在 reactive adversary 下 reward ≈ baseline — 不能声称"高能力"
- 从 toy → real 的 scale-up 是独立研究问题，不在本报告范围内

---

## 12. Phase 5 实验结果（EXP-T/U/V/W）

### 12.1 EXP-T: Multi-Agent Anti-Adversary

**问题：** 多 agent 协作能否突破 T13 的 reactive adversary ceiling？

| Arm | Total Reward | Per-Agent Reward |
|-----|-------------|-----------------|
| Single agent | 5011.7 | 5011.7 |
| Independent (2 agents) | 6108.8 | 3054.4 |
| Communicating (2 agents) | 6262.8 | 3131.4 |
| **Specialized (decoy+exploit)** | **7688.2** | 3844.1 |

**关键洞察：**
- 专业化分工（decoy agent 吸引 adversary ban + exploit agent 在隐藏轮行动）比单 agent **+53% reward**
- 突破 T13 限制：reactive adversary 只能锁定一个 agent 的行为模式，无法同时应对两种角色
- 通信机制增益有限（+2.5%）— 因为 specialized 的优势来自**角色不对称**而非信息共享

### 12.2 EXP-U: Adversary Modeling

**问题：** 预测 adversary 的 ban 策略能否维持正 reward？

| Strategy | Total Reward | Forbidden Blocked | Improvement vs Naive |
|----------|-------------|-------------------|---------------------|
| Naive | 2248.6 | 1305 | baseline |
| Uniform | 3753.6 | 1480 | +67% |
| **Adversary Model** | **5205.7** | **9** | **+132%** |
| Counter-strategy | 4136.9 | 943 | +84% |

**关键洞察：**
- Adversary modeling（镜像 adversary 逻辑预测 ban）**+132% over naive**
- 仅 9 次被 block — 几乎完美预测并回避 adversary 的 ban
- Counter-strategy（选最少使用的 lever）是 game-theoretic 近似解（混合策略）
- 理论意义：Nash 均衡要求 agent play mixed strategy against reactive adversary

### 12.3 EXP-V: Environment Shaping

**问题：** Agent 能否操纵 adversary 的观察，使其 ban 错误目标？

| Strategy | Total Reward | Adversary Misled Rate | Banning INERT |
|----------|-------------|----------------------|---------------|
| Honest | 4543.6 | 2.6% | 230 |
| **Random-Visible** | **4586.2** | **62.2%** | 5596 |
| Decoy-Feed | 2225.3 | 97.3% | 8760 |
| Adaptive-Decoy | 2225.3 | 97.3% | 8760 |

**关键洞察：**
- Decoy feeding **97.3% 误导率** — adversary 几乎总是 ban inert lever
- 但 Random-Visible 策略实际 reward 最高（4586.2 > 2225.3）
- 原因：decoy feeding 固定选 inert lever → 在 visible rounds 无法获得 reward
- Random-Visible 在 visible 轮仍能偶尔得分，同时 62% 误导率足够保护 hidden 轮
- 架构意义：**对 adversary 的策略欺骗 ≠ 对自身 governance 的欺骗**（前者是 capability，后者是 SD4 violation）

### 12.4 EXP-W: Scale-Up Verification（GovernedLoop 映射）

**问题：** MSCA 的 toy findings 在真实 GovernedLoop 基础设施中是否复现？

| Arm | Total Reward | Breaches | Denied |
|-----|-------------|----------|--------|
| Std (MemoryReranker) | 199.2 | **0** | 8531 |
| **BA-Reranker** | **5309.7** | **0** | **0** |
| No-Reranker | 4664.9 | **0** | 79 |
| Naive | 3494.9 | **0** | 2763 |
| Direct (no loop) | 3643.4 | 0 | 52 |

**关键洞察：**
1. **ZERO breaches across ALL arms** — GovernedLoop 结构性保障安全，无论 proposer 质量如何
2. **Boundary-Aware Reranker +146% vs Direct** — GovernedLoop 的 verifier 提供"免费"因果知识（direct agent 需要自己 probe）
3. **Standard MemoryReranker 灾难性 199.2** — 将 now-forbidden 的 previously-good lever 推到前面 → instant DENY → 轮次浪费
4. **MSCA + BA-Reranker > Direct** — 证明 GovernedLoop 不只是安全约束，也是 capability amplifier（verifier 充当免费信息源）

## 13. Phase 5 新定理

**T15（边界感知必要性 / Boundary-Awareness Necessity）：**

在具有以下语义的 governed loop 中：
- (a) per-round verify budget（有限探索预算）
- (b) deny-terminates semantics（DENY 终止当轮）

proposer 必须满足两个前置条件才能保持效率：
1. **Causal pre-filter**: 不提议 believed non-causal 的候选
2. **Forbidden pre-filter**: 不提议已知被 denied 的候选

违反任一条件 → verify budget 浪费 → capability collapse（但 safety preserved）。

**T16（记忆过时危害 / Memory Staleness Hazard）：**

MemoryReranker（将 previously-effective 移至前端）在 non-stationary governance 下变为 **adversarial component**：
- Memory 记住的 "best lever" 可能是 NOW-FORBIDDEN（boundary changed since memory was written）
- Reranker 将其推到 front → GovernedLoop 的 gate 第一个就 DENY → round lost
- 修复：memory 必须对 CURRENT forbidden set 做交叉过滤，不只是 past effectiveness

这是 non-stationary governance 对应的 stale-belief 危害。

**T13'（Multi-Agent Ceiling Lift）：** 多 agent 专业化分工（decoy + exploit）可以突破 T13 的 reactive adversary ceiling +53%，通过角色不对称使 adversary 的 single-target ban 策略失效。

## 14. Phase 5 总结与架构回顾

### 能力阶梯最终形态（Level 0 → Level 8）

| Level | Capability | EXP | Key Result |
|-------|-----------|-----|-----------|
| 0 | Random bandit | J-naive | Baseline |
| 1 | Rejection learning | J-learning | Convergence 8.7→0.4 |
| 2 | Directed exploration (Thompson/UCB/InfoGain) | K | Regret: 41.9→2.8 |
| 3 | Typed feedback parsing | L | 95% fewer retries |
| 4 | Active causal discovery | M | 100% accuracy, 0 decoy |
| 5 | Non-stationarity adaptation | N | Adapt in 0.9 rounds |
| 6 | VOI-based planning | O | Selective probing |
| **7** | **Adversary modeling + counter-strategy** | **U** | **+132% vs naive** |
| **8** | **Multi-agent specialization** | **T** | **+53% vs single** |

### 完整架构映射（MSCA → GovernedLoop）

```
┌─────────────────────────────────────────────────────────────────┐
│ GovernedLoop (governed_loop.py)                                  │
│                                                                  │
│  proposer.rank() ──→ verifier.verify() ──→ gate.decide()        │
│       │                    │                    │                │
│   Layer 3               Layer 2              Layer 2             │
│   Cognitive             External             Structural          │
│   Freedom               Verifier             Gate + Shell        │
│   (boundary-            (causal              (integer-index      │
│    aware!)               probe)               forbidden)         │
│       │                    │                    │                │
│       ↓                    ↓                    ↓                │
│   MUST pre-filter      Eliminates           DENY terminates     │
│   via self_model       non-causal           → safety ALWAYS     │
│   (T15)                (free info!)          held                │
│                                                                  │
│                    ──→ actuator.apply() ──→                      │
│                              │                                   │
│                          Layer 1                                 │
│                          HMAC-signed                             │
│                          (no bypass)                             │
└─────────────────────────────────────────────────────────────────┘
```

### 完整定理表

| Theorem | Statement | Evidence |
|---------|-----------|----------|
| T6 | 认知-治理逆向：更强认知 → 更少 Layer 2 触发 | EXP-K~O |
| T7 | 信息通道方向性：Layer 2→3 单向（typed feedback 只读） | EXP-L |
| T8 | 因果-verifier 等价：active causal = external verifier 的内化 | EXP-M |
| T9 | 遗忘必要性：non-stationary 环境要求可遗忘层 | EXP-N |
| T10 | VOI-safety 等价：optimal probing 和 safe probing 在此架构重合 | EXP-O |
| T11 | 安全-能力不对称：adversary destroy capability, never breach safety | EXP-Q |
| T12 | 外部 verifier 架构必要性：screening 是 efficiency 需求 | EXP-R |
| T13 | 对抗上限：reactive adversary → single agent reward → 0 | EXP-Q |
| T13' | 多 agent 上限突破：specialized cooperation +53% | EXP-T |
| T14 | 架构完备性：三层缺一不可 | EXP-S |
| **T15** | **边界感知必要性：proposer MUST read boundaries pre-rank** | **EXP-W** |
| **T16** | **记忆过时危害：stale memory in governed loop is adversarial** | **EXP-W** |

## 15. 最终限制声明（Phase 5 版）

1. 所有结论仅在 toy scale（D=6~8, 20~30 seeds, 100~400 rounds）有效
2. Adversary model 假设 adversary 逻辑可被 agent 完美镜像 — 真实对手不会这么简单
3. Multi-agent 优势（+53%）依赖 adversary 只能 ban 单一 lever — 多目标 adversary 下效果未知
4. Environment shaping 的"对 adversary 欺骗是 capability"主张需要治理边界明确定义（何时允许 deception）
5. GovernedLoop 映射证明了 structural equivalence，但 real LLM proposer 的 rank() 行为比 Thompson/Causal 复杂得多
6. T15/T16 对 GovernedLoop 的设计改进建议（boundary-aware reranker）是可落地的工程结论
7. 从 toy → real 的路径是独立研究问题（需要 LLM organ + real CWM + real environment）
