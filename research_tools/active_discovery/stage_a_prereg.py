from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from .canonical import content_digest
from .families.manifest import FamilyCode
from .families.unified import UnifiedFamilyAdapter


STAGE_A_PREREG_SCHEMA = "active-discovery-stage-a-prereg-candidate/v1"
EXPERIMENT_ID = "R-ACTIVE-DISCOVERY-1-STAGE-A"
APPROVED_MECHANISM_BASE = "fa9314ea8cd84c1ea33615d4382c5c5da7b74651"
PROBE_BUDGET_UNITS = 4
RANDOM_ARM_SEED = 1701
FAMILY_ALLOCATION = (
    (FamilyCode.F1, "QUALIFICATION_FAMILY", 101, 1009),
    (FamilyCode.F2, "QUALIFICATION_FAMILY", 103, 1013),
    (FamilyCode.F3, "QUALIFICATION_FAMILY", 107, 1019),
    (FamilyCode.F4, "HELD_OUT_FAMILY", None, 1021),
)
SOURCE_PATHS = (
    "research_tools/active_discovery/arm_runner.py",
    "research_tools/active_discovery/budget.py",
    "research_tools/active_discovery/canonical.py",
    "research_tools/active_discovery/catalogue.py",
    "research_tools/active_discovery/contracts.py",
    "research_tools/active_discovery/families/manifest.py",
    "research_tools/active_discovery/families/opaque_cli.py",
    "research_tools/active_discovery/families/opaque_expiry.py",
    "research_tools/active_discovery/families/opaque_graph.py",
    "research_tools/active_discovery/families/opaque_quota.py",
    "research_tools/active_discovery/families/unified.py",
    "research_tools/active_discovery/referee.py",
    "research_tools/active_discovery/selector.py",
    "research_tools/active_discovery/stage_a_prereg.py",
)
FORBIDDEN_ACTOR_TERMS = (
    "family_code",
    "manifest",
    "hidden_configuration",
    "source_precedence",
    "repeat_mode",
    "unknown_mode",
    "empty_is_missing",
    "atomic_on_error",
    "opaquecli",
    "lifetime_steps",
    "refresh_on_write",
    "expires_at_boundary",
    "opaqueexpiry",
    "capacity_units",
    "refill_per_step",
    "refill_before_request",
    "deny_consumes",
    "opaquequota",
    "directed",
    "remove_missing_error",
    "allow_self_loop",
    "opaquegraph",
)
VERDICT_GRAMMAR = (
    "QUALIFIED_FOR_NEXT_SCORING_SPEC",
    "REVISE",
    "INVALID_LEAKAGE",
    "INVALID_HIDDEN_TRUTH_ACCESS",
    "INVALID_MANIFEST_OR_SPLIT",
    "INVALID_SOURCE_DRIFT",
    "INVALID_BUDGET_MISMATCH",
    "INVALID_MISSING_DATA",
    "INVALID_C7_STOP_VIOLATION",
    "STOPPED_NO_VERDICT",
)
TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_version",
        "experiment_id",
        "mode",
        "candidate_state",
        "freeze_state",
        "run_state",
        "evidence_state",
        "authority_state",
        "approved_mechanism_base",
        "family_bindings",
        "family_matrix_digest",
        "arm_bindings",
        "random_arm_seed",
        "hidden_truth_contract",
        "qualification_metrics",
        "missing_data_policy",
        "leakage_policy",
        "c7_stop_policy",
        "verdict_grammar",
        "source_manifest",
        "source_manifest_digest",
        "candidate_digest",
    }
)


class StageAPreregValidationError(ValueError):
    """A Stage-A qualification candidate escaped its closed contract."""


@dataclass(frozen=True, slots=True)
class ValidatedStageAPrereg:
    candidate_digest: str
    source_manifest_digest: str
    family_matrix_digest: str
    candidate_state: str


