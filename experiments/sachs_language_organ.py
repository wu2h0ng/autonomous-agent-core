"""sachs_language_organ — compose the LANGUAGE organ (LLM domain knowledge) with the CAUSAL-VERIFY organ
(real governed interventions) on REAL Sachs biology, attacking the Stop-hook's untouched 'no language / no
cross-domain semantic transfer' gap. The goal: '语言、因果发现、信念、自我模型相互组合'.

The LLM proposes DIRECTED causal edges among the 11 proteins FROM THE NAMES ALONE (semantic/biology
knowledge, no data). We then measure — against REAL interventional ground truth:
  1. structure recovery: LLM-proposed skeleton vs the data-only precision-matrix skeleton vs ground truth.
  2. 强 (the confound-robust question): does LLM-ancestry predict REAL interventional effects better than
     observational CORRELATION? (does semantic knowledge beat surface correlation on real interventions?)
  3. COMPOSITION (the architecture point): do the REAL interventions VERIFY/CORRECT the LLM's edges? For each
     LLM edge X->T with X intervenable, does do(X) actually move T? -> the causal organ catches language errors.

HONEST CONFOUND (disclosed, not hidden): Sachs is a FAMOUS benchmark; the LLM's knowledge may include the
published network (memorization), so structure-recovery numbers are an UPPER bound on genuine reasoning. The
confound-ROBUST claims are #2 (semantic knowledge vs correlation on real interventions) and #3 (intervention
verifying/correcting the language organ) — neither is helped by memorizing the consensus DAG per se, since #2
compares to correlation and #3 tests whether the WORLD agrees with the LLM. NOT a freeze; real-data honest."""
from __future__ import annotations

import json
import math
import os
import statistics

from experiments.sachs_task import (load_obs, load_int, PROTEINS, INTERVENABLE, GROUND_TRUTH,
                                    ancestors, correlation)
from experiments.sachs_openworld import part1_skeleton

N = len(PROTEINS)
EFFECT_THRESHOLD = 0.30
CORR_THRESHOLD = 0.30
PROP_FILE = "experiments/sachs_llm_proposals.json"


def _llm_ancestors(edges, node):
    """ancestors of `node` under the LLM's DIRECTED edge set."""
    parents = {}
    for a, b in edges:
        parents.setdefault(b, set()).add(a)
    seen, stack = set(), list(parents.get(node, set()))
    while stack:
        p = stack.pop()
        if p in seen:
            continue
        seen.add(p)
        stack.extend(parents.get(p, set()))
    return seen


def _skeleton_scores(edges):
    prop = {frozenset({a, b}) for a, b in edges if a in PROTEINS and b in PROTEINS}
    true_sk = {frozenset({a, b}) for a, b in GROUND_TRUTH}
    tp = len(prop & true_sk)
    return {"proposed": len(prop), "recovered": tp, "true": len(true_sk),
            "recall": round(tp / len(true_sk), 3), "precision": round(tp / len(prop), 3) if prop else 0.0}


def _effect_confusion(edges, obs, by_code):
    """for each intervenable X and target T: real interventional effect vs LLM-ancestry vs correlation."""
    obs_base = {t: [r[t] for r in by_code.get(0, [])] for t in range(N)}
    conf = {"llm_TP": 0, "llm_FP": 0, "llm_TN": 0, "llm_FN": 0,
            "corr_TP": 0, "corr_FP": 0, "corr_TN": 0, "corr_FN": 0}
    llm_edge_verify = {"confirmed": 0, "refuted": 0}     # LLM edges X->T (X intervenable): does do(X) move T?
    for name, code in INTERVENABLE.items():
        xi = PROTEINS.index(name)
        do_rows = by_code.get(code, [])
        if len(do_rows) < 20:
            continue
        llm_anc_of = {PROTEINS[t]: (name in _llm_ancestors(edges, PROTEINS[t])) for t in range(N)}
        direct_targets = {b for a, b in edges if a == name}
        for t in range(N):
            if t == xi:
                continue
            tname = PROTEINS[t]
            do_vals = [r[t] for r in do_rows]
            ob = obs_base[t]
            sd = (statistics.pstdev(ob) + statistics.pstdev(do_vals)) / 2 or 1e-9
            real = abs(statistics.mean(do_vals) - statistics.mean(ob)) / sd > EFFECT_THRESHOLD
            llm_pred = llm_anc_of[tname]
            corr_pred = abs(correlation(obs, xi, t)) > CORR_THRESHOLD
            for tag, pred in (("llm", llm_pred), ("corr", corr_pred)):
                k = "TP" if pred and real else "FP" if pred and not real else "FN" if real else "TN"
                conf[f"{tag}_{k}"] += 1
            if tname in direct_targets:                  # composition: verify LLM's DIRECT edge by do(X)
                llm_edge_verify["confirmed" if real else "refuted"] += 1
    return conf, llm_edge_verify


