"""CWM-LEARN-5e-2 non-enumerable functional-form calibration pilot.

The zero-shot branch did not find a freeze-ready region. This branch probes the
second unique region from the 5e-2 design note: the proposer supplies typed
functional forms instead of finite pair products, and the existing invariant
verifier tests the supplied features. This is calibration only: no freeze
verdict, r-final, autonomy claim, product claim, route promotion, or C6/C7
change is authorized here.
"""
from __future__ import annotations

import json
import random
import statistics
from typing import Any, Iterable

from aac.invariant_structure import InvariantStructureFilter


GATE = "CWM-LEARN-5e-2"
FORM_KINDS = ("threshold_product", "saturation_product", "ratio")
FORM_PARAMS = {
    "n_raw": 60,
    "n_train": 240,
    "n_test": 1000,
    "n_envs": 4,
    "global_load": 0.25,
    "noise_sd": 0.85,
    "spurious": list(range(12, 20)),
    "spur_strength": 1.4,
    "spur_noise": 0.7,
    "spur_signs": [
        [+1, +1, -1, -1], [-1, +1, +1, -1], [+1, -1, +1, -1], [-1, -1, +1, +1],
        [+1, -1, -1, +1], [-1, +1, -1, +1], [+1, +1, +1, -1], [-1, -1, -1, +1],
    ],
    "test_signs": [-1, +1, -1, +1, -1, +1, -1, +1],
}
SEEDS = tuple(range(20, 24))
RANDOM_DRAWS = 3
NOT_AUTHORIZED = (
    "freeze_verdict",
    "r_final",
    "autonomy_claim",
    "product_claim",
    "route_promotion",
    "C6_C7_change",
)

TRUE_FORMS: list[dict[str, Any]] = [
    {"kind": "threshold_product", "a": 0, "b": 6, "threshold": 0.2, "name": "load_over_threshold_x_rpm"},
    {"kind": "saturation_product", "a": 4, "b": 9, "name": "temp_saturation_x_duty_cycle"},
    {"kind": "ratio", "num": 2, "den": 3, "name": "current_to_resistance_ratio"},
]
TRUE_WEIGHTS = (1.35, 1.1, 0.95)

PROPOSED_FORMS: list[dict[str, Any]] = TRUE_FORMS + [
    {"kind": "threshold_product", "a": 7, "b": 0, "threshold": 0.0, "name": "wear_threshold_x_load"},
    {"kind": "saturation_product", "a": 8, "b": 9, "name": "age_saturation_x_duty_cycle"},
    {"kind": "ratio", "num": 6, "den": 1, "name": "rpm_to_vibration_ratio"},
]

COND_B_TRUE_FORMS: list[dict[str, Any]] = [
    {"kind": "threshold_product", "a": 30, "b": 31, "threshold": 0.1, "name": "cable_threshold_x_torque"},
    {"kind": "saturation_product", "a": 34, "b": 35, "name": "cleaning_saturation_x_coolant"},
    {"kind": "ratio", "num": 40, "den": 41, "name": "brightness_to_desk_height_ratio"},
]


def _stream(seed: int, tag: str) -> random.Random:
    return random.Random(f"HD5e2Forms|{seed}|{tag}")


def _eval_form(row: list[float], spec: dict[str, Any]) -> float:
    kind = spec["kind"]
    if kind == "threshold_product":
        return max(0.0, row[int(spec["a"])] - float(spec.get("threshold", 0.0))) * row[int(spec["b"])]
    if kind == "saturation_product":
        v = row[int(spec["a"])]
        return (v / (1.0 + abs(v))) * row[int(spec["b"])]
    if kind == "ratio":
        return row[int(spec["num"])] / (1.0 + abs(row[int(spec["den"])]))
    raise ValueError(f"unknown form kind {kind!r}")


def expand_forms(rows: list[list[float]], forms: list[dict[str, Any]]) -> list[list[float]]:
    return [list(row) + [_eval_form(row, spec) for spec in forms] for row in rows]


