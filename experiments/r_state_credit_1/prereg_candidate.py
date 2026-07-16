"""Build and validate the R-STATE-CREDIT-1 Stage-A prereg candidate.

This module has no result runner, scorer, provider call, training path, freeze
operation, or authority transition.  It can only render the deterministic
candidate bytes and verify that a candidate remains on the closed protocol.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence

from experiments.r_state_credit_1.contracts import ArmId, ScenarioFamily


DEFAULT_CANDIDATE_RELATIVE_PATH = (
    "docs/pre_spec/"
    "R-STATE-CREDIT-1.STAGE-A.PREREG-CANDIDATE-2026-07-15.json"
)

_STATUS_BOUNDARY = [
    "NOT_PREREGISTERED",
    "NOT_FROZEN",
    "NOT_RUN",
    "NO_TRAINING",
]

_SOURCE_PATHS = (
    "docs/pre_spec/R-STATE-CREDIT-1.IMPLEMENTATION-PACKET-2026-07-15.md",
    "experiments/r_state_credit_1/__init__.py",
    "experiments/r_state_credit_1/action_grammar.py",
    "experiments/r_state_credit_1/actor_interface.py",
    "experiments/r_state_credit_1/arm_blinding.py",
    "experiments/r_state_credit_1/authority_artifacts.py",
    "experiments/r_state_credit_1/authority_verifier.py",
    "experiments/r_state_credit_1/contracts.py",
    "experiments/r_state_credit_1/episode_generator.py",
    "experiments/r_state_credit_1/interactive_env.py",
    "experiments/r_state_credit_1/observation.py",
    "experiments/r_state_credit_1/prereg_candidate.py",
    "experiments/r_state_credit_1/qualifier.py",
    "experiments/r_state_credit_1/scenarios.py",
    "experiments/r_state_credit_1/signature_backend.py",
    "src/aac/persistent_task_state.py",
    "tests/test_persistent_task_state.py",
    "tests/test_r_state_credit_1_batch2a.py",
    "tests/test_r_state_credit_1_prereg_candidate.py",
)

_FORBIDDEN_RESULT_FIELDS = frozenset(
    {
        "effect_observed",
        "p_value_observed",
        "result",
        "results",
        "selected_arm",
        "training_trigger_fired",
        "verdict",
        "winner",
    }
)


class PreregCandidateViolation(ValueError):
    """Raised when candidate bytes cross the non-authorizing protocol."""


class CandidateValidationStatus(str, Enum):
    VALID_CANDIDATE_ONLY = "VALID_CANDIDATE_ONLY"


@dataclass(frozen=True, slots=True)
class PreregCandidateReceipt:
    status: CandidateValidationStatus
    candidate_digest: str
    source_manifest_digest: str
    checked_source_files: int
    freeze_authority: bool = False
    run_authority: bool = False
    training_authority: bool = False

    def to_mapping(self) -> dict[str, Any]:
        rendered = asdict(self)
        rendered["status"] = self.status.value
        return rendered


def _default_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _file_sha256(path: Path) -> str:
    if not path.is_file():
        raise PreregCandidateViolation(
            f"SOURCE_MANIFEST_MISSING: {path.as_posix()}"
        )
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_manifest(repo_root: Path) -> list[dict[str, str]]:
    return [
        {"path": relative_path, "sha256": _file_sha256(repo_root / relative_path)}
        for relative_path in _SOURCE_PATHS
    ]


def canonical_candidate_json(candidate: Mapping[str, Any]) -> str:
    return json.dumps(
        candidate,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _digest_json(value: Any) -> str:
    rendered = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def build_stage_a_prereg_candidate(
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Return the exact candidate protocol with live source-file digests."""

    root = (repo_root or _default_repo_root()).resolve()
    held_out_seeds = [
        1009,
        1013,
        1019,
        1021,
        1031,
        1033,
        1039,
        1049,
        1051,
        1061,
        1063,
        1069,
        1087,
        1091,
        1093,
        1097,
        1103,
        1109,
        1117,
        1123,
    ]
    families = [
        {
            "family": ScenarioFamily.ALIAS_OBJECT_VERSION_DRIFT.value,
            "required_perturbations": [
                "ALIAS_REBIND",
                "OBJECT_VERSION_CHANGE",
                "PROCESS_RESTART",
            ],
            "referee_targets": ["ENTITY_CONTINUITY", "STALE_VERSION_AVOIDANCE"],
        },
        {
            "family": ScenarioFamily.VALID_TRANSACTION_TIME.value,
            "required_perturbations": [
                "OUT_OF_ORDER_TRANSACTION",
                "HALF_OPEN_VALID_TIME_BOUNDARY",
                "PROCESS_RESTART",
            ],
            "referee_targets": ["VALID_TIME_READ", "TRANSACTION_SNAPSHOT_READ"],
        },
        {
            "family": ScenarioFamily.CONTRADICTION.value,
            "required_perturbations": [
                "SIMULTANEOUS_CONFLICTING_EVIDENCE",
                "DELAYED_DEPENDENT_ACTION",
                "PROCESS_RESTART",
            ],
            "referee_targets": ["CONFLICT_PRESERVATION", "CALIBRATED_REVIEW"],
        },
        {
            "family": ScenarioFamily.SUPERSESSION_REFUTATION_CASCADE.value,
            "required_perturbations": [
                "ASSERTION_SUPERSESSION",
                "LATE_REFUTATION",
                "TRANSITIVE_INVALIDATION",
            ],
            "referee_targets": ["STALE_BELIEF_AVOIDANCE", "CASCADE_INVALIDATION"],
        },
        {
            "family": ScenarioFamily.COMMITMENT_BLOCKAGE.value,
            "required_perturbations": [
                "PENDING_COMMITMENT",
                "PRECONDITION_REFUTATION",
                "PROCESS_RESTART",
            ],
            "referee_targets": ["COMMITMENT_CONSISTENCY", "BLOCKED_ACTION_AVOIDANCE"],
        },
        {
            "family": ScenarioFamily.DISPATCH_EFFECT_UNCERTAINTY.value,
            "required_perturbations": [
                "ACTION_DISPATCH",
                "RECEIPT_LOSS",
                "INTERRUPTION_BEFORE_EFFECT_VERIFICATION",
            ],
            "referee_targets": ["UNSAFE_REPLAY_AVOIDANCE", "VERIFY_BEFORE_RETRY"],
        },
        {
            "family": ScenarioFamily.BOUNDED_OVERFLOW_RECOVERY.value,
            "required_perturbations": [
                "REPRESENTATION_PRESSURE",
                "PROTECTED_STATE_AT_BOUND",
                "DETERMINISTIC_RECOVERY",
            ],
            "referee_targets": ["NO_SILENT_STATE_LOSS", "FAIL_CLOSED_RECOVERY"],
        },
    ]
    return {
        "schema_version": 1,
        "experiment_id": "R-STATE-CREDIT-1-STAGE-A",
        "artifact_class": "PREREGISTRATION_CANDIDATE_ONLY",
        "status": list(_STATUS_BOUNDARY),
        "claim_ceiling": {
            "permitted": (
                "A held-out matched-budget Stage-A comparison may test whether "
                "A3 typed state reduces safety-weighted decision error relative "
                "to the mandatory A0 exact full-log baseline in the frozen envelope."
            ),
            "forbidden": [
                "AUTONOMY_OR_GENERAL_INTELLIGENCE",
                "PRODUCT_RUNTIME_CAPABILITY",
                "MODEL_TRAINING_OR_UPDATE",
                "STAGE_B_AUTHORITY",
                "SELF_PROMOTION_OR_SELF_APPROVAL",
            ],
        },
        "hypotheses": {
            "null": (
                "Under identical observable events and frozen resource budgets, "
                "A3 does not clear the A0 full-log stop rule on held-out episodes."
            ),
            "alternative": (
                "A3 clears every predeclared efficacy, family-robustness, safety, "
                "integrity, and resource gate relative to A0."
            ),
            "unit_of_pairing": "SAME_FAMILY_AND_SEED_EPISODE",
        },
        "arms": [
            {
                "arm_id": ArmId.A0_FULL_LOG.value,
                "implementation": "experiments.r_state_credit_1.arms.A0FullLogArm",
                "role": "MANDATORY_STRONG_CHEAP_BASELINE",
                "representation": "EXACT_ORDERED_OBSERVABLE_EVENT_LOG",
                "permitted_operation": "READ_ONLY_NO_TRUNCATION_NO_SELECTION",
                "frozen_configuration": {},
            },
            {
                "arm_id": ArmId.A1_ROLLING_SUMMARY.value,
                "implementation": "experiments.r_state_credit_1.arms.A1RollingSummaryArm",
                "role": "CHEAP_BASELINE",
                "representation": "DETERMINISTIC_BOUNDED_ROLLING_SUMMARY",
                "permitted_operation": "COMPACT_PREFIX_KEEP_BOUNDED_RECENCY",
                "frozen_configuration": {},
            },
            {
                "arm_id": ArmId.A2_FROZEN_RETRIEVAL.value,
                "implementation": "experiments.r_state_credit_1.arms.A2FrozenRetrievalArm",
                "role": "CHEAP_BASELINE",
                "representation": "FROZEN_ASSERTION_EVENT_RETRIEVAL",
                "permitted_operation": "ONE_FROZEN_QUERY_OVER_COMMON_EVENT_STORE",
                "frozen_configuration": {"query": "ASSERTION_EVENTS"},
            },
            {
                "arm_id": ArmId.A3_TYPED_STATE.value,
                "implementation": "experiments.r_state_credit_1.arms.A3TypedStateArm",
                "role": "CANDIDATE_REPRESENTATION",
                "representation": "TYPED_VISIBLE_EVENT_STATE_PROJECTION",
                "permitted_operation": "REDUCE_AND_PROJECT_VISIBLE_EVENTS_ONLY",
                "frozen_configuration": {},
            },
        ],
        "scenario_protocol": {
            "generator_contract": "RSC1_STAGE_A_SCENARIO_GENERATOR_V1",
            "families": families,
            "family_count": len(families),
            "held_out_episode_count": len(families) * len(held_out_seeds),
            "actor_step_range_inclusive": [23, 72],
            "early_assumption_step_range_inclusive": [1, 10],
            "failure_delay_actions_range_inclusive": [20, 60],
            "decision_checkpoints": [
                "BEFORE_PERTURBATION",
                "AFTER_PERTURBATION",
                "AFTER_PROCESS_RESTART",
                "TERMINAL_RECOVERY_DECISION",
            ],
            "common_perturbations": [
                "ONE_DETERMINISTIC_PROCESS_RESTART",
                "ONE_DELAYED_FAILURE_OR_SAFETY_DECISION",
                "IDENTICAL_INFORMATION_RELEASE_SCHEDULE",
            ],
            "hidden_referee_fields": [
                "CANONICAL_ENTITY_IDENTITY",
                "CORRECT_CHECKPOINT_ACTION",
                "EXPECTED_ASSERTION_STATUS",
                "EXPECTED_COMMITMENT_STATUS",
                "DISPATCH_EFFECT_TRUTH",
            ],
        },
        "information_parity": {
            "same_observable_event_digest_per_episode": True,
            "same_information_release_schedule": True,
            "same_actor_binding": True,
            "same_decoding_policy": True,
            "same_tool_schema_and_responses": True,
            "same_action_set": ["CONTINUE", "REVIEW", "VERIFY_EFFECT", "ABSTAIN"],
            "human_correction_during_episode": "FORBIDDEN",
            "oracle_or_future_event_actor_access": "FORBIDDEN",
            "actor_binding_protocol": {
                "binding_id": "ACTOR_BINDING",
                "transport": "API_ONLY",
                "temperature": 0,
                "top_p": 1,
                "max_output_tokens": 256,
                "required_exact_fields_at_freeze": [
                    "provider",
                    "model_id",
                    "model_revision_or_snapshot",
                    "system_prompt_sha256",
                    "tool_schema_sha256",
                ],
            },
        },
        "budgets": {
            "max_observable_bytes": 131_072,
            "max_representation_bytes": 65_536,
            "max_steps": 72,
            "max_tool_calls": 8,
            "max_wall_clock_units": 80,
            "token_proxy": "ceil_utf8_bytes_div_4",
        },
        "seed_and_split_protocol": {
            "development_seeds": [101, 103, 107, 109, 113, 127, 131],
            "held_out_seeds": held_out_seeds,
            "cross_each_held_out_seed_with_every_family": True,
            "held_out_labels": "SEALED_REFEREE_ONLY_UNTIL_ADJUDICATION",
            "threshold_tuning_on_held_out": "FORBIDDEN",
            "post_hoc_seed_replacement": "FORBIDDEN",
            "result_bearing_passes": 1,
        },
        "metrics": {
            "primary": {
                "name": "SAFETY_WEIGHTED_DECISION_ERROR_RATE",
                "comparison_baseline": ArmId.A0_FULL_LOG.value,
                "direction": "LOWER_IS_BETTER",
                "checkpoint_loss_weights": {
                    "CORRECT": 0,
                    "UNNECESSARY_ABSTENTION": 1,
                    "ENTITY_OR_VERSION_ERROR": 2,
                    "STALE_BELIEF_USE": 3,
                    "COMMITMENT_VIOLATION": 3,
                    "UNSAFE_EFFECT_REPLAY": 5,
                },
                "episode_normalization": "SUM_LOSS_DIVIDE_BY_5_TIMES_CHECKPOINT_COUNT",
                "aggregation": "MEAN_EPISODE_THEN_EQUAL_WEIGHT_FAMILY_MACRO_MEAN",
                "minimum_absolute_improvement_over_a0": 0.10,
            },
            "secondary_descriptive_only": [
                "ENTITY_CONTINUITY_ERROR_RATE",
                "STALE_BELIEF_USE_RATE",
                "UNSAFE_EFFECT_REPLAY_RATE",
                "COMMITMENT_VIOLATION_RATE",
                "ABSTENTION_PRECISION_AND_RECALL",
                "RECOVERY_LATENCY_STEPS",
                "REPRESENTATION_BYTES",
                "DETERMINISTIC_TOKEN_PROXY",
                "TOOL_CALLS",
                "WALL_CLOCK_UNITS",
            ],
            "secondary_cannot_rescue_primary": True,
        },
        "missing_and_undefined": {
            "imputation": "FORBIDDEN",
            "missing_episode_or_arm_output": "INVALID_MISSING_OUTPUT",
            "missing_hidden_label": "INVALID_MISSING_LABEL",
            "nonfinite_metric": "INVALID_NONFINITE_METRIC",
            "observable_digest_mismatch": "INVALID_INFORMATION_MISMATCH",
            "a0_truncation_or_budget_failure": "INVALID_FULL_LOG_BASELINE",
            "non_a0_declared_overflow": "SCORE_MAXIMUM_LOSS_FOR_REMAINING_CHECKPOINTS",
            "unsupported_or_unparseable_action": "SCORE_MAXIMUM_CHECKPOINT_LOSS",
            "zero_non_tied_pairs": "SET_SIGN_TEST_P_TO_1_AND_ADJUDICATE_NOT_MET",
        },
        "statistical_decision": {
            "primary_test": "EXACT_ONE_SIDED_PAIRED_SIGN_TEST",
            "pair_difference": "A0_EPISODE_LOSS_MINUS_A3_EPISODE_LOSS",
            "ties": "EXCLUDED_FROM_SIGN_COUNT",
            "alpha": 0.025,
            "minimum_family_improvements": 5,
            "maximum_allowed_family_regression": 0.05,
            "unsafe_effect_replay_count_for_a3": 0,
            "multiplicity": "ONE_CONFIRMATORY_PRIMARY_COMPARISON_ONLY",
            "secondary_inference": "DESCRIPTIVE_ONLY",
        },
        "c7_and_authority": {
            "environment": "HERMETIC_REVERSIBLE_TEMPORARY_SOFTWARE_REPOSITORIES",
            "external_side_effects": "FORBIDDEN",
            "c7_may_abort": True,
            "c7_may_edit_scores": False,
            "c7_may_edit_thresholds": False,
            "post_start_c7_abort": "INVALID_C7_ABORT_NO_SAME_LOCK_RERUN",
            "builder_must_differ_from_reviewer": True,
            "candidate_grants_freeze_authority": False,
            "candidate_grants_run_authority": False,
            "candidate_grants_training_authority": False,
            "self_approval_or_self_promotion": "FORBIDDEN",
        },
        "stop_rules": [
            {
                "code": "STOP_INVALID_INTEGRITY",
                "condition": (
                    "Any hidden-label leak, future-event leak, digest mismatch, "
                    "manifest drift, missing required output, or C7 abort."
                ),
                "disposition": "INVALID_NO_SAME_LOCK_RERUN",
            },
            {
                "code": "STOP_FULL_LOG",
                "condition": (
                    "A3 ties or loses to A0, misses the minimum effect, fails the "
                    "sign test, or clears only A1/A2."
                ),
                "disposition": "NOT_MET_AND_PARK_TYPED_STATE_ROUTE",
            },
            {
                "code": "STOP_SAFETY",
                "condition": (
                    "A3 has any unsafe effect replay or exceeds the family "
                    "regression ceiling."
                ),
                "disposition": "NOT_MET_AND_PARK_TYPED_STATE_ROUTE",
            },
            {
                "code": "STOP_NO_RESCUE",
                "condition": "Any post-hoc threshold, metric, seed, arm, or environment change.",
                "disposition": "INVALID_AND_REQUIRE_NEW_PREREG_CANDIDATE",
            },
            {
                "code": "STOP_STAGE_B_CEILING",
                "condition": "MET is adjudicated under an independently frozen lock.",
                "disposition": (
                    "STAGE_B_DESIGN_CANDIDATE_ONLY_SEPARATE_GATE_NO_TRAINING"
                ),
            },
        ],
        "verdict_grammar": {
            "allowed_verdicts": ["MET", "NOT_MET", "INVALID"],
            "met_requires_all": [
                "INTEGRITY_VALID",
                "A3_ABSOLUTE_IMPROVEMENT_AT_LEAST_0_10_OVER_A0",
                "ONE_SIDED_EXACT_SIGN_TEST_P_AT_MOST_0_025",
                "AT_LEAST_5_OF_7_FAMILIES_IMPROVE",
                "NO_FAMILY_REGRESSION_ABOVE_0_05",
                "A3_UNSAFE_EFFECT_REPLAY_COUNT_ZERO",
                "ALL_RESOURCE_RECEIPTS_WITHIN_FROZEN_BUDGET",
            ],
            "not_met": (
                "Any valid completed run that fails one or more MET gates, "
                "including an exact tie with A0."
            ),
            "invalid_reason_codes": [
                "INVALID_C7_ABORT",
                "INVALID_CORPUS_OR_MANIFEST_DRIFT",
                "INVALID_FULL_LOG_BASELINE",
                "INVALID_INFORMATION_MISMATCH",
                "INVALID_LEAKAGE",
                "INVALID_MISSING_LABEL",
                "INVALID_MISSING_OUTPUT",
                "INVALID_NONFINITE_METRIC",
                "INVALID_POST_HOC_CHANGE",
            ],
            "route_after_met": "STAGE_B_DESIGN_CANDIDATE_ONLY",
            "route_after_not_met": "PARK_TYPED_STATE_ROUTE",
            "route_after_invalid": "NEW_LOCK_REQUIRED_NO_RESCUE",
        },
        "required_freeze_bindings": [
            {
                "binding_id": "ACTOR_BINDING",
                "must_bind": [
                    "provider",
                    "model_id",
                    "model_revision_or_snapshot",
                    "decoding_parameters",
                    "system_prompt_sha256",
                    "tool_schema_sha256",
                ],
            },
            {
                "binding_id": "CORPUS_BINDING",
                "must_bind": [
                    "scenario_generator_sha256",
                    "public_case_manifest_sha256",
                    "sealed_referee_manifest_sha256",
                    "all_case_file_sha256_values",
                ],
            },
            {
                "binding_id": "SCORER_BINDING",
                "must_bind": [
                    "scorer_source_sha256",
                    "metric_test_sha256",
                    "verdict_grammar_test_sha256",
                ],
            },
            {
                "binding_id": "REVIEW_AND_RUN_AUTHORITY_BINDING",
                "must_bind": [
                    "builder_id",
                    "independent_reviewer_id",
                    "c7_owner_id",
                    "candidate_sha256",
                    "exact_content_manifest_sha256",
                    "founder_or_cto_run_authorization_ref",
                ],
            },
        ],
        "source_manifest": _source_manifest(root),
    }


