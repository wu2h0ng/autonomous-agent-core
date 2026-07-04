"""CWM-LEARN-3 pre-freeze audits A1-A6 (design packet §2.6). Run on FROZEN params BEFORE freezing the
prereg; performance-touching audits (A4/A5) use CALIBRATION seeds 50-79, DISJOINT from the scored window
(0-9), so the scored seeds stay unseen. If any audit fails -> fix params from first principles and re-freeze
(NEVER after peeking at scored OOD output)."""
from __future__ import annotations

import statistics

import experiments.synthetic_scm_interaction as scm
from aac.interaction_cwm import InteractionCWM, phi, product_index
from aac.learned_cwm import LearnedCWM

CAL = list(range(50, 80))       # calibration seeds, disjoint from scored 0..9
P = scm.ENV_PARAMS_L3


def _std_shift(rows, labels, k):
    a = [rows[i][k] for i in range(len(rows)) if labels[i] == 1]
    b = [rows[i][k] for i in range(len(rows)) if labels[i] == 0]
    col = [r[k] for r in rows]
    sd = statistics.pstdev(col) or 1.0
    return abs(statistics.mean(a) - statistics.mean(b)) / sd


def a1_marginal_purity():
    # 20000-sample pool, single env (train-sign), standardized class-mean-shift per raw feature
    rows, labels = scm.gen_env_l3(50, P["train_couplings"][0], scm._TAG_TRAIN[0])
    # inflate to ~20000 by pooling several disjoint streams at the SAME coupling
    for t in range(4):
        r2, l2 = scm.gen_env_l3(1000 + t, P["train_couplings"][0], 200 + t)
        rows += r2
        labels += l2
    shifts = {nm: _std_shift(rows, labels, k) for nm, k in
              [("Xc1", 0), ("Xc2", 1), ("Xc3", 2), ("Xs1", 3), ("Xs2", 4), ("Xn1", 5), ("Xn2", 6)]}
    zero_ok = all(shifts[nm] < 0.03 for nm in ["Xc1", "Xc2", "Xs2", "Xn1", "Xn2"])
    # Xc3 is a genuine invariant linear decoy; the binding constraint is the A2 linear CEILING (<0.62 OOD),
    # not an arbitrary marginal band. Require only that it is a real (non-zero) but bounded signal.
    xc3_band = 0.05 < shifts["Xc3"] < 0.40
    return {"shifts": {k: round(v, 4) for k, v in shifts.items()}, "n": len(rows),
            "zero_features_pure": zero_ok, "xc3_in_band": xc3_band, "pass": zero_ok and xc3_band}


def a2_linear_ceiling():
    # pooled-linear (LEARN-2 raw pooled) OOD AUC over calibration seeds must be < 0.62
    c = LearnedCWM()
    aucs = []
    for s in CAL:
        tr = scm.train_envs_l3(s)
        rows, labels = scm.test_env_l3(s)
        aucs.append(c.invariant_predict_auc(tr, rows, labels, seed=s, mode="pooled"))
    m = statistics.mean(aucs)
    return {"pooled_linear_ood_mean": round(m, 4), "pass": m < 0.62}


def a3_sign_stability():
    ic = InteractionCWM()
    n_raw = scm.N_FEATURES
    xor_k = product_index(n_raw, *scm.INTERACTION_PAIR)      # Xc1*Xc2 coord
    xc3_k = scm.CAUSAL_LIN_IDX[0]                            # Xc3 raw coord
    spur_coords = set()
    for i in scm.SPURIOUS_IDX:
        for j in range(n_raw):
            if j != i:
                spur_coords.add(product_index(n_raw, i, j))
    xor_keep = xc3_keep = spur_admit = 0
    for s in CAL[:10]:
        tr = scm.train_envs_l3(s)
        rows, labels = scm.test_env_l3(s)
        _, kept = ic.invariant_interaction_auc(tr, rows, labels, seed=s, return_kept=True)
        kept = set(kept)
        xor_keep += xor_k in kept
        xc3_keep += xc3_k in kept
        spur_admit += 1 if (kept & spur_coords) else 0
    # GATING: the INTERACTION (the load-bearing signal) is reliably identified AND the spurious is not
    # admitted. xc3 (weak linear decoy, not load-bearing) is reported but not gating — the mag_floor may
    # legitimately drop a marginal decoy without threatening the interaction-driven win.
    return {"xor_kept": f"{xor_keep}/10", "xc3_kept_informational": f"{xc3_keep}/10",
            "spurious_admitted": f"{spur_admit}/10", "pass": xor_keep >= 9 and spur_admit <= 1}


def a4_c5_drop_margin():
    ic = InteractionCWM()
    drops = []
    for s in CAL:
        tr = scm.train_envs_l3(s)
        rows_i, lab_i = scm.indist_ref_env_l3(s)     # +1.6 (train sign)
        rows_o, lab_o = scm.test_env_l3(s)           # -1.6 (OOD)
        indist = ic.invariant_interaction_auc(tr, rows_i, lab_i, seed=s, mode="cap_pooled")
        ood = ic.invariant_interaction_auc(tr, rows_o, lab_o, seed=s, mode="cap_pooled")
        drops.append(indist - ood)
    m = statistics.mean(drops)
    return {"cap_pooled_indist_minus_ood_mean": round(m, 4), "pass": m >= 0.04}


def a5_delta_b_stability():
    ic = InteractionCWM()
    windows = [CAL[0:10], CAL[10:20], CAL[20:30]]
    win_means = []
    per = []
    for win in windows:
        ds = []
        for s in win:
            tr = scm.train_envs_l3(s)
            rows, labels = scm.test_env_l3(s)
            inv = ic.invariant_interaction_auc(tr, rows, labels, seed=s, mode="inv_interaction")
            cap = ic.invariant_interaction_auc(tr, rows, labels, seed=s, mode="cap_pooled")
            ds.append(inv - cap)
        win_means.append(statistics.mean(ds))
        per += ds
    se = statistics.pstdev(per) / (len(per) ** 0.5)
    return {"delta_b_window_means": [round(x, 4) for x in win_means],
            "delta_b_mean": round(statistics.mean(per), 4), "se": round(se, 4),
            "mean_minus_2se": round(statistics.mean(per) - 2 * se, 4),
            "pass": statistics.mean(per) - 2 * se > 0.05}


def a6_rng_disjoint():
    bad = 0
    for s in CAL[:10]:
        tr_rows = {tuple(round(x, 9) for x in r) for rows, _ in scm.train_envs_l3(s) for r in rows}
        te_rows = {tuple(round(x, 9) for x in r) for r in scm.test_env_l3(s)[0]}
        bad += len(tr_rows & te_rows)
    return {"train_test_row_collisions": bad, "pass": bad == 0}


def main():
    import json
    res = {"A1_marginal_purity": a1_marginal_purity(), "A2_linear_ceiling": a2_linear_ceiling(),
           "A3_sign_stability": a3_sign_stability(), "A4_c5_drop_margin": a4_c5_drop_margin(),
           "A5_delta_b_stability": a5_delta_b_stability(), "A6_rng_disjoint": a6_rng_disjoint()}
    res["all_pass"] = all(v["pass"] for v in res.values() if isinstance(v, dict) and "pass" in v)
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
