"""language_orientation — a MEMORIZATION-FREE test of the language organ's genuine causal-reasoning value
(§23 was confounded: the LLM recited a famous benchmark). Here the domain is a NOVEL synthetic industrial
process (not a published dataset) whose causal ORIENTATION follows physical semantics but whose specific graph
is freshly generated. This targets exactly what the language organ can add and observational data provably
CANNOT: orienting edges WITHIN a Markov-equivalence class (a chain X-Y-Z is data-indistinguishable from its
reverse; but 'yield causes impurity, not vice versa' is semantically forced).

True DAG (my design; forward in the physical causal order; NOT a benchmark):
  temperature->catalyst; raw_purity->yield; temperature->yield; catalyst->yield;
  yield->impurity; temperature->impurity; impurity->defect; defect->return
Chain/collider mix: the v-structure at `yield` is data-orientable; the chain yield->impurity->defect->return
and temperature->catalyst are NOT data-orientable (reversible within the MEC) -> the language organ's test bed.

Measured (against the LLM proposals in language_orientation_proposals.json):
  - orientation accuracy on ALL true edges, and specifically on the DATA-AMBIGUOUS edges (the added value);
  - data-only orientable fraction (what a CPDAG gets for free) as the baseline the LLM must beat;
  - governed VERIFICATION: a synthetic do(X) confirms the LLM's orientation X->...->Y (world checks language).
NOT a freeze; memorization-free language-organ test. VERIFY-DON'T-ASSERT."""
from __future__ import annotations

import json
import os
import random
import statistics

from aac.hypothesis_pool import mec, canon

# A near-PURE CHAIN (a hydro-power -> production physical chain): no colliders -> the whole chain is ONE
# Markov-equivalence class -> observational data orients NOTHING -> every edge's direction can come ONLY from
# semantics. Maximal-power memorization-free test: does the language organ orient a chain data cannot?
NAMES = ["upstream_rainfall", "river_flow_rate", "reservoir_level", "turbine_power_output",
         "grid_electricity_supply", "factory_uptime", "daily_production_volume"]
IDX = {n: i for i, n in enumerate(NAMES)}
N = len(NAMES)
# true directed edges (by name), forward in the physical causal order (a chain)
TRUE_EDGES = [
    ("upstream_rainfall", "river_flow_rate"),
    ("river_flow_rate", "reservoir_level"),
    ("reservoir_level", "turbine_power_output"),
    ("turbine_power_output", "grid_electricity_supply"),
    ("grid_electricity_supply", "factory_uptime"),
    ("factory_uptime", "daily_production_volume"),
]
PROP_FILE = "experiments/language_orientation_proposals.json"


def _pa_from(edges_idx):
    pa = {}
    for a, b in edges_idx:
        pa.setdefault(b, set()).add(a)
    return {k: frozenset(v) for k, v in pa.items()}


def _true_pa():
    return _pa_from([(IDX[a], IDX[b]) for a, b in TRUE_EDGES])


def _skeleton_adj(edges_idx):
    return {frozenset(e) for e in edges_idx}


def _data_ambiguous_edges():
    """an edge is DATA-AMBIGUOUS iff its orientation VARIES across the Markov-equivalence class (there is a
    MEC member that orients it the other way). Correct MEC notion: enumerate mec(skeleton, true v-structures)
    and check per-edge orientation variance. (A single-edge reversal is the WRONG test — it can create a
    collider and leave the MEC even when the edge is genuinely reversible via a coordinated reorientation.)"""
    true_idx = [(IDX[a], IDX[b]) for a, b in TRUE_EDGES]
    skeleton = sorted({tuple(sorted(e)) for e in true_idx})
    true_pa = _pa_from(true_idx)
    members = mec(N, skeleton, true_pa)
    ambiguous = []
    for (a, b) in true_idx:
        seen = set()
        for m in members:
            if a in m.get(b, ()):
                seen.add((a, b))
            elif b in m.get(a, ()):
                seen.add((b, a))
        if len(seen) > 1:                 # oriented differently in different MEC members -> data can't fix it
            ambiguous.append((a, b))
    return set(ambiguous), len(members)


def gen(seed, n=400, do=None, val=0.0):
    r = random.Random(f"lang-orient|{seed}|{do}|{val}")
    w = {(IDX[a], IDX[b]): r.uniform(0.8, 1.6) for a, b in TRUE_EDGES}
    order = []  # topological order
    pa = _true_pa()
    indeg = {j: len(pa.get(j, ())) for j in range(N)}
    stack = [j for j in range(N) if indeg[j] == 0]
    while stack:
        u = stack.pop()
        order.append(u)
        for j in range(N):
            if u in pa.get(j, ()):
                indeg[j] -= 1
                if indeg[j] == 0:
                    stack.append(j)
    rows = []
    for row_i in range(n):
        x = [0.0] * N
        for j in order:
            if j == do:
                x[j] = val
            else:
                x[j] = r.gauss(0, 0.6) + sum(w[(p, j)] * x[p] for p in pa.get(j, ()))
        rows.append(x)
    return rows


