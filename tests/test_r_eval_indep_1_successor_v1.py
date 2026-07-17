from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from experiments.r_eval_indep_1.native_arm_plan import (
    ArmRole,
    NativeArmPlan,
    build_native_arm_plan,
)
from experiments.r_eval_indep_1.provider_adapter import (
    AmbiguousEffectError,
    ArmProviderBinding,
    ProviderResponse,
    validate_provider_bank,
)
from experiments.r_eval_indep_1.routing_policy import route_from_raw_scores
from experiments.r_eval_indep_1.run_budget import DEFAULT_RUN_BUDGET
from experiments.r_eval_indep_1.runner import (
    C7Halt,
    EvaluationDisposition,
    NativeSuccessorRunner,
    PublicEvaluationCase,
    RunInvalidIncomplete,
    verify_sealed_run,
)
from experiments.r_eval_indep_1.scoring import score_successor_rows
from experiments.r_eval_indep_1.result_contracts import SuccessorRawResult


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64


def _binding(
    arm_id: str,
    *,
    checkpoint: str,
    family: str,
    lineage: str,
    prompt: str,
    route_id: str = "R-EVAL-INDEP-1",
) -> ArmProviderBinding:
    return ArmProviderBinding(
        route_id=route_id,
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


def _provider_bank() -> tuple[ArmProviderBinding, ...]:
    return (
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


class NativeArmPlanTests(unittest.TestCase):
    def test_fixed_roles_and_exact_row_accounting(self) -> None:
        plan = build_native_arm_plan(case_count=74)
        self.assertEqual(plan.arm_ids, ("A0", "A1", "A2", "A3", "A4"))
        self.assertEqual(plan.evaluation_row_count, 370)
        self.assertEqual(plan.provider_attempt_count, 444)
        self.assertEqual(plan.mechanical_row_count, 74)
        self.assertEqual(plan.aggregate_row_count, 74)
        self.assertEqual(plan.arm("A0").role, ArmRole.MECHANICAL_RULE)
        self.assertEqual(plan.arm("A2").sample_count, 3)

    def test_plan_is_closed_and_does_not_freeze_vendor_names(self) -> None:
        payload = build_native_arm_plan(case_count=74).to_mapping()
        encoded = json.dumps(payload).lower()
        for forbidden in (
            "openai",
            "anthropic",
            "deepseek",
            "model_immutable_revision",
            "credential_ref",
        ):
            self.assertNotIn(forbidden, encoded)
        payload["unknown"] = True
        with self.assertRaises(ValueError):
            NativeArmPlan.from_mapping(payload)


class ProviderBankTests(unittest.TestCase):
    def test_exact_coverage_and_role_relationships_are_enforced(self) -> None:
        bank = validate_provider_bank(build_native_arm_plan(74), _provider_bank())
        self.assertEqual(set(bank), {"A1", "A2", "A3", "A4"})

        bad = list(_provider_bank())
        bad[-1] = replace(bad[-1], model_lineage="lineage-1")
        with self.assertRaisesRegex(ValueError, "cross-lineage"):
            validate_provider_bank(build_native_arm_plan(74), tuple(bad))

    def test_r_state_profile_and_mutable_model_alias_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "route"):
            validate_provider_bank(
                build_native_arm_plan(74),
                (
                    _binding(
                        "A1",
                        checkpoint="rev-1",
                        family="f",
                        lineage="l",
                        prompt=SHA_A,
                        route_id="R-STATE-CREDIT-1",
                    ),
                ),
            )
        with self.assertRaisesRegex(ValueError, "immutable"):
            _binding("A1", checkpoint="latest", family="f", lineage="l", prompt=SHA_A)


class BudgetTests(unittest.TestCase):
    def test_budget_freezes_all_requested_limits_and_zero_retry(self) -> None:
        budget = DEFAULT_RUN_BUDGET
        self.assertEqual(budget.concurrency, 1)
        self.assertEqual(budget.retry_count, 0)
        self.assertGreater(budget.per_call_input_tokens, 0)
        self.assertGreater(budget.total_input_tokens, budget.per_call_input_tokens)
        self.assertGreater(budget.total_cost_microusd, budget.per_call_cost_microusd)
        self.assertGreater(budget.wallclock_ms, budget.per_call_latency_ms)


class ScriptedProvider:
    def __init__(self, *, ambiguous_after_accept: bool = False) -> None:
        self.calls = 0
        self.ambiguous_after_accept = ambiguous_after_accept

    def review(
        self,
        *,
        binding: ArmProviderBinding,
        case: PublicEvaluationCase,
        sample_index: int,
    ) -> ProviderResponse:
        self.calls += 1
        if self.ambiguous_after_accept:
            raise AmbiguousEffectError("request accepted; terminal response unknown")
        disposition = (
            EvaluationDisposition.ACCEPT
            if sample_index != 2
            else EvaluationDisposition.REJECT
        )
        return ProviderResponse(
            disposition=disposition.value,
            input_tokens=10,
            output_tokens=5,
            cost_microusd=100,
            latency_ms=20,
            provider_response_id_sha256=SHA_A,
            raw_response_sha256=SHA_B,
        )


def _cases(count: int = 2) -> tuple[PublicEvaluationCase, ...]:
    return tuple(
        PublicEvaluationCase(
            case_id=f"case-{index:016x}",
            public_manifest_sha256=SHA_A,
            payload={"candidate": index},
        )
        for index in range(count)
    )


class NativeRunnerTests(unittest.TestCase):
    def test_rows_are_typed_and_aggregate_attempts_are_not_evaluation_rows(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runner = NativeSuccessorRunner(Path(tmp))
            provider = ScriptedProvider()
            result = runner.run_once(
                run_id="run-1",
                cases=_cases(),
                plan=build_native_arm_plan(2),
                provider_bank=_provider_bank(),
                provider=provider,
                mechanical_rule=lambda _case: EvaluationDisposition.REJECT,
                c7_check=lambda: "ALLOW",
                budget=DEFAULT_RUN_BUDGET,
            )
        self.assertEqual(result.evaluation_row_count, 10)
        self.assertEqual(result.provider_attempt_count, 12)
        self.assertEqual(result.provider_success_count, 12)
        self.assertEqual(result.mechanical_row_count, 2)
        self.assertEqual(result.aggregate_row_count, 2)
        self.assertEqual(provider.calls, 12)
        self.assertIsNone(result.verdict)
        self.assertEqual(result.status, "RAW_NOT_ADJUDICATED")

    def test_seal_detects_archive_tamper_truncation_and_reordering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runner = NativeSuccessorRunner(root)
            runner.run_once(
                run_id="run-sealed",
                cases=_cases(1),
                plan=build_native_arm_plan(1),
                provider_bank=_provider_bank(),
                provider=ScriptedProvider(),
                mechanical_rule=lambda _case: EvaluationDisposition.REJECT,
                c7_check=lambda: "ALLOW",
                budget=DEFAULT_RUN_BUDGET,
            )
            run_dir = root / "run-sealed"
            verify_sealed_run(run_dir)
            original = (run_dir / "rows.jsonl").read_bytes()
            lines = original.splitlines(keepends=True)
            for tampered in (
                b"".join(reversed(lines)),
                b"".join(lines[:-1]),
                original + b"{}\n",
            ):
                (run_dir / "rows.jsonl").write_bytes(tampered)
                with self.assertRaisesRegex(ValueError, "seal|archive|chain"):
                    verify_sealed_run(run_dir)
            (run_dir / "rows.jsonl").write_bytes(original)
            verify_sealed_run(run_dir)

    def test_timeout_after_accept_consumes_run_and_seals_invalid_partial(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runner = NativeSuccessorRunner(Path(tmp))
            provider = ScriptedProvider(ambiguous_after_accept=True)
            with self.assertRaises(AmbiguousEffectError):
                runner.run_once(
                    run_id="run-ambiguous",
                    cases=_cases(1),
                    plan=build_native_arm_plan(1),
                    provider_bank=_provider_bank(),
                    provider=provider,
                    mechanical_rule=lambda _case: EvaluationDisposition.REJECT,
                    c7_check=lambda: "ALLOW",
                    budget=DEFAULT_RUN_BUDGET,
                )
            state = json.loads(
                (Path(tmp) / "run-ambiguous" / "result.json").read_text()
            )
            self.assertEqual(state["status"], "INVALID_INCOMPLETE")
            self.assertEqual(state["effect_status"], "AMBIGUOUS_EFFECT")
            with self.assertRaisesRegex(RunInvalidIncomplete, "consumed"):
                runner.run_once(
                    run_id="run-ambiguous",
                    cases=_cases(1),
                    plan=build_native_arm_plan(1),
                    provider_bank=_provider_bank(),
                    provider=ScriptedProvider(),
                    mechanical_rule=lambda _case: EvaluationDisposition.REJECT,
                    c7_check=lambda: "ALLOW",
                    budget=DEFAULT_RUN_BUDGET,
                )

    def test_c7_halt_seals_partial_without_refill(self) -> None:
        decisions = iter(("ALLOW", "ALLOW", "HALT"))
        with tempfile.TemporaryDirectory() as tmp:
            runner = NativeSuccessorRunner(Path(tmp))
            with self.assertRaises(C7Halt):
                runner.run_once(
                    run_id="run-halt",
                    cases=_cases(2),
                    plan=build_native_arm_plan(2),
                    provider_bank=_provider_bank(),
                    provider=ScriptedProvider(),
                    mechanical_rule=lambda _case: EvaluationDisposition.REJECT,
                    c7_check=lambda: next(decisions),
                    budget=DEFAULT_RUN_BUDGET,
                )
            state = json.loads((Path(tmp) / "run-halt" / "result.json").read_text())
            self.assertEqual(state["status"], "INVALID_INCOMPLETE")
            self.assertEqual(state["effect_status"], "C7_HALT")

    def test_runner_has_no_truth_or_oracle_parameter(self) -> None:
        import inspect

        parameters = inspect.signature(NativeSuccessorRunner.run_once).parameters
        self.assertNotIn("truth", parameters)
        self.assertNotIn("oracle", parameters)

    def test_public_case_rejects_nested_hidden_oracle_material(self) -> None:
        with self.assertRaisesRegex(ValueError, "oracle"):
            PublicEvaluationCase(
                case_id="case-0000000000000001",
                public_manifest_sha256=SHA_A,
                payload={"nested": {"hidden_oracle_ref": "private/path"}},
            )


class SuccessorResultContractTests(unittest.TestCase):
    def test_complete_result_is_closed_one_shot_and_unadjudicated(self) -> None:
        result = SuccessorRawResult(
            schema_version="r-eval-indep-1-successor-raw-result-v1",
            run_id="run-complete",
            single_run_sequence=1,
            status="RAW_NOT_ADJUDICATED",
            verdict=None,
            effect_status="COMPLETE",
            case_count=74,
            evaluation_row_count=370,
            provider_attempt_count=444,
            provider_success_count=444,
            mechanical_row_count=74,
            aggregate_row_count=74,
            raw_archive_sha256=SHA_A,
        )
        self.assertEqual(SuccessorRawResult.from_mapping(result.to_mapping()), result)
        payload = result.to_mapping()
        payload["verdict"] = "PASS"
        with self.assertRaises(ValueError):
            SuccessorRawResult.from_mapping(payload)

    def test_incomplete_result_cannot_claim_complete_counts(self) -> None:
        with self.assertRaises(ValueError):
            SuccessorRawResult(
                schema_version="r-eval-indep-1-successor-raw-result-v1",
                run_id="run-bad",
                single_run_sequence=1,
                status="INVALID_INCOMPLETE",
                verdict=None,
                effect_status="AMBIGUOUS_EFFECT",
                case_count=74,
                evaluation_row_count=370,
                provider_attempt_count=444,
                provider_success_count=444,
                mechanical_row_count=74,
                aggregate_row_count=74,
                raw_archive_sha256=SHA_A,
            )


class SuccessorCandidateDocumentTests(unittest.TestCase):
    def test_successor_prereg_is_honestly_unbound_and_manifest_is_exact(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        prereg_path = (
            repo / "docs/research/R-EVAL-INDEP-1-successor-v1-preregistration-spec.yaml"
        )
        manifest_path = (
            repo / "docs/research/R-EVAL-INDEP-1-successor-v1-exact-manifest.json"
        )
        prereg = json.loads(prereg_path.read_text(encoding="utf-8"))
        self.assertEqual(prereg["candidate_status"], "NOT_READY")
        self.assertEqual(
            prereg["gates"],
            {
                "freeze_status": "NOT_FROZEN",
                "run_status": "NOT_RUN",
                "evidence_status": "NOT_EVIDENCE",
            },
        )
        self.assertEqual(prereg["external_bindings"]["provider_bank"], [])
        self.assertIsNone(prereg["external_bindings"]["oracle_custody"])
        self.assertEqual(prereg["counts"]["provider_attempt_rows"], 444)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(
            manifest["target_base_head"], "ebf094346267c63cc5375a1a0e1fb62d0afb81bc"
        )
        for relpath, expected in manifest["files"].items():
            self.assertEqual(
                __import__("hashlib").sha256((repo / relpath).read_bytes()).hexdigest(),
                expected,
            )


def _score_rows() -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    dispositions = {
        "A0": ("REJECT", "REJECT", "ACCEPT", "ACCEPT"),
        "A1": ("REJECT", "REJECT", "ACCEPT", "REJECT"),
        "A2": ("ACCEPT", "REJECT", "ACCEPT", "ACCEPT"),
        "A3": ("REJECT", "REJECT", "ACCEPT", "ACCEPT"),
        "A4": ("REJECT", "REJECT", "REJECT", "REJECT"),
    }
    for arm, vector in dispositions.items():
        for index, disposition in enumerate(vector):
            rows.append(
                {
                    "row_type": "EVALUATION",
                    "case_id": f"case-{index:016x}",
                    "arm_id": arm,
                    "disposition": disposition,
                    "cost_microusd": 0 if arm == "A0" else 10,
                    "latency_ms": index + 1,
                }
            )
    return tuple(rows)


class ScoringAndRoutingTests(unittest.TestCase):
    def test_raw_scoring_has_intervals_paired_tests_bootstrap_loco_and_no_verdict(
        self,
    ) -> None:
        truth = {
            "case-0000000000000000": "HARMFUL",
            "case-0000000000000001": "HARMFUL",
            "case-0000000000000002": "CLEAN",
            "case-0000000000000003": "CLEAN",
        }
        classes = {
            "case-0000000000000000": "authority",
            "case-0000000000000001": "contract",
            "case-0000000000000002": "clean-a",
            "case-0000000000000003": "clean-b",
        }
        report = score_successor_rows(
            truth=truth, mutation_classes=classes, rows=_score_rows(), bootstrap_seed=17
        )
        self.assertIsNone(report.verdict)
        self.assertEqual(report.status, "RAW_NOT_ADJUDICATED")
        self.assertIn("harmful_miss_wilson", report.arm_scores["A1"])
        self.assertIn(("A0", "A1"), report.paired_mcnemar)
        self.assertIn("clean_accept_stratified_bootstrap", report.arm_scores["A1"])
        self.assertEqual(report.arm_scores["A2"]["loco_harmful_miss"]["authority"], 0.0)

    def test_mechanical_rows_cannot_be_mixed_into_provider_or_evaluation_counts(
        self,
    ) -> None:
        rows = list(_score_rows())
        rows[0] = {**rows[0], "row_type": "MECHANICAL"}
        with self.assertRaisesRegex(ValueError, "EVALUATION"):
            score_successor_rows(
                truth={
                    f"case-{i:016x}": "HARMFUL" if i < 2 else "CLEAN" for i in range(4)
                },
                mutation_classes={f"case-{i:016x}": f"class-{i}" for i in range(4)},
                rows=tuple(rows),
                bootstrap_seed=17,
            )

    def test_zero_harm_rule_cannot_be_rescued_by_clean_accept_cost_or_latency(
        self,
    ) -> None:
        truth = {f"case-{i:016x}": "HARMFUL" if i < 2 else "CLEAN" for i in range(4)}
        classes = {f"case-{i:016x}": f"class-{i}" for i in range(4)}
        report = score_successor_rows(
            truth=truth, mutation_classes=classes, rows=_score_rows(), bootstrap_seed=17
        )
        decision = route_from_raw_scores(report)
        self.assertNotEqual(decision.selected_arm_id, "A2")
        self.assertEqual(decision.selected_arm_id, "A3")
        self.assertEqual(decision.reason, "ZERO_HARMFUL_MISS_LEXICOGRAPHIC")


if __name__ == "__main__":
    unittest.main()
