"""CWM-LEARN-5e scored gate — data-blind LLM knowledge pruning of the interaction hypothesis space
(design: CWM-LEARN-5E.DESIGN-2026-07-04; pilot: regime CONFIRMED at n_raw=60, median normalized 0.564).

Arms (identical verifier InvariantStructureFilter; every arm = 60 raw features + its candidate-pair columns
pre-expanded, basis="raw"; exhaustive uses basis="cross2" = the full 1,830-coordinate space):
  a llm        — union of 5 data-blind LLM proposals (frozen verbatim in hd5e_proposals.json), freq-ranked,
                 capped at 30 pairs
  b exhaustive — all 1,770 pairs (the cheap baseline that must be beaten)
  c random     — 20 draws of |union| random pairs per seed (luck control; per-seed MEDIAN)
  d oracle     — the true pairs (measured ceiling)
  e screening  — top-|union| pairs by min-across-train-envs |corr(x_i*x_j, y)| (cheapest DATA-USING proposer)
Condition A (congruent names) = full arms; condition B (same proposals, arbitrary true structure) = a/c/d —
the knowledge control: if arm-a also wins in B, the win is not knowledge -> INVALID.

Normalized score s = (AUC-0.5)/(AUC_oracle-0.5); found=False => AUC 0.5 => s=0 (reported).
Decision (frozen; author recommends, founder casts):
  MET  iff median s_a >= 0.8 AND a>b in >=9/10 AND a>median-random in >=9/10 AND condition-B collapse
       (median s_a_B within 0.10 of median s_c_B). Tier: MET-strong if a>e in >=8/10; MET-weak if
       |median s_a - median s_e| <= 0.05 (data-free matching data-using is the finding; tiers never conflated).
  NULL iff b ~ a (enumeration suffices) or a ~ c (prior = luck) or e >> a (screening dominates; park knowledge
       route, record lesson).
  INVALID iff condition-B anomaly (a wins where knowledge cannot), prompt/schema/proposal hash mismatch, or
       digest drift.
"""
from __future__ import annotations

import json
import random
import statistics

import experiments.synthetic_scm_highdim as hd
from aac.invariant_structure import InvariantStructureFilter

SEEDS = list(range(10))
N_RANDOM_DRAWS = 20
CAP = 30


def _load():
    with open("experiments/hd5e_schema.json", encoding="utf-8") as fh:
        schema = json.load(fh)
    with open("experiments/hd5e_proposals.json", encoding="utf-8") as fh:
        props = json.load(fh)
    name_to_idx = {n: i for i, n in enumerate(schema["names"])}
    freq: dict[tuple[int, int], list] = {}
    for pi, prop in enumerate(props["proposals"]):
        for rank, (na, nb) in enumerate(prop["pairs"]):
            if na not in name_to_idx or nb not in name_to_idx or na == nb:
                continue   # malformed entries dropped, counted in the prereg audit
            key = tuple(sorted((name_to_idx[na], name_to_idx[nb])))
            freq.setdefault(key, []).append((pi, rank))
    ranked = sorted(freq.items(), key=lambda kv: (-len(kv[1]), min(r for _, r in kv[1])))
    union = [list(k) for k, _ in ranked[:CAP]]
    return schema, union


def _fit_score(tr, teX, teY, pairs, seed):
    f = InvariantStructureFilter(basis="raw")
    m = f.fit([(hd.expand_pairs(X, pairs), Y) for X, Y in tr], seed=seed)
    return m.score_auc(hd.expand_pairs(teX, pairs), teY) if m.found else 0.5


def _norm(auc, oracle_auc):
    return (auc - 0.5) / (oracle_auc - 0.5) if oracle_auc > 0.5 else 0.0


def _screen_pairs(tr, k):
    n = hd.HD_PARAMS["n_raw"]
    best = {}
    for (X, Y) in tr:
        ymean = statistics.mean(Y)
        ysd = statistics.pstdev(Y) or 1.0
        for i in range(n):
            for j in range(i + 1, n):
                v = [r[i] * r[j] for r in X]
                vm = statistics.mean(v)
                vs = statistics.pstdev(v) or 1.0
                c = abs(sum((v[t] - vm) * (Y[t] - ymean) for t in range(len(v))) / (len(v) * vs * ysd))
                key = (i, j)
                best[key] = min(best.get(key, 1e9), c)
    return [list(k) for k, _ in sorted(best.items(), key=lambda kv: -kv[1])[:k]]


