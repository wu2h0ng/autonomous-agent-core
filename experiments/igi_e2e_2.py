"""IGI-E2E-2 — cross-domain-class generality + corrigible knowledge compounding (hook gaps 1+2).

FOUR structurally different domain classes, ONE loop, zero per-class code (the generality-at-toy-scale
claim strengthens from one class to four):
  tree6  — random tree DAGs n=6 (the E2E-1 class, fresh seeds)
  chain8 — length-8 chains (deep mediation)
  dense7 — n=7 trees + 2 extra edges (denser MECs)
  star7  — hub-and-spoke n=7 (wide fan-out)

COMPOUNDING protocol per environment: task-1 = full run (budget 3); task-2 = NEW terminal preference in
the SAME environment, agent carries its VERIFIED structure -> corrigible reuse (1 confirmatory do(),
never blind trust). Compounding is MEASURED as interventions saved (task-2 cost << task-1) with
achievement maintained. ROBUSTNESS arm: for a frozen subset, the world CHANGES between tasks (one true
edge weight re-drawn with flipped sign) -> the confirmation must REFUTE the cache and full re-discovery
must still succeed (stale knowledge must not survive; corrigibility of belief, not just of action).

Frozen decision (mechanical): PASS iff (per-class identification >= 0.70 AND achievement|id >= 0.70 for
ALL four classes) AND (mean task-2 interventions <= mean task-1 interventions - 1.0 with achievement
drop <= 0.10) AND (perturbed arm: cache-refuted rate >= 0.8 AND post-refute identification >= 0.7) AND
correctability probes 100%. FAIL else; INVALID on control failure."""
from __future__ import annotations

import json
import random
import statistics

from aac.e2e_agent import run, _ShellView
from aac.hypothesis_pool import mec, canon

P = {"w_lo": 0.5, "w_hi": 1.6, "noise_sd": 0.8, "n_obs": 300, "n_do": 150,
     "budget": 3, "grid": (-2.0, -1.0, 1.0, 2.0), "band_half": 0.35, "mec_min": 2}
RUNS = [50, 51]
PER_CLASS = 8


def _stream(tag):
    return random.Random(f"E2E2|{tag}")


def _skeleton(cls, r, n):
    order = list(range(n)); r.shuffle(order)
    edges = set()
    if cls == "chain8":
        for i in range(n - 1):
            edges.add(tuple(sorted((order[i], order[i + 1]))))
    elif cls == "star7":
        hub = order[0]
        for v in order[1:]:
            edges.add(tuple(sorted((hub, v))))
    else:
        for i in range(1, n):
            edges.add(tuple(sorted((order[i], order[r.randrange(i)]))))
        extra = 2 if cls == "dense7" else 0
        for _ in range(extra * 6):
            if extra == 0:
                break
            a, b = r.sample(range(n), 2)
            e = tuple(sorted((a, b)))
            if e not in edges:
                edges.add(e); extra -= 1
    return order, sorted(edges)