class StageAQualificationVerdict(str, Enum):
    QUALIFIED_FOR_NEXT_SCORING_SPEC = "QUALIFIED_FOR_NEXT_SCORING_SPEC"
    REVISE = "REVISE"
    INVALID_LEAKAGE = "INVALID_LEAKAGE"
    INVALID_HIDDEN_TRUTH_ACCESS = "INVALID_HIDDEN_TRUTH_ACCESS"
    INVALID_MANIFEST_OR_SPLIT = "INVALID_MANIFEST_OR_SPLIT"
    INVALID_SOURCE_DRIFT = "INVALID_SOURCE_DRIFT"
    INVALID_BUDGET_MISMATCH = "INVALID_BUDGET_MISMATCH"
    INVALID_MISSING_DATA = "INVALID_MISSING_DATA"
    INVALID_C7_STOP_VIOLATION = "INVALID_C7_STOP_VIOLATION"
    STOPPED_NO_VERDICT = "STOPPED_NO_VERDICT"


@dataclass(frozen=True, slots=True)
class QualificationAudit:
    halted: bool = False
    missing_cells: int = 0
    halt_caused_missing_cells: int = 0
    duplicate_cells: int = 0
    extra_cells: int = 0
    leakage_violations: int = 0
    preseal_hidden_truth_accesses: int = 0
    manifest_or_split_violations: int = 0
    source_drift_violations: int = 0
    budget_mismatch_violations: int = 0
    c7_post_stop_accesses: int = 0
    qualification_failures: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.halted, bool):
            raise StageAPreregValidationError("halted must be a boolean")
        for field_name in (
            "missing_cells",
            "halt_caused_missing_cells",
            "duplicate_cells",
            "extra_cells",
            "leakage_violations",
            "preseal_hidden_truth_accesses",
            "manifest_or_split_violations",
            "source_drift_violations",
            "budget_mismatch_violations",
            "c7_post_stop_accesses",
            "qualification_failures",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise StageAPreregValidationError(
                    f"{field_name} must be an integer >= 0"
                )
        if self.halt_caused_missing_cells > self.missing_cells:
            raise StageAPreregValidationError(
                "halt-caused missing cells cannot exceed total missing cells"
            )
        if not self.halted and self.halt_caused_missing_cells:
            raise StageAPreregValidationError(
                "halt-caused missing cells require an observed halt"
            )


def candidate_digest(raw: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in raw.items() if key != "candidate_digest"}
    return content_digest("active-discovery-stage-a-prereg-candidate", payload)


def _manifest_binding(family_code: FamilyCode, seed: int) -> dict[str, Any]:
    manifest = UnifiedFamilyAdapter.build(
        family_code=family_code,
        seed=seed,
        probe_budget_units=PROBE_BUDGET_UNITS,
    ).manifest
    return {
        "manifest": manifest.to_mapping(),
        "manifest_digest": manifest.manifest_digest,
    }


def _family_bindings() -> list[dict[str, Any]]:
    return [
        {
            "family_code": family_code.value,
            "family_role": family_role,
            "qualification_manifest": (
                None
                if qualification_seed is None
                else _manifest_binding(family_code, qualification_seed)
            ),
            "evaluation_manifest": _manifest_binding(family_code, evaluation_seed),
        }
        for (
            family_code,
            family_role,
            qualification_seed,
            evaluation_seed,
        ) in FAMILY_ALLOCATION
    ]


def _source_manifest(repo_root: Path) -> list[dict[str, str]]:
    manifest: list[dict[str, str]] = []
    for relative_path in SOURCE_PATHS:
        source_path = repo_root / relative_path
        if not source_path.is_file():
            raise StageAPreregValidationError(
                f"required source file is missing: {relative_path}"
            )
        manifest.append(
            {
                "path": relative_path,
                "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
            }
        )
    return manifest


def build_stage_a_candidate(repo_root: Path) -> dict[str, Any]:
    family_bindings = _family_bindings()
    family_matrix_digest = content_digest(
        "active-discovery-stage-a-family-matrix",
        [
            {
                "family_code": row["family_code"],
                "family_role": row["family_role"],
                "evaluation_manifest_digest": row["evaluation_manifest"][
                    "manifest_digest"
                ],
            }
            for row in family_bindings
        ],
    )
    source_manifest = _source_manifest(repo_root)
    source_manifest_digest = content_digest(
        "active-discovery-stage-a-source-manifest", source_manifest
    )
    family_commitments = [
        {
            "family_code": row["family_code"],
            "evaluation_manifest_digest": row["evaluation_manifest"]["manifest_digest"],
            "hidden_configuration_digest": row["evaluation_manifest"]["manifest"][
                "hidden_configuration_digest"
            ],
        }
        for row in family_bindings
    ]
    candidate: dict[str, Any] = {
        "schema_version": STAGE_A_PREREG_SCHEMA,
        "experiment_id": EXPERIMENT_ID,
        "mode": "NOT_EVIDENCE",
        "candidate_state": "FREEZE_READY_CANDIDATE",
        "freeze_state": "NOT_FROZEN",
        "run_state": "NOT_RUN",
        "evidence_state": "NOT_EVIDENCE",
        "authority_state": "VALIDATION_ONLY",
        "approved_mechanism_base": APPROVED_MECHANISM_BASE,
        "family_bindings": family_bindings,
        "family_matrix_digest": family_matrix_digest,
        "arm_bindings": [
            {
                "arm_kind": arm_kind,
                "budget_units": PROBE_BUDGET_UNITS,
                "family_matrix_digest": family_matrix_digest,
            }
            for arm_kind in ("SYSTEMATIC", "RANDOM", "VOI")
        ],
        "random_arm_seed": RANDOM_ARM_SEED,
        "hidden_truth_contract": {
            "access_policy": "REFEREE_ONLY_AFTER_TRANSCRIPT_SEAL",
            "committed_family_count": 4,
            "seal_digest": content_digest(
                "active-discovery-stage-a-hidden-truth-seal",
                {
                    "source_manifest_digest": source_manifest_digest,
                    "family_commitments": family_commitments,
                },
            ),
        },
        "qualification_metrics": {
            "metric_scope": "INSTRUMENT_INTEGRITY_ONLY",
            "expected_evaluation_cells": 12,
            "required_complete_sealed_receipts": 12,
            "required_exact_budget_receipts": 12,
            "maximum_preseal_hidden_truth_accesses": 0,
            "maximum_leakage_violations": 0,
            "maximum_c7_post_stop_adapter_accesses": 0,
            "scientific_arm_comparison": "FORBIDDEN",
        },
        "missing_data_policy": {
            "expected_cell_count": 12,
            "imputation": "FORBIDDEN",
            "arm_or_family_drop": "FORBIDDEN",
            "duplicate_cell_action": "INVALID_MISSING_DATA",
            "extra_cell_action": "INVALID_MISSING_DATA",
            "non_halt_missing_cell_action": "INVALID_MISSING_DATA",
            "clean_halt_missing_cell_action": "STOPPED_NO_VERDICT",
        },
        "leakage_policy": {
            "actor_surface_violation_verdict": "INVALID_LEAKAGE",
            "preseal_hidden_truth_verdict": "INVALID_HIDDEN_TRUTH_ACCESS",
            "forbidden_actor_channels": [
                "SOURCE_IDENTITY",
                "VERSION_LABEL",
                "FAMILY_IDENTITY",
                "HIDDEN_TEST",
                "REFEREE_SCORE",
                "ORACLE_OUTPUT",
                "MANIFEST_OR_SEAL_PAYLOAD",
            ],
            "forbidden_actor_terms": list(FORBIDDEN_ACTOR_TERMS),
        },
        "c7_stop_policy": {
            "halt_check": "BEFORE_DYNAMIC_ADAPTER_STATE_OR_EXECUTE",
            "post_halt_adapter_access_limit": 0,
            "clean_halt_verdict": "STOPPED_NO_VERDICT",
            "halt_after_integrity_violation": "PRESERVE_INVALID",
            "partial_verdict": "FORBIDDEN",
        },
        "verdict_grammar": list(VERDICT_GRAMMAR),
        "source_manifest": source_manifest,
        "source_manifest_digest": source_manifest_digest,
    }
    candidate["candidate_digest"] = candidate_digest(candidate)
    return candidate


def _validate_source_manifest(raw: Mapping[str, Any], repo_root: Path) -> None:
    manifest = raw.get("source_manifest")
    if not isinstance(manifest, list):
        raise StageAPreregValidationError("source_manifest must be a list")
    paths: list[str] = []
    for row in manifest:
        if not isinstance(row, dict) or set(row) != {"path", "sha256"}:
            raise StageAPreregValidationError("source manifest row is not closed")
        relative_path = row["path"]
        source_digest = row["sha256"]
        if not isinstance(relative_path, str) or not isinstance(source_digest, str):
            raise StageAPreregValidationError("source manifest row types are invalid")
        paths.append(relative_path)
        source_path = repo_root / relative_path
        if not source_path.is_file():
            raise StageAPreregValidationError(
                f"source drift: missing file {relative_path}"
            )
        actual_digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
        if actual_digest != source_digest:
            raise StageAPreregValidationError(
                f"source drift: digest mismatch for {relative_path}"
            )
    if tuple(paths) != SOURCE_PATHS:
        raise StageAPreregValidationError("source drift: path set or order changed")
    expected_manifest_digest = content_digest(
        "active-discovery-stage-a-source-manifest", manifest
    )
    if raw.get("source_manifest_digest") != expected_manifest_digest:
        raise StageAPreregValidationError("source drift: manifest digest mismatch")


def validate_stage_a_candidate(
    raw: Mapping[str, Any], repo_root: Path
) -> ValidatedStageAPrereg:
    unknown = set(raw) - TOP_LEVEL_FIELDS
    missing = TOP_LEVEL_FIELDS - set(raw)
    if unknown:
        raise StageAPreregValidationError(f"unknown fields: {sorted(unknown)}")
    if missing:
        raise StageAPreregValidationError(f"missing fields: {sorted(missing)}")
    stored_candidate_digest = raw.get("candidate_digest")
    if not isinstance(
        stored_candidate_digest, str
    ) or stored_candidate_digest != candidate_digest(raw):
        raise StageAPreregValidationError("candidate digest mismatch")
    _validate_source_manifest(raw, repo_root)
    expected = build_stage_a_candidate(repo_root)
    if dict(raw) != expected:
        raise StageAPreregValidationError(
            "candidate content does not match deterministic Stage-A contract"
        )
    return ValidatedStageAPrereg(
        candidate_digest=stored_candidate_digest,
        source_manifest_digest=expected["source_manifest_digest"],
        family_matrix_digest=expected["family_matrix_digest"],
        candidate_state=expected["candidate_state"],
    )


def load_stage_a_candidate(path: Path, repo_root: Path) -> ValidatedStageAPrereg:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StageAPreregValidationError("candidate JSON could not be read") from exc
    if not isinstance(raw, dict):
        raise StageAPreregValidationError("candidate JSON must contain an object")
    return validate_stage_a_candidate(raw, repo_root)


def qualification_verdict(
    audit: QualificationAudit,
) -> StageAQualificationVerdict:
    integrity_precedence = (
        (audit.leakage_violations, StageAQualificationVerdict.INVALID_LEAKAGE),
        (
            audit.preseal_hidden_truth_accesses,
            StageAQualificationVerdict.INVALID_HIDDEN_TRUTH_ACCESS,
        ),
        (
            audit.manifest_or_split_violations,
            StageAQualificationVerdict.INVALID_MANIFEST_OR_SPLIT,
        ),
        (
            audit.source_drift_violations,
            StageAQualificationVerdict.INVALID_SOURCE_DRIFT,
        ),
        (
            audit.budget_mismatch_violations,
            StageAQualificationVerdict.INVALID_BUDGET_MISMATCH,
        ),
        (
            audit.c7_post_stop_accesses,
            StageAQualificationVerdict.INVALID_C7_STOP_VIOLATION,
        ),
    )
    for violation_count, verdict in integrity_precedence:
        if violation_count:
            return verdict
    if (
        audit.halted
        and audit.missing_cells == audit.halt_caused_missing_cells
        and audit.duplicate_cells == 0
        and audit.extra_cells == 0
    ):
        return StageAQualificationVerdict.STOPPED_NO_VERDICT
    if audit.missing_cells or audit.duplicate_cells or audit.extra_cells:
        return StageAQualificationVerdict.INVALID_MISSING_DATA
    if audit.qualification_failures:
        return StageAQualificationVerdict.REVISE
    return StageAQualificationVerdict.QUALIFIED_FOR_NEXT_SCORING_SPEC
