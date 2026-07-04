"""5e-2 FORMS arena + pilot (calibration): true mechanism uses NON-ENUMERABLE functional forms.
Load-bearing pilot question: PRODUCT-PROXY LEAKAGE — can plain x_a*x_b capture a threshold/saturation/
ratio mechanism well enough to verify? Arena is legitimate iff oracle-FORM verified AUC >> best
product-proxy verified AUC (the knowledge channel's exclusive region exists structurally)."""
from __future__ import annotations

import json
import math
import random
import statistics

from aac.invariant_structure import InvariantStructureFilter

FORMS = {
    "threshold": lambda a, b: b * (1.0 if a > 0.5 else 0.0),
    "saturation": lambda a, b: b * math.tanh(2.0 * a),
    "ratio": lambda a, b: a / (1.0 + abs(b)),
}
P = {"n_raw": 20, "n_envs": 3, "n": 300, "noise": 0.6, "spur_c": [1.5, -1.2, 0.9], "beta": 1.6}
SEEDS = [500, 501, 502]


def gen(seed, form_name, pair, env_i):
    r = random.Random(f"5e2f|{seed}|{form_name}|{env_i}")
    f = FORMS[form_name]
    a_i, b_i = pair
    rows, ys = [], []
    for _ in range(P["n"]):
        x = [r.gauss(0, 1) for _ in range(P["n_raw"])]
        t = P["beta"] * f(x[a_i], x[b_i]) + r.gauss(0, P["noise"])
        y = 1 if t > 0 else 0
        x[5] += P["spur_c"][env_i] * (2 * y - 1) + r.gauss(0, 0.8)   # env-flipping spurious
        rows.append(x)
        ys.append(y)
    return rows, ys


def verify_with_feature(envs, te, feat_fn, seed):
    tr = [( [r + [feat_fn(r)] for r in X], Y) for X, Y in envs]
    teX = [r + [feat_fn(r)] for r in te[0]]
    m = InvariantStructureFilter(basis="raw").fit(tr, seed=seed)
    return m.score_auc(teX, te[1]) if m.found else 0.5


def main():
    out = {"per_form": {}}
    for form_name in FORMS:
        pair = (2, 7)
        o_scores, p_scores, w_scores = [], [], []
        for s in SEEDS:
            envs = [gen(s + i, form_name, pair, i) for i in range(P["n_envs"])]
            te = gen(s + 50, form_name, pair, 0)
            f_true = FORMS[form_name]
            o_scores.append(verify_with_feature(envs, te, lambda r: f_true(r[pair[0]], r[pair[1]]), s))
            p_scores.append(verify_with_feature(envs, te, lambda r: r[pair[0]] * r[pair[1]], s))
            fw = FORMS["saturation" if form_name != "saturation" else "threshold"]
            w_scores.append(verify_with_feature(envs, te, lambda r: fw(r[pair[0]], r[pair[1]]), s))
        out["per_form"][form_name] = {
            "oracle_form_auc": round(statistics.mean(o_scores), 3),
            "product_proxy_auc": round(statistics.mean(p_scores), 3),
            "wrong_form_auc": round(statistics.mean(w_scores), 3),
            "exclusive_gap": round(statistics.mean(o_scores) - statistics.mean(p_scores), 3)}
        print(form_name, json.dumps(out["per_form"][form_name]))
    gaps = [v["exclusive_gap"] for v in out["per_form"].values()]
    out["arena_legitimate_forms"] = [k for k, v in out["per_form"].items() if v["exclusive_gap"] >= 0.05]
    open("experiments/e5_2_forms_pilot.result.json", "w").write(json.dumps(out, indent=2))
    print(json.dumps({k: v for k, v in out.items() if k != "per_form"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