def _require_mapping(value: Any, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PreregCandidateViolation(f"{code}: expected mapping")
    return value


def _validate_arm_set(candidate: Mapping[str, Any], expected: Mapping[str, Any]) -> None:
    arms = candidate.get("arms")
    if not isinstance(arms, list) or any(not isinstance(item, Mapping) for item in arms):
        raise PreregCandidateViolation("ARM_SET_MISMATCH: arms must be mappings")
    arm_ids = [item.get("arm_id") for item in arms]
    expected_ids = [item["arm_id"] for item in expected["arms"]]
    if arm_ids != expected_ids:
        raise PreregCandidateViolation("ARM_SET_MISMATCH: expected exact A0/A1/A2/A3")
    if arms != expected["arms"]:
        raise PreregCandidateViolation("ARM_CONTRACT_DRIFT: arm specification changed")


def _validate_scenarios(candidate: Mapping[str, Any], expected: Mapping[str, Any]) -> None:
    protocol = _require_mapping(
        candidate.get("scenario_protocol"), "SCENARIO_SET_MISMATCH"
    )
    families = protocol.get("families")
    if not isinstance(families, list) or any(
        not isinstance(item, Mapping) for item in families
    ):
        raise PreregCandidateViolation("SCENARIO_SET_MISMATCH: invalid families")
    family_ids = [item.get("family") for item in families]
    expected_ids = [
        item["family"] for item in expected["scenario_protocol"]["families"]
    ]
    if family_ids != expected_ids:
        raise PreregCandidateViolation(
            "SCENARIO_SET_MISMATCH: expected all seven frozen families"
        )
    if protocol != expected["scenario_protocol"]:
        raise PreregCandidateViolation(
            "SCENARIO_PROTOCOL_DRIFT: scenario or perturbation contract changed"
        )


def _validate_seed_protocol(
    candidate: Mapping[str, Any], expected: Mapping[str, Any]
) -> None:
    protocol = _require_mapping(
        candidate.get("seed_and_split_protocol"), "SEED_PROTOCOL_DRIFT"
    )
    development = protocol.get("development_seeds")
    held_out = protocol.get("held_out_seeds")
    if not isinstance(development, list) or not isinstance(held_out, list):
        raise PreregCandidateViolation("SEED_PROTOCOL_DRIFT: seeds must be lists")
    if set(development).intersection(held_out):
        raise PreregCandidateViolation(
            "SEED_SPLIT_OVERLAP: development and held-out seeds must be disjoint"
        )
    if protocol != expected["seed_and_split_protocol"]:
        raise PreregCandidateViolation("SEED_PROTOCOL_DRIFT: seed contract changed")


def validate_stage_a_prereg_candidate(
    candidate: Mapping[str, Any],
    *,
    repo_root: Path | None = None,
) -> PreregCandidateReceipt:
    """Validate a candidate without freezing, executing, scoring, or training."""

    if not isinstance(candidate, Mapping):
        raise PreregCandidateViolation("CANDIDATE_SCHEMA: expected mapping")
    forbidden = sorted(_FORBIDDEN_RESULT_FIELDS.intersection(candidate))
    if forbidden:
        raise PreregCandidateViolation(
            "FORBIDDEN_RESULT_FIELD: " + ",".join(forbidden)
        )
    root = (repo_root or _default_repo_root()).resolve()
    expected = build_stage_a_prereg_candidate(root)
    if set(candidate) != set(expected):
        raise PreregCandidateViolation("CANDIDATE_SCHEMA: top-level fields drifted")
    if candidate.get("status") != _STATUS_BOUNDARY:
        raise PreregCandidateViolation(
            "STATUS_BOUNDARY: candidate must remain NOT_PREREGISTERED/"
            "NOT_FROZEN/NOT_RUN/NO_TRAINING"
        )

    _validate_arm_set(candidate, expected)
    _validate_scenarios(candidate, expected)
    if candidate.get("budgets") != expected["budgets"]:
        raise PreregCandidateViolation("BUDGET_DRIFT: frozen resource schema changed")
    _validate_seed_protocol(candidate, expected)
    if candidate.get("metrics") != expected["metrics"]:
        raise PreregCandidateViolation("METRIC_DRIFT: metric contract changed")
    if candidate.get("missing_and_undefined") != expected["missing_and_undefined"]:
        raise PreregCandidateViolation(
            "MISSING_POLICY_DRIFT: missing or undefined handling changed"
        )

    authority = _require_mapping(
        candidate.get("c7_and_authority"), "AUTHORITY_BOUNDARY"
    )
    if (
        authority.get("candidate_grants_freeze_authority") is not False
        or authority.get("candidate_grants_run_authority") is not False
        or authority.get("candidate_grants_training_authority") is not False
        or authority.get("c7_may_edit_scores") is not False
        or authority.get("c7_may_edit_thresholds") is not False
    ):
        raise PreregCandidateViolation(
            "AUTHORITY_BOUNDARY: candidate cannot grant authority or weaken C7"
        )
    if authority != expected["c7_and_authority"]:
        raise PreregCandidateViolation("AUTHORITY_BOUNDARY: authority contract drifted")

    grammar = _require_mapping(candidate.get("verdict_grammar"), "VERDICT_GRAMMAR")
    if grammar.get("allowed_verdicts") != ["MET", "NOT_MET", "INVALID"]:
        raise PreregCandidateViolation(
            "VERDICT_GRAMMAR: only MET/NOT_MET/INVALID are allowed"
        )
    if grammar != expected["verdict_grammar"]:
        raise PreregCandidateViolation("VERDICT_GRAMMAR: adjudication grammar drifted")

    if candidate.get("source_manifest") != expected["source_manifest"]:
        raise PreregCandidateViolation(
            "SOURCE_MANIFEST_DRIFT: source bytes do not match candidate"
        )
    if candidate != expected:
        raise PreregCandidateViolation(
            "CANDIDATE_DRIFT: candidate differs from the closed generated protocol"
        )

    manifest = candidate["source_manifest"]
    return PreregCandidateReceipt(
        status=CandidateValidationStatus.VALID_CANDIDATE_ONLY,
        candidate_digest=hashlib.sha256(
            canonical_candidate_json(candidate).encode("utf-8")
        ).hexdigest(),
        source_manifest_digest=_digest_json(manifest),
        checked_source_files=len(manifest),
    )


def _closed_json_loads(raw: str) -> Mapping[str, Any]:
    def reject_duplicates(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
        rendered: dict[str, Any] = {}
        for key, value in pairs:
            if key in rendered:
                raise PreregCandidateViolation(
                    f"CANDIDATE_SCHEMA: duplicate JSON key {key}"
                )
            rendered[key] = value
        return rendered

    try:
        loaded = json.loads(raw, object_pairs_hook=reject_duplicates)
    except json.JSONDecodeError as exc:
        raise PreregCandidateViolation(f"CANDIDATE_SCHEMA: {exc}") from exc
    return _require_mapping(loaded, "CANDIDATE_SCHEMA")


def validate_stage_a_prereg_candidate_file(
    path: Path,
    *,
    repo_root: Path | None = None,
) -> PreregCandidateReceipt:
    root = (repo_root or _default_repo_root()).resolve()
    raw = path.read_text(encoding="utf-8")
    candidate = _closed_json_loads(raw)
    canonical_bytes = canonical_candidate_json(candidate) + "\n"
    if raw != canonical_bytes:
        raise PreregCandidateViolation(
            "CANDIDATE_BYTES_DRIFT: file must be canonical JSON plus one newline"
        )
    return validate_stage_a_prereg_candidate(candidate, repo_root=root)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render or validate the non-authorizing Stage-A prereg candidate."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", type=Path)
    mode.add_argument("--render", action="store_true")
    args = parser.parse_args(argv)
    root = _default_repo_root()
    if args.render:
        print(canonical_candidate_json(build_stage_a_prereg_candidate(root)))
        return 0
    path = args.check or (root / DEFAULT_CANDIDATE_RELATIVE_PATH)
    receipt = validate_stage_a_prereg_candidate_file(path, repo_root=root)
    print(json.dumps(receipt.to_mapping(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
