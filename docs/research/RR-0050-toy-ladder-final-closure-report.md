# RR-0050: Toy-Scale 能力阶梯研究 — 最终综合报告

> Date: 2026-07-05
> Status: CLOSED (research line complete)
> Branch: research/causal-world-model-2026-06-30
> Prior: RR-0048 (实验报告), RR-0049 (深化分析)
> Scope: autonomous-agent-core / object layer research

## 0. 摘要

14 个实验（EXP-J~W），5 个 Phase，16 条定理（T6~T16），在 D=6~8 的 toy causal-lever 环境中完整建立了：

1. **9 级能力阶梯**（Level 0~8）：从 random bandit 到 multi-agent specialization
2. **三层架构完备性证明**（Layer 1/2/3 缺一不可）
3. **GovernedLoop 映射验证**（toy MSCA ↔ production `governed_loop.py` 结构等价）
4. **两个可落地的工程修复**（BoundaryAwareReranker, T15/T16）

研究线在 toy scale 已经到顶。下一步需要跨越到 less-toy 验证（多维 state space / real LLM）。

---

## 1. 实验全景

| Phase | Experiments | Core Question | Key Finding |
|-------|------------|---------------|-------------|
| 1 | EXP-A~C | C7-off governance cost | C7 对能力无损; self-model 软约束不可信 |
| 2 | EXP-D~I | Isolation / HMAC / timing | Process isolation 必要; HMAC 不可绕过 |
| 3 | EXP-J~O | Individual capabilities | 7-level ladder established |
| 4 | EXP-P~S | Integration / adversary | Composition interference; MSCA capstone |
| 5 | EXP-T~W | Multi-agent / scale-up | +53% cooperation; GovernedLoop mapping |

---

## 2. 能力阶梯（最终版）

| Level | Capability | Mechanism | Key Metric |
|-------|-----------|-----------|-----------|
| 0 | Random bandit | Uniform sampling | Baseline regret |
| 1 | Rejection learning | Rejection memory + penalty | Convergence 8.7→0.4 rounds |
| 2 | Directed exploration | Thompson / UCB1 / InfoGain | Regret 41.9→2.8 |
| 3 | Typed feedback | Categorical rejection parsing | 95% fewer retries |
| 4 | Active causal discovery | do-calculus + targeted probing | 100% accuracy, 0 decoy |
| 5 | Non-stationarity | Windowed decay / change-point | Adapt in 0.9 rounds |
| 6 | VOI planning | Value-of-information probing | Selective allocation |
| 7 | Adversary modeling | Mirror adversary logic + avoid | +132% over naive |
| 8 | Multi-agent specialization | Decoy + exploit role split | +53% over single |

---

## 3. 定理汇总

| ID | Name | Statement | Evidence |
|----|------|-----------|----------|
| T6 | Cognitive-Governance Inverse | 更强认知 → 更少 Layer 2 触发 | EXP-K~O |
| T7 | Information Channel Directionality | Layer 2→3 单向 typed feedback (只读) | EXP-L |
| T8 | Causal-Verifier Equivalence | Active causal = internal verifier | EXP-M |
| T9 | Forgetting Necessity | Non-stationary 要求可遗忘层 | EXP-N |
| T10 | VOI-Safety Equivalence | Optimal probing = safe probing (此架构) | EXP-O |
| T11 | Safety-Capability Asymmetry | Adversary destroys capability, never safety | EXP-Q |
| T12 | External Verifier Necessity | Screening = efficiency (not just safety) | EXP-R |
| T13 | Adversarial Ceiling | Reactive adversary → single agent reward → 0 | EXP-Q |
| T13' | Multi-Agent Ceiling Lift | Specialized cooperation +53% | EXP-T |
| T14 | Architecture Completeness | 三层缺一不可 | EXP-S |
| T15 | Boundary-Awareness Necessity | Proposer MUST pre-filter forbidden + non-causal | EXP-W |
| T16 | Memory Staleness Hazard | Stale memory in governed loop is adversarial | EXP-W |

---

## 4. 架构映射（MSCA → GovernedLoop → Production）

```
MSCA (toy)                    GovernedLoop (code)              Production (future)
─────────────                 ──────────────────               ──────────────────
Layer 1: HMAC actuator    →   actuator.apply()             →   Signed execution endpoint
Layer 2: Integer gate     →   gate.decide() + shell_view   →   GovernedDecisionGate + C7
Layer 3: Cognitive policy →   proposer.rank()              →   LLM organ + CWM + beliefs
  ↳ boundary-aware        →   BoundaryAwareReranker        →   AgentSelfModel.denied_tools
  ↳ causal beliefs        →   (internal to proposer)       →   CWM world model
  ↳ adversary model       →   (internal to proposer)       →   Opponent modeling module
  ↳ memory                →   ActionMemory                 →   Belief ledger
```

**关键验证结果 (EXP-W):**
- GovernedLoop 安全性 = MSCA 安全性（ZERO breaches, unconditional）
- BoundaryAwareReranker reward > Direct agent reward（+46%）— loop's verifier = free causal info
- Standard MemoryReranker 在 non-stationary governance 下灾难性失败（199 vs 5310）

