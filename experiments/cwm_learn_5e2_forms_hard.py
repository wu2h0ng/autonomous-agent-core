"""CWM-LEARN-5e-2 hard functional-form arena calibration.

The first forms arena showed real form signal but pair products proxied the
forms too well. This calibration probes a harder arena: labels depend on
bandpass-gated products where the gating variable is near zero. The supplied
typed form remains verifiable, while a finite pair-product screener should lose
the cheap proxy. This remains calibration only; it is not a freeze verdict.
"""
from __future__ import annotations

import json
import random
import statistics
from typing import Any, Iterable

from aac.invariant_structure import InvariantStructureFilter


GATE = "CWM-LEARN-5e-2"
HARD_FORM_KINDS = ("bandpass_product",)
HARD_FORM_PARAMS = {
    "n_raw": 60,
    "n_train": 260,
    "n_test": 1200,
    "n_envs": 4,
    "global_load": 0.15,
    "noise_sd": 0.55,
    "spurious": list(range(12, 20)),
    "spur_strength": 1.3,
    "spur_noise": 0.7,
    "spur_signs": [
        [+1, +1, -1, -1], [-1, +1, +1, -1], [+1, -1, +1, -1], [-1, -1, +1, +1],
        [+1, -1, -1, +1], [-1, +1, -1, +1], [+1, +1, +1, -1], [-1, -1, -1, +1],
    ],
    "test_signs": [-1, +1, -1, +1, -1, +1, -1, +1],
}
SEEDS = tuple(range(30, 34))
RANDOM_DRAWS = 3
NOT_AUTHORIZED = (
    "freeze_verdict",
    "r_final",
    "autonomy_claim",
    "product_claim",
    "route_promotion",
    "C6_C7_change",
)

TRUE_HARD_FORMS: list[dict[str, Any]] = [
    {"kind": "bandpass_product", "gate": 0, "signal": 6, "center": 0.0, "width": 0.55,
     "name": "near_nominal_load_gates_rpm"},
    {"kind": "bandpass_product", "gate": 4, "signal": 9, "center": 0.0, "width": 0.55,
     "name": "near_nominal_temp_gates_duty"},
    {"kind": "bandpass_product", "gate": 2, "signal": 3, "center": 0.0, "width": 0.55,
     "name": "near_nominal_current_gates_resistance"},
]
TRUE_HARD_WEIGHTS = (1.45, 1.25, 1.05)

PROPOSED_HARD_FORMS: list[dict[str, Any]] = TRUE_HARD_FORMS + [
    {"kind": "bandpass_product", "gate": 7, "signal": 0, "center": 0.0, "width": 0.55,
     "name": "wear_band_gates_load"},
    {"kind": "bandpass_product", "gate": 8, "signal": 9, "center": 0.0, "width": 0.55,
     "name": "age_band_gates_duty"},
    {"kind": "bandpass_product", "gate": 6, "signal": 1, "center": 0.0, "width": 0.55,
     "name": "rpm_band_gates_vibration"},
]

COND_B_TRUE_HARD_FORMS: list[dict[str, Any]] = [
    {"kind": "bandpass_product", "gate": 30, "signal": 31, "center": 0.0, "width": 0.55,
     "name": "cable_band_gates_torque"},
    {"kind": "bandpass_product", "gate": 34, "signal": 35, "center": 0.0, "width": 0.55,
     "name": "cleaning_band_gates_coolant"},
    {"kind": "bandpass_product", "gate": 40, "signal": 41, "center": 0.0, "width": 0.55,
     "name": "brightness_band_gates_desk_height"},
]


def _stream(seed: int, tag: str) -> random.Random:
    return random.Random(f"HD5e2HardForms|{seed}|{tag}")


def _eval_hard_form(row: list[float], spec: dict[str, Any]) -> float:
    if spec["kind"] != "bandpass_product":
        raise ValueError(f"unknown hard form kind {spec['kind']!r}")
    gate = row[int(spec["gate"])]
    signal = row[int(spec["signal"])]
    center = float(spec.get("center", 0.0))
    width = float(spec["width"])
    active = max(0.0, 1.0 - abs(gate - center) / width)
    return active * signal


def expand_hard_forms(rows: list[list[float]], forms: list[dict[str, Any]]) -> list[list[float]]:
    return [list(row) + [_eval_hard_form(row, spec) for spec in forms] for row in rows]


def _expand_pairs(rows: list[list[float]], pairs: list[list[int]]) -> list[list[float]]:
    return [list(row) + [row[a] * row[b] for a, b in pairs] for row in rows]


