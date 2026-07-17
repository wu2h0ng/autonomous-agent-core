from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from experiments.r_eval_indep_1.contracts import canonical_digest
from experiments.r_eval_indep_1.corpus_registry import compile_corpus_dev
from experiments.r_eval_indep_1.freeze_run_context import (
    RunExecutionPermit,
    SignedReceipt,
    verify_freeze_run_context,
)
from experiments.r_eval_indep_1.native_arm_plan import build_native_arm_plan
from experiments.r_eval_indep_1.native_protocol import CollectionPermit
from experiments.r_eval_indep_1.provider_adapter import (
    ArmProviderBinding,
    ProviderCanaryReceipt,
    ProviderRequest,
    ProviderResponse,
    verify_provider_bank,
)
from experiments.r_eval_indep_1.routing_policy import route_from_raw_scores
from experiments.r_eval_indep_1.run_budget import DEFAULT_RUN_BUDGET, RunBudget
from experiments.r_eval_indep_1.runner import (
    EvaluationDisposition,
    FrozenPublicCorpus,
    NativeSuccessorRunner,
    RunInvalidIncomplete,
    SignedC7Decision,
    verify_sealed_run,
)
from experiments.r_eval_indep_1.scoring import (
    score_successor_run,
    verify_truth_custody,
)


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
REPO_ROOT = Path(__file__).resolve().parents[1]


class AcceptAllVerifier:
    def verify(self, receipt: SignedReceipt) -> bool:
        return bool(receipt.signature_sha256)


VERIFIER = AcceptAllVerifier()


def _signed(role: str, subject: str, signer: str) -> SignedReceipt:
    return SignedReceipt(
        role=role,
        subject_sha256=subject,
        signer_id=signer,
        public_key_sha256=SHA_A,
        signature_sha256=SHA_B,
    )


def _binding(
    arm_id: str,
    *,
    checkpoint: str,
    family: str,
    lineage: str,
    prompt: str,
) -> ArmProviderBinding:
    return ArmProviderBinding(
        route_id="R-EVAL-INDEP-1",
        arm_id=arm_id,
        provider="provider-a",
        endpoint_origin_sha256=SHA_A,
        model_immutable_revision=checkpoint,
        model_family=family,
        model_lineage=lineage,
        system_prompt_sha256=prompt,
        tool_schema_sha256=SHA_B,
        decoding_config_sha256=SHA_C,
        credential_ref_sha256=SHA_D,
    )


def _verified_bank():
    bindings = (
        _binding(
            "A1",
            checkpoint="rev-1",
            family="family-1",
            lineage="lineage-1",
            prompt=SHA_A,
        ),
        _binding(
            "A2",
            checkpoint="rev-1",
            family="family-1",
            lineage="lineage-1",
            prompt=SHA_B,
        ),
        _binding(
            "A3",
            checkpoint="rev-2",
            family="family-1",
            lineage="lineage-1",
            prompt=SHA_A,
        ),
        _binding(
            "A4",
            checkpoint="rev-x",
            family="family-x",
            lineage="lineage-x",
            prompt=SHA_A,
        ),
    )
    canaries = []
    for binding in bindings:
        placeholder = _signed(
            "PROVIDER_CANARY_CUSTODIAN", SHA_A, f"canary-{binding.arm_id}"
        )
        canary = ProviderCanaryReceipt(
            arm_id=binding.arm_id,
            binding_sha256=binding.digest(),
            served_provider=binding.provider,
            served_model_immutable_revision=binding.model_immutable_revision,
            served_model_family=binding.model_family,
            served_model_lineage=binding.model_lineage,
            canary_request_sha256=SHA_B,
            canary_response_sha256=SHA_C,
            signed_receipt=placeholder,
        )
        canaries.append(
            replace(
                canary,
                signed_receipt=_signed(
                    "PROVIDER_CANARY_CUSTODIAN",
                    canary.digest(),
                    f"canary-{binding.arm_id}",
                ),
            )
        )
    return verify_provider_bank(
        build_native_arm_plan(74), bindings, tuple(canaries), VERIFIER
    )


