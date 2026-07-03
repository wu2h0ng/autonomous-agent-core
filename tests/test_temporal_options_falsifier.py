"""Temporal Options falsifier contract tests.

These tests are intentionally written before the implementation. They pin the
approved Temporal Options contract and should fail until
``experiments.temporal_options_falsifier`` exists with the required behavior.

They do not select seeds, create locks, write result artifacts, run an
experiment, or authorize any autonomy/product claim.
"""

from __future__ import annotations

import importlib
import inspect
import pathlib
import unittest


EXPECTED_ARMS = {
    "P0_FROZEN",
    "RESET_O1",
    "RECENCY_MACRO",
    "EWMA_MACRO",
    "LAST_SEQUENCE",
    "MACRO_1",
    "MACRO_2",
    "MACRO_4",
    "MACRO_8",
    "MACRO_ADAPTIVE_CHEAP",
    "TEMP_OPTION_CANDIDATE",
}

PRE_SPEC_DRAFT = (
    pathlib.Path(__file__).resolve().parents[1]
    / "docs/pre_spec/temporal_options_spec_draft.md"
)


def temporal_options_pre_spec_blocks_tests() -> bool:
    if not PRE_SPEC_DRAFT.is_file():
        return False
    text = PRE_SPEC_DRAFT.read_text(encoding="utf-8")
    return (
        "Status: PRE_SPEC_DRAFT" in text
        and "- tests;" in text
        and "- implementation;" in text
    )


def load_temporal_options_module():
    try:
        return importlib.import_module("experiments.temporal_options_falsifier")
    except ModuleNotFoundError as exc:
        if temporal_options_pre_spec_blocks_tests():
            raise unittest.SkipTest(
                "Temporal Options remains PRE_SPEC_DRAFT and explicitly does not "
                "authorize tests or implementation."
            ) from exc
        raise AssertionError(
            "Expected experiments.temporal_options_falsifier to exist before "
            "Temporal Options tests can pass."
        ) from exc


class TestTemporalOptionsStaticContract(unittest.TestCase):
    def test_default_spec_matches_tracked_pre_spec(self) -> None:
        exp = load_temporal_options_module()

        spec = exp.build_default_spec()
        self.assertEqual(spec["horizon"], 240)
        self.assertEqual(spec["actions"], ["A", "B", "C", "D", "WAIT"])
        self.assertEqual(
            spec["latent_sequences"],
            {
                "R0": ["A", "A", "B", "B"],
                "R1": ["C", "D", "C", "D"],
                "R2": ["B", "C", "A", "D"],
            },
        )
        self.assertEqual(
            {cell["id"]: cell["shift_times"] for cell in spec["cells"]},
            {
                "NO_SHIFT": [],
                "SLOW_SHIFT": [80, 160],
                "FAST_SHIFT": [40, 80, 120, 160, 200],
            },
        )

    def test_required_arms_are_complete_and_cell_blind(self) -> None:
        exp = load_temporal_options_module()

        spec = exp.build_default_spec()
        arms = {arm["id"]: arm for arm in spec["arms"]}
        self.assertEqual(set(arms), EXPECTED_ARMS)
        for arm in arms.values():
            self.assertNotIn("cell", arm)
            self.assertNotIn("cell_id", arm)
            self.assertNotIn("shift_times", arm)
            self.assertNotIn("future_shifts", arm)

    def test_no_external_or_product_dependencies_are_declared(self) -> None:
        exp = load_temporal_options_module()

        spec = exp.build_default_spec()
        self.assertFalse(spec.get("llm_enabled", False))
        self.assertFalse(spec.get("network_enabled", False))
        self.assertNotIn("business_domain", spec)
        self.assertNotIn("product_semantics", spec)


class TestTemporalOptionsObservationAndCorrection(unittest.TestCase):
    def test_correction_events_are_seed_step_deterministic_and_arm_blind(self) -> None:
        exp = load_temporal_options_module()

        signature = inspect.signature(exp.forbidden_action_for_step)
        self.assertEqual(set(signature.parameters), {"seed", "step"})

        events_a = [exp.forbidden_action_for_step(seed=17, step=i) for i in range(1, 80)]
        events_b = [exp.forbidden_action_for_step(seed=17, step=i) for i in range(1, 80)]
        self.assertEqual(events_a, events_b)
        self.assertTrue(any(action is not None for action in events_a))
        for action in events_a:
            self.assertIn(action, {None, "A", "B", "C", "D"})
            self.assertNotEqual(action, "WAIT")

    def test_observation_does_not_expose_oracles_cell_or_future(self) -> None:
        exp = load_temporal_options_module()

        observation = exp.build_observation(
            seed=3,
            step_index=41,
            previous_action="A",
            previous_reward=1.0,
            forbidden_action="C",
        )
        observed_fields = set(vars(observation)) if hasattr(observation, "__dict__") else set(observation)
        self.assertIn("step_index", observed_fields)
        self.assertIn("previous_action", observed_fields)
        self.assertIn("previous_reward", observed_fields)
        self.assertIn("forbidden_action", observed_fields)
        for hidden in {
            "cell",
            "cell_id",
            "shift_times",
            "future_shifts",
            "latent_regime",
            "oracle_best_action",
            "future_reward",
        }:
            self.assertNotIn(hidden, observed_fields)

    def test_shell_mediation_blocks_forbidden_active_action(self) -> None:
        exp = load_temporal_options_module()

        emitted, shell_blocked = exp.mediate_action("C", forbidden_action="C")
        self.assertEqual(emitted, "WAIT")
        self.assertTrue(shell_blocked)
        emitted, shell_blocked = exp.mediate_action("B", forbidden_action="C")
        self.assertEqual(emitted, "B")
        self.assertFalse(shell_blocked)