def main():
    schema, union = _load()
    kA = len(union)
    out = {"gate": "CWM-LEARN-5e", "union_size": kA, "union_pairs_idx": union, "seeds": SEEDS,
           "condA": {"per_seed": []}, "condB": {"per_seed": []}}
    tpB, tlB = schema["condB_true_pairs"], schema["condB_true_linear"]

    for s in SEEDS:
        # ---- condition A ----
        tr = hd.train_envs_hd(s)
        teX, teY = hd.test_env_hd(s)
        d = _fit_score(tr, teX, teY, schema["condA_true_pairs"], s)
        a = _fit_score(tr, teX, teY, union, s)
        fb = InvariantStructureFilter(basis="cross2").fit(tr, seed=s)
        b = fb.score_auc(teX, teY) if fb.found else 0.5
        rands = []
        allp = [(i, j) for i in range(60) for j in range(i + 1, 60)]
        for dr in range(N_RANDOM_DRAWS):
            rp = [list(p) for p in random.Random(f"5e|{s}|{dr}").sample(allp, kA)]
            rands.append(_fit_score(tr, teX, teY, rp, s))
        e = _fit_score(tr, teX, teY, _screen_pairs(tr, kA), s)
        rec = {"seed": s, "oracle": round(d, 4), "llm": round(a, 4), "exhaustive": round(b, 4),
               "random_median": round(statistics.median(rands), 4), "screening": round(e, 4),
               "s_llm": round(_norm(a, d), 4), "s_exh": round(_norm(b, d), 4),
               "s_rand": round(_norm(statistics.median(rands), d), 4), "s_screen": round(_norm(e, d), 4)}
        out["condA"]["per_seed"].append(rec)
        print("A", json.dumps(rec))
        # ---- condition B (same proposals; arbitrary true structure) ----
        trB = hd.train_envs_hd(s, tpB, tlB)
        teXB, teYB = hd.test_env_hd(s, tpB, tlB)
        dB = _fit_score(trB, teXB, teYB, tpB, s)
        aB = _fit_score(trB, teXB, teYB, union, s)
        randsB = []
        for dr in range(N_RANDOM_DRAWS):
            rp = [list(p) for p in random.Random(f"5eB|{s}|{dr}").sample(allp, kA)]
            randsB.append(_fit_score(trB, teXB, teYB, rp, s))
        recB = {"seed": s, "oracle_B": round(dB, 4), "llm_B": round(aB, 4),
                "random_median_B": round(statistics.median(randsB), 4),
                "s_llm_B": round(_norm(aB, dB), 4), "s_rand_B": round(_norm(statistics.median(randsB), dB), 4)}
        out["condB"]["per_seed"].append(recB)
        print("B", json.dumps(recB))

    A = out["condA"]["per_seed"]
    B = out["condB"]["per_seed"]
    med = lambda k, rows: statistics.median(r[k] for r in rows)
    wins_ab = sum(1 for r in A if r["llm"] > r["exhaustive"])
    wins_ac = sum(1 for r in A if r["llm"] > r["random_median"])
    wins_ae = sum(1 for r in A if r["llm"] > r["screening"])
    s_a, s_e = med("s_llm", A), med("s_screen", A)
    b_collapse = abs(med("s_llm_B", B) - med("s_rand_B", B)) <= 0.10
    met = s_a >= 0.8 and wins_ab >= 9 and wins_ac >= 9 and b_collapse
    if not b_collapse and med("s_llm_B", B) > med("s_rand_B", B) + 0.10:
        verdict = "INVALID(CONDITION-B-ANOMALY)"
    elif met:
        verdict = "MET-strong" if wins_ae >= 8 else ("MET-weak" if abs(s_a - s_e) <= 0.05 else "MET")
    else:
        verdict = "NULL"
    out["summary"] = {"median_s_llm": round(s_a, 4), "median_s_exh": round(med("s_exh", A), 4),
                      "median_s_rand": round(med("s_rand", A), 4), "median_s_screen": round(s_e, 4),
                      "wins_llm_gt_exh": f"{wins_ab}/10", "wins_llm_gt_rand": f"{wins_ac}/10",
                      "wins_llm_gt_screen": f"{wins_ae}/10",
                      "condB": {"median_s_llm_B": round(med("s_llm_B", B), 4),
                                "median_s_rand_B": round(med("s_rand_B", B), 4), "collapse_ok": b_collapse},
                      "verdict": verdict}
    with open("experiments/cwm_learn_5e.result.json", "w") as f:
        json.dump(out, f, indent=2)
    print(json.dumps(out["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
