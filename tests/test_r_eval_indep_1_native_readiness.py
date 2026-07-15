from __future__ import annotations

import copy
import unittest
from pathlib import Path

from experiments.r_eval_indep_1.native_readiness import (
    NativePreregCandidate,
    ReadinessError,
    ReviewGateRecord,
    assess_native_readiness,
    assert_native_readiness,
    load_native_prereg,
)


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
REPO_ROOT = Path(__file__).resolve().parents[1]
PREREG_PATH = REPO_ROOT / "docs/research/R-EVAL-INDEP-1-preregistration-spec.yaml"


def _provider_binding(
    *, public_cases_sha256: str, reviewer_id: str = "external-reviewer-a"
) -> dict[str, object]:
    return {
        "arm_id": "native-arm-a",
        "reviewer_identity": {
            "reviewer_id": reviewer_id,
            "provider_family": "provider-family-a",
            "served_model_id": "served-model-a",
            "model_version": "immutable-revision-a",
            "endpoint_class": "responses-api",
            "system_prompt_sha256": SHA_A,
            "task_prompt_sha256": SHA_B,
            "tool_profile_sha256": SHA_C,
            "context_manifest_sha256": SHA_A,
            "decoding_config_sha256": SHA_B,
            "fallback_policy": "FORBIDDEN",
        },
        "transport": "API_ONLY",
        "api_protocol": "RESPONSES_API",
        "credential_ref_sha256": SHA_A,
        "endpoint_origin_sha256": SHA_B,
        "public_cases_sha256": public_cases_sha256,
    }


def _fully_bound_candidate() -> NativePreregCandidate:
    base_candidate = load_native_prereg(PREREG_PATH)
    payload = copy.deepcopy(base_candidate.to_mapping())
    manifest_sha = payload["exact_manifest"]["sha256"]
    bindings = payload["external_bindings"]
    bindings["provider_bindings"] = [
        _provider_binding(
            public_cases_sha256=base_candidate.corpus.public_cases_sha256
        )
    ]
    bindings["oracle_custody"] = {
        "custodian_id": "external-oracle-custodian",
        "sealed_referee_sha256": base_candidate.corpus.referee_cases_sha256,
    }
    bindings["c7_authority"] = {
        "authority_id": "external-c7-authority",
        "writable_by_runtime": False,
    }
    bindings["independent_review"] = {
        "builder_id": "native-readiness-builder",
        "reviewer_id": "external-code-reviewer",
        "target_head": SHA_A[:40],
        "prereg_candidate_sha256": base_candidate.review_subject_sha256(),
        "exact_manifest_sha256": manifest_sha,
        "verdict": "ACCEPT",
        "review_record_sha256": SHA_C,
    }
    bindings["freezer_identity"] = "external-freezer"
    bindings["run_authority"] = {
        "authority_id": "external-run-authority",
        "single_run_sequence": 1,
    }
    return NativePreregCandidate.from_mapping(payload)