def _expand_pairs(rows: list[list[float]], pairs: list[list[int]]) -> list[list[float]]:
    return [list(row) + [row[a] * row[b] for a, b in pairs] for row in rows]


def _gen(seed: int, tag: str, n: int, signs: list[int], true_forms: list[dict[str, Any]]):
    rng = _stream(seed, tag)
    p = FORM_PARAMS
    rows, labels = [], []
    for _ in range(n):
        g = rng.gauss(0, 1)
        row = [p["global_load"] * g + rng.gauss(0, 1) for _ in range(p["n_raw"])]
        score = sum(weight * _eval_form(row, spec) for weight, spec in zip(TRUE_WEIGHTS, true_forms))
        y = 1 if score + rng.gauss(0, p["noise_sd"]) > 0 else 0
        for ci, k in enumerate(p["spurious"]):
            row[k] += signs[ci] * p["spur_strength"] * (2 * y - 1) + rng.gauss(0, p["spur_noise"])
        rows.append(row)
        labels.append(y)
    return rows, labels


def train_envs_forms(seed: int, true_forms: list[dict[str, Any]] = TRUE_FORMS):
    p = FORM_PARAMS
    return [
        _gen(seed, f"env{env}", p["n_train"], [p["spur_signs"][c][env] for c in range(len(p["spurious"]))],
             true_forms)
        for env in range(p["n_envs"])
    ]


def test_env_forms(seed: int, true_forms: list[dict[str, Any]] = TRUE_FORMS):
    return _gen(seed, "test", FORM_PARAMS["n_test"], FORM_PARAMS["test_signs"], true_forms)


def _verifier() -> InvariantStructureFilter:
    return InvariantStructureFilter(basis="raw", epochs=90)


def _fit_score_forms(tr, te_x, te_y, forms: list[dict[str, Any]], seed: int) -> float:
    model = _verifier().fit(
        [(expand_forms(rows, forms), labels) for rows, labels in tr],
        seed=seed,
    )
    return model.score_auc(expand_forms(te_x, forms), te_y) if model.found else 0.5


def _fit_score_pairs(tr, te_x, te_y, pairs: list[list[int]], seed: int) -> float:
    model = _verifier().fit(
        [(_expand_pairs(rows, pairs), labels) for rows, labels in tr],
        seed=seed,
    )
    return model.score_auc(_expand_pairs(te_x, pairs), te_y) if model.found else 0.5


def _screen_pairs(tr, k: int) -> list[list[int]]:
    n_raw = FORM_PARAMS["n_raw"]
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


_FORM_UNIVERSE_CACHE: list[dict[str, Any]] | None = None


def _form_universe() -> list[dict[str, Any]]:
    global _FORM_UNIVERSE_CACHE
    if _FORM_UNIVERSE_CACHE is not None:
        return _FORM_UNIVERSE_CACHE
    forms: list[dict[str, Any]] = []
    n_raw = FORM_PARAMS["n_raw"]
    for a in range(n_raw):
        for b in range(n_raw):
            if a == b:
                continue
            forms.append({"kind": "threshold_product", "a": a, "b": b, "threshold": 0.0})
            forms.append({"kind": "saturation_product", "a": a, "b": b})
            forms.append({"kind": "ratio", "num": a, "den": b})
    _FORM_UNIVERSE_CACHE = forms
    return forms


def _random_forms(seed: int, draw: int, k: int) -> list[dict[str, Any]]:
    return random.Random(f"5e2-forms|{seed}|{draw}").sample(_form_universe(), k)


def _norm(auc: float, oracle_auc: float) -> float:
    return (auc - 0.5) / (oracle_auc - 0.5) if oracle_auc > 0.5 else 0.0


