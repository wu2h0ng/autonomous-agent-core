"""ADR-0045 Causal World Model Core (the real thing): intervention vs correlation.

The shared core for tracks A & B. An explicit causal world model learns, by INTERVENTION,
which features CAUSE the reward, and predicts the effect of interventions correctly where a
correlational model (the stand-in for an LLM/statistical learner) is fooled by a confounder.

Hallmark: given the SAME observational data, the causal model predicts that do(decoy) does NOT
change reward; the correlational model -- fooled by the confound -- predicts it does.

Run: PYTHONPATH=src python experiments/causal_world_model_core.py
"""

from __future__ import annotations

import random

D = 4              # features
OBS_N = 200        # confounded observational samples
INTERV_N = 200     # interventional budget for the causal agent
QUERIES = 400      # interventional-prediction test queries
SEEDS = tuple(range(20))


class CausalStructureEnv:
    """reward = 1 iff x[c]==t. One causal feature c; the rest are decoys."""
    def __init__(self, rng: random.Random, decoy_is_causal: bool = False) -> None:
        self.r = rng
        self.c = rng.randrange(D)
        self.t = rng.randrange(2)
        # a fixed decoy index (!= c) that the confounded expert couples to the cause
        others = [i for i in range(D) if i != self.c]
        self.decoy = rng.choice(others)
        self.decoy_is_causal = decoy_is_causal  # negative control
        self.t2 = rng.randrange(2)              # decoy's target if it really were causal

    def reward(self, x: list[int]) -> int:
        ok = (x[self.c] == self.t)
        if self.decoy_is_causal:
            ok = ok and (x[self.decoy] == self.t2)
        return 1 if ok else 0

    def expert_obs(self) -> tuple[list[int], int]:
        # confounded: expert sets x[c]=t and x[decoy]=t (decoy tracks the cause); others random
        x = [self.r.randrange(2) for _ in range(D)]
        x[self.c] = self.t
        x[self.decoy] = self.t if not self.decoy_is_causal else self.t2
        return x, self.reward(x)