class CommittedPreregCandidateTests(unittest.TestCase):
    def test_candidate_is_formal_exact_and_honestly_blocked(self) -> None:
        candidate = load_native_prereg(PREREG_PATH)
        self.assertEqual(candidate.prereg_id, "R-EVAL-INDEP-1")
        self.assertEqual(
            candidate.mechanism.channel_claim,
            "other(research-evaluator-independence)",
        )
        self.assertTrue(candidate.mechanism.files)
        self.assertEqual(
            set(candidate.mechanism.files), set(candidate.exact_manifest.files)
        )
        self.assertIn(candidate.result_schema_path, candidate.mechanism.files)
        candidate.exact_manifest.verify(REPO_ROOT)
        self.assertTrue(candidate.controls.one_result_bearing_run)
        self.assertEqual(candidate.controls.provider_transport, "API_ONLY")
        self.assertEqual(candidate.controls.provider_fallback, "FORBIDDEN")
        self.assertEqual(candidate.controls.rerun, "FORBIDDEN")
        self.assertEqual(candidate.controls.rescue, "FORBIDDEN")
        self.assertEqual(candidate.controls.rethreshold, "FORBIDDEN")
        self.assertEqual(candidate.controls.rearm, "FORBIDDEN")
        self.assertEqual(candidate.controls.refill, "FORBIDDEN")
        self.assertTrue(candidate.controls.c7_external)
        self.assertFalse(candidate.controls.c7_writable_by_runtime)

        report = assess_native_readiness(candidate, REPO_ROOT)
        self.assertEqual(report.status, "BLOCKED_UNBOUND")
        self.assertEqual(
            report.blockers,
            (
                "PROVIDER_BINDINGS_UNBOUND",
                "ORACLE_CUSTODY_UNBOUND",
                "C7_AUTHORITY_UNBOUND",
                "INDEPENDENT_REVIEW_UNBOUND",
                "FREEZER_IDENTITY_UNBOUND",
                "RUN_AUTHORITY_UNBOUND",
            ),
        )
        with self.assertRaises(ReadinessError):
            assert_native_readiness(candidate, REPO_ROOT)

    def test_candidate_has_no_placeholder_or_invented_external_identity(self) -> None:
        candidate = load_native_prereg(PREREG_PATH)
        self.assertEqual(candidate.external_bindings.provider_bindings, ())
        self.assertIsNone(candidate.external_bindings.oracle_custody)
        self.assertIsNone(candidate.external_bindings.c7_authority)
        self.assertIsNone(candidate.external_bindings.independent_review)
        self.assertIsNone(candidate.external_bindings.freezer_identity)
        self.assertIsNone(candidate.external_bindings.run_authority)
        self.assertEqual(candidate.gates.freeze_status, "NOT_FROZEN")
        self.assertEqual(candidate.gates.run_status, "NOT_RUN")
        self.assertEqual(candidate.gates.evidence_status, "NOT_EVIDENCE")


class ReadinessBrakeTests(unittest.TestCase):
    def test_test_only_complete_fixture_can_reach_external_freeze_readiness(self) -> None:
        candidate = _fully_bound_candidate()
        report = assert_native_readiness(candidate, REPO_ROOT)
        self.assertEqual(report.status, "READY_FOR_EXTERNAL_FREEZE")
        self.assertEqual(report.blockers, ())

    def test_review_gate_is_closed_and_builder_must_differ_from_reviewer(self) -> None:
        payload = _fully_bound_candidate().to_mapping()
        review = payload["external_bindings"]["independent_review"]
        review["reviewer_id"] = review["builder_id"]
        with self.assertRaises(ValueError):
            assess_native_readiness(NativePreregCandidate.from_mapping(payload), REPO_ROOT)

        review_payload = _fully_bound_candidate().external_bindings.independent_review
        self.assertIsInstance(review_payload, ReviewGateRecord)
        assert review_payload is not None
        unknown = review_payload.to_mapping()
        unknown["acceptance_note"] = "invented"
        with self.assertRaises(ValueError):
            ReviewGateRecord.from_mapping(unknown)

    def test_sovereign_identity_collapse_and_manifest_drift_fail_closed(self) -> None:
        payload = _fully_bound_candidate().to_mapping()
        payload["external_bindings"]["freezer_identity"] = "external-c7-authority"
        with self.assertRaises(ValueError):
            assess_native_readiness(NativePreregCandidate.from_mapping(payload), REPO_ROOT)

        payload = _fully_bound_candidate().to_mapping()
        first_path = next(iter(payload["exact_manifest"]["files"]))
        payload["exact_manifest"]["files"][first_path] = SHA_A
        with self.assertRaises(ValueError):
            assess_native_readiness(NativePreregCandidate.from_mapping(payload), REPO_ROOT)


if __name__ == "__main__":
    unittest.main()