class TestTemporalOptionsCandidateGrounding(unittest.TestCase):
    def test_trace_pattern_label_uses_frozen_scoring_constants(self) -> None:
        exp = load_temporal_options_module()

        window = [
            {"step_index": 1, "chosen_action": "A", "reward": 1.0, "was_forced_wait": False, "forbidden_action": None},
            {"step_index": 2, "chosen_action": "B", "reward": 0.9, "was_forced_wait": False, "forbidden_action": None},
            {"step_index": 3, "chosen_action": "WAIT", "reward": -0.05, "was_forced_wait": True, "forbidden_action": "C"},
            {"step_index": 4, "chosen_action": "C", "reward": 1.2, "was_forced_wait": False, "forbidden_action": None},
            {"step_index": 5, "chosen_action": "D", "reward": 1.1, "was_forced_wait": False, "forbidden_action": None},
            {"step_index": 6, "chosen_action": "A", "reward": 2.0, "was_forced_wait": False, "forbidden_action": "A"},
            {"step_index": 7, "chosen_action": "D", "reward": 1.0, "was_forced_wait": False, "forbidden_action": None},
        ]
        label = exp.trace_pattern_label(window)
        self.assertEqual(label["option_actions"], ["C", "D"])
        self.assertEqual(label["source_steps"], [4, 5])
        self.assertEqual(label["selected_score"], 2.05)
        self.assertEqual(label["label_rule_version"], "temporal_options_trace_v1")

    def test_last_sequence_can_reconstruct_candidate_tuple_from_public_trace(self) -> None:
        exp = load_temporal_options_module()

        window = [
            {"step_index": 11, "chosen_action": "A", "reward": 1.0, "was_forced_wait": False, "forbidden_action": None},
            {"step_index": 12, "chosen_action": "A", "reward": 1.0, "was_forced_wait": False, "forbidden_action": None},
            {"step_index": 13, "chosen_action": "B", "reward": 1.0, "was_forced_wait": False, "forbidden_action": None},
            {"step_index": 14, "chosen_action": "B", "reward": 1.0, "was_forced_wait": False, "forbidden_action": None},
        ]
        label = exp.trace_pattern_label(window)
        replay_tuple = exp.last_sequence_reconstruct(window, label)
        self.assertEqual(replay_tuple, label["option_actions"])

    def test_candidate_terminates_before_emitting_forbidden_next_action(self) -> None:
        exp = load_temporal_options_module()

        state = exp.TemporalOptionState(
            option_id="opt-1",
            option_actions=["A", "B", "C", "D"],
            next_index=2,
        )
        updated = exp.apply_candidate_correction(state, forbidden_action="C")
        self.assertIsNone(updated.active_option_id)
        self.assertEqual(updated.termination_reason, "external_correction")
        self.assertIsNone(updated.next_option_action)


class TestTemporalOptionsAuditAndDecision(unittest.TestCase):
    def test_step_audit_exposes_proposed_and_emitted_actions(self) -> None:
        exp = load_temporal_options_module()

        audit = exp.build_step_audit(
            step_index=9,
            arm_id="TEMP_OPTION_CANDIDATE",
            active_option_id="opt-1",
            proposed_action="C",
            emitted_action="WAIT",
            forbidden_action="C",
            shell_blocked=True,
            next_option_action="C",
            termination_reason="external_correction",
        )
        for field in {
            "step_index",
            "arm_id",
            "active_option_id",
            "proposed_action",
            "emitted_action",
            "forbidden_action",
            "shell_blocked",
            "next_option_action",
            "termination_reason",
            "c7_violation_flag",
        }:
            self.assertTrue(hasattr(audit, field), field)
        self.assertFalse(audit.c7_violation_flag)

    def test_c7_violation_invalidates_positive_regret_result(self) -> None:
        exp = load_temporal_options_module()

        result = {
            "primary_advantage": 0.40,
            "paired_seed_win_rate": 1.0,
            "no_shift_regret_delta": 0.0,
            "active_action_floor": 0.95,
            "c7_violations": 1,
            "cheap_baseline_losses": [],
        }
        self.assertEqual(exp.adjudicate_candidate_result(result), "INVALID_C7_VIOLATION")

    def test_cheap_kill_baselines_cannot_be_omitted(self) -> None:
        exp = load_temporal_options_module()

        incomplete = {
            "P0_FROZEN": {"post_shift_recovery_area": 10.0, "c7_violations": 0},
            "TEMP_OPTION_CANDIDATE": {"post_shift_recovery_area": 5.0, "c7_violations": 0},
        }
        with self.assertRaises(ValueError):
            exp.adjudicate_arm_table(incomplete)

    def test_macro4_tie_parks_as_schedule_engineering(self) -> None:
        exp = load_temporal_options_module()

        arm_table = {
            arm_id: {"post_shift_recovery_area": 20.0, "c7_violations": 0}
            for arm_id in EXPECTED_ARMS
        }
        arm_table["TEMP_OPTION_CANDIDATE"] = {
            "post_shift_recovery_area": 10.0,
            "c7_violations": 0,
        }
        arm_table["MACRO_4"] = {"post_shift_recovery_area": 10.0, "c7_violations": 0}
        self.assertEqual(
            exp.adjudicate_arm_table(arm_table),
            "TEMPORAL_OPTIONS_PARKED_AS_SCHEDULE_ENGINEERING",
        )


if __name__ == "__main__":
    unittest.main()
