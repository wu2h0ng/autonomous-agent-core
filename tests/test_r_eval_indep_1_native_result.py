from __future__ import annotations

import copy
import json
import math
import unittest
from pathlib import Path
from typing import Any

from experiments.r_eval_indep_1.contracts import canonical_digest
from experiments.r_eval_indep_1.native_result import (
    RawRFinalResult,
    validate_raw_rfinal_result,
)


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
REPO_ROOT = Path(__file__).resolve().parents[1]


def _result_mapping() -> dict[str, Any]:
    metrics: dict[str, object] = {
        "case_count": 74,
        "arm_count": 2,
        "arm_scores": {"native-arm-a": {"false_acceptance_rate": 0.1}},
        "pairwise_scores": [],
        "undefined_rule": "UNDEFINED_ON_ZERO_CLASS_CENTERED_VARIANCE",
    }
    return {
        "schema_version": "r-eval-indep-1-raw-rfinal-v1",
        "prereg_id": "R-EVAL-INDEP-1",
        "run_id": "r-eval-indep-1-rfinal-001",
        "single_run_sequence": 1,
        "status": "RAW_NOT_ADJUDICATED",
        "verdict": None,
        "target_head": SHA_A[:40],
        "prereg_lock_sha256": SHA_A,
        "prereg_candidate_sha256": SHA_B,
        "exact_manifest_sha256": SHA_C,
        "independent_review_sha256": SHA_A,
        "provider_bindings_sha256": SHA_B,
        "oracle_custody_sha256": SHA_C,
        "public_cases_sha256": SHA_A,
        "referee_cases_sha256": SHA_B,
        "response_matrix_sha256": SHA_C,
        "truth_join_sha256": SHA_A,
        "raw_response_archive_sha256": SHA_B,
        "metrics": metrics,
        "metrics_sha256": canonical_digest(metrics),
        "case_count": 74,
        "arm_count": 2,
        "provider_response_count": 148,
        "provider_call_count": 148,
        "correction_epoch": 9,
        "collection_operator_id": "external-collection-operator",
        "run_authority_id": "external-run-authority",
        "c7_authority_id": "external-c7-authority",
        "c7_decision": "ALLOW",
        "result_adjudicator_id": None,
    }


class RawRFinalContractTests(unittest.TestCase):
    def test_closed_raw_result_binds_exact_run_inputs_and_remains_unadjudicated(self) -> None:
        payload = _result_mapping()
        result = validate_raw_rfinal_result(payload)
        self.assertIsInstance(result, RawRFinalResult)
        self.assertEqual(result.status, "RAW_NOT_ADJUDICATED")
        self.assertIsNone(result.verdict)
        self.assertIsNone(result.result_adjudicator_id)
        self.assertEqual(result.provider_response_count, 74 * 2)
        self.assertEqual(result.to_mapping(), payload)

    def test_unknown_fields_status_verdict_or_second_run_are_rejected(self) -> None:
        for field, value in (
            ("unknown", "field"),
            ("status", "ACCEPTED"),
            ("verdict", "PASS"),
            ("single_run_sequence", 2),
        ):
            payload = _result_mapping()
            payload[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_raw_rfinal_result(payload)

    def test_digest_matrix_role_and_metric_drift_fail_closed(self) -> None:
        mutations = []
        zero_digest = _result_mapping()
        zero_digest["prereg_lock_sha256"] = "0" * 64
        mutations.append(zero_digest)

        ragged = _result_mapping()
        ragged["provider_response_count"] = 147
        mutations.append(ragged)

        role_collapse = _result_mapping()
        role_collapse["c7_authority_id"] = role_collapse["run_authority_id"]
        mutations.append(role_collapse)

        metrics_drift = _result_mapping()
        metrics_drift["metrics_sha256"] = SHA_A
        mutations.append(metrics_drift)

        empty_metrics = _result_mapping()
        empty_metrics["metrics"] = {}
        empty_metrics["metrics_sha256"] = canonical_digest({})
        mutations.append(empty_metrics)

        for index, payload in enumerate(mutations):
            with self.subTest(index=index), self.assertRaises(ValueError):
                validate_raw_rfinal_result(payload)

    def test_nonfinite_metric_is_rejected_by_canonical_binding(self) -> None:
        payload = _result_mapping()
        metrics = copy.deepcopy(payload["metrics"])
        metrics["nan"] = math.nan
        payload["metrics"] = metrics
        payload["metrics_sha256"] = SHA_A
        with self.assertRaises(ValueError):
            validate_raw_rfinal_result(payload)

    def test_formal_schema_is_closed_and_module_exposes_no_runner(self) -> None:
        schema_path = REPO_ROOT / "experiments/r_eval_indep_1/native_result_schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["status"]["const"], "RAW_NOT_ADJUDICATED")
        self.assertEqual(schema["properties"]["verdict"]["type"], "null")
        self.assertEqual(schema["properties"]["single_run_sequence"]["const"], 1)

        import experiments.r_eval_indep_1.native_result as native_result

        self.assertFalse(hasattr(native_result, "run_rfinal"))
        self.assertFalse(hasattr(native_result, "write_result"))


if __name__ == "__main__":
    unittest.main()
