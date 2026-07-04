"""E2E-2c ARENA PILOT (pre-freeze; the RR-0046 protocol-self-check discipline made procedural).
Question: which frozen config makes discovery GENUINELY expensive (task-1 mean >= 3.5 interventions)
while keeping identification honest (>= 0.7)? Physics: noisier worlds -> coarser tolerance -> coarser
signature partitions -> less information per do() -> more do()s needed -> caching has room to pay.
Sweep 3 candidate configs on calibration seeds (2000+); the WINNER is frozen into E2E-2c."""
from __future__ import annotations

import json
import statistics

import experiments.igi_e2e_2b as base2b
from experiments.igi_e2e_2 import P
from experiments.igi_e2e_2b import DenseEnv
from aac.e2e_agent import run

CONFIGS = [
    {"name": "A", "noise_sd": 1.8, "n_do": 60, "tol": 1.0, "budget": 8},
    {"name": "B", "noise_sd": 2.4, "n_do": 50, "tol": 1.3, "budget": 8},
    {"name": "C", "noise_sd": 1.8, "n_do": 40, "tol": 1.2, "budget": 8},
]
CAL_SEEDS_START = 2000
N_ENVS = 6
RUNS = [0, 1]


def main():
    keepP = dict(P)
    out = {"configs": []}
    for cfg in CONFIGS:
        P["noise_sd"], P["n_do"] = cfg["noise_sd"], cfg["n_do"]
        envs, s = [], CAL_SEEDS_START
        while len(envs) < N_ENVS and s < 2600:
            e = DenseEnv(s)
            s += 1
            if len(e.pool) >= 12 and e.truth_index is not None:
                envs.append(e)
        costs, ids = [], []
        for env in envs:
            for rs in RUNS:
                r = run(env.n, env.pool, env.truth_index, env.obs(rs),
                        lambda k, st: env.do_rows(k, rs, st), lambda nd, vl: env.act(nd, vl, rs),
                        env.target, env.band, cfg["budget"], P["grid"], seed=rs, tol=cfg["tol"])
                ids.append(1.0 if (r.identified and r.correct_structure) else 0.0)
                if r.identified:
                    costs.append(len(r.interventions))
        rec = {"config": cfg, "t1_mean": round(statistics.mean(costs), 3) if costs else None,
               "identification": round(statistics.mean(ids), 3),
               "valid": bool(costs and statistics.mean(costs) >= 3.5 and statistics.mean(ids) >= 0.7)}
        out["configs"].append(rec)
        print(json.dumps(rec))
    P.update(keepP)
    winners = [r for r in out["configs"] if r["valid"]]
    out["winner"] = winners[0]["config"]["name"] if winners else None
    out["action"] = f"FREEZE E2E-2c with config {out['winner']}" if winners else \
        "NO config valid -> escalate noise/MEC further or record arena-infeasible-at-toy-scale"
    open("experiments/igi_e2e_2c_pilot.result.json", "w").write(json.dumps(out, indent=2))
    print(json.dumps({k: v for k, v in out.items() if k != "configs"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
