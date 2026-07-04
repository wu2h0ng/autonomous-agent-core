"""CWM-LEARN-5e-2 zero-shot calibration pilot.

5e was MET-weak because data-blind proposals reached the oracle ceiling but a
cheap data-using screener matched them. 5e-2 starts with the first unique region:
the proposer acts before data exists, then later-arriving small data is used only
by the verifier and the screening baseline. This file calibrates the sample
sizes where screening collapses while frozen zero-shot proposals can still be
verified. It is not a freeze, verdict, or autonomy claim.
"""
from __future__ import annotations

import json
import random
import statistics
from contextlib import contextmanager
from typing import Any, Iterable

import experiments.synthetic_scm_highdim as hd
from experiments.cwm_learn_5e import _fit_score, _load, _norm, _screen_pairs


GATE = "CWM-LEARN-5e-2"
SEEDS = tuple(range(10, 16))
TRAIN_SIZES = (30, 36, 38, 40, 60, 80)
RANDOM_DRAWS = 10
NOT_AUTHORIZED = (
    "freeze_verdict",
    "r_final",
    "autonomy_claim",
    "product_claim",
    "route_promotion",
    "C6_C7_change",
)


@contextmanager
def _temporary_train_size(n_train: int):
    old = hd.HD_PARAMS["n_train"]
    hd.HD_PARAMS["n_train"] = int(n_train)
    try:
        yield
    finally:
        hd.HD_PARAMS["n_train"] = old


def _score_seed(seed: int, train_size: int, union: list[list[int]], random_draws: int) -> dict[str, Any]:
    with _temporary_train_size(train_size):
        tr = hd.train_envs_hd(seed)
        te_x, te_y = hd.test_env_hd(seed)
        oracle_auc = _fit_score(tr, te_x, te_y, hd.HD_PARAMS["true_pairs"], seed)
        zeroshot_auc = _fit_score(tr, te_x, te_y, union, seed)
        screening_auc = _fit_score(tr, te_x, te_y, _screen_pairs(tr, len(union)), seed)
        all_pairs = [(i, j) for i in range(hd.HD_PARAMS["n_raw"]) for j in range(i + 1, hd.HD_PARAMS["n_raw"])]
        random_aucs = []
        for draw in range(random_draws):
            pairs = [
                list(pair)
                for pair in random.Random(f"5e2|{seed}|{train_size}|{draw}").sample(all_pairs, len(union))
            ]
            random_aucs.append(_fit_score(tr, te_x, te_y, pairs, seed))
    return {
        "seed": seed,
        "oracle": round(oracle_auc, 4),
        "zeroshot": round(zeroshot_auc, 4),
        "screening": round(screening_auc, 4),
        "random_median": round(statistics.median(random_aucs), 4),
        "s_zeroshot": round(_norm(zeroshot_auc, oracle_auc), 4),
        "s_screening": round(_norm(screening_auc, oracle_auc), 4),
        "s_random": round(_norm(statistics.median(random_aucs), oracle_auc), 4),
    }


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    median = lambda key: statistics.median(row[key] for row in rows)
    wins_vs_screen = sum(1 for row in rows if row["zeroshot"] > row["screening"])
    wins_vs_random = sum(1 for row in rows if row["zeroshot"] > row["random_median"])
    return {
        "median_s_zeroshot": round(median("s_zeroshot"), 4),
        "median_s_screening": round(median("s_screening"), 4),
        "median_s_random": round(median("s_random"), 4),
        "zeroshot_gt_screening": f"{wins_vs_screen}/{len(rows)}",
        "zeroshot_gt_random": f"{wins_vs_random}/{len(rows)}",
        "candidate_freeze_region": (
            median("s_zeroshot") >= 0.80
            and median("s_screening") <= 0.60
            and wins_vs_random >= max(1, int(0.8 * len(rows)))
        ),
    }


def run_zero_shot_calibration(
    *,
    seeds: Iterable[int] = SEEDS,
    train_sizes: Iterable[int] = TRAIN_SIZES,
    random_draws: int = RANDOM_DRAWS,
) -> dict[str, Any]:
    _, union = _load()
    seed_list = [int(seed) for seed in seeds]
    out: dict[str, Any] = {
        "gate": GATE,
        "schema_version": "cwm_learn_5e2_zero_shot_calibration_v1",
        "evidence_level": "calibration_pilot_not_freeze",
        "claim_scope": "zero_shot_pre_data_candidate_pruning",
        "proposal_source": "frozen_data_blind_5e_union",
        "union_size": len(union),
        "seeds": seed_list,
        "random_draws": random_draws,
        "not_authorized": list(NOT_AUTHORIZED),
        "train_sizes": {},
    }
    for train_size in train_sizes:
        rows = [_score_seed(seed, int(train_size), union, random_draws) for seed in seed_list]
        out["train_sizes"][str(int(train_size))] = {
            "per_seed": rows,
            "summary": _summarize(rows),
        }
    return out


def main() -> int:
    result = run_zero_shot_calibration()
    with open("experiments/cwm_learn_5e2.result.json", "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, sort_keys=True)
    printable = {
        size: payload["summary"]
        for size, payload in result["train_sizes"].items()
    }
    print(json.dumps(printable, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
