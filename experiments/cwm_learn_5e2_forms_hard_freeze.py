"""CWM-LEARN-5e-2 hard forms fresh scored gate.

Calibration found a candidate region on seeds 30..33. This runner scores the
same frozen hard-form arena on disjoint fresh seeds. It is still not r-final and
does not authorize autonomy/product claims or any C6/C7 change.
"""
from __future__ import annotations

import json
from typing import Any, Iterable

from experiments import cwm_learn_5e2_forms_hard as hard


GATE = "CWM-LEARN-5e-2"
CALIBRATION_SEEDS = (30, 31, 32, 33)
SCORING_SEEDS = (40, 41, 42, 43, 44, 45)
RANDOM_DRAWS = 3
NOT_AUTHORIZED = (
    "r_final",
    "autonomy_claim",
    "product_claim",
    "route_promotion",
    "C6_C7_change",
    "manual_threshold_rescue",
)


def _wins(value: str) -> int:
    return int(value.split("/", 1)[0])


def _decide_verdict(cond_a: dict[str, Any], cond_b: dict[str, Any], *, n: int) -> str:
    if cond_b["median_s_proposed_hard_forms"] > cond_b["median_s_random_hard_forms"] + 0.10:
        return "INVALID(CONDITION-B-ANOMALY)"
    met = (
        cond_a["median_s_proposed_hard_forms"] >= 0.80
        and cond_a["median_s_pair_screening"] <= 0.60
        and cond_a["median_s_random_hard_forms"] <= 0.20
        and _wins(cond_a["proposed_gt_pair_screening"]) >= max(1, int(0.8 * n))
        and _wins(cond_a["proposed_gt_random_hard_forms"]) >= max(1, int(0.8 * n))
    )
    return "MET" if met else "NULL"


def run_scored_gate(
    *,
    seeds: Iterable[int] = SCORING_SEEDS,
    random_draws: int = RANDOM_DRAWS,
) -> dict[str, Any]:
    result = hard.run_hard_form_calibration(seeds=seeds, random_draws=random_draws)
    seed_list = result["seeds"]
    cond_a_summary = result["condA"]["summary"]
    cond_b_summary = result["condB"]["summary"]
    verdict = _decide_verdict(cond_a_summary, cond_b_summary, n=len(seed_list))
    result.update({
        "schema_version": "cwm_learn_5e2_hard_forms_fresh_scored_v1",
        "evidence_level": "fresh_scored_gate_not_r_final",
        "claim_scope": "hard_non_enumerable_function_forms_fresh_score",
        "calibration_seed_source": list(CALIBRATION_SEEDS),
        "scoring_seed_overlap_with_calibration": bool(set(seed_list) & set(CALIBRATION_SEEDS)),
        "not_authorized": list(NOT_AUTHORIZED),
    })
    result["summary"].update({
        "verdict": verdict,
        "decision_rule": {
            "met": [
                "median_s_proposed_hard_forms >= 0.80",
                "median_s_pair_screening <= 0.60",
                "median_s_random_hard_forms <= 0.20",
                "proposed beats pair screening in >=80% seeds",
                "proposed beats random hard forms in >=80% seeds",
                "Condition-B proposed does not exceed random by >0.10",
            ],
            "invalid": "Condition-B proposed exceeds random by >0.10",
            "otherwise": "NULL",
        },
    })
    return result


def main() -> int:
    result = run_scored_gate()
    with open("experiments/cwm_learn_5e2_forms_hard_freeze.result.json", "w", encoding="utf-8") as fh:
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
