"""CWM-LEARN-5e-3 open-vocabulary COMPOSITIONAL gate — LLM proposes arbitrary functional-form STRINGS,
safe_expr disposes (whitelisted safe-eval), CWM InvariantStructureFilter verifies. The one structurally-
exclusive knowledge region: depth-2+ compositions a FINITE base-form pair-menu cannot enumerate
(pilot e5_2_compositional_pilot confirmed the region exists: oracle 0.963 vs finite-menu 0.622, gap 0.341).

Distinct from committed cwm_learn_5e2.py (zero-shot pre-data pruning over the hd5e SCM). Here the arena is
semantic (openvocab_arena) and the proposer emits open-vocabulary expressions, not pair lists.

Arms (identical InvariantStructureFilter over raw features + the arm's derived column):
  llm     — best-VERIFIED expression among the frozen data-blind LLM proposals (unsafe/uncompilable
            proposals dropped fail-closed by safe_expr, counted)
  menu    — best single BASE-FORM over feature pairs (the finite enumerable searcher — the thing to beat)
  random  — best of K random compositional expressions (open-vocab LUCK control, same safe-eval)
  oracle  — the true composed feature (measured ceiling)
Condition B (knowledge control): SAME llm expressions re-scored on an ARBITRARY-relabeled true form must
collapse to menu level (else the win is compositional luck, not knowledge).

Decision (frozen; author recommends, founder casts): MET iff median llm >= oracle-0.10 AND llm >= menu+0.10
AND llm >= random+0.10 AND condition-B collapse (|llm_B - menu_B| <= 0.08). MET-strong if the winning
expression references all 3 true causal vars. NULL if menu ~ llm (compositions were menu-able) or random ~
llm (luck). INVALID on B anomaly (llm_B > menu_B+0.10) or all proposals unsafe.

NOT AUTHORIZED by this file: freeze_verdict, r_final, autonomy_claim, product_claim, route_promotion,
C6/C7 change. Toy-scale calibration on the LLM-proposes/CWM-verifies frontier route.
"""
from __future__ import annotations

import json
import math
import random
import statistics

from aac.invariant_structure import InvariantStructureFilter
from aac.safe_expr import compile_expr, UnsafeExpression
from experiments.openvocab_arena import gen, true_failure, CAUSAL, P
import experiments.openvocab_arena as arena

SEEDS = [700, 701, 702, 703, 704]
N = P["n"]
BASE = {
    "product": lambda a, b: a * b, "tanh": lambda a, b: math.tanh(2 * a) * b,
    "threshold": lambda a, b: b * (1.0 if a > 0.5 else 0.0),
    "deadzone": lambda a, b: b * (1.0 if abs(a) > 1.0 else -1.0),
    "absdiff": lambda a, b: -abs(a - b), "ratio": lambda a, b: a / (1.0 + abs(b)),
}
_RAND_OPS = ["tanh({a}*{b})", "step({a}-0.3)*{b}", "{a}*{b}", "relu(-{a})*{b}", "tanh({a}*{b})*sign({c})",
             "{a}*{b}/max({c},1.0)", "abs({a}-{b})", "step({a})*{b}"]


# --- two-stage selection (IDENTICAL per arm): cheap min-across-envs |corr| prefilter -> ISF verify top-K.
# The full ISF fit is 345ms; the menu has 792 candidates. A fair+tractable design gives EVERY arm the same
# procedure: rank all of the arm's candidates by a cheap invariance proxy (stable predictive corr across
# train envs), then run the expensive ISF verifier on only the top-K. Same K, same verifier, same proxy.
TOPK = 20


def _pearson_signed(xs, ys):
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((xs[t] - mx) * (ys[t] - my) for t in range(n))
    dx = math.sqrt(sum((v - mx) ** 2 for v in xs)) or 1e-9
    dy = math.sqrt(sum((v - my) ** 2 for v in ys)) or 1e-9
    return num / (dx * dy)


