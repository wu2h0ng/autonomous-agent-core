"""ADR-0043 Causal World Model G2 (product line): human interventions per task.

A minimal agent loop with a confidence-gated escalation policy (the G10/P0 lever):
confidence >= theta -> act alone; confidence < theta -> escalate to the human (+1 intervention).
Both agents share the SAME escalation policy; the ONLY difference is the world model
(CWM causal/invariant vs STAT statistical/cue-exploiting). Negative control + DiD per ADR-0043.

Run: PYTHONPATH=src python experiments/causal_world_model_g2.py
"""

from __future__ import annotations

import random
from collections import deque

from experiments.causal_world_model_g1 import (
    CausalRegimeEnv, N, RH, RL, NOISE, PM, LAM, TLAM, TFLOOR, _wilcoxon_one_sided,
)

T = 3000
SURFACE = 60
CAUSAL = 600
WIN = 15
K = 8
THETA = 0.625
EPS = 0.05
SEEDS = tuple(range(10))


class CWMAgent:
    """Causal/invariant world model: per-action interventional effect; ignores the marker."""
    def __init__(self, seed: int) -> None:
        self.r = random.Random(30_000 + seed)
        self.q = [0.0] * N
        self.recent: deque[int] = deque(maxlen=K)

    def confidence(self) -> float:
        return sum(self.recent) / K if len(self.recent) == K else 1.0

    def predict(self, m: int) -> int:
        if self.r.random() < EPS:
            return self.r.randrange(N)
        return max(range(N), key=lambda a: self.q[a])

    def on_autonomous(self, a: int, success: bool, reward: float) -> None:
        self.q[a] = (1 - LAM) * self.q[a] + LAM * reward
        self.recent.append(1 if success else 0)

    def on_escalation(self, g: int, m: int) -> None:
        self.q[g] = (1 - LAM) * self.q[g] + LAM * RH
        self.recent.append(1)


class STATAgent:
    """Statistical world model: exploits the predictive marker with adaptive trust."""
    def __init__(self, seed: int) -> None:
        self.r = random.Random(40_000 + seed)
        self.q = [0.0] * N
        self.trust = 0.5
        self.recent: deque[int] = deque(maxlen=K)
        self._followed = False
        self._m = 0

    def confidence(self) -> float:
        return sum(self.recent) / K if len(self.recent) == K else 1.0

    def predict(self, m: int) -> int:
        self._m = m
        self._followed = self.r.random() < max(self.trust, TFLOOR)
        if self._followed:
            return m
        if self.r.random() < EPS:
            return self.r.randrange(N)
        return max(range(N), key=lambda a: self.q[a])

    def on_autonomous(self, a: int, success: bool, reward: float) -> None:
        self.q[a] = (1 - LAM) * self.q[a] + LAM * reward
        if self._followed:
            self.trust = (1 - TLAM) * self.trust + TLAM * (1.0 if success else 0.0)
        self.recent.append(1 if success else 0)

    def on_escalation(self, g: int, m: int) -> None:
        self.q[g] = (1 - LAM) * self.q[g] + LAM * RH
        # learn whether the cue pointed at the truth (this is how STAT learns the cue broke)
        self.trust = (1 - TLAM) * self.trust + TLAM * (1.0 if m == g else 0.0)
        self.recent.append(1)


def run(seed: int, condition: str, agent_cls) -> dict[str, float]:
    env = CausalRegimeEnv(seed, condition)
    agent = agent_cls(seed)
    interv = {"surface": 0, "causal": 0}
    auto_fail = 0
    auto_n = 0
    win_left, win_type = 0, None
    for _ in range(T):
        m = env.observe()
        a = agent.predict(m)
        if agent.confidence() < THETA:
            # escalate: ask the human
            if win_left > 0 and win_type is not None:
                interv[win_type] += 1
            agent.on_escalation(env.g, m)
        else:
            success = (a == env.g)
            auto_n += 1
            if not success:
                auto_fail += 1
            agent.on_autonomous(a, success, env.reward(a))
        env.advance()
        if env.just is not None:
            win_left, win_type = WIN, env.just
        elif win_left > 0:
            win_left -= 1
    return {"surface": float(interv["surface"]), "causal": float(interv["causal"]),
            "auto_fail_rate": auto_fail / max(auto_n, 1)}


def main() -> None:
    print(f"ADR-0043 Causal World Model G2 (interventions/task)  seeds={SEEDS} T={T} K={K} theta={THETA}")
    out = {}
    for cond in ("SPURIOUS", "CAUSAL_CUE"):
        rows = {"CWM": [run(s, cond, CWMAgent) for s in SEEDS],
                "STAT": [run(s, cond, STATAgent) for s in SEEDS]}
        out[cond] = rows
        print(f"\n=== {cond} ===")
        print(f"{'agent':>6} | {'surface-win intervs':>20} | {'causal-win intervs':>18} | {'auto-fail rate':>14}")
        for ag in ("CWM", "STAT"):
            s = sum(x["surface"] for x in rows[ag]) / len(SEEDS)
            c = sum(x["causal"] for x in rows[ag]) / len(SEEDS)
            f = sum(x["auto_fail_rate"] for x in rows[ag]) / len(SEEDS)
            print(f"{ag:>6} | {s:>20.1f} | {c:>18.1f} | {f:>14.3f}")

    print("\n=== DIFFERENCE-IN-DIFFERENCES (surface-window interventions; control = CAUSAL_CUE) ===")
    sp, cc = out["SPURIOUS"], out["CAUSAL_CUE"]
    did = {}
    for ag in ("CWM", "STAT"):
        ex = [sp[ag][i]["surface"] - cc[ag][i]["surface"] for i in range(len(SEEDS))]
        did[ag] = ex
        print(f"  {ag:>6} excess surface-window interventions (SPURIOUS - CAUSAL_CUE) = {sum(ex)/len(SEEDS):.1f}")
    cwm_ex = sum(did["CWM"]) / len(SEEDS)
    stat_ex = sum(did["STAT"]) / len(SEEDS)
    ratio = cwm_ex / stat_ex if stat_ex > 0 else float("nan")
    p = _wilcoxon_one_sided([did["STAT"][i] - did["CWM"][i] for i in range(len(SEEDS))])
    # quality check: CWM auto-fail not worse
    cwm_f = sum(x["auto_fail_rate"] for x in sp["CWM"]) / len(SEEDS)
    stat_f = sum(x["auto_fail_rate"] for x in sp["STAT"]) / len(SEEDS)
    print(f"  CWM raises {ratio*100:.0f}% of STAT's surface-shift intervention load  (Wilcoxon p={p:.4f})")
    print(f"  quality check (SPURIOUS auto-fail rate): CWM={cwm_f:.3f}  STAT={stat_f:.3f}  (CWM not worse: {cwm_f <= stat_f + 0.02})")
    if ratio < 0.5 and p < 0.05 and cwm_f <= stat_f + 0.02:
        print(f"  VERDICT: G2-CWM-MET — the causal-WM agent removes {100-ratio*100:.0f}% of the statistical agent's "
              f"surface-shift hand-holding, at no worse autonomous quality.")
    else:
        print("  VERDICT: G2-CWM-NOT-MET (confound-controlled).")


if __name__ == "__main__":
    main()