def _score_seed(seed: int, true_forms: list[dict[str, Any]], random_draws: int) -> dict[str, Any]:
    tr = train_envs_forms(seed, true_forms)
    te_x, te_y = test_env_forms(seed, true_forms)
    oracle = _fit_score_forms(tr, te_x, te_y, true_forms, seed)
    proposed = _fit_score_forms(tr, te_x, te_y, PROPOSED_FORMS, seed)
    pair_screening = _fit_score_pairs(tr, te_x, te_y, _screen_pairs(tr, len(PROPOSED_FORMS)), seed)
    random_aucs = [
        _fit_score_forms(tr, te_x, te_y, _random_forms(seed, draw, len(PROPOSED_FORMS)), seed)
        for draw in range(random_draws)
    ]
    random_median = statistics.median(random_aucs)
    return {
        "seed": seed,
        "oracle_forms": round(oracle, 4),
        "proposed_forms": round(proposed, 4),
        "pair_screening": round(pair_screening, 4),
        "random_forms_median": round(random_median, 4),
        "s_proposed_forms": round(_norm(proposed, oracle), 4),
        "s_pair_screening": round(_norm(pair_screening, oracle), 4),
        "s_random_forms": round(_norm(random_median, oracle), 4),
    }


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    med = lambda key: statistics.median(row[key] for row in rows)
    wins_pair = sum(1 for row in rows if row["proposed_forms"] > row["pair_screening"])
    wins_random = sum(1 for row in rows if row["proposed_forms"] > row["random_forms_median"])
    return {
        "median_s_proposed_forms": round(med("s_proposed_forms"), 4),
        "median_s_pair_screening": round(med("s_pair_screening"), 4),
        "median_s_random_forms": round(med("s_random_forms"), 4),
        "proposed_gt_pair_screening": f"{wins_pair}/{len(rows)}",
        "proposed_gt_random_forms": f"{wins_random}/{len(rows)}",
    }


def run_form_calibration(
    *,
    seeds: Iterable[int] = SEEDS,
    random_draws: int = RANDOM_DRAWS,
) -> dict[str, Any]:
    seed_list = [int(seed) for seed in seeds]
    cond_a_rows = [_score_seed(seed, TRUE_FORMS, random_draws) for seed in seed_list]
    cond_b_rows = [_score_seed(seed, COND_B_TRUE_FORMS, random_draws) for seed in seed_list]
    cond_a_summary = _summarize(cond_a_rows)
    cond_b_summary = _summarize(cond_b_rows)
    cond_b_collapse = (
        cond_b_summary["median_s_proposed_forms"]
        <= cond_b_summary["median_s_random_forms"] + 0.10
    )
    candidate_freeze_region = (
        cond_a_summary["median_s_proposed_forms"] >= 0.80
        and cond_a_summary["median_s_pair_screening"] <= 0.60
        and cond_a_summary["proposed_gt_random_forms"].startswith(("5/", "6/"))
        and cond_b_collapse
    )
    return {
        "gate": GATE,
        "schema_version": "cwm_learn_5e2_forms_calibration_v1",
        "evidence_level": "calibration_pilot_not_freeze",
        "claim_scope": "non_enumerable_function_forms",
        "proposal_source": "manual_data_blind_function_form_proposals_v0",
        "screening_baseline": "finite_pair_products_only",
        "form_kinds": list(FORM_KINDS),
        "proposed_form_count": len(PROPOSED_FORMS),
        "seeds": seed_list,
        "random_draws": random_draws,
        "not_authorized": list(NOT_AUTHORIZED),
        "condA": {"true_forms": TRUE_FORMS, "per_seed": cond_a_rows, "summary": cond_a_summary},
        "condB": {"true_forms": COND_B_TRUE_FORMS, "per_seed": cond_b_rows, "summary": cond_b_summary},
        "summary": {
            "candidate_freeze_region": candidate_freeze_region,
            "condB_collapse_ok": cond_b_collapse,
        },
    }


def main() -> int:
    result = run_form_calibration()
    with open("experiments/cwm_learn_5e2_forms.result.json", "w", encoding="utf-8") as fh:
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