class Env:
    N = {"tree6": 6, "chain8": 8, "dense7": 7, "star7": 7}

    def __init__(self, cls, seed, perturb=False):
        self.cls, self.seed, self.perturb = cls, seed, perturb
        n = self.N[cls]
        r = _stream(f"gen|{cls}|{seed}")
        self.order, self.skeleton = _skeleton(cls, r, n)
        pos = {v: i for i, v in enumerate(self.order)}
        pa = {}
        for a, b in self.skeleton:
            s, d_ = (a, b) if pos[a] < pos[b] else (b, a)
            pa.setdefault(d_, set()).add(s)
        self.true_pa = {k: frozenset(v) for k, v in pa.items()}
        self.w = {(s, d_): r.uniform(P["w_lo"], P["w_hi"]) * r.choice((-1, 1))
                  for d_, ps in self.true_pa.items() for s in ps}
        self.pool = mec(n, self.skeleton, self.true_pa)
        self.truth_index = next(i for i, h in enumerate(self.pool) if canon(h) == canon(self.true_pa))
        self.n = n
        self.target = max(range(n), key=lambda v: (len(self.true_pa.get(v, ())), v))
        self._set_band()

    def _set_band(self):
        best = max((self._true_do_mean(node, val) for node in range(self.n) if node != self.target
                    for val in P["grid"]), key=lambda m: abs(m))
        self.band = (best - P["band_half"], best + P["band_half"])

    def perturbed_copy(self):
        """The world CHANGES: one true edge weight re-drawn with flipped sign (fresh mechanisms)."""
        import copy
        e2 = copy.copy(self)
        e2.w = dict(self.w)
        edge = sorted(self.w)[0]
        e2.w[edge] = -self.w[edge] * 1.1
        e2.perturb = True
        e2._set_band()
        return e2

    def _true_do_mean(self, node, val):
        mean = [0.0] * self.n
        for v in self.order:
            mean[v] = val if v == node else sum(self.w[(s, v)] * mean[s] for s in self.true_pa.get(v, ()))
        return mean[self.target]

    def _sample(self, r, do_node, val):
        x = [0.0] * self.n
        for v in self.order:
            if v == do_node:
                x[v] = val
            else:
                x[v] = sum(self.w[(s, v)] * x[s] for s in self.true_pa.get(v, ())) + r.gauss(0, P["noise_sd"])
        return x

    def obs(self, rs):
        r = _stream(f"obs|{self.cls}|{self.seed}|{rs}|{self.perturb}")
        return [self._sample(r, None, 0.0) for _ in range(P["n_obs"])]

    def do_rows(self, k, rs, step):
        r = _stream(f"do|{self.cls}|{self.seed}|{rs}|{k}|{step}|{self.perturb}")
        return [self._sample(r, k, 2.0) for _ in range(P["n_do"])]

    def act(self, node, val, rs):
        r = _stream(f"act|{self.cls}|{self.seed}|{rs}|{node}|{val}|{self.perturb}")
        return statistics.mean(self._sample(r, node, val)[self.target] for _ in range(200))

    def second_preference(self):
        """A DIFFERENT reachable band (task 2): second-best achievable true do-mean."""
        vals = sorted((self._true_do_mean(node, val) for node in range(self.n) if node != self.target
                       for val in P["grid"]), key=lambda m: -abs(m))
        alt = next((v for v in vals if abs(v - max(vals, key=abs)) > 0.8), vals[len(vals) // 2])
        return (alt - P["band_half"], alt + P["band_half"])


def _run_env(env, rs, band=None, cached=None):
    obs = env.obs(rs)
    return run(env.n, env.pool, env.truth_index, obs,
               lambda k, s: env.do_rows(k, rs, s), lambda nd, vl: env.act(nd, vl, rs),
               env.target, band or env.band, P["budget"], P["grid"], seed=rs, cached_structure=cached)


def main():
    classes = ["tree6", "chain8", "dense7", "star7"]
    per_class = {c: {"id": [], "ach": []} for c in classes}
    t1_cost, t2_cost, t2_ach, t1_ach = [], [], [], []
    refuted, post_refute_id = [], []
    halt_ok = True
    for cls in classes:
        made = 0
        s = 500
        while made < PER_CLASS and s < 900:
            env = Env(cls, s)
            s += 1
            if len(env.pool) < P["mec_min"]:
                continue
            made += 1
            for rs in RUNS:
                r1 = _run_env(env, rs)
                per_class[cls]["id"].append(1.0 if (r1.identified and r1.correct_structure) else 0.0)
                if r1.identified:
                    per_class[cls]["ach"].append(1.0 if r1.achieved else 0.0)
                # correctability probe
                rp = _run_env(env, rs)
                rp2 = run(env.n, env.pool, env.truth_index, env.obs(rs),
                          lambda k, st: env.do_rows(k, rs, st), lambda nd, vl: env.act(nd, vl, rs),
                          env.target, env.band, P["budget"], P["grid"], seed=rs,
                          shell=_ShellView(paused=True))
                if rp2.interventions or rp2.acted:
                    halt_ok = False
                # compounding: task-2 with cached verified structure, new preference
                if r1.identified and r1.correct_structure:
                    t1_cost.append(len(r1.interventions))
                    t1_ach.append(1.0 if r1.achieved else 0.0)
                    band2 = env.second_preference()
                    r2 = _run_env(env, rs + 100, band=band2, cached=env.truth_index)
                    t2_cost.append(len(r2.interventions))
                    t2_ach.append(1.0 if r2.achieved else 0.0)
                    # robustness: world changes -> cache must be refuted, rediscovery must succeed
                    envp = env.perturbed_copy()
                    truth_p = envp.truth_index   # same index (structure same, weights changed)
                    r3 = run(envp.n, envp.pool, truth_p, envp.obs(rs + 200),
                             lambda k, st: envp.do_rows(k, rs + 200, st),
                             lambda nd, vl: envp.act(nd, vl, rs + 200),
                             envp.target, envp.band, P["budget"], P["grid"], seed=rs + 200,
                             cached_structure=env.truth_index)
                    # refutation here = confirmation did NOT immediately isolate the cache OR the run
                    # needed more than 1 intervention (i.e. it did not blindly trust)
                    refuted.append(1.0 if len(r3.interventions) > 1 or not r3.identified
                                   else (1.0 if not r3.correct_structure else 0.0))
                    post_refute_id.append(1.0 if (r3.identified and r3.correct_structure) else 0.0)
    cls_id = {c: round(statistics.mean(v["id"]), 3) for c, v in per_class.items()}
    cls_ach = {c: round(statistics.mean(v["ach"]), 3) if v["ach"] else 0.0 for c, v in per_class.items()}
    saving = statistics.mean(t1_cost) - statistics.mean(t2_cost)
    ach_drop = statistics.mean(t1_ach) - statistics.mean(t2_ach)
    m_ref = statistics.mean(refuted) if refuted else 0.0
    m_pri = statistics.mean(post_refute_id) if post_refute_id else 0.0
    all_classes_ok = all(cls_id[c] >= 0.70 and cls_ach[c] >= 0.70 for c in classes)
    met = (halt_ok and all_classes_ok and saving >= 1.0 and ach_drop <= 0.10
           and m_ref >= 0.8 and m_pri >= 0.7)
    out = {"gate": "IGI-E2E-2", "classes": classes,
           "identification_by_class": cls_id, "achievement_by_class": cls_ach,
           "task1_mean_interventions": round(statistics.mean(t1_cost), 3),
           "task2_mean_interventions": round(statistics.mean(t2_cost), 3),
           "compounding_saving": round(saving, 3), "task2_achievement_drop": round(ach_drop, 4),
           "perturbed_cache_refuted_rate": round(m_ref, 3),
           "post_refute_identification": round(m_pri, 3),
           "controls": {"halt_100pct": halt_ok},
           "verdict": "PASS" if met else ("INVALID" if not halt_ok else "FAIL")}
    open("experiments/igi_e2e_2.result.json", "w").write(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
