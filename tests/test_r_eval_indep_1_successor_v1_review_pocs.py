from __future__ import annotations

import hashlib
import inspect
import json
import unittest
from dataclasses import replace
from pathlib import Path

from experiments.r_eval_indep_1.freeze_run_context import (
    RunExecutionPermit,
    SignedReceipt,
    VerifiedReceiptIdentity,
    verify_freeze_run_context,
)
from experiments.r_eval_indep_1.native_protocol import CollectionPermit
from experiments.r_eval_indep_1.contracts import canonical_json_bytes
from experiments.r_eval_indep_1.runner import NativeSuccessorRunner, _canonical


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
COLLECTION_KEY = "1" * 64
RUN_KEY = "2" * 64
C7_KEY = "3" * 64
ORACLE_KEY = "4" * 64
TRUST_REGISTRY = "5" * 64
REPO_ROOT = Path(__file__).resolve().parents[1]


class RejectAllVerifier:
    def verify(self, receipt: SignedReceipt) -> VerifiedReceiptIdentity | None:
        return None


class AcceptAllVerifier:
    def verify(self, receipt: SignedReceipt) -> VerifiedReceiptIdentity | None:
        return VerifiedReceiptIdentity(
            receipt_sha256=receipt.digest(),
            signer_id=receipt.signer_id,
            public_key_sha256=receipt.public_key_sha256,
            trust_registry_sha256=TRUST_REGISTRY,
        )


class ReattachingVerifier:
    def verify(self, receipt: SignedReceipt) -> VerifiedReceiptIdentity | None:
        return VerifiedReceiptIdentity(
            receipt_sha256=receipt.digest(),
            signer_id="trusted-run-authority",
            public_key_sha256=SHA_C,
            trust_registry_sha256=SHA_B,
        )


