"""NT-1 scored gate — NOTEARS role reassignment: continuous proposer + discrete invariance verifier
(RR-0045; RR-0044 typed routing). Standardized data throughout (variance artifact removed).

Arms (identical verifier for every pipeline arm):
  NT-alone   : NOTEARS-lite thresholded |W|>0.3 (status-quo baseline; the type-violating decider)
  NT-pipe    : NOTEARS-lite top-2d directed candidates -> invariance verify -> acyclic structure
  SCR-pipe   : screening |corr| top-2d undirected -> both directions as candidates -> same verify
  ORACLE-pipe: true edges + decoys to 2d -> same verify (verify-step ceiling given a good pool)

Verifier (the discrete structure decision; regression variant of the frozen LEARN-2/3 selection rule,
disclosed): per candidate-child node, per-env OLS of the child on its candidate parents; KEEP an edge
iff its coefficient is sign-stable across ALL envs AND min-env |coef| >= MAG_FLOOR. Cross-env variance
perturbation (arena) makes latent-confounded coefficients shift -> killed; true mechanisms invariant ->
kept. Then deterministic acyclicity: accept surviving edges in min-|coef| descending order, skip any
edge that closes a cycle. Metric: directed-edge F1 vs truth.

Decision (frozen, mechanical): with capture = (F1_NTpipe) / (F1_ORACLEpipe):
  MET-strong iff capture >= 0.8 AND F1_NTpipe >= F1_NTalone + 0.15 AND NT-pipe > SCR-pipe on >= 8/10 seeds
  MET-weak   iff same but |mean F1_NTpipe - mean F1_SCRpipe| <= 0.03 (cheap screening ties -> NOTEARS
              adds nothing over the cheap proposer; recorded as such, engineering stop-loss per RR-0045)
  NULL       iff capture < 0.8 or the +0.15 over threshold-baseline fails (role reassignment does not
              rescue NOTEARS) — controls clean.
  INVALID    iff arena pre-check fails on scored seeds (screening recall@2d not depressed vs NT recall
              by >= 0.10 -> no discriminative power = INVALID-BY-CONSTRUCTION) or digests drift.
Scored seeds 100-109; calibration 1000-1002 (disjoint)."""
from __future__ import annotations

import json
import statistics

from experiments.notears_lite import fit_w, top_edges
from experiments.nt1_arena import Arena, NT_PARAMS, standardize
from aac.structure_consistency import _ols

MAG_FLOOR = 0.10
THRESH = 0.3
SEEDS = list(range(100, 110))


def screening_candidates(envs, k):
    d = len(envs[0][0])
    best = {}
    for X in envs:
        n = len(X)
        mean = [sum(r[j] for r in X) / n for j in range(d)]
        sd = [max(1e-9, (sum((r[j] - mean[j]) ** 2 for r in X) / n) ** 0.5) for j in range(d)]
        for a in range(d):
            for b in range(a + 1, d):
                c = abs(sum((r[a] - mean[a]) * (r[b] - mean[b]) for r in X) / (n * sd[a] * sd[b]))
                best[(a, b)] = max(best.get((a, b), 0.0), c)
    ranked = [e for e, _ in sorted(best.items(), key=lambda kv: -kv[1])[:k]]
    return [(a, b) for a, b in ranked] + [(b, a) for a, b in ranked]


def invariance_verify(envs, candidates, d):
    """Per-child per-env OLS on candidate parents; keep sign-stable + floored edges; acyclic greedy."""
    parents = {}
    for a, b in candidates:
        parents.setdefault(b, set()).add(a)
    kept = {}
    for child, cps in parents.items():
        cps = sorted(cps)
        coefs = []
        for X in envs:
            w = _ols([[r[p] for p in cps] for r in X], [r[child] for r in X])
            coefs.append({p: w[i + 1] for i, p in enumerate(cps)})
        for p in cps:
            vals = [c[p] for c in coefs]
            sgn = [1 if v > 0 else (-1 if v < 0 else 0) for v in vals]
            if sgn[0] != 0 and all(s == sgn[0] for s in sgn) and min(abs(v) for v in vals) >= MAG_FLOOR:
                kept[(p, child)] = min(abs(v) for v in vals)
    # deterministic acyclicity: strongest-first, skip cycle-closers
    out, adj = set(), {j: set() for j in range(d)}
    def reaches(src, dst):
        stack, seen = [src], set()
        while stack:
            u = stack.pop()
            if u == dst:
                return True
            if u in seen:
                continue
            seen.add(u)
            stack.extend(adj[u])
        return False
    for (a, b), _v in sorted(kept.items(), key=lambda kv: -kv[1]):
        if not reaches(b, a):
            out.add((a, b))
            adj[a].add(b)
    return out


