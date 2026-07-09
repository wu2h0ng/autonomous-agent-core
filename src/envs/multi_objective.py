"""MultiObjectiveEnv — regime-shifting environment with decomposable metric signals.

Each step produces a vector of K independent metric signals, one per action.
A regime defines the ground-truth importance (weight) of each metric. The agent's
scalar reward is the dot product of its adopted weight vector and the metric vector
of the chosen action.

STRATEGY = weight vector (simplex Δ^{K-1}). Changing the strategy does NOT change
which action is optimal — it changes what "optimal" MEANS. The action space remains
N discrete actions; the strategy space is continuous.

The LLM organ reads a noisy situation vector (hints at the current regime) and
proposes a weight vector. The gate decides whether to adopt it. The G10 policy
still picks actions through confidence-gated belief updates.

This is the G11 environment: two-layer decision — LLM proposes WHAT MATTERS,
G10 chooses HOW TO ACT.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field


@dataclass
class _Regime:
    """One regime in the fixed library: reward vectors per action and ground-truth weights."""

    action_rewards: list[list[float]]  # [action][metric]
    true_weights: list[float]          # [metric]
    metric_names: list[str]            # e.g. ["流量", "转化率", "客单价"]
    phase_label: str                   # "拉新期" | "收割期" | "利润期"


class MultiObjectiveEnv:
    """Regime-shifting env with K metric dimensions and strategy=weight-vector.

    Constructor generates a fixed library of M regimes. At step boundaries, the
    regime shifts to a different one from the library (recurrence = exploitable
    structure). The agent's scalar reward per step is::

        Σ(weights[k] × action_reward[k]) + noise
    """

    def __init__(
        self,
        n_actions: int = 8,
        n_metrics: int = 3,
        n_regimes: int = 4,
        period: int = 50,             # shorter -> more shifts -> LLM has more chances
        noise: float = 0.2,
        reward_low: float = -1.0,
        reward_high: float = 4.0,
        rng: random.Random | None = None,
        metric_names: list[str] | None = None,
        phase_labels: list[str] | None = None,
    ) -> None:
        if n_actions <= 0 or n_metrics <= 1 or n_regimes <= 1 or period <= 0:
            raise ValueError("n_actions>0, n_metrics>1, n_regimes>1, period>0")
        self.n_actions = n_actions
        self.n_metrics = n_metrics
        self.n_regimes = n_regimes
        self.period = period
        self.noise = noise
        self.rng = rng if rng is not None else random.Random()

        if metric_names is None:
            metric_names = ["流量", "转化率", "客单价"]
        if phase_labels is None:
            phase_labels = ["拉新期", "收割期", "利润期", "均衡期"]

        # Fixed distinct regimes: each regime has ONE dominant metric at ~0.8
        regime_templates: list[tuple[list[float], str]] = [
            ([0.80, 0.10, 0.10], "拉新期"),   # 流量为王
            ([0.10, 0.80, 0.10], "收割期"),   # 转化为王
            ([0.10, 0.10, 0.80], "利润期"),   # 利润为王
            ([0.34, 0.33, 0.33], "均衡期"),   # 均匀
        ]

        self._library: list[_Regime] = []
        for m in range(min(n_regimes, len(regime_templates))):
            true_w, phase = regime_templates[m]
            # Each action has random per-metric rewards, but the dominant metric
            # is consistently high across actions
            action_rewards: list[list[float]] = []
            for a in range(n_actions):
                row: list[float] = []
                for k in range(n_metrics):
                    if k == true_w.index(max(true_w)):
                        # Dominant metric: higher mean
                        row.append(self.rng.uniform(1.0, reward_high))
                    else:
                        row.append(self.rng.uniform(reward_low, 1.5))
                action_rewards.append(row)
            self._library.append(_Regime(
                action_rewards=action_rewards,
                true_weights=list(true_w),
                metric_names=list(metric_names),
                phase_label=phase,
            ))

        self._current: int = 0
        self.t: int = 0
        self.regime_index: int = 0
        self.last_regret: float = 0.0
        self.just_shifted: bool = False
        self.last_action: int | None = None
        self.last_reward: float | None = None
        self.last_metric_vector: list[float] | None = None
        # Running window for situation reporting
        self._history: list[dict] = []
        self._history_max: int = 40

    @property
    def _regime(self) -> _Regime:
        return self._library[self._current]

    @property
    def true_weights(self) -> list[float]:
        """Ground-truth importance weights (oracle-only)."""
        return list(self._regime.true_weights)

    @property
    def phase_label(self) -> str:
        return self._regime.phase_label

    def best_action_given(self, weights: list[float]) -> int:
        """Best action under the given weight vector and current regime."""
        return max(
            range(self.n_actions),
            key=lambda a: sum(
                w * self._regime.action_rewards[a][k]
                for k, w in enumerate(weights)
            ),
        )

    @property
    def best_action_oracle(self) -> int:
        """Best action under the ground-truth weights."""
        return self.best_action_given(self.true_weights)

    def expected_random_regret(self, weights: list[float] | None = None) -> float:
        """Scoring use: max action minus mean action under given weights."""
        w = weights if weights is not None else self.true_weights
        values = [
            sum(w[k] * self._regime.action_rewards[a][k] for k in range(self.n_metrics))
            for a in range(self.n_actions)
        ]
        return max(values) - sum(values) / self.n_actions

    def situation(self) -> dict:
        """Rich contextual history for LLM regime inference.

        Provides:
        - Natural language description of current state
        - Per-action reward summary (LLM can infer which metric dominates)
        - Recent reward trend by action
        - Transition detection flags
        """
        recent = self._history[-40:] if self._history else []
        description = self._build_textual_description()

        # Per-action reward stats over recent window
        action_rewards: dict[int, list[float]] = {}
        for h in recent:
            a = h["action"]
            action_rewards.setdefault(a, []).append(h["reward"])

        action_summary = {}
        for a, rewards in sorted(action_rewards.items()):
            if rewards:
                action_summary[a] = {
                    "count": len(rewards),
                    "mean": round(sum(rewards) / len(rewards), 2),
                    "trend": "上升" if len(rewards) >= 5 and sum(rewards[-5:])/5 > sum(rewards[:5])/5 + 0.2
                        else "下降" if len(rewards) >= 5 and sum(rewards[-5:])/5 < sum(rewards[:5])/5 - 0.2
                        else "稳定",
                }

        # Track "best action" shifts to detect regime changes
        if len(action_summary) >= 3:
            best_now = max(action_summary, key=lambda a: action_summary[a]["mean"])
            older = [h for h in self._history[-40:-20]] if len(self._history) >= 20 else []
            older_action_rewards: dict[int, list[float]] = {}
            for h in older:
                older_action_rewards.setdefault(h["action"], []).append(h["reward"])
            if older_action_rewards:
                best_old = max(older_action_rewards, key=lambda a: sum(older_action_rewards[a])/len(older_action_rewards[a]))
            else:
                best_old = best_now
        else:
            best_now = best_old = 0

        return {
            "description": description,
            "step": self.t,
            "just_shifted": self.just_shifted,
            "action_summary": action_summary,
            "best_action_shifted": best_now != best_old,
            "best_action_now": best_now,
            "best_action_before": best_old,
        }

    def _build_textual_description(self) -> str:
        """Generate a natural-language business observation from numeric signals."""
        reg = self._regime
        recent = self._history[-20:] if self._history else []
        recent_rewards = [h["reward"] for h in recent[-15:]] if recent else []
        avg_reward = sum(recent_rewards) / len(recent_rewards) if recent_rewards else 0.0

        older_rewards = [h["reward"] for h in self._history[-30:-15]] if len(self._history) >= 30 else recent_rewards
        older_avg = sum(older_rewards) / len(older_rewards) if older_rewards else avg_reward
        reward_trend = avg_reward - older_avg

        recent_actions = [h["action"] for h in recent[-10:]] if recent else []
        action_stability = len(set(recent_actions)) / max(1, len(recent_actions)) if recent_actions else 1.0

        parts = []
        if avg_reward > 2.5:
            parts.append("近期整体业绩表现强劲")
        elif avg_reward > 1.0:
            parts.append("近期整体业绩处于正常水平")
        elif avg_reward > 0.0:
            parts.append("近期整体业绩略显疲软")
        else:
            parts.append("近期整体业绩处于亏损状态")

        if reward_trend > 0.5:
            parts.append("奖励呈明显上升趋势")
        elif reward_trend > 0.1:
            parts.append("奖励略有回升")
        elif reward_trend < -0.5:
            parts.append("奖励出现显著下滑")
        elif reward_trend < -0.1:
            parts.append("奖励小幅走低")
        else:
            parts.append("奖励趋势平稳")

        if action_stability < 0.4:
            parts.append("代理在不同动作间频繁切换")
        elif action_stability < 0.7:
            parts.append("代理已在少数几个动作上收敛")
        else:
            parts.append("代理已高度聚焦于单一动作")

        hints = self._regime_hints(reg)
        if hints:
            parts.append(hints)

        if self.just_shifted:
            parts.append("⚠️ 刚刚检测到市场环境发生重大变化")

        return "。".join(parts) + "。"

    def _regime_hints(self, reg: _Regime) -> str:
        """Generate clear regime-specific business hints from true weights."""
        w = reg.true_weights
        if w[0] > 0.7:
            return "市场信号明确指向用户增长：新用户注册量激增，各渠道投放ROI持续上升，这是典型的流量红利窗口，团队共识是抢量优先"
        if w[1] > 0.7:
            return "市场信号明确指向转化效率：流量成本上升但转化率显著改善，老客复购率提升，精细化的用户运营和成交效率成为当前核心KPI"
        if w[2] > 0.7:
            return "市场信号明确指向利润导向：客单价稳步提升，高价品动销率走高，用户对价格敏感度下降，提升利润率比扩大规模更重要"
        return "市场信号较为混杂，没有明确的单一指标占主导地位，各维度指标权重较为均衡"

    def recent_history(self, n: int = 20) -> list[dict]:
        """Last n steps of (action, reward) history."""
        return self._history[-n:] if self._history else []

    def act(self, action: int, weights: list[float]) -> float:
        """Execute action under the given weight vector.

        Returns scalar reward = Σ(weights[k] × metric_signal[k]) + noise.
        """
        reg = self._regime
        metric_vec = [
            reg.action_rewards[action][k] + self.rng.gauss(0.0, self.noise)
            for k in range(self.n_metrics)
        ]
        reward = sum(w * metric_vec[k] for k, w in enumerate(weights))
        reward += self.rng.gauss(0.0, self.noise * 0.1)

        oracle_best = max(
            sum(w * reg.action_rewards[a][k] for k, w in enumerate(weights))
            for a in range(self.n_actions)
        )
        current_value = sum(w * reg.action_rewards[action][k] for k, w in enumerate(weights))
        self.last_regret = oracle_best - current_value

        self.last_action = action
        self.last_reward = reward
        self.last_metric_vector = [round(v, 4) for v in metric_vec]
        self._history.append({"action": action, "reward": round(reward, 4)})
        if len(self._history) > self._history_max:
            self._history.pop(0)

        self.t += 1
        self.just_shifted = False
        if self.t % self.period == 0:
            self.force_regime_change()
        return reward

    def force_regime_change(self) -> None:
        self.regime_index += 1
        choices = [i for i in range(self.n_regimes) if i != self._current]
        self._current = self.rng.choice(choices)
        self.just_shifted = True