def _freeze_context(public_corpus, provider_bank, budget=DEFAULT_RUN_BUDGET):
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
        corpus_manifest_sha256=public_corpus.corpus_manifest_sha256,
        public_cases_sha256=public_corpus.public_cases_sha256,
        provider_bank_sha256=provider_bank.sha256,
        budget_sha256=budget.digest(),
        freeze_receipt_sha256=SHA_B,
        run_authority_receipt_sha256=SHA_C,
    )
    return verify_freeze_run_context(
        collection_permit=collection,
        collection_receipt=_signed(
            "COLLECTION_AUTHORITY", collection.digest(), "collection-authority"
        ),
        execution_permit=execution,
        execution_receipt=_signed("RUN_AUTHORITY", execution.digest(), "run-authority"),
        verifier=VERIFIER,
    )


class AllowC7:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def check(self, *, freeze_run, phase: str, request_sha256: str) -> SignedC7Decision:
        self.calls.append((phase, request_sha256))
        placeholder = _signed("C7_AUTHORITY", SHA_A, "c7-authority")
        decision = SignedC7Decision(
            decision="ALLOW",
            phase=phase,
            request_sha256=request_sha256,
            execution_permit_sha256=freeze_run.execution_permit.digest(),
            correction_epoch=freeze_run.execution_permit.correction_epoch,
            signed_receipt=placeholder,
        )
        return replace(
            decision,
            signed_receipt=_signed(
                "C7_AUTHORITY", decision.subject_digest(), "c7-authority"
            ),
        )


class EchoProvider:
    def __init__(self, *, drift: str | None = None, tie_a2: bool = False) -> None:
        self.calls = 0
        self.drift = drift
        self.tie_a2 = tie_a2

    def review(self, *, request: ProviderRequest) -> ProviderResponse:
        self.calls += 1
        dispositions = ("ACCEPT", "REJECT", "ABSTAIN")
        disposition = (
            dispositions[request.sample_index - 1]
            if self.tie_a2 and request.arm_id == "A2"
            else "REJECT"
        )
        response = ProviderResponse(
            request_sha256=request.digest(),
            provider_binding_sha256=request.provider_binding_sha256,
            provider_canary_sha256=request.provider_canary_sha256,
            provider_canary_receipt_sha256=request.provider_canary_receipt_sha256,
            endpoint_origin_sha256=request.endpoint_origin_sha256,
            model_immutable_revision=request.model_immutable_revision,
            system_prompt_sha256=request.system_prompt_sha256,
            tool_schema_sha256=request.tool_schema_sha256,
            decoding_config_sha256=request.decoding_config_sha256,
            credential_ref_sha256=request.credential_ref_sha256,
            disposition=disposition,
            input_tokens=1,
            output_tokens=1,
            cost_microusd=1,
            latency_ms=1,
            provider_response_id_sha256=SHA_A,
            raw_response_sha256=SHA_B,
        )
        return replace(response, **{self.drift: SHA_D}) if self.drift else response


class SuccessorReviewRemediationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        compiled = compile_corpus_dev(REPO_ROOT)
        cls.compiled = compiled
        cls.public_corpus = FrozenPublicCorpus.build(
            corpus_manifest_sha256=compiled.manifest.corpus_manifest_sha256,
            cases=compiled.manifest.public_cases,
        )

    def test_fixed_counts_and_canary_bank_not_caller_claims(self) -> None:
        plan = build_native_arm_plan(74)
        self.assertEqual(
            (
                plan.evaluation_row_count,
                plan.provider_attempt_count,
                plan.mechanical_row_count,
                plan.aggregate_row_count,
            ),
            (370, 444, 74, 74),
        )
        bank = _verified_bank()
        self.assertEqual(set(bank.canaries), {"A1", "A2", "A3", "A4"})

        changed_canaries = tuple(
            replace(
                canary,
                signed_receipt=replace(canary.signed_receipt, signature_sha256=SHA_D),
            )
            for canary in bank.canaries.values()
        )
        changed_bank = verify_provider_bank(
            plan,
            tuple(bank.bindings.values()),
            changed_canaries,
            VERIFIER,
        )
        self.assertNotEqual(bank.sha256, changed_bank.sha256)

    def test_response_drift_seals_partial_and_consumes_freeze_subject(self) -> None:
        bank = _verified_bank()
        context = _freeze_context(self.public_corpus, bank)
        with tempfile.TemporaryDirectory() as tmp:
            runner = NativeSuccessorRunner(Path(tmp))
            with self.assertRaisesRegex(RunInvalidIncomplete, "binding drift"):
                runner.run_once(
                    freeze_run=context,
                    public_corpus=self.public_corpus,
                    plan=build_native_arm_plan(74),
                    provider_bank=bank,
                    provider=EchoProvider(drift="model_immutable_revision"),
                    mechanical_rule=lambda _case: EvaluationDisposition.REJECT,
                    c7_authority=AllowC7(),
                    budget=DEFAULT_RUN_BUDGET,
                )
            run_dir = Path(tmp) / SHA_C / "global-sequence-1"
            result = verify_sealed_run(run_dir)
            self.assertEqual(result.status, "INVALID_INCOMPLETE")
            with self.assertRaisesRegex(RunInvalidIncomplete, "consumed"):
                runner.run_once(
                    freeze_run=context,
                    public_corpus=self.public_corpus,
                    plan=build_native_arm_plan(74),
                    provider_bank=bank,
                    provider=EchoProvider(),
                    mechanical_rule=lambda _case: EvaluationDisposition.REJECT,
                    c7_authority=AllowC7(),
                    budget=DEFAULT_RUN_BUDGET,
                )

    def test_complete_archive_binds_every_effect_and_c7_before_after(self) -> None:
        bank = _verified_bank()
        context = _freeze_context(self.public_corpus, bank)
        c7 = AllowC7()
        provider = EchoProvider(tie_a2=True)
        with tempfile.TemporaryDirectory() as tmp:
            result = NativeSuccessorRunner(Path(tmp)).run_once(
                freeze_run=context,
                public_corpus=self.public_corpus,
                plan=build_native_arm_plan(74),
                provider_bank=bank,
                provider=provider,
                mechanical_rule=lambda _case: EvaluationDisposition.REJECT,
                c7_authority=c7,
                budget=DEFAULT_RUN_BUDGET,
            )
            run_dir = Path(tmp) / SHA_C / "global-sequence-1"
            rows = [
                json.loads(line)
                for line in (run_dir / "rows.jsonl").read_text().splitlines()
            ]
        self.assertEqual(result.status, "RAW_NOT_ADJUDICATED")
        self.assertEqual(provider.calls, 444)
        self.assertEqual(len(c7.calls), 888)
        aggregate = [row for row in rows if row["row_type"] == "AGGREGATE"]
        self.assertEqual(len(aggregate), 74)
        self.assertTrue(all(row["disposition"] == "ABSTAIN" for row in aggregate))
        success = next(row for row in rows if row["row_type"] == "PROVIDER_SUCCESS")
        for field in (
            "public_case_sha256",
            "request_sha256",
            "response_sha256",
            "endpoint_origin_sha256",
            "system_prompt_sha256",
            "tool_schema_sha256",
            "decoding_config_sha256",
            "credential_ref_sha256",
            "provider_canary_sha256",
            "provider_canary_receipt_sha256",
        ):
            self.assertRegex(success[field], r"^[0-9a-f]{64}$")

    def test_remaining_budget_is_checked_before_next_effect(self) -> None:
        bank = _verified_bank()
        budget = RunBudget(
            per_call_input_tokens=10,
            per_call_output_tokens=10,
            per_call_cost_microusd=10,
            per_call_latency_ms=10,
            total_input_tokens=10,
            total_output_tokens=10,
            total_cost_microusd=10,
            total_latency_ms=10,
            wallclock_ms=1000,
            concurrency=1,
            retry_count=0,
        )
        context = _freeze_context(self.public_corpus, bank, budget)
        provider = EchoProvider()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RunInvalidIncomplete, "remaining total budget"):
                NativeSuccessorRunner(Path(tmp)).run_once(
                    freeze_run=context,
                    public_corpus=self.public_corpus,
                    plan=build_native_arm_plan(74),
                    provider_bank=bank,
                    provider=provider,
                    mechanical_rule=lambda _case: EvaluationDisposition.REJECT,
                    c7_authority=AllowC7(),
                    budget=budget,
                )
        self.assertEqual(provider.calls, 1)

    def test_c7_signer_must_match_freeze_bound_authority(self) -> None:
        class WrongSignerC7(AllowC7):
            def check(
                self, *, freeze_run, phase: str, request_sha256: str
            ) -> SignedC7Decision:
                decision = super().check(
                    freeze_run=freeze_run,
                    phase=phase,
                    request_sha256=request_sha256,
                )
                return replace(
                    decision,
                    signed_receipt=replace(
                        decision.signed_receipt, signer_id="wrong-c7-authority"
                    ),
                )

        bank = _verified_bank()
        context = _freeze_context(self.public_corpus, bank)
        provider = EchoProvider()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RunInvalidIncomplete, "C7"):
                NativeSuccessorRunner(Path(tmp)).run_once(
                    freeze_run=context,
                    public_corpus=self.public_corpus,
                    plan=build_native_arm_plan(74),
                    provider_bank=bank,
                    provider=provider,
                    mechanical_rule=lambda _case: EvaluationDisposition.REJECT,
                    c7_authority=WrongSignerC7(),
                    budget=DEFAULT_RUN_BUDGET,
                )
        self.assertEqual(provider.calls, 0)

    def test_scorer_requires_verified_complete_archive_and_truth_custody(self) -> None:
        bank = _verified_bank()
        context = _freeze_context(self.public_corpus, bank)
        placeholder = _signed("ORACLE_CUSTODIAN", SHA_A, "oracle-custodian")
        truth = {
            case.case_id: case.case_truth.value
            for case in self.compiled.manifest.referee_cases
        }
        strata = {
            case.case_id: "CLEAN_CONTROL"
            if case.mutation_class is None
            else case.mutation_class.value
            for case in self.compiled.manifest.referee_cases
        }
        subject = canonical_digest(
            {
                "corpus_manifest_sha256": self.compiled.manifest.corpus_manifest_sha256,
                "referee_cases_sha256": self.compiled.manifest.referee_cases_sha256,
                "truth_sha256": canonical_digest(truth),
                "strata_sha256": canonical_digest(strata),
            }
        )
        custody = verify_truth_custody(
            corpus_manifest_sha256=self.compiled.manifest.corpus_manifest_sha256,
            referee_cases_sha256=self.compiled.manifest.referee_cases_sha256,
            referee_cases=self.compiled.manifest.referee_cases,
            custody_receipt=replace(placeholder, subject_sha256=subject),
            verifier=VERIFIER,
        )
        collapsed_custody = verify_truth_custody(
            corpus_manifest_sha256=self.compiled.manifest.corpus_manifest_sha256,
            referee_cases_sha256=self.compiled.manifest.referee_cases_sha256,
            referee_cases=self.compiled.manifest.referee_cases,
            custody_receipt=replace(
                placeholder,
                subject_sha256=subject,
                signer_id="run-authority",
            ),
            verifier=VERIFIER,
        )
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / SHA_C / "global-sequence-1"
            NativeSuccessorRunner(Path(tmp)).run_once(
                freeze_run=context,
                public_corpus=self.public_corpus,
                plan=build_native_arm_plan(74),
                provider_bank=bank,
                provider=EchoProvider(),
                mechanical_rule=lambda _case: EvaluationDisposition.REJECT,
                c7_authority=AllowC7(),
                budget=DEFAULT_RUN_BUDGET,
            )
            report = score_successor_run(
                run_dir=run_dir, freeze_run=context, truth_custody=custody
            )
            with self.assertRaisesRegex(ValueError, "independent"):
                score_successor_run(
                    run_dir=run_dir,
                    freeze_run=context,
                    truth_custody=collapsed_custody,
                )
        self.assertIsNone(report.verdict)
        self.assertIn(("A0", "A1"), report.paired_mcnemar)
        decision = route_from_raw_scores(report)
        self.assertEqual(decision.disposition, "SELECT_ARM")
        self.assertEqual(decision.selected_arm_id, "A1")


if __name__ == "__main__":
    unittest.main()
