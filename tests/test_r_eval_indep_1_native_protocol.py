from __future__ import annotations

import unittest

from experiments.r_eval_indep_1.contracts import (
    ContractValidationError,
    ReviewDisposition,
    ReviewerIdentity,
    canonical_digest,
)
from experiments.r_eval_indep_1.corpus_contracts import PublicCaseManifest
from experiments.r_eval_indep_1.native_protocol import (
    CollectionPermit,
    NativeReviewResponse,
    ReviewCollectionError,
    ReviewRequest,
    ReviewerClient,
    ReviewerEndpointBinding,
    collect_complete_response_matrix,
)


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def _identity(*, reviewer_id: str = "reviewer-a") -> ReviewerIdentity:
    return ReviewerIdentity.from_mapping(
        {
            "reviewer_id": reviewer_id,
            "provider_family": "provider-family-a",
            "served_model_id": "served-model-a",
            "model_version": "revision-2026-07-15",
            "endpoint_class": "responses-api",
            "system_prompt_sha256": SHA_A,
            "task_prompt_sha256": SHA_B,
            "tool_profile_sha256": SHA_C,
            "context_manifest_sha256": SHA_A,
            "decoding_config_sha256": SHA_B,
            "fallback_policy": "FORBIDDEN",
        }
    )


def _public_case(index: int) -> PublicCaseManifest:
    unsigned: dict[str, object] = {
        "case_id": f"case-{index:016x}",
        "source_relpath": "src/aac/example.py",
        "source_sha256": SHA_A,
        "test_relpath": "tests/test_example.py",
        "test_sha256": SHA_B,
        "support_sha256": {},
        "candidate_sha256": SHA_C,
        "patch_sha256": canonical_digest({"patch": index}),
        "candidate_patch": f"--- a/example.py\n+++ b/example.py\n@@ case {index}\n",
        "public_checks": ["python-I-independent-oracle-v1"],
    }
    payload = dict(unsigned)
    payload["public_manifest_sha256"] = canonical_digest(unsigned)
    return PublicCaseManifest.from_mapping(payload)


def _endpoint(
    *, arm_id: str, public_cases_sha256: str, reviewer_id: str
) -> ReviewerEndpointBinding:
    identity = _identity(reviewer_id=reviewer_id)
    return ReviewerEndpointBinding.from_mapping(
        {
            "arm_id": arm_id,
            "reviewer_identity": identity.to_mapping(),
            "transport": "API_ONLY",
            "api_protocol": "RESPONSES_API",
            "credential_ref_sha256": SHA_A,
            "endpoint_origin_sha256": SHA_B,
            "public_cases_sha256": public_cases_sha256,
        }
    )


def _permit(**updates: object) -> CollectionPermit:
    payload: dict[str, object] = {
        "run_id": "r-eval-indep-1-test-run",
        "prereg_lock_sha256": SHA_A,
        "exact_manifest_sha256": SHA_B,
        "independent_review_sha256": SHA_C,
        "run_authority_id": "test-run-authority",
        "c7_authority_id": "test-c7-authority",
        "correction_epoch": 7,
        "c7_decision": "ALLOW",
        "single_run_sequence": 1,
    }
    payload.update(updates)
    return CollectionPermit.from_mapping(payload)


class FakeReviewerClient:
    def __init__(self, endpoint_binding: ReviewerEndpointBinding) -> None:
        self._endpoint_binding = endpoint_binding
        self.requests: list[ReviewRequest] = []

    @property
    def endpoint_binding(self) -> ReviewerEndpointBinding:
        return self._endpoint_binding

    def review_api(self, request: ReviewRequest) -> NativeReviewResponse:
        self.requests.append(request)
        return NativeReviewResponse.from_mapping(
            {
                "case_id": request.case_id,
                "arm_id": request.arm_id,
                "request_sha256": request.request_sha256,
                "endpoint_binding_sha256": request.endpoint_binding_sha256,
                "reviewer_identity_digest": request.reviewer_identity_digest,
                "public_manifest_sha256": request.public_manifest_sha256,
                "disposition": ReviewDisposition.REJECT.value,
                "p_candidate_valid_micros": 100_000,
                "blocking_findings": ["typed finding"],
                "generated_test_patch": None,
                "input_tokens": 100,
                "output_tokens": 20,
                "cost_microusd": 30,
                "latency_ms": 40,
                "provider_response_id_sha256": SHA_A,
                "raw_response_sha256": SHA_B,
            }
        )


class ReviewerEndpointContractTests(unittest.TestCase):
    def test_api_only_transport_and_no_fallback_are_closed(self) -> None:
        public_digest = canonical_digest([_public_case(1).to_mapping()])
        binding = _endpoint(
            arm_id="arm-a",
            public_cases_sha256=public_digest,
            reviewer_id="reviewer-a",
        )
        self.assertEqual(binding.transport.value, "API_ONLY")
        self.assertEqual(binding.reviewer_identity.fallback_policy, "FORBIDDEN")
        self.assertIsInstance(FakeReviewerClient(binding), ReviewerClient)

        payload = binding.to_mapping()
        payload["transport"] = "CLI"
        with self.assertRaises(ContractValidationError):
            ReviewerEndpointBinding.from_mapping(payload)

        payload = binding.to_mapping()
        payload["api_protocol"] = "SHELL"
        with self.assertRaises(ContractValidationError):
            ReviewerEndpointBinding.from_mapping(payload)

    def test_identity_digest_changes_with_model_prompt_or_decoding(self) -> None:
        original = _identity()
        for field, value in (
            ("model_version", "revision-b"),
            ("system_prompt_sha256", SHA_C),
            ("decoding_config_sha256", SHA_C),
        ):
            payload = original.to_mapping()
            payload[field] = value
            changed = ReviewerIdentity.from_mapping(payload)
            with self.subTest(field=field):
                self.assertNotEqual(changed.digest(), original.digest())


