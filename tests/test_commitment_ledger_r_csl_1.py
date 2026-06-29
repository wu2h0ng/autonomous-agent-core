"""R-CSL-1 no-model commitment ledger guards.

These tests cover the implementation-cast boundary only: real mechanism files,
C6/C7 guards, and no-run-before-freeze behavior. They do not run r-final.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aac.commitment_ledger import (
    CommitmentFeedback,
    CommitmentLedgerPolicy,
    CommitmentOutcome,
)
from envs.commitment_correction import CorrectionSignal
from experiments import r_csl_1


class TestCommitmentLedgerPolicy(unittest.TestCase):
    def test_selects_only_external_admissible_actions_without_mutating_c7_input(self) -> None:
        policy = CommitmentLedgerPolicy(
            n_actions=4,
            action_commitments={0: "hold", 1: "hold", 2: "repair", 3: "neutral"},
        )
        policy.observe(
            CommitmentFeedback(
                action=0,
                outcome=CommitmentOutcome.PRESERVED,
                violation=False,
                budget_delta=+1.0,
            )
        )
        admissible = {1, 2, 3}

        decision = policy.select(admissible_actions=admissible)

        self.assertEqual(decision.action, 1)
        self.assertEqual(admissible, {1, 2, 3}, "policy must not mutate C7 truth input")
        self.assertEqual(policy.c7_violation_count, 0)
        self.assertNotIn(0, decision.trace.admissible_actions)

    def test_violation_and_break_raise_repair_priority_without_shell_write(self) -> None:
        policy = CommitmentLedgerPolicy(
            n_actions=4,
            action_commitments={0: "hold", 1: "hold", 2: "repair", 3: "neutral"},
        )

        policy.observe(
            CommitmentFeedback(
                action=0,
                outcome=CommitmentOutcome.BROKEN,
                violation=True,
                budget_delta=-2.0,
                repair_commitment="repair",
            )
        )
        decision = policy.select(admissible_actions={1, 2, 3})

        self.assertEqual(decision.action, 2)
        self.assertGreater(policy.snapshot().repair_priority["repair"], 0.0)
        self.assertNotIn("preferred_action", decision.trace.correction_fields)

    def test_rejects_subject_or_correction_payload_that_contains_action_advice(self) -> None:
        with self.assertRaisesRegex(ValueError, "preferred_action"):
            CorrectionSignal.from_mapping(
                {
                    "admissible_actions": [0, 1],
                    "previous_violation": False,
                    "budget_delta": 0.0,
                    "commitment_outcome": "neutral",
                    "preferred_action": 1,
                }
            )

    def test_correction_signal_is_external_and_immutable_to_policy(self) -> None:
        signal = CorrectionSignal.from_mapping(
            {
                "admissible_actions": [0, 2],
                "previous_violation": False,
                "budget_delta": 0.0,
                "commitment_outcome": "neutral",
                "audit_ref": "audit:1",
            }
        )
        policy = CommitmentLedgerPolicy(n_actions=3)

        decision = policy.step(signal)

        self.assertIn(decision.action, signal.admissible_actions)
        self.assertEqual(signal.admissible_actions, (0, 2))
        with self.assertRaises(AttributeError):
            signal.admissible_actions = (1,)  # type: ignore[misc]


class TestRCSL1ExperimentBoundary(unittest.TestCase):
    def test_frozen_constants_match_preregistration(self) -> None:
        self.assertEqual(r_csl_1.DEVELOPMENT_SMOKE_SEEDS, tuple(range(2400, 2420)))
        self.assertEqual(r_csl_1.CALIBRATION_SEEDS, tuple(range(2420, 2440)))
        self.assertEqual(r_csl_1.R_FINAL_SEEDS, tuple(range(2500, 2530)))
        self.assertIn("CSL", r_csl_1.ARMS)
        self.assertIn("ACTION_SUPPRESSOR", r_csl_1.BASELINE_BATTERY)

    def test_rfinal_refuses_without_runner_prereg_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_lock = Path(temp_dir) / "prereg.lock"
            with self.assertRaisesRegex(r_csl_1.RunLockedError, "prereg.lock"):
                r_csl_1.assert_rfinal_unlocked(lock_path=missing_lock)

    def test_rfinal_refuses_non_json_prereg_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = Path(temp_dir) / "prereg.lock"
            lock_path.write_text("locked\n", encoding="utf-8")

            with self.assertRaisesRegex(r_csl_1.RunLockedError, "valid JSON"):
                r_csl_1.assert_rfinal_unlocked(lock_path=lock_path)

    def test_environment_step_returns_current_external_c7_truth(self) -> None:
        env = r_csl_1.CommitmentCorrectionEnv(seed=2400)
        signal = env.correction_signal()
        for _ in range(6):
            signal = env.step(1)

        self.assertEqual(signal.admissible_actions, env.correction_signal().admissible_actions)
        self.assertNotIn(0, signal.admissible_actions)

    def test_rfinal_has_review_gated_execution_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            lock_path = temp_path / "prereg.lock"
            review_path = temp_path / "pr-architecture-review.json"
            self._write_valid_prereg_lock(lock_path)
            review_path.write_text(
                json.dumps(
                    {
                        "actor": "codex-builder-r-csl-1",
                        "artifact_hashes": self._current_review_artifact_hashes(),
                        "gate_name": "pr-architecture-review",
                        "prior_gate": "implementation-cast",
                        "reviewed_by": "independent-reviewer",
                        "standard": "PARADIGM-INNOVATION-LOOP-OS",
                        "verdict": "accept",
                        "output_digest": "review-digest",
                    }
                ),
                encoding="utf-8",
            )

            expected_result = {
                "prereg_id": "R-CSL-1",
                "seeds": list(r_csl_1.R_FINAL_SEEDS),
                "arms": list(r_csl_1.ARMS),
                "verdict": "NOT_MET",
            }
            with mock.patch.object(
                r_csl_1,
                "run_protocol",
                return_value=expected_result,
            ) as protocol_runner:
                result = r_csl_1.run_rfinal(
                    lock_path=lock_path,
                    pr_architecture_review_path=review_path,
                    expected_pr_architecture_review_digest="review-digest",
                    bootstrap_resamples=200,
                )

        self.assertEqual(result["prereg_id"], "R-CSL-1")
        self.assertEqual(result["seeds"], list(r_csl_1.R_FINAL_SEEDS))
        self.assertEqual(result["arms"], list(r_csl_1.ARMS))
        self.assertIn(result["verdict"], {"MET", "NOT_MET", "INCONCLUSIVE", "INVALID"})
        protocol_runner.assert_called_once_with(
            seeds=r_csl_1.R_FINAL_SEEDS,
            bootstrap_resamples=200,
            allow_rfinal=True,
        )

    def test_protocol_covers_requested_seed_and_arm_sets(self) -> None:
        result = r_csl_1.run_protocol(
            seeds=r_csl_1.DEVELOPMENT_SMOKE_SEEDS[:2],
            arms=r_csl_1.ARMS,
            steps=8,
            bootstrap_resamples=25,
        )

        self.assertEqual(result["prereg_id"], "R-CSL-1")
        self.assertEqual(result["seeds"], list(r_csl_1.DEVELOPMENT_SMOKE_SEEDS[:2]))
        self.assertEqual(result["arms"], list(r_csl_1.ARMS))
        self.assertIn("per_seed", result)
        self.assertIn("summary", result)
        self.assertIn("criteria", result)

    def test_rfinal_refuses_minimal_forged_accepted_review_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            lock_path = temp_path / "prereg.lock"
            review_path = temp_path / "pr-architecture-review.json"
            self._write_valid_prereg_lock(lock_path)
            review_path.write_text(
                json.dumps(
                    {
                        "gate_name": "pr-architecture-review",
                        "verdict": "accept",
                        "output_digest": "review-digest",
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(r_csl_1.RunLockedError, "standard"):
                r_csl_1.run_rfinal(
                    lock_path=lock_path,
                    pr_architecture_review_path=review_path,
                    expected_pr_architecture_review_digest="review-digest",
                    bootstrap_resamples=10,
                )

    def test_protocol_refuses_rfinal_seeds_without_rfinal_gate(self) -> None:
        with self.assertRaisesRegex(r_csl_1.RunLockedError, "r-final seeds"):
            r_csl_1.run_protocol(
                seeds=r_csl_1.R_FINAL_SEEDS,
                arms=("CSL", "P0"),
                steps=4,
                bootstrap_resamples=10,
            )

    def test_rfinal_refuses_blocked_pr_architecture_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            lock_path = temp_path / "prereg.lock"
            review_path = temp_path / "pr-architecture-review.json"
            self._write_valid_prereg_lock(lock_path)
            review_path.write_text(
                json.dumps(
                    {
                        "actor": "codex-builder-r-csl-1",
                        "artifact_hashes": {
                            "autonomous-agent-core/experiments/r_csl_1.py": "hash",
                            "autonomous-agent-core/src/aac/commitment_ledger.py": "hash",
                            "autonomous-agent-core/src/envs/commitment_correction.py": "hash",
                            "autonomous-agent-core/tests/test_commitment_ledger_r_csl_1.py": "hash",
                        },
                        "gate_name": "pr-architecture-review",
                        "prior_gate": "implementation-cast",
                        "reviewed_by": "independent-reviewer",
                        "standard": "PARADIGM-INNOVATION-LOOP-OS",
                        "verdict": "block",
                        "output_digest": "blocked-digest",
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(r_csl_1.RunLockedError, "not accepted"):
                r_csl_1.run_rfinal(
                    lock_path=lock_path,
                    pr_architecture_review_path=review_path,
                    expected_pr_architecture_review_digest="blocked-digest",
                    bootstrap_resamples=10,
                )

    def test_rfinal_refuses_lock_review_mechanism_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            lock_path = temp_path / "prereg.lock"
            review_path = temp_path / "pr-architecture-review.json"
            self._write_valid_prereg_lock(lock_path)
            artifact_hashes = self._current_review_artifact_hashes()
            artifact_hashes["autonomous-agent-core/experiments/r_csl_1.py"] = "different-hash"
            review_path.write_text(
                json.dumps(
                    {
                        "actor": "codex-builder-r-csl-1",
                        "artifact_hashes": artifact_hashes,
                        "gate_name": "pr-architecture-review",
                        "prior_gate": "implementation-cast",
                        "reviewed_by": "independent-reviewer",
                        "standard": "PARADIGM-INNOVATION-LOOP-OS",
                        "verdict": "accept",
                        "output_digest": "review-digest",
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.object(
                r_csl_1,
                "run_protocol",
                return_value={"prereg_id": "R-CSL-1", "verdict": "NOT_MET"},
            ):
                with self.assertRaisesRegex(r_csl_1.RunLockedError, "does not match"):
                    r_csl_1.run_rfinal(
                        lock_path=lock_path,
                        pr_architecture_review_path=review_path,
                        expected_pr_architecture_review_digest="review-digest",
                        bootstrap_resamples=10,
                    )

    def test_rfinal_refuses_current_mechanism_file_hash_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            lock_path = temp_path / "prereg.lock"
            review_path = temp_path / "pr-architecture-review.json"
            lock_path.write_text(
                json.dumps(
                    {
                        "frozen_at": "2026-06-25T00:00:00+00:00",
                        "mechanism_files": {
                            "experiments/r_csl_1.py": "stale-hash",
                            "src/aac/commitment_ledger.py": "stale-hash",
                            "src/envs/commitment_correction.py": "stale-hash",
                            "tests/test_commitment_ledger_r_csl_1.py": "stale-hash",
                        },
                        "prereg_id": "R-CSL-1",
                        "spec_file_sha256": self._current_prereg_spec_hash(),
                        "spec_sha256": "a" * 64,
                        "target_head": "b" * 40,
                    }
                ),
                encoding="utf-8",
            )
            review_path.write_text(
                json.dumps(
                    {
                        "actor": "codex-builder-r-csl-1",
                        "artifact_hashes": {
                            "autonomous-agent-core/experiments/r_csl_1.py": "stale-hash",
                            "autonomous-agent-core/src/aac/commitment_ledger.py": "stale-hash",
                            "autonomous-agent-core/src/envs/commitment_correction.py": "stale-hash",
                            "autonomous-agent-core/tests/test_commitment_ledger_r_csl_1.py": "stale-hash",
                        },
                        "gate_name": "pr-architecture-review",
                        "prior_gate": "implementation-cast",
                        "reviewed_by": "independent-reviewer",
                        "standard": "PARADIGM-INNOVATION-LOOP-OS",
                        "verdict": "accept",
                        "output_digest": "review-digest",
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.object(
                r_csl_1,
                "run_protocol",
                return_value={"prereg_id": "R-CSL-1", "verdict": "NOT_MET"},
            ):
                with self.assertRaisesRegex(r_csl_1.RunLockedError, "current mechanism file"):
                    r_csl_1.run_rfinal(
                        lock_path=lock_path,
                        pr_architecture_review_path=review_path,
                        expected_pr_architecture_review_digest="review-digest",
                        bootstrap_resamples=10,
                    )

    def test_rfinal_refuses_current_prereg_spec_file_hash_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            lock_path = temp_path / "prereg.lock"
            review_path = temp_path / "pr-architecture-review.json"
            self._write_valid_prereg_lock(lock_path, spec_file_sha256="c" * 64)
            review_path.write_text(
                json.dumps(
                    {
                        "actor": "codex-builder-r-csl-1",
                        "artifact_hashes": self._current_review_artifact_hashes(),
                        "gate_name": "pr-architecture-review",
                        "prior_gate": "implementation-cast",
                        "reviewed_by": "independent-reviewer",
                        "standard": "PARADIGM-INNOVATION-LOOP-OS",
                        "verdict": "accept",
                        "output_digest": "review-digest",
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.object(
                r_csl_1,
                "run_protocol",
                return_value={"prereg_id": "R-CSL-1", "verdict": "NOT_MET"},
            ):
                with self.assertRaisesRegex(r_csl_1.RunLockedError, "current prereg spec"):
                    r_csl_1.run_rfinal(
                        lock_path=lock_path,
                        pr_architecture_review_path=review_path,
                        expected_pr_architecture_review_digest="review-digest",
                        bootstrap_resamples=10,
                    )

    def test_seed_changes_deterministic_episode_task(self) -> None:
        first = r_csl_1.run_episode(seed=2500, arm="CSL", steps=12)
        second = r_csl_1.run_episode(seed=2501, arm="CSL", steps=12)

        self.assertNotEqual(first.diagnostics["task_signature"], second.diagnostics["task_signature"])

    def _write_valid_prereg_lock(
        self,
        lock_path: Path,
        *,
        spec_file_sha256: str | None = None,
    ) -> None:
        lock_path.write_text(
            json.dumps(
                {
                    "frozen_at": "2026-06-25T00:00:00+00:00",
                    "mechanism_files": self._current_lock_hashes(),
                    "prereg_id": "R-CSL-1",
                    "spec_file_sha256": spec_file_sha256 or self._current_prereg_spec_hash(),
                    "spec_sha256": "a" * 64,
                    "target_head": "b" * 40,
                }
            ),
            encoding="utf-8",
        )

    def _current_lock_hashes(self) -> dict[str, str]:
        repo_root = Path(__file__).resolve().parents[1]
        relative_paths = (
            "experiments/r_csl_1.py",
            "src/aac/commitment_ledger.py",
            "src/envs/commitment_correction.py",
            "tests/test_commitment_ledger_r_csl_1.py",
        )
        return {
            relative_path: hashlib.sha256((repo_root / relative_path).read_bytes()).hexdigest()
            for relative_path in relative_paths
        }

    def _current_review_artifact_hashes(self) -> dict[str, str]:
        return {
            f"autonomous-agent-core/{relative_path}": digest
            for relative_path, digest in self._current_lock_hashes().items()
        }

    def _current_prereg_spec_hash(self) -> str:
        workspace_root = Path(__file__).resolve().parents[2]
        spec_path = workspace_root / "docs/research/R-CSL-1.PREREG-2026-06-25.yaml"
        return hashlib.sha256(spec_path.read_bytes()).hexdigest()


if __name__ == "__main__":
    unittest.main()