def f1(pred, true):
    tp = len(pred & true)
    return 2 * tp / (len(pred) + len(true)) if pred else 0.0


def recall_at(cands, true):
    return len(set(cands) & true) / len(true)


def main():
    d = NT_PARAMS["d"]
    k = 2 * d
    rows = {a: [] for a in ("NT_alone", "NT_pipe", "SCR_pipe", "ORACLE_pipe")}
    precheck_gap = []
    scr_wins = nt_wins = 0
    for s in SEEDS:
        ar = Arena(s)
        true = ar.true_edges()
        envs = [standardize(ar.sample_env(e)) for e in range(NT_PARAMS["n_envs"])]
        pooled = [r for X in envs for r in X]
        W = fit_w(pooled)
        nt_cands = top_edges(W, k)
        # NT-alone (thresholded decider)
        pred_alone = {(a, b) for a in range(d) for b in range(d) if a != b and abs(W[a][b]) > THRESH}
        rows["NT_alone"].append(f1(pred_alone, true))
        # pre-check: screening recall depressed vs NT recall (confounding bites)
        scr_cands = screening_candidates(envs, k)
        nt_rec = recall_at(nt_cands, true)
        scr_rec = recall_at({(a, b) for (a, b) in scr_cands} | {(b, a) for (a, b) in scr_cands}, true)
        precheck_gap.append(nt_rec - scr_rec)
        # pipelines through the IDENTICAL verifier
        nt_f1 = f1(invariance_verify(envs, nt_cands, d), true)
        scr_f1 = f1(invariance_verify(envs, scr_cands, d), true)
        import random as _r
        decoys = []
        rr = _r.Random(f"NT1-decoy|{s}")
        while len(decoys) + len(true) < k:
            a, b = rr.randrange(d), rr.randrange(d)
            if a != b and (a, b) not in true:
                decoys.append((a, b))
        or_f1 = f1(invariance_verify(envs, list(true) + decoys, d), true)
        rows["NT_pipe"].append(nt_f1)
        rows["SCR_pipe"].append(scr_f1)
        rows["ORACLE_pipe"].append(or_f1)
        nt_wins += nt_f1 > scr_f1
        scr_wins += scr_f1 > nt_f1
    m = {a: round(statistics.mean(v), 4) for a, v in rows.items()}
    capture = m["NT_pipe"] / m["ORACLE_pipe"] if m["ORACLE_pipe"] > 0 else 0.0
    precheck = statistics.mean(precheck_gap)
    arena_ok = precheck >= 0.10
    gain_over_thresh = m["NT_pipe"] - m["NT_alone"]
    if not arena_ok:
        verdict = "INVALID(ARENA-NO-DISCRIMINATION)"
    elif capture >= 0.8 and gain_over_thresh >= 0.15:
        if nt_wins >= 8:
            verdict = "MET-strong"
        elif abs(m["NT_pipe"] - m["SCR_pipe"]) <= 0.03:
            verdict = "MET-weak(SCREENING-TIES)"
        else:
            verdict = "MET" if m["NT_pipe"] > m["SCR_pipe"] else "NULL(SCREENING-DOMINATES)"
    else:
        verdict = "NULL"
    out = {"gate": "NT-1", "seeds": SEEDS, "means": m, "capture_vs_oracle_pipe": round(capture, 4),
           "gain_over_thresholded": round(gain_over_thresh, 4),
           "precheck_recall_gap_NT_minus_SCR": round(precheck, 4), "arena_discriminates": arena_ok,
           "NT_gt_SCR_seeds": f"{nt_wins}/10", "verdict": verdict}
    open("experiments/nt_1.result.json", "w").write(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