class CompleteResponseCollectorTests(unittest.TestCase):
    def _fixture(
        self,
    ) -> tuple[
        tuple[PublicCaseManifest, ...],
        tuple[ReviewerEndpointBinding, ...],
        dict[str, FakeReviewerClient],
    ]:
        cases = (_public_case(1), _public_case(2))
        public_digest = canonical_digest([case.to_mapping() for case in cases])
        bindings = (
            _endpoint(
                arm_id="arm-a",
                public_cases_sha256=public_digest,
                reviewer_id="reviewer-a",
            ),
            _endpoint(
                arm_id="arm-b",
                public_cases_sha256=public_digest,
                reviewer_id="reviewer-b",
            ),
        )
        clients = {
            binding.arm_id: FakeReviewerClient(binding) for binding in bindings
        }
        return cases, bindings, clients

    def test_collects_exact_case_by_arm_matrix_with_bound_requests(self) -> None:
        cases, bindings, clients = self._fixture()
        rows = collect_complete_response_matrix(
            permit=_permit(),
            public_cases=cases,
            endpoint_bindings=bindings,
            clients=clients,
        )
        self.assertEqual(len(rows), 4)
        self.assertEqual(
            [(row.case_id, row.arm_id) for row in rows],
            [
                (cases[0].case_id, "arm-a"),
                (cases[0].case_id, "arm-b"),
                (cases[1].case_id, "arm-a"),
                (cases[1].case_id, "arm-b"),
            ],
        )
        self.assertTrue(all(row.cost_microusd == 30 for row in rows))
        self.assertEqual(sum(len(client.requests) for client in clients.values()), 4)
        first = clients["arm-a"].requests[0]
        self.assertEqual(first.model_version, "revision-2026-07-15")
        self.assertEqual(first.system_prompt_sha256, SHA_A)
        self.assertEqual(first.decoding_config_sha256, SHA_B)
        self.assertEqual(first.public_manifest_sha256, cases[0].public_manifest_sha256)

    def test_c7_halt_and_incomplete_client_map_fail_before_calls(self) -> None:
        cases, bindings, clients = self._fixture()
        with self.assertRaisesRegex(ReviewCollectionError, "C7"):
            collect_complete_response_matrix(
                permit=_permit(c7_decision="HALT"),
                public_cases=cases,
                endpoint_bindings=bindings,
                clients=clients,
            )
        self.assertEqual(sum(len(client.requests) for client in clients.values()), 0)

        with self.assertRaisesRegex(ReviewCollectionError, "client map"):
            collect_complete_response_matrix(
                permit=_permit(),
                public_cases=cases,
                endpoint_bindings=bindings,
                clients={"arm-a": clients["arm-a"]},
            )
        self.assertEqual(sum(len(client.requests) for client in clients.values()), 0)

    def test_client_binding_or_response_binding_drift_fails_closed(self) -> None:
        cases, bindings, clients = self._fixture()
        clients["arm-a"] = FakeReviewerClient(bindings[1])
        with self.assertRaisesRegex(ReviewCollectionError, "client binding"):
            collect_complete_response_matrix(
                permit=_permit(),
                public_cases=cases,
                endpoint_bindings=bindings,
                clients=clients,
            )

        cases, bindings, clients = self._fixture()

        class DriftedResponseClient(FakeReviewerClient):
            def review_api(self, request: ReviewRequest) -> NativeReviewResponse:
                response = super().review_api(request).to_mapping()
                response["request_sha256"] = SHA_C
                return NativeReviewResponse.from_mapping(response)

        clients["arm-a"] = DriftedResponseClient(bindings[0])
        with self.assertRaisesRegex(ReviewCollectionError, "response binding"):
            collect_complete_response_matrix(
                permit=_permit(),
                public_cases=cases,
                endpoint_bindings=bindings,
                clients=clients,
            )

    def test_endpoint_public_set_digest_must_match_exact_case_bytes(self) -> None:
        cases, bindings, clients = self._fixture()
        payload = bindings[0].to_mapping()
        payload["public_cases_sha256"] = SHA_C
        drifted = ReviewerEndpointBinding.from_mapping(payload)
        with self.assertRaisesRegex(ReviewCollectionError, "public case set"):
            collect_complete_response_matrix(
                permit=_permit(),
                public_cases=cases,
                endpoint_bindings=(drifted, bindings[1]),
                clients={"arm-a": FakeReviewerClient(drifted), "arm-b": clients["arm-b"]},
            )


if __name__ == "__main__":
    unittest.main()