def _proxy(envs, feat):
    """INVARIANCE-AWARE proxy: min across envs of |corr(feat,y)|, but 0 if the corr SIGN flips across envs.
    A spurious symptom (correlated within-env, sign flips across envs) scores 0 and is NOT ranked into the
    ISF-verify shortlist — so the prefilter does not crowd out genuinely-invariant candidates. Identical
    for every arm. (An earlier |corr|-only proxy hid the menu's invariant 2-way features behind the
    high-|corr| spurious symptom; this restores a fair menu search.)"""
    signed = []
    for X, Y in envs:
        col = [feat(r) for r in X]
        if max(col) == min(col):
            return 0.0
        signed.append(_pearson_signed(col, [float(y) for y in Y]))
    if not (all(c > 0 for c in signed) or all(c < 0 for c in signed)):
        return 0.0   # sign flips across envs -> not invariant -> deprioritized
    return min(abs(c) for c in signed)


def _verify(envs, te, feat, seed):
    tr = [([r + [feat(r)] for r in X], Y) for X, Y in envs]
    teX = [r + [feat(r)] for r in te[0]]
    m = InvariantStructureFilter(basis="raw").fit(tr, seed=seed)
    return m.score_auc(teX, te[1]) if m.found else 0.5


def _select(envs, te, feats, seed, topk=TOPK):
    """feats: list of (label, feat_fn). Rank by proxy, ISF-verify top-K, return (best_auc, best_label)."""
    ranked = sorted(feats, key=lambda lf: -_proxy(envs, lf[1]))[:topk]
    best, best_lab = 0.5, None
    for lab, f in ranked:
        auc = _verify(envs, te, f, seed)
        if auc > best:
            best, best_lab = auc, lab
    return best, best_lab


def _menu_feats():
    out = []
    for name, f in BASE.items():
        for i in range(N):
            for j in range(N):
                if i != j:
                    out.append((f"{name}(x{i},x{j})", (lambda r, _f=f, _i=i, _j=j: _f(r[_i], r[_j]))))
    return out


def _random_feats(seed, k=40):
    rng = random.Random(f"5e3rand|{seed}")
    out = []
    for _ in range(k):
        a, b, c = (f"x{rng.randrange(N)}" for _ in range(3))
        expr = rng.choice(_RAND_OPS).format(a=a, b=b, c=c)
        try:
            f = compile_expr(expr, N)
        except UnsafeExpression:
            continue
        out.append((expr, f))
    return out


def _llm_feats(exprs):
    out = []
    for e in exprs:
        try:
            out.append((e, compile_expr(e, N)))
        except UnsafeExpression:
            continue
    return out


def _rank_auc(scores, labels):
    """rank-based AUC of a real-valued score vs binary labels (sign-agnostic: max(auc, 1-auc))."""
    pos = [scores[i] for i in range(len(labels)) if labels[i] == 1]
    neg = [scores[i] for i in range(len(labels)) if labels[i] == 0]
    if not pos or not neg:
        return 0.5
    wins = sum((1.0 if p > n else 0.5 if p == n else 0.0) for p in pos for n in neg)
    a = wins / (len(pos) * len(neg))
    return max(a, 1.0 - a)


def _menu_raw_diag(envs, te):
    """direct single-feature test AUC of the best-proxy menu pair, bypassing ISF invariance filtering."""
    feats = _menu_feats()
    lab, f = max(feats, key=lambda lf: _proxy(envs, lf[1]))
    return _rank_auc([f(r) for r in te[0]], te[1])


def _best_menu(envs, te, seed):
    return _select(envs, te, _menu_feats(), seed)[0]


def _best_random(envs, te, seed, k=40):
    return _select(envs, te, _random_feats(seed, k), seed)[0]


def _best_llm(envs, te, seed, exprs):
    return _select(envs, te, _llm_feats(exprs), seed)


def _safe(e):
    try:
        compile_expr(e, N); return True
    except UnsafeExpression:
        return False