def _acc(conf, tag):
    tp, fp, tn, fn = (conf[f"{tag}_{k}"] for k in ("TP", "FP", "TN", "FN"))
    tot = tp + fp + tn + fn
    return round((tp + tn) / tot, 3) if tot else None


def main():
    if not os.path.exists(PROP_FILE):
        print(json.dumps({"status": "WAITING", "note": f"populate {PROP_FILE} with LLM edges first"}))
        return 0
    props = json.load(open(PROP_FILE))
    obs = load_obs()
    intdata = load_int()
    by_code = {}
    for vals, code in intdata:
        by_code.setdefault(code, []).append(vals)

    data_skeleton = part1_skeleton(obs)
    out = {"gate": "sachs-language-organ",
           "domain": "REAL Sachs (LLM proposes structure from NAMES; real interventions verify)",
           "data_only_skeleton_best_recall": max(v["recall"] for v in data_skeleton.values()),
           "proposers": {}}
    all_edges = []
    for who, edges in props.get("proposers", {}).items():
        norm = [[a, b] for a, b in edges if a in PROTEINS and b in PROTEINS and a != b]
        all_edges += norm
        conf, verify = _effect_confusion(norm, obs, by_code)
        out["proposers"][who] = {
            "n_edges": len(norm), "skeleton_vs_truth": _skeleton_scores(norm),
            "llm_ancestry_effect_accuracy": _acc(conf, "llm"),
            "correlation_effect_accuracy": _acc(conf, "corr"),
            "llm_direct_edges_confirmed_by_intervention": verify}
    # union of proposers
    uniq = [list(e) for e in {tuple(x) for x in all_edges}]
    conf_u, verify_u = _effect_confusion(uniq, obs, by_code)
    out["union"] = {"n_edges": len(uniq), "skeleton_vs_truth": _skeleton_scores(uniq),
                    "llm_ancestry_effect_accuracy": _acc(conf_u, "llm"),
                    "correlation_effect_accuracy": _acc(conf_u, "corr"),
                    "llm_direct_edges_confirmed_by_intervention": verify_u}
    la = out["union"]["llm_ancestry_effect_accuracy"]
    ca = out["union"]["correlation_effect_accuracy"]
    gt = 0.62   # §22 ground-truth-ancestry effect accuracy, for reference
    out["headline"] = {
        "language_organ_beats_correlation_on_real_interventions": (la is not None and ca is not None and la > ca),
        "llm_ancestry_acc": la, "correlation_acc": ca, "ground_truth_ancestry_acc_ref": gt,
        "llm_skeleton_recall": out["union"]["skeleton_vs_truth"]["recall"],
        "data_skeleton_recall": out["data_only_skeleton_best_recall"],
        "llm_edges_confirmed_by_world": verify_u}
    refuted = verify_u["refuted"]
    confirmed = verify_u["confirmed"]
    # MEMORIZATION-AWARE verdict: skeleton recall ~1.0 on a famous benchmark that BOTH proposers self-reported
    # reciting is NOT reasoning. The language-organ-REASONING claim is unsupported here. What survives the
    # confound: (a) structure (even memorized) beats correlation on real interventions; (b) real interventions
    # CORRECT expert-consensus belief (edges refuted).
    memorized = out["union"]["skeleton_vs_truth"]["recall"] >= 0.9
    out["verdict"] = ("MEMORIZATION-CONFOUNDED" if memorized else
                      "LANGUAGE-ORGAN-REASONS" if la and ca and la > ca and la >= 0.55 else "NULL")
    out["what_holds_confound_robust"] = {
        "structure_beats_correlation_on_real_interventions": (la is not None and ca is not None and la > ca),
        "world_corrects_expert_belief_(consensus_edges_refuted_by_intervention)": refuted,
        "consensus_direct_edges_confirmed": confirmed}
    out["what_does_NOT_hold"] = ("language-organ REASONING is NOT demonstrated: skeleton recall ~1.0 and BOTH "
                                 "proposers explicitly self-reported reciting the famous Sachs benchmark -> this "
                                 "is memorization/recall, not causal reasoning from semantics. The §22 result "
                                 "(structure beats correlation) is replicated but with a MEMORIZED structure, "
                                 "so it adds no genuine language-organ evidence.")
    out["confound_disclosure"] = ("Sachs is a famous benchmark and BOTH LLM proposers SELF-REPORTED reciting "
                                  "its consensus network -> memorization confound CONFIRMED, not merely "
                                  "possible. A genuine language-organ-reasoning test needs a domain NOT in "
                                  "training data (hard: any real domain the LLM knows is memorizable; a "
                                  "synthetic domain has no semantics to reason from) -- the same knowledge-vs-"
                                  "naturalness tension as 5e-3. The ONLY confound-robust value here is the "
                                  "COMPOSITION: real interventions refuted " + str(refuted) + " of the "
                                  "consensus direct edges -> the world corrects even expert belief.")
    open("experiments/sachs_language_organ.result.json", "w").write(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
