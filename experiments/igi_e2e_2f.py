"""IGI-E2E-2f — CROSS-ENVIRONMENT class-knowledge compounding + cross-CLASS harm bound.

Class knowledge = statistical regularity of a domain (here: biased path-root positions, 70% modal).
Learned from M solved environments as root-position frequencies; enters NEW environments of the class
ONLY as a NOMINATED candidate structure (the law's shape: the prior NOMINATES, the world CONFIRMS via
the 2-confirm protocol; a wrong nomination is refuted and full discovery resumes — priors are
corrigible, never trusted untested).

Arms (fresh scored envs, seeds disjoint from the learning set):
  A-prior on class-A: prior-guided cost vs no-prior cost (compounding saving across ENVIRONMENTS)
  A-prior on class-B (opposite bias): correctness must NOT degrade (harm bound; wrong priors die by
    verification) and cost penalty bounded.

Frozen decision (mechanical): PASS iff class-A prior saving >= 1.0 do AND prior-run correctness >= 0.90
AND cross-class correctness drop <= 0.05 AND cross-class cost penalty <= 1.0 do AND halt 100%.
Learning set: 10 class-A envs (seeds 5000+); scored: 8 fresh class-A (5200+) + 8 class-B (5400+),
runs {66,67}. Frozen prediction: modal-hit 70% -> prior path ~2 dos, miss -> ~2+3.5; expected prior
cost ~2.9 vs no-prior ~4.5 -> saving ~1.6; correctness ~0.95 (confirms catch non-modal); cross-class:
prior nearly always refuted in 2 confirms -> penalty ~+1.6... LIVE RISK: penalty bar 1.0 may be
exceeded (refutation costs are real) -> honest FAIL path. PASS ~55%."""
from __future__ import annotations

import json
import random
import statistics

from aac.e2e_agent import run, _ShellView
from aac.hypothesis_pool import canon, mec
from aac.intervention_chooser import choose
from aac.structure_consistency import Exhausted, fit_mechanisms, predict_do_means, prune
from experiments.igi_e2e_2 import P
from experiments.igi_e2e_2c2_pilot import PathEnv, _stream

RUNS = [66, 67]
BUDGET = 10
CONFIRMS = 2
TOL = 0.6


class BiasedPathEnv(PathEnv):
    """PathEnv with BIASED root positions: modal root (head for class A, tail for class B) w.p. 0.7."""

    def __init__(self, seed, bias="head"):
        self.bias = bias
        super().__init__(seed)
        r = _stream(f"bias|{seed}|{bias}")
        lab_r = _stream(f"gen|{seed}")
        lab = list(range(13)); lab_r.shuffle(lab)
        paths = [lab[0:5], lab[5:10], lab[10:13]]
        pa = {}
        self.roots = []
        for pth in paths:
            if r.random() < 0.7:
                root = 0 if bias == "head" else len(pth) - 1
            else:
                root = r.randrange(len(pth))
            self.roots.append(root)
            for i in range(len(pth) - 1):
                a, b = pth[i], pth[i + 1]
                if i + 1 <= root:
                    pa.setdefault(a, set()).add(b)
                else:
                    pa.setdefault(b, set()).add(a)
        self.true_pa = {k: frozenset(v) for k, v in pa.items()}
        wr = _stream(f"biasw|{seed}|{bias}")
        self.w = {(s_, d_): wr.uniform(P["w_lo"], P["w_hi"]) * wr.choice((-1, 1))
                  for d_, ps in self.true_pa.items() for s_ in ps}
        self.pool = mec(13, self.skeleton, self.true_pa)
        self.truth_index = next((i for i, h in enumerate(self.pool) if canon(h) == canon(self.true_pa)), None)
        self.order = self._topo()
        best = max((self._tdm(node, val) for node in range(13) if node != self.target
                    for val in P["grid"]), key=lambda m: abs(m))
        self.band = (best - P["band_half"], best + P["band_half"])
        self.paths = paths

    def modal_structure(self, modal_root_frac_pos):
        """Build the class-prior's NOMINATED structure: per path, root at the modal position."""
        pa = {}
        for pth in self.paths:
            root = 0 if modal_root_frac_pos == 0.0 else len(pth) - 1
            for i in range(len(pth) - 1):
                a, b = pth[i], pth[i + 1]
                if i + 1 <= root:
                    pa.setdefault(a, set()).add(b)
                else:
                    pa.setdefault(b, set()).add(a)
        return {k: frozenset(v) for k, v in pa.items()}


def full_discover(env, rs):
    obs = env.obs(rs)
    mechs = [fit_mechanisms(env.n, h, obs) for h in env.pool]
    bases = [predict_do_means(env.n, h, m, -1, 0.0) for h, m in zip(env.pool, mechs)]
    alive = list(range(len(env.pool)))
    cost = 0
    for step in range(BUDGET):
        if len(alive) <= 1:
            break
        k = choose(env.n, [env.pool[i] for i in alive], [mechs[i] for i in alive],
                   list(range(env.n)), 2.0, [bases[i] for i in alive], TOL)
        rows = env.do_rows(k, rs, step)
        cost += 1
        try:
            keep, _ = prune(env.n, [env.pool[i] for i in alive], [mechs[i] for i in alive],
                            k, 2.0, rows, TOL)
        except Exhausted:
            return None, cost
        alive = [alive[i] for i in keep]
    return (alive[0] if len(alive) == 1 else None), cost