def _gen(seed: int, tag: str, n: int, signs: list[int], true_forms: list[dict[str, Any]]):
    rng = _stream(seed, tag)
    p = HARD_FORM_PARAMS
    rows, labels = [], []
    for _ in range(n):
        g = rng.gauss(0, 1)
        row = [p["global_load"] * g + rng.gauss(0, 1) for _ in range(p["n_raw"])]
        score = sum(weight * _eval_hard_form(row, spec) for weight, spec in zip(TRUE_HARD_WEIGHTS, true_forms))
        y = 1 if score + rng.gauss(0, p["noise_sd"]) > 0 else 0
        for ci, k in enumerate(p["spurious"]):
            row[k] += signs[ci] * p["spur_strength"] * (2 * y - 1) + rng.gauss(0, p["spur_noise"])
        rows.append(row)
        labels.append(y)
    return rows, labels


def train_envs_hard_forms(seed: int, true_forms: list[dict[str, Any]] = TRUE_HARD_FORMS):
    p = HARD_FORM_PARAMS
    return [
        _gen(seed, f"env{env}", p["n_train"], [p["spur_signs"][c][env] for c in range(len(p["spurious"]))],
             true_forms)
        for env in range(p["n_envs"])
    ]


def test_env_hard_forms(seed: int, true_forms: list[dict[str, Any]] = TRUE_HARD_FORMS):
    return _gen(seed, "test", HARD_FORM_PARAMS["n_test"], HARD_FORM_PARAMS["test_signs"], true_forms)


def _verifier() -> InvariantStructureFilter:
    return InvariantStructureFilter(basis="raw", epochs=100)


def _fit_score_forms(tr, te_x, te_y, forms: list[dict[str, Any]], seed: int) -> float:
    model = _verifier().fit(
        [(expand_hard_forms(rows, forms), labels) for rows, labels in tr],
        seed=seed,
    )
    return model.score_auc(expand_hard_forms(te_x, forms), te_y) if model.found else 0.5


def _fit_score_pairs(tr, te_x, te_y, pairs: list[list[int]], seed: int) -> float:
    model = _verifier().fit(
        [(_expand_pairs(rows, pairs), labels) for rows, labels in tr],
        seed=seed,
    )
    return model.score_auc(_expand_pairs(te_x, pairs), te_y) if model.found else 0.5


def _screen_pairs(tr, k: int) -> list[list[int]]:
    n_raw = HARD_FORM_PARAMS["n_raw"]
    best: dict[tuple[int, int], float] = {}
    for rows, labels in tr:
        y_mean = statistics.mean(labels)
        y_sd = statistics.pstdev(labels) or 1.0
        for i in range(n_raw):
            for j in range(i + 1, n_raw):
                values = [row[i] * row[j] for row in rows]
                v_mean = statistics.mean(values)
                v_sd = statistics.pstdev(values) or 1.0
                corr = abs(
                    sum((values[t] - v_mean) * (labels[t] - y_mean) for t in range(len(values)))
                    / (len(values) * v_sd * y_sd)
                )
                key = (i, j)
                best[key] = min(best.get(key, 1e9), corr)
    return [list(pair) for pair, _ in sorted(best.items(), key=lambda kv: -kv[1])[:k]]


_HARD_FORM_UNIVERSE_CACHE: list[dict[str, Any]] | None = None


def _hard_form_universe() -> list[dict[str, Any]]:
    global _HARD_FORM_UNIVERSE_CACHE
    if _HARD_FORM_UNIVERSE_CACHE is not None:
        return _HARD_FORM_UNIVERSE_CACHE
    forms: list[dict[str, Any]] = []
    n_raw = HARD_FORM_PARAMS["n_raw"]
    for gate in range(n_raw):
        for signal in range(n_raw):
            if gate == signal:
                continue
            forms.append({"kind": "bandpass_product", "gate": gate, "signal": signal, "center": 0.0, "width": 0.55})
    _HARD_FORM_UNIVERSE_CACHE = forms
    return forms


def _random_forms(seed: int, draw: int, k: int) -> list[dict[str, Any]]:
    return random.Random(f"5e2-hard-forms|{seed}|{draw}").sample(_hard_form_universe(), k)


def _norm(auc: float, oracle_auc: float) -> float:
    return (auc - 0.5) / (oracle_auc - 0.5) if oracle_auc > 0.5 else 0.0