class ReviewPermitPoCs(unittest.TestCase):
    def test_archive_uses_the_route_canonical_json_contract(self) -> None:
        value = {"model_revision": "模型-版本-1"}
        self.assertEqual(_canonical(value), canonical_json_bytes(value))

    def test_exact_manifest_binds_every_successor_remediation_file(self) -> None:
        manifest_path = (
            REPO_ROOT / "docs/research/R-EVAL-INDEP-1-successor-v1-exact-manifest.json"
        )
        manifest = json.loads(manifest_path.read_text())
        expected_files = {
            "docs/research/R-EVAL-INDEP-1-successor-v1-preregistration-spec.yaml",
            "experiments/r_eval_indep_1/freeze_run_context.py",
            "experiments/r_eval_indep_1/native_arm_plan.py",
            "experiments/r_eval_indep_1/provider_adapter.py",
            "experiments/r_eval_indep_1/result_contracts.py",
            "experiments/r_eval_indep_1/routing_policy.py",
            "experiments/r_eval_indep_1/run_budget.py",
            "experiments/r_eval_indep_1/runner.py",
            "experiments/r_eval_indep_1/scoring.py",
            "tests/test_r_eval_indep_1_successor_v1.py",
            "tests/test_r_eval_indep_1_successor_v1_review_pocs.py",
        }
        self.assertEqual(
            manifest["target_base_head"],
            "19eb054394174d95dafbe4b206efbcffc624c477",
        )
        self.assertEqual(set(manifest["files"]), expected_files)
        for relative_path, expected_sha256 in manifest["files"].items():
            actual_sha256 = hashlib.sha256(
                (REPO_ROOT / relative_path).read_bytes()
            ).hexdigest()
            self.assertEqual(actual_sha256, expected_sha256, relative_path)

    def test_unsigned_or_unverified_collection_and_execution_permits_are_rejected(
        self,
    ) -> None:
        collection = CollectionPermit.from_mapping(
            {
                "run_id": "r-eval-indep-1-rfinal-001",
                "prereg_lock_sha256": SHA_A,
                "exact_manifest_sha256": SHA_B,
                "independent_review_sha256": SHA_C,
                "run_authority_id": "run-authority",
                "c7_authority_id": "c7-authority",
                "correction_epoch": 7,
                "c7_decision": "ALLOW",
                "single_run_sequence": 1,
            }
        )
        execution = RunExecutionPermit(
            route_id="R-EVAL-INDEP-1",
            run_id=collection.run_id,
            global_run_sequence=1,
            collection_permit_sha256=collection.digest(),
            prereg_spec_sha256=SHA_A,
            exact_manifest_sha256=SHA_B,
            freeze_subject_sha256=SHA_C,
            correction_epoch=7,
            corpus_manifest_sha256=SHA_A,
            public_cases_sha256=SHA_B,
            provider_bank_sha256=SHA_C,
            budget_sha256=SHA_A,
            freeze_receipt_sha256=SHA_B,
            run_authority_receipt_sha256=SHA_C,
            collection_authority_id="collection-authority",
            collection_authority_public_key_sha256=COLLECTION_KEY,
            run_authority_public_key_sha256=RUN_KEY,
            c7_authority_public_key_sha256=C7_KEY,
            oracle_custodian_id="oracle-custodian",
            oracle_custodian_public_key_sha256=ORACLE_KEY,
            trust_registry_sha256=TRUST_REGISTRY,
        )
        receipt = SignedReceipt(
            role="RUN_AUTHORITY",
            subject_sha256=execution.digest(),
            signer_id="external-run-authority",
            public_key_sha256=SHA_A,
            signature_sha256=SHA_B,
        )
        with self.assertRaisesRegex(ValueError, "signature"):
            verify_freeze_run_context(
                collection_permit=collection,
                collection_receipt=receipt,
                execution_permit=execution,
                execution_receipt=receipt,
                verifier=RejectAllVerifier(),
            )

    def test_runner_has_no_caller_selected_run_id_or_arbitrary_case_contract(
        self,
    ) -> None:
        parameters = inspect.signature(NativeSuccessorRunner.run_once).parameters
        self.assertNotIn("run_id", parameters)
        self.assertNotIn("cases", parameters)
        self.assertIn("public_corpus", parameters)
        self.assertIn("freeze_run", parameters)

    def test_execution_permit_cannot_drift_prereg_or_run_authority(self) -> None:
        collection = CollectionPermit.from_mapping(
            {
                "run_id": "r-eval-indep-1-rfinal-001",
                "prereg_lock_sha256": SHA_A,
                "exact_manifest_sha256": SHA_B,
                "independent_review_sha256": SHA_C,
                "run_authority_id": "run-authority",
                "c7_authority_id": "c7-authority",
                "correction_epoch": 7,
                "c7_decision": "ALLOW",
                "single_run_sequence": 1,
            }
        )
        execution = RunExecutionPermit(
            route_id="R-EVAL-INDEP-1",
            run_id=collection.run_id,
            global_run_sequence=1,
            collection_permit_sha256=collection.digest(),
            prereg_spec_sha256=SHA_C,
            exact_manifest_sha256=SHA_B,
            freeze_subject_sha256=SHA_C,
            correction_epoch=7,
            corpus_manifest_sha256=SHA_A,
            public_cases_sha256=SHA_B,
            provider_bank_sha256=SHA_C,
            budget_sha256=SHA_A,
            freeze_receipt_sha256=SHA_B,
            run_authority_receipt_sha256=SHA_C,
            collection_authority_id="collection-authority",
            collection_authority_public_key_sha256=COLLECTION_KEY,
            run_authority_public_key_sha256=RUN_KEY,
            c7_authority_public_key_sha256=C7_KEY,
            oracle_custodian_id="oracle-custodian",
            oracle_custodian_public_key_sha256=ORACLE_KEY,
            trust_registry_sha256=TRUST_REGISTRY,
        )
        collection_receipt = SignedReceipt(
            role="COLLECTION_AUTHORITY",
            subject_sha256=collection.digest(),
            signer_id="collection-authority",
            public_key_sha256=COLLECTION_KEY,
            signature_sha256=SHA_B,
        )
        execution_receipt = SignedReceipt(
            role="RUN_AUTHORITY",
            subject_sha256=execution.digest(),
            signer_id="wrong-run-authority",
            public_key_sha256=RUN_KEY,
            signature_sha256=SHA_B,
        )
        with self.assertRaisesRegex(ValueError, "prereg|run authority"):
            verify_freeze_run_context(
                collection_permit=collection,
                collection_receipt=collection_receipt,
                execution_permit=execution,
                execution_receipt=execution_receipt,
                verifier=AcceptAllVerifier(),
            )

    def test_self_reported_signer_and_key_cannot_be_reattached(self) -> None:
        collection = CollectionPermit.from_mapping(
            {
                "run_id": "r-eval-indep-1-rfinal-001",
                "prereg_lock_sha256": SHA_A,
                "exact_manifest_sha256": SHA_B,
                "independent_review_sha256": SHA_C,
                "run_authority_id": "run-authority",
                "c7_authority_id": "c7-authority",
                "correction_epoch": 7,
                "c7_decision": "ALLOW",
                "single_run_sequence": 1,
            }
        )
        execution = RunExecutionPermit(
            route_id="R-EVAL-INDEP-1",
            run_id=collection.run_id,
            global_run_sequence=1,
            collection_permit_sha256=collection.digest(),
            prereg_spec_sha256=SHA_A,
            exact_manifest_sha256=SHA_B,
            freeze_subject_sha256=SHA_C,
            correction_epoch=7,
            corpus_manifest_sha256=SHA_A,
            public_cases_sha256=SHA_B,
            provider_bank_sha256=SHA_C,
            budget_sha256=SHA_A,
            freeze_receipt_sha256=SHA_B,
            run_authority_receipt_sha256=SHA_C,
            collection_authority_id="collection-authority",
            collection_authority_public_key_sha256=COLLECTION_KEY,
            run_authority_public_key_sha256=RUN_KEY,
            c7_authority_public_key_sha256=C7_KEY,
            oracle_custodian_id="oracle-custodian",
            oracle_custodian_public_key_sha256=ORACLE_KEY,
            trust_registry_sha256=TRUST_REGISTRY,
        )
        collection_receipt = SignedReceipt(
            role="COLLECTION_AUTHORITY",
            subject_sha256=collection.digest(),
            signer_id="self-reported-collection-authority",
            public_key_sha256=COLLECTION_KEY,
            signature_sha256=SHA_B,
        )
        execution_receipt = SignedReceipt(
            role="RUN_AUTHORITY",
            subject_sha256=execution.digest(),
            signer_id="run-authority",
            public_key_sha256=RUN_KEY,
            signature_sha256=SHA_B,
        )
        with self.assertRaisesRegex(ValueError, "trusted identity"):
            verify_freeze_run_context(
                collection_permit=collection,
                collection_receipt=collection_receipt,
                execution_permit=execution,
                execution_receipt=execution_receipt,
                verifier=ReattachingVerifier(),
            )

    def test_oracle_public_key_cannot_collapse_with_c7_authority(self) -> None:
        collection = CollectionPermit.from_mapping(
            {
                "run_id": "r-eval-indep-1-rfinal-001",
                "prereg_lock_sha256": SHA_A,
                "exact_manifest_sha256": SHA_B,
                "independent_review_sha256": SHA_C,
                "run_authority_id": "run-authority",
                "c7_authority_id": "c7-authority",
                "correction_epoch": 7,
                "c7_decision": "ALLOW",
                "single_run_sequence": 1,
            }
        )
        execution = RunExecutionPermit(
            route_id="R-EVAL-INDEP-1",
            run_id=collection.run_id,
            global_run_sequence=1,
            collection_permit_sha256=collection.digest(),
            prereg_spec_sha256=SHA_A,
            exact_manifest_sha256=SHA_B,
            freeze_subject_sha256=SHA_C,
            correction_epoch=7,
            corpus_manifest_sha256=SHA_A,
            public_cases_sha256=SHA_B,
            provider_bank_sha256=SHA_C,
            budget_sha256=SHA_A,
            freeze_receipt_sha256=SHA_B,
            run_authority_receipt_sha256=SHA_C,
            collection_authority_id="collection-authority",
            collection_authority_public_key_sha256=COLLECTION_KEY,
            run_authority_public_key_sha256=RUN_KEY,
            c7_authority_public_key_sha256=C7_KEY,
            oracle_custodian_id="oracle-custodian",
            oracle_custodian_public_key_sha256=ORACLE_KEY,
            trust_registry_sha256=TRUST_REGISTRY,
        )
        with self.assertRaisesRegex(ValueError, "public keys must be distinct"):
            replace(execution, oracle_custodian_public_key_sha256=C7_KEY)


if __name__ == "__main__":
    unittest.main()