def prior_guided(env, rs, nominated_canon):
    """Prior NOMINATES a structure; 2-confirm verify (2c protocol); refuted -> full discovery."""
    obs = env.obs(rs)
    mechs = [fit_mechanisms(env.n, h, obs) for h in env.pool]
    bases = [predict_do_means(env.n, h, m, -1, 0.0) for h, m in zip(env.pool, mechs)]
    alive = list(range(len(env.pool)))
    cost = 0

    def nom_alive():
        return any(canon(env.pool[i]) == nominated_canon for i in alive)

    for stepc in range(CONFIRMS):
        if not nom_alive() or len(alive) == 1:
            break
        k = choose(env.n, [env.pool[i] for i in alive], [mechs[i] for i in alive],
                   list(range(env.n)), 2.0, [bases[i] for i in alive], TOL)
        rows = env.do_rows(k, rs, stepc)
        cost += 1
        try:
            keep, _ = prune(env.n, [env.pool[i] for i in alive], [mechs[i] for i in alive],
                            k, 2.0, rows, TOL)
        except Exhausted:
            return None, cost
        alive = [alive[i] for i in keep]
    if nom_alive() and cost == CONFIRMS:
        return next(i for i in alive if canon(env.pool[i]) == nominated_canon), cost
    for step in range(cost, BUDGET):
        if len(alive) <= 1:
            break
        k = choose(env.n, [env.pool[i] for i in alive], [mechs[i] for i in alive],
                   list(range(env.n)), 2.0, [bases[i] for i in alive], TOL)
        rows = env.do_rows(k, rs, step)
        cost += 1
        try:
            keep, _ = prune(env.n, [env.pool[i] for i in alive], [mechs[i] for i in alive],
                            k, 2.0, rows, TOL)
        except Exhausted:
            return None, cost
        alive = [alive[i] for i in keep]
    return (alive[0] if len(alive) == 1 else None), cost


def collect(bias, start, n):
    envs, s = [], start
    while len(envs) < n and s < start + 400:
        e = BiasedPathEnv(s, bias)
        s += 1
        if e.truth_index is not None and len(e.pool) >= 40:
            envs.append(e)
    return envs


def main():
    # ---- learn the class prior from 10 SOLVED class-A envs ----
    learn = collect("head", 5000, 10)
    root_positions = []
    for env in learn:
        idx, _ = full_discover(env, 55)
        if idx is not None and canon(env.pool[idx]) == canon(env.true_pa):
            root_positions.extend(0.0 if r == 0 else 1.0 for r in env.roots)
    modal = 0.0 if root_positions.count(0.0) >= len(root_positions) / 2 else 1.0
    prior_strength = max(root_positions.count(0.0), root_positions.count(1.0)) / max(1, len(root_positions))

    scoredA = collect("head", 5200, 8)
    scoredB = collect("tail", 5400, 8)
    a_np, a_pr, a_ok = [], [], []
    b_np, b_pr, b_ok_np, b_ok_pr = [], [], [], []
    halt_ok = True
    for env in scoredA:
        for rs in RUNS:
            i0, c0 = full_discover(env, rs)
            a_np.append(c0)
            nom = canon(env.modal_structure(modal))
            i1, c1 = prior_guided(env, rs + 100, nom)
            a_pr.append(c1)
            a_ok.append(1.0 if (i1 is not None and canon(env.pool[i1]) == canon(env.true_pa)) else 0.0)
            rp = run(env.n, env.pool, env.truth_index, env.obs(rs),
                     lambda k, st: env.do_rows(k, rs, st), lambda nd, vl: env.act(nd, vl, rs),
                     env.target, env.band, BUDGET, P["grid"], seed=rs, shell=_ShellView(paused=True))
            if rp.interventions or rp.acted:
                halt_ok = False
    for env in scoredB:
        for rs in RUNS:
            i0, c0 = full_discover(env, rs)
            b_np.append(c0)
            b_ok_np.append(1.0 if (i0 is not None and canon(env.pool[i0]) == canon(env.true_pa)) else 0.0)
            nom = canon(env.modal_structure(modal))       # the WRONG-class prior
            i1, c1 = prior_guided(env, rs + 100, nom)
            b_pr.append(c1)
            b_ok_pr.append(1.0 if (i1 is not None and canon(env.pool[i1]) == canon(env.true_pa)) else 0.0)
    saving = statistics.mean(a_np) - statistics.mean(a_pr)
    corr = statistics.mean(a_ok)
    cross_drop = statistics.mean(b_ok_np) - statistics.mean(b_ok_pr)
    cross_pen = statistics.mean(b_pr) - statistics.mean(b_np)
    met = (halt_ok and saving >= 1.0 and corr >= 0.90 and cross_drop <= 0.05 and cross_pen <= 1.0)
    out = {"gate": "IGI-E2E-2f", "prior": {"modal_root": "head" if modal == 0.0 else "tail",
                                           "strength": round(prior_strength, 3), "learned_from": len(learn)},
           "classA_noprior_cost": round(statistics.mean(a_np), 3),
           "classA_prior_cost": round(statistics.mean(a_pr), 3),
           "cross_env_saving": round(saving, 3), "classA_prior_correctness": round(corr, 4),
           "classB_correctness_drop": round(cross_drop, 4), "classB_cost_penalty": round(cross_pen, 3),
           "controls": {"halt_100pct": halt_ok},
           "verdict": "INVALID" if not halt_ok else ("PASS" if met else "FAIL")}
    open("experiments/igi_e2e_2f.result.json", "w").write(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
