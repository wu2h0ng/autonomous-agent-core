"""5e-2 decisive cheap baseline: FORM-AWARE ENUMERATING SCREENER — with a finite public form menu,
rank ALL form x pair features by min-env |corr|, take top-1, verify. If it reaches the oracle, the
finite-menu knowledge region is EMPTY too (the only exclusive region = OPEN-VOCABULARY form proposal)."""
from __future__ import annotations

import json
import math
import statistics

from experiments.e5_2_forms2_pilot import FORMS, P, SEEDS, gen, verify_with_feature

MENU = dict(FORMS)
MENU["product"] = lambda a, b: a * b
MENU["threshold"] = lambda a, b: b * (1.0 if a > 0.5 else 0.0)
MENU["saturation"] = lambda a, b: b * math.tanh(2.0 * a)


def form_screen_best(envs, k_pairs=20):
    """Rank all form x (i,j) features by min-env |corr with y|; return the top feature fn."""
    n = P["n_raw"]
    best_key, best_score = None, -1.0
    for fname, f in MENU.items():
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                worst = None
                for X, Y in envs:
                    ym = statistics.mean(Y)
                    ys = statistics.pstdev(Y) or 1.0
                    v = [f(r[i], r[j]) for r in X]
                    vm = statistics.mean(v)
                    vs = statistics.pstdev(v) or 1.0
                    c = abs(sum((v[t] - vm) * (Y[t] - ym) for t in range(len(v))) / (len(v) * vs * ys))
                    worst = c if worst is None else min(worst, c)
                if worst > best_score:
                    best_score, best_key = worst, (fname, i, j)
    fname, i, j = best_key
    return best_key, (lambda r, _f=MENU[fname], _i=i, _j=j: _f(r[_i], r[_j]))


def main():
    out = {}
    for form_name in ("deadzone", "absdiff"):
        pair = (2, 7)
        o, fs = [], []
        hits = 0
        for s in SEEDS:
            envs = [gen(s + i, form_name, pair, i) for i in range(P["n_envs"])]
            te = gen(s + 50, form_name, pair, 0)
            f_true = FORMS[form_name]
            o.append(verify_with_feature(envs, te, lambda r: f_true(r[pair[0]], r[pair[1]]), s))
            key, feat = form_screen_best(envs)
            fs.append(verify_with_feature(envs, te, feat, s))
            hits += (key[0] == form_name and {key[1], key[2]} == set(pair))
        out[form_name] = {"oracle": round(statistics.mean(o), 3),
                          "form_aware_screener": round(statistics.mean(fs), 3),
                          "screener_found_true_combo": f"{hits}/{len(SEEDS)}",
                          "gap": round(statistics.mean(o) - statistics.mean(fs), 3)}
        print(form_name, json.dumps(out[form_name]))
    open("experiments/e5_2_formscreen.result.json", "w").write(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