def _score_seed(seed: int, true_forms: list[dict[str, Any]], random_draws: int) -> dict[str, Any]:
    tr = train_envs_hard_forms(seed, true_forms)
    te_x, te_y = test_env_hard_forms(seed, true_forms)
    oracle = _fit_score_forms(tr, te_x, te_y, true_forms, seed)
    proposed = _fit_score_forms(tr, te_x, te_y, PROPOSED_HARD_FORMS, seed)
    pair_screening = _fit_score_pairs(tr, te_x, te_y, _screen_pairs(tr, len(PROPOSED_HARD_FORMS)), seed)
    random_aucs = [
        _fit_score_forms(tr, te_x, te_y, _random_forms(seed, draw, len(PROPOSED_HARD_FORMS)), seed)
        for draw in range(random_draws)
    ]
    random_median = statistics.median(random_aucs)
    return {
        "seed": seed,
        "oracle_hard_forms": round(oracle, 4),
        "proposed_hard_forms": round(proposed, 4),
        "pair_screening": round(pair_screening, 4),
        "random_hard_forms_median": round(random_median, 4),
        "s_proposed_hard_forms": round(_norm(proposed, oracle), 4),
        "s_pair_screening": round(_norm(pair_screening, oracle), 4),
        "s_random_hard_forms": round(_norm(random_median, oracle), 4),
    }


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    med = lambda key: statistics.median(row[key] for row in rows)
    wins_pair = sum(1 for row in rows if row["proposed_hard_forms"] > row["pair_screening"])
    wins_random = sum(1 for row in rows if row["proposed_hard_forms"] > row["random_hard_forms_median"])
    return {
        "median_s_proposed_hard_forms": round(med("s_proposed_hard_forms"), 4),
        "median_s_pair_screening": round(med("s_pair_screening"), 4),
        "median_s_random_hard_forms": round(med("s_random_hard_forms"), 4),
        "proposed_gt_pair_screening": f"{wins_pair}/{len(rows)}",
        "proposed_gt_random_hard_forms": f"{wins_random}/{len(rows)}",
    }


def run_hard_form_calibration(
    *,
    seeds: Iterable[int] = SEEDS,
    random_draws: int = RANDOM_DRAWS,
) -> dict[str, Any]:
    seed_list = [int(seed) for seed in seeds]
    cond_a_rows = [_score_seed(seed, TRUE_HARD_FORMS, random_draws) for seed in seed_list]
    cond_b_rows = [_score_seed(seed, COND_B_TRUE_HARD_FORMS, random_draws) for seed in seed_list]
    cond_a_summary = _summarize(cond_a_rows)
    cond_b_summary = _summarize(cond_b_rows)
    cond_b_collapse = (
        cond_b_summary["median_s_proposed_hard_forms"]
        <= cond_b_summary["median_s_random_hard_forms"] + 0.10
    )
    wins_random = cond_a_summary["proposed_gt_random_hard_forms"].split("/")[0]
    candidate_freeze_region = (
        cond_a_summary["median_s_proposed_hard_forms"] >= 0.80
        and cond_a_summary["median_s_pair_screening"] <= 0.60
        and int(wins_random) >= max(1, int(0.8 * len(seed_list)))
        and cond_b_collapse
    )
    return {
        "gate": GATE,
        "schema_version": "cwm_learn_5e2_hard_forms_calibration_v1",
        "evidence_level": "calibration_pilot_not_freeze",
        "claim_scope": "hard_non_enumerable_function_forms",
        "proposal_source": "manual_data_blind_bandpass_form_proposals_v0",
        "screening_baseline": "finite_pair_products_only",
        "form_kinds": list(HARD_FORM_KINDS),
        "proposed_form_count": len(PROPOSED_HARD_FORMS),
        "seeds": seed_list,
        "random_draws": random_draws,
        "not_authorized": list(NOT_AUTHORIZED),
        "condA": {"true_forms": TRUE_HARD_FORMS, "per_seed": cond_a_rows, "summary": cond_a_summary},
        "condB": {"true_forms": COND_B_TRUE_HARD_FORMS, "per_seed": cond_b_rows, "summary": cond_b_summary},
        "summary": {
            "candidate_freeze_region": candidate_freeze_region,
            "condB_collapse_ok": cond_b_collapse,
            "pair_proxy_gap_observed": (
                cond_a_summary["median_s_proposed_hard_forms"] >= 0.80
                and cond_a_summary["median_s_pair_screening"] <= 0.60
            ),
        },
    }


def main() -> int:
    result = run_hard_form_calibration()
    with open("experiments/cwm_learn_5e2_forms_hard.result.json", "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, sort_keys=True)
    printable = {
        "condA": result["condA"]["summary"],
        "condB": result["condB"]["summary"],
        "summary": result["summary"],
    }
    print(json.dumps(printable, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