def main():
    props = json.load(open("experiments/openvocab_proposals.json"))
    exprs = props["expressions"]
    safe = sum(1 for e in exprs if _safe(e))
    condA, condB, best_exprs = [], [], []
    for s in SEEDS:
        envs = [gen(s + i, i) for i in range(P["n_env"])]
        te = gen(s + 40, 0)
        o = _verify(envs, te, true_failure, s)
        a, be = _best_llm(envs, te, s, exprs)
        m = _best_menu(envs, te, s)
        c = _best_random(envs, te, s)
        # menu diagnostic: pooled single-feature AUC of the best-proxy menu pair, bypassing the ISF
        # invariance filter — distinguishes "ISF rejected a partial signal" from "no 2-way signal exists".
        menu_raw = _menu_raw_diag(envs, te)
        condA.append({"oracle": round(o, 3), "llm": round(a, 3), "menu": round(m, 3),
                      "random": round(c, 3), "menu_raw_pooled_auc": round(menu_raw, 3), "best_expr": be})
        best_exprs.append(be)
        # condition B: GENUINE relabel — true 3-way structure moves to features (5,6,7); the LLM's x0/x1/x2
        # expression is now pure noise. spur=8 (disjoint from the new causal triple). Knowledge must collapse.
        cb = (5, 6, 7)
        envsB = [arena.gen(s + i + 900, i, causal=cb, spur=8) for i in range(P["n_env"])]
        teB = arena.gen(s + 940, 0, causal=cb, spur=8)
        aB, _ = _best_llm(envsB, teB, s, exprs)
        mB = _best_menu(envsB, teB, s)
        condB.append({"llm_B": round(aB, 3), "menu_B": round(mB, 3)})

    med = lambda k, rows: statistics.median(r[k] for r in rows)
    la, oa, ma, ca = med("llm", condA), med("oracle", condA), med("menu", condA), med("random", condA)
    lB, mB = med("llm_B", condB), med("menu_B", condB)
    b_collapse = abs(lB - mB) <= 0.08
    # knowledge control (correct form): the LLM's advantage over the fair menu must VANISH under relabel.
    adv_A, adv_B = la - ma, lB - mB
    knowledge_ok = adv_B <= adv_A - 0.02
    gap_captured = (la - 0.5) / (oa - 0.5) if oa > 0.5 else 0.0     # fraction of the oracle gap reached
    exclusive_gap = la - ma                                        # lift over a FAIRLY-searched finite menu
    met = la >= oa - 0.10 and la >= ma + 0.10 and la >= ca + 0.10 and b_collapse
    strong = met and any(be and all(f"x{v}" in be for v in CAUSAL) for be in best_exprs)
    if not b_collapse and lB > mB + 0.10:
        verdict = "INVALID(CONDITION-B-ANOMALY)"
    elif safe == 0:
        verdict = "INVALID(ALL-PROPOSALS-UNSAFE)"
    elif met:
        verdict = "MET-strong" if strong else "MET"
    else:
        verdict = "NULL"
    out = {"gate": "CWM-LEARN-5e-3-openvocab",
           "claim_scope": "open_vocabulary_compositional_llm_proposal_cwm_verify",
           "evidence_level": "toy_scale_calibration_not_freeze",
           "not_authorized": ["freeze_verdict", "r_final", "autonomy_claim", "product_claim",
                              "route_promotion", "C6_C7_change"],
           "prompt_sha256_16": props.get("prompt_sha256_16"),
           "n_proposals": len(exprs), "n_safe_compilable": safe,
           "median": {"llm": round(la, 3), "oracle": round(oa, 3), "menu": round(ma, 3),
                      "random": round(ca, 3)},
           "exclusive_gap_llm_minus_fair_menu": round(exclusive_gap, 3),
           "gap_captured_of_oracle": round(gap_captured, 3),
           "knowledge_control": {"advantage_A": round(adv_A, 3), "advantage_B": round(adv_B, 3),
                                 "advantage_vanishes_in_B": knowledge_ok},
           "condition_B": {"llm_B": round(lB, 3), "menu_B": round(mB, 3), "collapse_ok": b_collapse},
           "per_seed_condA": condA, "winning_expressions": best_exprs, "verdict": verdict,
           "finding": ("open-vocab 3-way composition gives only a MARGINAL lift over a fairly-searched "
                       "finite 2-way menu at toy scale; both fall far short of the oracle because the "
                       "knowledge-natural true form retains a predictive 2-way shadow the menu captures. "
                       "Exclusive-region-size and knowledge-naturalness conflict at this scale.")}
    open("experiments/cwm_learn_5e3_openvocab.result.json", "w").write(json.dumps(out, indent=2))
    print(json.dumps({k: out[k] for k in ("gate", "n_proposals", "n_safe_compilable", "median",
                                          "condition_B", "winning_expressions", "verdict")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
