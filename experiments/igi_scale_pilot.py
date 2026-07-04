"""SCALE PILOT (founder cast item 4, first measurement): the EXISTING e2e_agent loop — zero code
changes — on n=12 trees and n=14 chains (previous max n=8). Measures whether identification /
achievement / governance hold as the hypothesis space and mechanism depth grow (MEC sizes grow;
budget scales as ceil(log2 MEC)+2). The no-rebuild claim extended along the SIZE dimension."""
from __future__ import annotations

import json
import random
import statistics

from aac.e2e_agent import run, _ShellView
from aac.hypothesis_pool import mec, canon
from experiments.igi_e2e_2 import P, _skeleton, Env

RUNS = [110, 111]
PER_CLASS = 6


class ScaleEnv(Env):
    N = dict(Env.N)
    N.update({"tree12": 12, "chain14": 14})


def _sk(cls, r, n):
    if cls == "chain14":
        order = list(range(n)); r.shuffle(order)
        return order, sorted(tuple(sorted((order[i], order[i + 1]))) for i in range(n - 1))
    return _skeleton("tree6", r, n)   # random tree generator, just bigger n


# patch skeleton dispatch for the new classes (zero changes to the frozen module)
import experiments.igi_e2e_2 as base_mod


def _patched_skeleton(cls, r, n):
    if cls in ("tree12", "chain14"):
        return _sk(cls, r, n)
    return _orig(cls, r, n)


_orig = base_mod._skeleton
base_mod._skeleton = _patched_skeleton


def main():
    out = {}
    for cls in ("tree12", "chain14"):
        made, s = 0, 12000
        ids, achs, mecs, halts = [], [], [], True
        while made < PER_CLASS and s < 12600:
            try:
                env = ScaleEnv(cls, s)
            except Exception:
                s += 1
                continue
            s += 1
            if env.truth_index is None or len(env.pool) < 2:
                continue
            made += 1
            mecs.append(len(env.pool))
            import math
            budget = math.ceil(math.log2(len(env.pool))) + 2
            for rs in RUNS:
                obs = env.obs(rs)
                r1 = run(env.n, env.pool, env.truth_index, obs,
                         lambda k, st: env.do_rows(k, rs, st), lambda nd, vl: env.act(nd, vl, rs),
                         env.target, env.band, budget, P["grid"], seed=rs)
                ids.append(1.0 if (r1.identified and r1.correct_structure) else 0.0)
                if r1.identified:
                    achs.append(1.0 if r1.achieved else 0.0)
                rp = run(env.n, env.pool, env.truth_index, obs,
                         lambda k, st: env.do_rows(k, rs, st), lambda nd, vl: env.act(nd, vl, rs),
                         env.target, env.band, budget, P["grid"], seed=rs,
                         shell=_ShellView(paused=True))
                if rp.interventions or rp.acted:
                    halts = False
        out[cls] = {"mec_sizes": mecs, "identification": round(statistics.mean(ids), 3),
                    "achievement_given_id": round(statistics.mean(achs), 3) if achs else None,
                    "halt_100pct": halts}
        print(cls, json.dumps(out[cls]))
    open("experiments/igi_scale_pilot.result.json", "w").write(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
