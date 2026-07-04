"""CWM-LEARN-5e-2 hard forms r-final.

Runs the preregistered hard bandpass-form gate on r-final seeds after verifying
the prereg lock. Scope is narrow: supplied typed forms vs finite pair-product
screening/random hard-form controls, plus Condition-B leak control.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from experiments import cwm_learn_5e2_forms_hard as hard


GATE = "CWM-LEARN-5e-2"
PREREG_ID = "CWM-LEARN-5e-2-hard-forms-rfinal-2026-07-04"
PREREG_FILE = "docs/pre_spec/5E-2.HARD-FORMS-RFINAL.PREREG-2026-07-04.md"
LOCK_FILE = "docs/pre_spec/5E-2.HARD-FORMS-RFINAL.lock.json"
LOCKED_FILES = (
    PREREG_FILE,
    "experiments/cwm_learn_5e2_forms_hard.py",
    "experiments/cwm_learn_5e2_forms_hard_rfinal.py",
    "tests/test_cwm_learn_5e2_forms_hard_rfinal.py",
)
CALIBRATION_SEEDS = (30, 31, 32, 33)
FRESH_SCORED_SEEDS = (40, 41, 42, 43, 44, 45)
RFINAL_SEEDS = (60, 61, 62, 63, 64, 65, 66, 67, 68, 69)
RANDOM_DRAWS = 3
NOT_AUTHORIZED = (
    "LLM_capability_claim",
    "autonomy_claim",
    "product_claim",
    "route_promotion_without_review",
    "C6_C7_change",
    "governance_weakening",
)
REPO_ROOT = Path(__file__).resolve().parents[1]


class PreregLockDrift(RuntimeError):
    """Raised when the prereg lock is missing, malformed, incomplete, or drifted."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_prereg_lock(lock_path: str | Path = LOCK_FILE, *, root: Path = REPO_ROOT) -> dict[str, Any]:
    path = root / lock_path
    if not path.exists():
        raise PreregLockDrift(f"RFINAL_PREREG_DRIFT: missing lock {lock_path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("prereg_id") != PREREG_ID:
        raise PreregLockDrift("RFINAL_PREREG_DRIFT: prereg_id mismatch")
    files = data.get("files")
    if not isinstance(files, dict):
        raise PreregLockDrift("RFINAL_PREREG_DRIFT: lock files map missing")
    missing = [rel for rel in LOCKED_FILES if rel not in files]
    if missing:
        raise PreregLockDrift(f"RFINAL_PREREG_DRIFT: lock missing files {missing}")
    for rel in LOCKED_FILES:
        actual = _sha256(root / rel)
        if files[rel] != actual:
            raise PreregLockDrift(f"RFINAL_PREREG_DRIFT: digest mismatch for {rel}")
    return data


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


def run_rfinal(
    *,
    seeds: Iterable[int] = RFINAL_SEEDS,
    random_draws: int = RANDOM_DRAWS,
    lock_path: str | Path = LOCK_FILE,
) -> dict[str, Any]:
    lock = verify_prereg_lock(lock_path)
    result = hard.run_hard_form_calibration(seeds=seeds, random_draws=random_draws)
    seed_list = result["seeds"]
    if set(seed_list) & (set(CALIBRATION_SEEDS) | set(FRESH_SCORED_SEEDS)):
        raise ValueError("r-final seeds overlap prior calibration or fresh-scored seed bands")
    cond_a_summary = result["condA"]["summary"]
    cond_b_summary = result["condB"]["summary"]
    verdict = _decide_verdict(cond_a_summary, cond_b_summary, n=len(seed_list))
    result.update({
        "schema_version": "cwm_learn_5e2_hard_forms_rfinal_v1",
        "evidence_level": "r_final_preregistered",
        "claim_scope": "hard_non_enumerable_function_forms_rfinal",
        "prereg_id": PREREG_ID,
        "prereg_file": PREREG_FILE,
        "prereg_lock": str(lock_path),
        "prereg_lock_verified": True,
        "prereg_lock_files": lock["files"],
        "calibration_seed_source": list(CALIBRATION_SEEDS),
        "fresh_scored_seed_source": list(FRESH_SCORED_SEEDS),
        "scoring_seed_overlap_with_prior": False,
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
    result = run_rfinal()
    with open("experiments/cwm_learn_5e2_forms_hard_rfinal.result.json", "w", encoding="utf-8") as fh:
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