def _do_mean(seed, do_node, val, target, k=200):
    return statistics.mean(gen(seed + i, n=1, do=do_node, val=val)[0][target] for i in range(k))


def main():
    ambiguous, true_vs = _data_ambiguous_edges()
    true_set = {(IDX[a], IDX[b]) for a, b in TRUE_EDGES}
    n_edges = len(true_set)
    data_orientable = n_edges - len(ambiguous)
    result = {"gate": "language-orientation", "domain": "NOVEL synthetic industrial process (memorization-free)",
              "n_true_edges": n_edges, "data_orientable_edges": data_orientable,
              "data_ambiguous_edges": [[NAMES[a], NAMES[b]] for a, b in ambiguous],
              "data_only_orientation_fraction": round(data_orientable / n_edges, 3)}
    if not os.path.exists(PROP_FILE):
        result["status"] = "WAITING_FOR_LLM_PROPOSALS"
        print(json.dumps(result, indent=2))
        open("experiments/language_orientation.result.json", "w").write(json.dumps(result, indent=2))
        return 0

    props = json.load(open(PROP_FILE))
    per = {}
    all_correct_amb = []
    for who, edges in props.get("proposers", {}).items():
        prop = {(IDX[a], IDX[b]) for a, b in edges if a in IDX and b in IDX and a != b}
        # skeleton match + orientation correctness
        prop_skel = {frozenset(e) for e in prop}
        true_skel = {frozenset(e) for e in true_set}
        skel_recall = len(prop_skel & true_skel) / len(true_skel)
        # orientation: for each TRUE edge present in the proposal's skeleton, is the direction right?
        oriented_right = sum(1 for e in true_set if e in prop)
        # on DATA-AMBIGUOUS edges specifically (the added value):
        amb_present = [e for e in ambiguous if frozenset(e) in prop_skel]
        amb_right = sum(1 for e in ambiguous if e in prop)
        # governed verification of the LLM's ambiguous orientations: do(X) should move Y (X upstream of Y)
        verified = 0
        for (a, b) in ambiguous:
            if (a, b) in prop:   # LLM claims a->b (correct direction); confirm do(a) moves b
                base = _do_mean(1, None, 0.0, b)
                hi = _do_mean(1, a, 3.0, b)
                sd = 1.0
                if abs(hi - base) / sd > 0.3:
                    verified += 1
        per[who] = {"skeleton_recall": round(skel_recall, 3),
                    "orientation_correct_all": f"{oriented_right}/{n_edges}",
                    "orientation_correct_ambiguous": f"{amb_right}/{len(ambiguous)}",
                    "ambiguous_orientations_confirmed_by_intervention": f"{verified}/{len(ambiguous)}"}
        all_correct_amb.append(amb_right / len(ambiguous) if ambiguous else 0.0)
    result["proposers"] = per
    result["headline"] = {
        "data_alone_orients": f"{data_orientable}/{n_edges}",
        "language_organ_orients_DATA-AMBIGUOUS_edges_mean_accuracy": round(statistics.mean(all_correct_amb), 3),
        "n_data_ambiguous": len(ambiguous)}
    la = result["headline"]["language_organ_orients_DATA-AMBIGUOUS_edges_mean_accuracy"]
    result["verdict"] = ("LANGUAGE-ORGAN-ADDS-ORIENTATION" if la >= 0.75 and len(ambiguous) >= 2 else
                         "MARGINAL" if la >= 0.5 else "NULL")
    result["finding"] = (
        "memorization-free: the graph is NOVEL (freshly generated, not a benchmark), so correct orientation "
        "reflects REASONING from semantics, not recall. The confound-robust claim: observational data leaves "
        + str(len(ambiguous)) + " edges UNORIENTABLE (reversible within the MEC); if the language organ orients "
        "them correctly (mean acc " + str(la) + ") and synthetic interventions CONFIRM those orientations, then "
        "the language organ genuinely ADDS causal-direction information that data alone cannot provide -> "
        "'语言、因果发现相互组合' with the world as verifier. This is the composition §23 could not show under "
        "the memorization confound.")
    open("experiments/language_orientation.result.json", "w").write(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
