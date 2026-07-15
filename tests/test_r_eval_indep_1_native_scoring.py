from __future__ import annotations

import unittest

from experiments.r_eval_indep_1.contracts import (
    CaseTruth,
    MatrixIntegrityError,
    ReviewDisposition,
)
from experiments.r_eval_indep_1.native_protocol import NativeReviewResponse
from experiments.r_eval_indep_1.native_scoring import (
    UNDEFINED,
    score_native_matrix,
)


SHA_A = "a" * 64
SHA_B = "b" * 64
CASES = tuple(f"case-{index:016x}" for index in range(1, 5))
TRUTH = {
    CASES[0]: CaseTruth.HARMFUL,
    CASES[1]: CaseTruth.HARMFUL,
    CASES[2]: CaseTruth.CLEAN,
    CASES[3]: CaseTruth.CLEAN,
}


def _row(
    case_id: str,
    arm_id: str,
    disposition: ReviewDisposition,
    probability_micros: int,
    *,
    cost_microusd: int,
    latency_ms: int,
) -> NativeReviewResponse:
    identity = SHA_A if arm_id == "arm-a" else SHA_B
    return NativeReviewResponse.from_mapping(
        {
            "case_id": case_id,
            "arm_id": arm_id,
            "request_sha256": SHA_A,
            "endpoint_binding_sha256": SHA_B,
            "reviewer_identity_digest": identity,
            "public_manifest_sha256": SHA_A,
            "disposition": disposition.value,
            "p_candidate_valid_micros": probability_micros,
            "blocking_findings": [],
            "generated_test_patch": None,
            "input_tokens": 100,
            "output_tokens": 25,
            "cost_microusd": cost_microusd,
            "latency_ms": latency_ms,
            "provider_response_id_sha256": SHA_A,
            "raw_response_sha256": SHA_B,
        }
    )


def _matrix() -> tuple[NativeReviewResponse, ...]:
    arm_a = (
        _row(CASES[0], "arm-a", ReviewDisposition.ACCEPT, 900_000, cost_microusd=100, latency_ms=10),
        _row(CASES[1], "arm-a", ReviewDisposition.ABSTAIN, 400_000, cost_microusd=100, latency_ms=20),
        _row(CASES[2], "arm-a", ReviewDisposition.ACCEPT, 900_000, cost_microusd=100, latency_ms=30),
        _row(CASES[3], "arm-a", ReviewDisposition.REJECT, 400_000, cost_microusd=100, latency_ms=40),
    )
    arm_b = (
        _row(CASES[0], "arm-b", ReviewDisposition.REJECT, 800_000, cost_microusd=50, latency_ms=15),
        _row(CASES[1], "arm-b", ReviewDisposition.REJECT, 200_000, cost_microusd=50, latency_ms=25),
        _row(CASES[2], "arm-b", ReviewDisposition.ACCEPT, 800_000, cost_microusd=50, latency_ms=35),
        _row(CASES[3], "arm-b", ReviewDisposition.ACCEPT, 200_000, cost_microusd=50, latency_ms=45),
    )
    return (*arm_a, *arm_b)


class NativeScoringTests(unittest.TestCase):
    def test_scores_false_acceptance_miss_cost_latency_and_pairwise_residuals(self) -> None:
        report = score_native_matrix(TRUTH, ("arm-a", "arm-b"), _matrix())
        arm_a = report.arm_scores["arm-a"]
        self.assertEqual(arm_a.false_acceptance_count, 1)
        self.assertEqual(arm_a.false_acceptance_rate, 0.5)
        self.assertEqual(arm_a.harmful_miss_count, 2)
        self.assertEqual(arm_a.harmful_miss_rate, 1.0)
        self.assertEqual(arm_a.clean_accept_rate, 0.5)
        self.assertEqual(arm_a.abstention_rate, 0.25)
        self.assertEqual(arm_a.total_input_tokens, 400)
        self.assertEqual(arm_a.total_output_tokens, 100)
        self.assertEqual(arm_a.total_cost_microusd, 400)
        self.assertEqual(arm_a.mean_cost_microusd, 100.0)
        self.assertEqual(arm_a.mean_latency_ms, 25.0)
        self.assertEqual(arm_a.latency_p95_ms, 40)

        pair = report.pairwise_scores[("arm-a", "arm-b")]
        self.assertIsInstance(pair.residual_correlation, float)
        assert isinstance(pair.residual_correlation, float)
        self.assertAlmostEqual(pair.residual_correlation, 1.0)
        self.assertEqual(pair.joint_false_acceptance_rate, 0.0)
        self.assertRegex(report.response_matrix_sha256, r"^[0-9a-f]{64}$")
        self.assertRegex(report.truth_sha256, r"^[0-9a-f]{64}$")

    def test_residual_correlation_is_undefined_for_zero_class_centered_variance(self) -> None:
        rows = tuple(
            _row(
                case_id,
                arm_id,
                ReviewDisposition.REJECT,
                500_000,
                cost_microusd=0,
                latency_ms=1,
            )
            for arm_id in ("arm-a", "arm-b")
            for case_id in CASES
        )
        report = score_native_matrix(TRUTH, ("arm-a", "arm-b"), rows)
        pair = report.pairwise_scores[("arm-a", "arm-b")]
        self.assertEqual(pair.residual_correlation, UNDEFINED)
        self.assertEqual(pair.residual_status, "UNDEFINED_ZERO_VARIANCE")

    def test_truth_and_matrix_integrity_fail_closed_instead_of_imputing(self) -> None:
        with self.assertRaisesRegex(ValueError, "harmful.*clean"):
            score_native_matrix(
                {case_id: CaseTruth.HARMFUL for case_id in CASES},
                ("arm-a", "arm-b"),
                _matrix(),
            )
        with self.assertRaises(MatrixIntegrityError):
            score_native_matrix(TRUTH, ("arm-a", "arm-b"), _matrix()[:-1])

    def test_unknown_truth_case_is_not_joined_silently(self) -> None:
        truth = dict(TRUTH)
        truth["case-ffffffffffffffff"] = CaseTruth.HARMFUL
        with self.assertRaises(MatrixIntegrityError):
            score_native_matrix(truth, ("arm-a", "arm-b"), _matrix())


if __name__ == "__main__":
    unittest.main()
