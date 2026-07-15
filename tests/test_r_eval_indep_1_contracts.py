from __future__ import annotations

import unittest

from experiments.r_eval_indep_1.contracts import (
    CaseTruth,
    ContractValidationError,
    IdentityCollapseError,
    MatrixIntegrityError,
    PublicCaseBundle,
    ReviewDisposition,
    ReviewerIdentity,
    ReviewResponse,
    canonical_digest,
    validate_identity_separation,
    validate_response_matrix,
)


SHA_A = "a" * 64
SHA_B = "b" * 64
CASES = ("case-0000000000000001", "case-0000000000000002")
ARMS = ("arm-a", "arm-b")


def reviewer_mapping(**updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "reviewer_id": "reviewer-a",
        "provider_family": "provider-a",
        "served_model_id": "model-a",
        "model_version": "version-a",
        "endpoint_class": "api",
        "system_prompt_sha256": SHA_A,
        "task_prompt_sha256": SHA_B,
        "tool_profile_sha256": SHA_A,
        "context_manifest_sha256": SHA_B,
        "decoding_config_sha256": SHA_A,
        "fallback_policy": "FORBIDDEN",
    }
    payload.update(updates)
    return payload


def response(case_id: str, arm_id: str, disposition: ReviewDisposition) -> ReviewResponse:
    return ReviewResponse.from_mapping(
        {
            "case_id": case_id,
            "arm_id": arm_id,
            "reviewer_identity_digest": SHA_A,
            "disposition": disposition.value,
            "p_candidate_valid_micros": 500_000,
            "blocking_findings": [],
            "generated_test_patch": None,
            "input_tokens": 10,
            "output_tokens": 5,
            "latency_ms": 25,
            "raw_response_sha256": SHA_B,
        }
    )


class ClosedContractTests(unittest.TestCase):
    def test_unknown_fields_fail_closed(self) -> None:
        payload = reviewer_mapping(unknown_field="must-not-pass")
        with self.assertRaises(ContractValidationError):
            ReviewerIdentity.from_mapping(payload)

    def test_provider_fallback_is_forbidden(self) -> None:
        with self.assertRaises(ContractValidationError):
            ReviewerIdentity.from_mapping(reviewer_mapping(fallback_policy="ALLOW"))

    def test_hidden_paths_and_labels_cannot_enter_public_bundle(self) -> None:
        unsigned = {
            "case_id": CASES[0],
            "source_language": "python",
            "base_snapshot_sha256": SHA_A,
            "candidate_patch": "--- a/module.py\n+++ b/module.py\n",
            "public_requirements": ["Preserve the typed contract."],
            "public_checks": ["python -m py_compile module.py"],
        }
        base = dict(unsigned)
        base["public_manifest_sha256"] = canonical_digest(unsigned)
        PublicCaseBundle.from_mapping(base)

        leaked_path = dict(base)
        leaked_path["candidate_patch"] = "+++ b/referee/hidden_oracle.py"
        with self.assertRaises(ContractValidationError):
            PublicCaseBundle.from_mapping(leaked_path)

        leaked_label = dict(base)
        leaked_label["label"] = CaseTruth.HARMFUL.value
        with self.assertRaises(ContractValidationError):
            PublicCaseBundle.from_mapping(leaked_label)

        leaked_text = dict(base)
        leaked_text["public_requirements"] = ["Read gold_label before deciding."]
        unsigned_leaked = dict(leaked_text)
        unsigned_leaked.pop("public_manifest_sha256")
        leaked_text["public_manifest_sha256"] = canonical_digest(unsigned_leaked)
        with self.assertRaises(ContractValidationError):
            PublicCaseBundle.from_mapping(leaked_text)

    def test_public_manifest_digest_must_bind_exact_public_content(self) -> None:
        payload = {
            "case_id": CASES[0],
            "source_language": "python",
            "base_snapshot_sha256": SHA_A,
            "candidate_patch": "--- a/module.py\n+++ b/module.py\n",
            "public_requirements": ["Preserve behavior."],
            "public_checks": ["python -m py_compile module.py"],
            "public_manifest_sha256": SHA_B,
        }
        with self.assertRaises(ContractValidationError):
            PublicCaseBundle.from_mapping(payload)

    def test_canonical_digest_is_stable_and_not_constant(self) -> None:
        first = canonical_digest({"b": 2, "a": 1})
        reordered = canonical_digest({"a": 1, "b": 2})
        changed = canonical_digest({"a": 1, "b": 3})
        self.assertEqual(first, reordered)
        self.assertNotEqual(first, changed)
        self.assertRegex(first, r"^[0-9a-f]{64}$")


class IdentitySeparationTests(unittest.TestCase):
    def test_builder_or_referee_cannot_be_a_reviewer(self) -> None:
        reviewer = ReviewerIdentity.from_mapping(reviewer_mapping(reviewer_id="builder"))
        with self.assertRaises(IdentityCollapseError):
            validate_identity_separation(
                mutation_builder_id="builder",
                oracle_author_id="oracle",
                adjudicator_id="adjudicator",
                reviewers=(reviewer,),
            )

    def test_sovereign_roles_must_be_distinct(self) -> None:
        reviewer = ReviewerIdentity.from_mapping(reviewer_mapping())
        with self.assertRaises(IdentityCollapseError):
            validate_identity_separation(
                mutation_builder_id="builder",
                oracle_author_id="builder",
                adjudicator_id="adjudicator",
                reviewers=(reviewer,),
            )


class ResponseMatrixTests(unittest.TestCase):
    def test_complete_matrix_is_accepted(self) -> None:
        rows = tuple(
            response(case_id, arm_id, ReviewDisposition.ACCEPT)
            for case_id in CASES
            for arm_id in ARMS
        )
        validated = validate_response_matrix(CASES, ARMS, rows)
        self.assertEqual(len(validated), 4)

    def test_duplicate_case_arm_pair_is_rejected(self) -> None:
        row = response(CASES[0], ARMS[0], ReviewDisposition.ACCEPT)
        with self.assertRaises(MatrixIntegrityError):
            validate_response_matrix(CASES[:1], ARMS[:1], (row, row))

    def test_missing_arm_and_ragged_zip_are_rejected(self) -> None:
        rows = (
            response(CASES[0], ARMS[0], ReviewDisposition.ACCEPT),
            response(CASES[0], ARMS[1], ReviewDisposition.REJECT),
            response(CASES[1], ARMS[0], ReviewDisposition.ACCEPT),
        )
        with self.assertRaises(MatrixIntegrityError):
            validate_response_matrix(CASES, ARMS, rows)

    def test_unexpected_case_or_arm_is_rejected(self) -> None:
        rows = (response("case-ffffffffffffffff", ARMS[0], ReviewDisposition.ACCEPT),)
        with self.assertRaises(MatrixIntegrityError):
            validate_response_matrix(CASES[:1], ARMS[:1], rows)

    def test_reviewer_identity_cannot_drift_within_an_arm(self) -> None:
        first = response(CASES[0], ARMS[0], ReviewDisposition.ACCEPT)
        second_payload = response(
            CASES[1], ARMS[0], ReviewDisposition.REJECT
        ).to_mapping()
        second_payload["reviewer_identity_digest"] = SHA_B
        second = ReviewResponse.from_mapping(second_payload)
        with self.assertRaises(MatrixIntegrityError):
            validate_response_matrix(CASES, ARMS[:1], (first, second))


if __name__ == "__main__":
    unittest.main()
