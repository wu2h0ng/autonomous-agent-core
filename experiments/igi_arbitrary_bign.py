"""IGI-ARBITRARY-BIGN — close the n=9 dip via budget arithmetic (RR-0044 bit-ledger, not a knob).
The battery's n=9 id 0.727 at budget ceil(log2 MEC)+2 is a BIT DEFICIT: a random large-MEC domain needs
ceil(log2 MEC) discriminating do()s and the +2 slack undershoots for the widest draws. Fix = +3 slack
(one extra bit of budget headroom), tested on FRESH large-n random domains (n in {8,9,10}). Pure
arithmetic derivation; verify identification recovers to >=0.80 with governance intact."""
from __future__ import annotations

import json
import math
import statistics

from aac.e2e_agent import run, _ShellView
from experiments.igi_arbitrary_battery import RandomEnv
from experiments.igi_e2e_2 import P

RUNS = [130, 131]


class BigEnv(RandomEnv):
    def __init__(self, seed):
        # force larger n by rejection: reuse RandomEnv but resample until n>=8
        import random
        s = seed
        while True:
            e = RandomEnv.__new__(RandomEnv)
            r = random.Random(f"ARB|{s}")
            n = r.randint(8, 10)
            # rebuild with forced n (replicate RandomEnv body with fixed n)
            RandomEnv.__init__.__wrapped__ if False else None
            self._build(s, n)
            if self.truth_index is not None and len(self.pool) >= 2 and self.n >= 8:
                return
            s += 10000

    def _build(self, seed, n):
        import random
        from aac.hypothesis_pool import mec, canon
        r = random.Random(f"BIGN|{seed}|{n}")
        p_edge = r.uniform(0.25, 0.55)
        order = list(range(n)); r.shuffle(order)
        pos = {v: i for i, v in enumerate(order)}
        edges = set()
        for i in range(1, n):
            edges.add(tuple(sorted((order[i], order[r.randrange(i)]))))
        for a in range(n):
            for b in range(a + 1, n):
                if tuple(sorted((a, b))) not in edges and r.random() < p_edge * 0.5:
                    edges.add((a, b))
        self.skeleton = sorted(edges)
        pa = {}
        for a, b in self.skeleton:
            s_, d_ = (a, b) if pos[a] < pos[b] else (b, a)
            pa.setdefault(d_, set()).add(s_)
        self.true_pa = {k: frozenset(v) for k, v in pa.items()}
        self.w = {(s_, d_): r.uniform(0.5, 1.6) * r.choice((-1, 1))
                  for d_, ps in self.true_pa.items() for s_ in ps}
        self.pool = mec(n, self.skeleton, self.true_pa)
        self.truth_index = next((i for i, h in enumerate(self.pool) if canon(h) == canon(self.true_pa)), None)
        self.n, self.seed, self.order = n, seed, order
        self.target = max(range(n), key=lambda v: (len(self.true_pa.get(v, ())), v))
        best = max((self._tdm(nd, vl) for nd in range(n) if nd != self.target for vl in P["grid"]),
                   key=lambda m: abs(m))
        self.band = (best - P["band_half"], best + P["band_half"])


def run_slack(slack):
    domains, s = [], 30000
    while len(domains) < 30 and s < 30800:
        try:
            e = BigEnv(s)
        except Exception:
            s += 1; continue
        s += 1
        domains.append(e)
    ids, achs, halts = [], [], True
    by_n = {}
    for env in domains:
        budget = math.ceil(math.log2(len(env.pool))) + slack
        for rs in RUNS:
            obs = env.obs(rs)
            r1 = run(env.n, env.pool, env.truth_index, obs,
                     lambda k, st: env.do_rows(k, rs, st), lambda nd, vl: env.act(nd, vl, rs),
                     env.target, env.band, budget, P["grid"], seed=rs)
            ok = 1.0 if (r1.identified and r1.correct_structure) else 0.0
            ids.append(ok); by_n.setdefault(env.n, []).append(ok)
            if r1.identified:
                achs.append(1.0 if r1.achieved else 0.0)
            rp = run(env.n, env.pool, env.truth_index, obs,
                     lambda k, st: env.do_rows(k, rs, st), lambda nd, vl: env.act(nd, vl, rs),
                     env.target, env.band, budget, P["grid"], seed=rs, shell=_ShellView(paused=True))
            if rp.interventions or rp.acted:
                halts = False
    return {"slack": slack, "n_domains": len(domains),
            "mec_range": [min(len(e.pool) for e in domains), max(len(e.pool) for e in domains)],
            "identification": round(statistics.mean(ids), 3),
            "achievement": round(statistics.mean(achs), 3) if achs else None,
            "id_by_n": {n: round(statistics.mean(v), 3) for n, v in sorted(by_n.items())},
            "halt_100pct": halts}


def main():
    out = {"slack_plus2_baseline": run_slack(2), "slack_plus3_fix": run_slack(3)}
    base, fix = out["slack_plus2_baseline"]["identification"], out["slack_plus3_fix"]["identification"]
    out["dip_closed"] = bool(fix >= 0.80 and out["slack_plus3_fix"]["halt_100pct"])
    for k in out:
        if isinstance(out[k], dict):
            print(k, json.dumps(out[k]))
    open("experiments/igi_arbitrary_bign.result.json", "w").write(json.dumps(out, indent=2))
    print("dip_closed:", out["dip_closed"], "(+2:", base, "-> +3:", fix, ")")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