---

## 5. 可落地工程成果

### 5.1 BoundaryAwareReranker（已合入）

- **File**: `src/aac/governed_loop.py`
- **Tests**: `tests/test_governed_loop_slice.py::BoundaryAwareRerankerTests` (4 tests)
- **Fix**: Memory-known candidates 在 promote 前过滤 current forbidden set
- **Effect**: 从 199.2 → 5309.7 reward（26x improvement in governed loop efficiency）

### 5.2 Design Pattern for Proposer

任何 GovernedLoop proposer 必须：
1. 读 `self_model.denied_tools` **before** ranking
2. 将 currently-denied candidates 排到 `verify_budget` 之后（永远不会被触及）
3. 如果有 causal beliefs，优先排 high-confidence causal candidates

---

## 6. 研究线关闭理由

1. **到顶标志**：Level 8 (multi-agent) 是 toy bandit 的自然上限（再加能力需要 richer state）
2. **理论饱和**：16 条定理覆盖了 safety/capability/adversary/composition/scale-up 全维度
3. **Diminishing returns**：新实验在同一 D=8 环境中不会产生新的结构性洞察
4. **工程闭环**：发现 → 修复 → 测试 → 合入 完整走通（T15/T16 → BoundaryAwareReranker）
5. **Scale gap**：下一个有意义的问题需要跨越到 continuous state / LLM / real CWM

---

## 7. 限制声明（诚实边界）

1. 所有结论仅在 toy scale 有效（D=6~8, 20~30 seeds, 100~400 rounds）
2. "Adversary" 是简化模型（reactive/deceptive with known logic）— real adversaries 更复杂
3. "Causal discovery" 是 true interventional — real world 没有 free clean interventions
4. "Multi-agent" 假设 adversary 只能 ban 一个 lever — 不 scale to multi-target adversary
5. T14 (Architecture Completeness) 是 toy-scale 主张，不能直接声称 real-scale 完备
6. Anti-deception dual-model 依赖 "act rewards 不可篡改"（Layer 1 HMAC）— 如果物理层被破坏，定理失效
7. GovernedLoop mapping (EXP-W) 证明 structural equivalence，但 real LLM proposer 的 rank() 比 Thompson 复杂几个数量级

---

## 8. 下一步（研究线关闭后的方向）

### 8.1 D 方向：Less-Toy Verification

从 toy 到 less-toy 的自然路径：
- **Multi-dimensional state space**: lever → multi-feature decision (e.g. 20 features, combinatorial actions)
- **Partial observability**: agent 不能直接看到 all lever states
- **LLM-in-the-loop**: proposer 是 actual LLM call，not hand-coded Thompson
- **Real CWM**: causal model 是 learned (not given)，有 noise/lag

### 8.2 C 方向：OS Product Seam

T15/T16 对 OS 产品层的契约提案：
- **Contract**: `ProposerBoundaryContract` — proposer 必须实现 `update_boundaries(forbidden)` 接口
- **Enforcement**: GovernedLoop 在每次 `run_task` 前调用 `proposer.update_boundaries()` if available
- **Fallback**: 如果 proposer 不实现该接口，log warning + continue（backward compatible）

---

## 9. 文件清单

| File | Role |
|------|------|
| `experiments/c7_off_exp_j_rejection_learning.py` | EXP-J: Level 1 |
| `experiments/c7_off_exp_k_directed_exploration.py` | EXP-K: Level 2 |
| `experiments/c7_off_exp_l_rich_rejection.py` | EXP-L: Level 3 |
| `experiments/c7_off_exp_m_causal_discovery.py` | EXP-M: Level 4 |
| `experiments/c7_off_exp_n_nonstationary.py` | EXP-N: Level 5 |
| `experiments/c7_off_exp_o_multistep.py` | EXP-O: Level 6 |
| `experiments/c7_off_exp_p_integration.py` | EXP-P: Integration |
| `experiments/c7_off_exp_q_adversarial.py` | EXP-Q: Adversarial |
| `experiments/c7_off_exp_r_unified.py` | EXP-R: Unified agent |
| `experiments/c7_off_exp_s_msca.py` | EXP-S: MSCA capstone |
| `experiments/c7_off_exp_t_multiagent.py` | EXP-T: Multi-agent |
| `experiments/c7_off_exp_u_adversary_model.py` | EXP-U: Adversary model |
| `experiments/c7_off_exp_v_shaping.py` | EXP-V: Env shaping |
| `experiments/c7_off_exp_w_scaleup_verification.py` | EXP-W: Scale-up |
| `src/aac/governed_loop.py` | BoundaryAwareReranker (T15/T16 fix) |
| `tests/test_governed_loop_slice.py` | 4 new tests for BA-reranker |
| `docs/research/RR-0048-*` | Phase 3 report |
| `docs/research/RR-0049-*` | Phase 4+5 deepening analysis |
| `docs/research/RR-0050-*` | This closure report |