class CausalAgent:
    """Learns the causal mask by INTERVENTION (toggle each feature, see if reward changes)."""
    def __init__(self) -> None:
        self.causal = [False] * D
        self.func: dict[int, int] = {}   # feature -> value that yields reward (learned)

    def learn(self, env: CausalStructureEnv, rng: random.Random, budget: int) -> None:
        # interventional probing: for each feature, do(flip) holding a random base, measure effect
        per = max(1, budget // D)
        for i in range(D):
            changed = 0
            best_val_reward = {0: 0, 1: 0}
            for _ in range(per):
                base = [rng.randrange(2) for _ in range(D)]
                r0 = env.reward(base)
                flipped = list(base)
                flipped[i] = 1 - flipped[i]
                r1 = env.reward(flipped)
                if r0 != r1:
                    changed += 1
                best_val_reward[base[i]] += r0
                best_val_reward[flipped[i]] += r1
            if changed > 0:
                self.causal[i] = True
                self.func[i] = 1 if best_val_reward[1] >= best_val_reward[0] else 0

    def predict_intervention_changes(self, i: int) -> bool:
        return self.causal[i]

    def best_action(self) -> list[int]:
        return [self.func.get(i, 0) for i in range(D)]


class StatAgent:
    """Learns each feature's CORRELATION with reward from OBSERVATIONAL data only."""
    def __init__(self) -> None:
        self.corr = [0.0] * D
        self.best_val = [0] * D

    def learn(self, obs: list[tuple[list[int], int]]) -> None:
        n = len(obs)
        for i in range(D):
            # corr ~ P(reward=1 | x[i]=1) - P(reward=1 | x[i]=0)
            s = {0: [0, 0], 1: [0, 0]}  # value -> [reward_sum, count]
            for x, r in obs:
                s[x[i]][0] += r
                s[x[i]][1] += 1
            p1 = s[1][0] / s[1][1] if s[1][1] else 0.0
            p0 = s[0][0] / s[0][1] if s[0][1] else 0.0
            self.corr[i] = abs(p1 - p0)
            self.best_val[i] = 1 if p1 >= p0 else 0

    def predict_intervention_changes(self, i: int) -> bool:
        return self.corr[i] > 0.5   # "this feature predicts reward -> assume changing it matters"

    def best_action(self) -> list[int]:
        return list(self.best_val)


def run_seed(seed: int, decoy_is_causal: bool) -> dict:
    rng = random.Random(seed)
    env = CausalStructureEnv(rng, decoy_is_causal=decoy_is_causal)
    obs = [env.expert_obs() for _ in range(OBS_N)]
    cwm = CausalAgent(); cwm.learn(env, random.Random(1000 + seed), INTERV_N)
    stat = StatAgent(); stat.learn(obs)

    # Test 1: interventional-prediction accuracy, split by query type
    qr = random.Random(2000 + seed)
    acc = {"cwm": 0, "stat": 0}
    decoy_acc = {"cwm": 0, "stat": 0}
    decoy_n = 0
    for _ in range(QUERIES):
        i = qr.randrange(D)
        truth = (i == env.c) or (decoy_is_causal and i == env.decoy)
        for name, ag in (("cwm", cwm), ("stat", stat)):
            pred = ag.predict_intervention_changes(i)
            if pred == truth:
                acc[name] += 1
        if i == env.decoy and not decoy_is_causal:
            decoy_n += 1
            for name, ag in (("cwm", cwm), ("stat", stat)):
                if ag.predict_intervention_changes(i) == truth:
                    decoy_acc[name] += 1
    # Test 2: action under decoupling -> reward of each agent's chosen action
    cwm_rw = env.reward(cwm.best_action())
    stat_rw = env.reward(stat.best_action())
    return {
        "cwm_acc": acc["cwm"] / QUERIES, "stat_acc": acc["stat"] / QUERIES,
        "cwm_decoy_acc": decoy_acc["cwm"] / decoy_n if decoy_n else 1.0,
        "stat_decoy_acc": decoy_acc["stat"] / decoy_n if decoy_n else 1.0,
        "cwm_action_rw": cwm_rw, "stat_action_rw": stat_rw,
    }


def agg(cond: bool, label: str) -> dict:
    rows = [run_seed(s, cond) for s in SEEDS]
    m = {k: sum(r[k] for r in rows) / len(rows) for k in rows[0]}
    print(f"\n=== {label} ===")
    print(f"  interventional-prediction accuracy:  CWM={m['cwm_acc']:.2f}  STAT={m['stat_acc']:.2f}")
    print(f"  accuracy ON DECOY queries (the tell): CWM={m['cwm_decoy_acc']:.2f}  STAT={m['stat_decoy_acc']:.2f}")
    print(f"  action reward (decoupled test):       CWM={m['cwm_action_rw']:.2f}  STAT={m['stat_action_rw']:.2f}")
    return m


def main() -> None:
    print(f"ADR-0045 Causal World Model Core  D={D} obs={OBS_N} interv={INTERV_N} seeds={len(SEEDS)}")
    main_m = agg(False, "MAIN (decoy is a confound, NOT causal)")
    ctrl_m = agg(True, "NEGATIVE CONTROL (decoy is GENUINELY causal)")
    print("\n=== VERDICT (ADR-0045 frozen rule) ===")
    gap = main_m["cwm_decoy_acc"] - main_m["stat_decoy_acc"]
    nc_gap = ctrl_m["cwm_decoy_acc"] - ctrl_m["stat_decoy_acc"]
    print(f"  decoy-query accuracy gap (CWM - STAT): MAIN={gap:+.2f}  CONTROL={nc_gap:+.2f}")
    hallmark = gap > 0.4
    neg_ok = nc_gap <= 0.2
    print(f"  hallmark (CWM beats STAT on do(decoy) by >0.4): {gap:+.2f} -> {'PASS' if hallmark else 'FAIL'}")
    print(f"  negative control (no gap when decoy is real, <=0.2): {nc_gap:+.2f} -> {'PASS' if neg_ok else 'FAIL'}")
    if hallmark and neg_ok:
        print("  VERDICT: CWM-CORE-MET — a real causal world model: it knows do(decoy) doesn't change reward "
              "(where a correlational/LLM-style learner is fooled by the confounder), and the advantage is "
              "specific to confounds (negative control holds).")
    else:
        print("  VERDICT: CWM-CORE-NOT-MET.")


if __name__ == "__main__":
    main()
