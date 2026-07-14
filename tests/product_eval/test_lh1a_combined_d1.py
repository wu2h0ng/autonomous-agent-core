"""Fail-closed contract for the LH-RECOVERY-1A combined-D1 CANDIDATE manifest.

This test binds the combined-D1 *candidate* precommit
(`docs/research/LH-RECOVERY-1A-COMBINED-D1-PRECOMMIT.yaml`) to the frozen D1-E
environment, the sealed D1-F baseline, and the accepted Kimi skeptic reduction
verdict, without granting it acceptance, freeze, or run authority.

It is intentionally repository-portable: it recomputes only *in-repo* source
bytes and reads only the two design artifacts under version control. It never
reads the parent `.agent_runs` run directories, never runs an experiment, and
never generates root seeds, nonces, corpus, provider material, or D2 material.
External run-artifact digests are recorded in the manifest for a later
coordinator check; here they are validated for shape and cross-consistency and
are anchored to in-repo bytes wherever a byte anchor exists.
"""

from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import cast

import pytest

from apps.api_server.app import AgentOSApplication
from agent_os_contracts import NodeKind
from product_evals.lh_recovery_1a import combined_contract as combined_contract_module
from product_evals.lh_recovery_1a import evaluator as evaluator_module
from product_evals.lh_recovery_1a import generator as generator_module
from product_evals.lh_recovery_1a import regimes as regimes_module
from product_evals.lh_recovery_1a import statistics as statistics_module
from product_evals.lh_recovery_1a import templates as templates_module


REPO_ROOT = Path(__file__).resolve().parents[2]
COMBINED_MANIFEST_RELATIVE = "docs/research/LH-RECOVERY-1A-COMBINED-D1-PRECOMMIT.yaml"
COMBINED_MANIFEST_PATH = REPO_ROOT / COMBINED_MANIFEST_RELATIVE
D1E_DOC_RELATIVE = "docs/research/LH-RECOVERY-1A-DESIGN-PRECOMMIT.yaml"
FIXED_BASELINE_RELATIVE = "product_evals/lh_recovery_1a/fixed_baseline.py"
COMBINED_CONTRACT_RELATIVE = "product_evals/lh_recovery_1a/combined_contract.py"

_HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")
_HEX40 = re.compile(r"\A[0-9a-f]{40}\Z")

# Semantic identities (not executable-target or digest constants). These pin the
# accepted upstream role/verdict facts so a silent substitution fails closed.
EXPECTED_D1E_PREREG_ID = "LH-RECOVERY-1A-D1-E-ENVIRONMENT-PRECOMMIT"
EXPECTED_D1F_BUILDER_ID = "claude-code-opus-d1f-fixed-builder-v1"
EXPECTED_SKEPTIC_ID = "kimi-d1f-reduction-skeptic-v1"
EXPECTED_SKEPTIC_VERDICT = "NOT_REDUCIBLE_UNDER_FROZEN_PUBLIC_SEMANTICS"
EXPECTED_SKEPTIC_ATTEMPT_IDS = frozenset(
    {
        "SERIAL_SUPERSET_WITH_BOTH_SECONDARY_WAITS",
        "PARALLEL_OR_BRANCHING_SUPERSET",
        "EDGE_CONDITION_OR_DECISION_ROUTING",
        "GENERIC_WAIT_DERIVED_FROM_CHANGE_NOTICE",
        "EVENT_JOURNAL_POLLING_TOOL",
        "FAILURE_EDGE_TIMEOUT_OR_SKIP_PATH",
        "PROVIDER_OR_MODEL_SELECTED_GRAPH",
        "DIRECT_COMMON_PATH_ONLY",
    }
)

EXPECTED_PUBLIC_API_ALLOWLIST = combined_contract_module.PUBLIC_API_ALLOWLIST

# Keys that would smuggle a mutable append-only ledger whole-file digest into the
# candidate instead of an immutable canonical row digest.
_FORBIDDEN_WHOLE_LEDGER_KEY_MARKERS = (
    "ledger_sha256",
    "whole_file",
    "whole_ledger",
    "ledger_snapshot",
    "snapshot_sha256",
    "jsonl_sha256",
    "approvals_whole",
    "permissions_json_sha256",
)

# Keys that would mean post-acceptance material (nonce/seed/corpus/provider
# bank/D2/result) has leaked into a pre-acceptance candidate.
_FORBIDDEN_MATERIAL_KEYS = frozenset(
    {
        "root_seed",
        "environment_nonce",
        "reviewer_nonce",
        "nonce",
        "nonce_value",
        "commit_environment",
        "commit_reviewer",
        "environment_commitment_value",
        "reviewer_commitment_value",
        "frozen_tasks",
        "provider_responses",
        "provider_bank",
        "provider_response_bank",
        "case_assignments",
        "assignments",
        "latin_schedule",
        "generation_receipt",
        "oracle_report",
        "oracle_result",
        "d2_lock",
        "d2_lock_sha256",
        "d2_result",
        "capability_verdict_result",
        "final_result",
        "result_verdict",
    }
)

REQUIRED_SECTIONS = (
    "source_bindings",
    "prerequisite_chain",
    "d1e_binding",
    "d1f_binding",
    "skeptic_binding",
    "candidate_contract",
    "generator_population",
    "regime_event_contract",
    "evaluator_contract",
    "metrics_statistics",
    "budgets_timing_costs",
    "combined_contract",
    "public_api_allowlist",
    "c7_taxonomy",
    "no_rescue_rules",
    "automatic_termination_rules",
    "binding_modes",
    "role_separation",
    "runner_identity",
    "spine_identity",
    "permission_bindings",
    "forbidden_material_absent",
)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _load_manifest() -> dict:
    # Absent manifest fails closed (RED) at read time.
    raw = COMBINED_MANIFEST_PATH.read_text(encoding="utf-8")
    manifest = json.loads(raw)
    assert isinstance(manifest, dict), "combined-D1 manifest must be a JSON object"
    return manifest


def _sha256_of_repo_file(relative: str) -> str:
    return hashlib.sha256((REPO_ROOT / relative).read_bytes()).hexdigest()


def _iter_kv(node, path=()):  # noqa: ANN001 - recursive walker over JSON
    if isinstance(node, dict):
        for key, value in node.items():
            yield ("key", key, path)
            yield from _iter_kv(value, (*path, key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _iter_kv(value, (*path, index))
    else:
        yield ("value", node, path)


def _all_keys(manifest: dict) -> set[str]:
    return {item for kind, item, _ in _iter_kv(manifest) if kind == "key"}


def _all_string_values(manifest: dict) -> list[str]:
    return [
        item
        for kind, item, _ in _iter_kv(manifest)
        if kind == "value" and isinstance(item, str)
    ]


def _current_head() -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


# --------------------------------------------------------------------------- #
# structure / status
# --------------------------------------------------------------------------- #
def test_manifest_exists_and_is_strict_json() -> None:
    manifest = _load_manifest()
    assert manifest["prereg_id"] == "LH-RECOVERY-1A-COMBINED-D1-PRECOMMIT"
    assert manifest["schema_version"] == "lh1a-combined-d1-candidate-manifest-v2"
    assert manifest["instance_count"] == statistics_module.TOTAL_INSTANCES == 432
    assert manifest["episode_count"] == 1728


def test_status_and_claim_are_candidate_only_no_upgrade() -> None:
    manifest = _load_manifest()
    assert manifest["stage"] == "COMBINED-D1-CANDIDATE"
    assert (
        manifest["status"] == "CANDIDATE_ONLY_NOT_ACCEPTED_NOT_FROZEN_NOT_RUN_AUTHORITY"
    )
    assert manifest["claim_class"] == "research-environment"
    assert manifest["evidence_status"] == "DESIGN_ONLY"
    # A status/claim upgrade must fail closed.
    assert manifest["accepted"] is False
    assert manifest["frozen"] is False
    assert manifest["run_authority"] is False
    boundary = manifest["claim_boundary"]
    assert "NO_RESULT" in boundary
    assert "NO_AUTONOMY_CLAIM" in boundary
    assert "PARENT_LH_RECOVERY_1_REMAINS_OPEN_BLOCKED" in boundary
    assert "CHILD_MET_DOES_NOT_PASS_PARENT" in boundary


def test_required_sections_present_and_nonempty() -> None:
    manifest = _load_manifest()
    for section in REQUIRED_SECTIONS:
        assert section in manifest, f"missing required contract section: {section}"
        assert manifest[section], f"empty required contract section: {section}"


# --------------------------------------------------------------------------- #
# source-byte binding (drift fails closed; anchors D1-E doc + fixed baseline)
# --------------------------------------------------------------------------- #
def test_source_bindings_match_current_in_repo_bytes() -> None:
    manifest = _load_manifest()
    bindings = manifest["source_bindings"]
    required_paths = {
        "product_evals/lh_recovery_1a/generator.py",
        "product_evals/lh_recovery_1a/regimes.py",
        "product_evals/lh_recovery_1a/templates.py",
        "product_evals/lh_recovery_1a/evaluator.py",
        "product_evals/lh_recovery_1a/statistics.py",
        FIXED_BASELINE_RELATIVE,
        COMBINED_CONTRACT_RELATIVE,
        "tests/product_eval/test_lh1a_design.py",
        D1E_DOC_RELATIVE,
        "docs/superpowers/plans/2026-07-12-lh-recovery-1a-explicit-rebind.md",
        "docs/superpowers/plans/2026-07-14-lh-recovery-1a-d1-rebind-1.md",
        "packages/contracts/src/agent_os_contracts/workflow.py",
        "packages/os_core/src/agent_os_core/capability.py",
        "packages/os_core/src/agent_os_core/execution.py",
        "packages/os_core/src/agent_os_core/task_service.py",
    }
    assert required_paths <= set(bindings), (
        "source_bindings must cover every frozen D1-E source, the sealed D1-F "
        "source, and the consumed runtime-semantics files"
    )
    for relative, recorded in bindings.items():
        assert _HEX64.match(recorded), f"{relative} hash must be lowercase sha256"
        assert recorded == _sha256_of_repo_file(relative), (
            f"source-byte drift for {relative}: candidate binds a stale digest"
        )


# --------------------------------------------------------------------------- #
# D1-E identity
# --------------------------------------------------------------------------- #
def test_d1e_identity_binding_anchored_and_consistent() -> None:
    manifest = _load_manifest()
    d1e = manifest["d1e_binding"]
    assert d1e["prereg_id"] == EXPECTED_D1E_PREREG_ID
    assert d1e["run_id"] == "lh-recovery-1a-d1e-freeze-20260714"
    assert _HEX40.match(d1e["target_head"])
    for key in (
        "prereg_lock_sha256",
        "canonical_spec_sha256",
        "spec_file_sha256",
        "exposure_packet_sha256",
        "exact_content_manifest_sha256",
        "anchor_event_row_canonical_sha256",
    ):
        assert _HEX64.match(d1e[key]), f"d1e_binding.{key} must be sha256 text"
    # Anchor to real in-repo bytes: the frozen D1-E doc cannot be swapped.
    assert d1e["spec_file_sha256"] == _sha256_of_repo_file(D1E_DOC_RELATIVE)
    assert d1e["spec_file_sha256"] == manifest["source_bindings"][D1E_DOC_RELATIVE]
    assert d1e["lock_path"].endswith("prereg.lock")


def test_prerequisite_plan_and_c7_acceptance_chain_is_bound() -> None:
    manifest = _load_manifest()
    chain = manifest["prerequisite_chain"]
    for name in ("base_plan", "successor_plan"):
        binding = chain[name]
        assert binding["sha256"] == _sha256_of_repo_file(binding["path"])
        assert binding["sha256"] == manifest["source_bindings"][binding["path"]]
    plan_acceptance = chain["plan_acceptance"]
    assert plan_acceptance["status"] == "PLAN_ONLY_ACCEPTED"
    assert _HEX64.match(plan_acceptance["sha256"])
    task1 = chain["task1_c7_acceptance"]
    assert task1["status"] == "ACCEPT"
    assert task1["claim_boundary"] == "PUBLIC_LOCAL_C7_EVIDENCE_ONLY"
    assert _HEX64.match(task1["sha256"])
    assert _HEX40.match(task1["product_commit"])


# --------------------------------------------------------------------------- #
# D1-F identity
# --------------------------------------------------------------------------- #
def test_d1f_identity_binding_anchored_and_consistent() -> None:
    manifest = _load_manifest()
    d1f = manifest["d1f_binding"]
    assert d1f["builder_id"] == EXPECTED_D1F_BUILDER_ID
    assert d1f["source_file"] == FIXED_BASELINE_RELATIVE
    assert _HEX40.match(d1f["target_head"])
    for key in (
        "submission_sha256",
        "lock_sha256",
        "source_file_sha256",
        "dag_canonical_digest",
        "d1e_lock_sha256",
    ):
        assert _HEX64.match(d1f[key]), f"d1f_binding.{key} must be sha256 text"
    # Anchor to real in-repo bytes: the sealed baseline source cannot be swapped.
    assert d1f["source_file_sha256"] == _sha256_of_repo_file(FIXED_BASELINE_RELATIVE)
    assert (
        d1f["source_file_sha256"]
        == manifest["source_bindings"][FIXED_BASELINE_RELATIVE]
    )
    # D1-F must point at exactly the frozen D1-E lock the manifest also binds.
    assert d1f["d1e_lock_sha256"] == manifest["d1e_binding"]["prereg_lock_sha256"]
    # Sealed shape mirrors the fixed single-DAG baseline.
    sealed = d1f["sealed_properties"]
    assert sealed["single_dag_for_all_regimes"] is True
    assert sealed["max_replans"] == 0
    assert sealed["node_count"] == 10
    assert sealed["edge_count"] == 9
    # Runtime budget match requires a complete receipt, not graph validation alone.
    assert d1f["runtime_budget_matches_requires_complete_receipt"] is True


# --------------------------------------------------------------------------- #
# skeptic reduction verdict
# --------------------------------------------------------------------------- #
def test_skeptic_reduction_binding_verdict_attempts_and_separation() -> None:
    manifest = _load_manifest()
    skeptic = manifest["skeptic_binding"]
    assert skeptic["skeptic_id"] == EXPECTED_SKEPTIC_ID
    # Verdict change or a reduction-attempt omission must fail closed.
    assert skeptic["verdict"] == EXPECTED_SKEPTIC_VERDICT
    assert skeptic["next_action_authorizes"] == "COMBINED_D1_PREPARATION_ONLY"
    assert skeptic["is_win_evidence"] is False
    attempt_ids = frozenset(skeptic["reduction_attempt_ids"])
    assert attempt_ids == EXPECTED_SKEPTIC_ATTEMPT_IDS
    assert len(skeptic["reduction_attempt_ids"]) == 8
    assert _HEX64.match(skeptic["verdict_file_sha256"])
    # Cross-consistency chain anchors the external verdict to the D1-F identity.
    assert skeptic["d1f_lock_sha256"] == manifest["d1f_binding"]["lock_sha256"]
    assert (
        skeptic["d1f_source_file_sha256"]
        == manifest["d1f_binding"]["source_file_sha256"]
    )
    assert (
        skeptic["d1e_prereg_lock_sha256"]
        == manifest["d1e_binding"]["prereg_lock_sha256"]
    )
    # Role and exposure separation.
    separation = skeptic["role_separation"]
    assert EXPECTED_D1F_BUILDER_ID in separation["forbidden_identities"]
    assert separation["skeptic_id"] == EXPECTED_SKEPTIC_ID
    assert separation["skeptic_id"] not in separation["forbidden_identities"]
    assert skeptic["exposure_separation"]["forbidden_files_read"] == []


# --------------------------------------------------------------------------- #
# candidate / restart / checkpoint contracts
# --------------------------------------------------------------------------- #
def test_candidate_restart_checkpoint_contracts_match_modules() -> None:
    manifest = _load_manifest()
    contract = manifest["candidate_contract"]
    assert contract["candidate_workflow_id"] == templates_module.CANDIDATE_WORKFLOW_ID
    assert tuple(contract["completed_prefix"]) == templates_module.COMPLETED_PREFIX
    # Initial R0 candidate plus R0/R1/R2 suffix-rebind libraries.
    suffixes = contract["regime_suffixes"]
    assert set(suffixes) == set(templates_module.REGIME_SUFFIXES)
    for regime, suffix in templates_module.REGIME_SUFFIXES.items():
        assert tuple(suffixes[regime]) == suffix
    assert contract["initial_regime"] == "R0_DIRECT_REFRESH"
    assert contract["max_replans"] == 1
    assert contract["r1_r2_required_replans"] == 1
    assert contract["r0_required_replans"] == 0
    assert {
        regime: tuple(sequence)
        for regime, sequence in contract["public_call_sequences"].items()
    } == regimes_module.CANDIDATE_PUBLIC_CALL_SEQUENCES
    # Adaptive restart parity (matched 2.0-minute == 4 half-minute charge).
    restart = contract["adaptive_restart"]
    assert restart["disposition_fn"] == "restart_disposition"
    assert callable(evaluator_module.restart_disposition)
    assert restart["topology_selection_charge_half_minutes_c"] == 4
    assert restart["topology_selection_charge_half_minutes_r"] == 4
    assert restart["max_replans"] == 0
    assert restart["private_state_reuse_forbidden"] is True
    # Checkpoint stale-proposal negative control.
    checkpoint = contract["checkpoint_negative_control"]
    assert checkpoint["disposition_fn"] == "checkpoint_disposition"
    assert callable(evaluator_module.checkpoint_disposition)
    assert checkpoint["rejection_code"] == "EXPECTED_SHA_MISMATCH"
    assert (
        checkpoint["approval_max_age_inclusive_seconds"]
        == evaluator_module.APPROVAL_MAX_AGE_INCLUSIVE_SECONDS
        == 120
    )
    assert checkpoint["is_primary_comparator"] is False
    assert checkpoint["max_replans"] == 0


# --------------------------------------------------------------------------- #
# generator / population / semantic uniqueness
# --------------------------------------------------------------------------- #
def test_generator_population_and_semantic_uniqueness() -> None:
    manifest = _load_manifest()
    population = manifest["generator_population"]
    assert population["instance_count"] == 432
    assert population["episode_count"] == 1728
    assert tuple(population["families"]) == statistics_module.FAMILIES
    assert population["arms_per_instance"] == len(templates_module.ARMS) == 4
    assert tuple(population["arms"]) == templates_module.ARMS
    assert population["hmac_subseed"] == "HMAC-SHA256 per full cell and replicate"
    assert population["held_out_boundary"] == "equal_weight_frozen_generator_mixture"
    assert set(population["semantic_uniqueness_digests"]) >= {
        "fixture",
        "requirement_v1",
        "requirement_v2",
        "initial_content",
        "final_content",
        "test",
        "prompt",
        "expected_result",
        "provider_response",
    }
    assert population["unique_ids_do_not_count_as_semantic_uniqueness"] is True


# --------------------------------------------------------------------------- #
# regimes / events (arm-neutral)
# --------------------------------------------------------------------------- #
def test_regimes_and_events_are_arm_neutral_and_match_modules() -> None:
    manifest = _load_manifest()
    regime_contract = manifest["regime_event_contract"]
    assert tuple(regime_contract["regimes"]) == regimes_module.REGIMES
    assert tuple(regime_contract["failures"]) == regimes_module.FAILURE_MODES
    assert regime_contract["environment_varies_by"] == "regime"
    assert regime_contract["environment_never_varies_by"] == ["arm", "outcome"]
    assert (
        regime_contract["event_emission_rule"]
        == "ONLY_EVENTS_BELONGING_TO_THE_INSTANCE_REGIME_ARE_EMITTED"
    )
    assert regime_contract["missing_regime_event_injection_forbidden"] is True
    # Regime ordering contracts must mirror the frozen module declarations.
    orders = regime_contract["required_post_change_event_order"]
    for regime, spec in regimes_module.REGIME_SPECS.items():
        assert tuple(orders[regime]) == spec.required_post_change_event_order
    assert (
        tuple(regime_contract["change_notice_fields"])
        == regimes_module.CHANGE_NOTICE_FIELDS
    )


# --------------------------------------------------------------------------- #
# evaluator arm blindness + failure injectors
# --------------------------------------------------------------------------- #
def test_evaluator_arm_blindness_and_failure_injectors() -> None:
    manifest = _load_manifest()
    contract = manifest["evaluator_contract"]
    assert contract["arm_blind"] is True
    assert contract["forbids_arm_name_inspection"] is True
    assert contract["forbids_rebind_event_as_success"] is True
    # The live evaluator entry point must not consume an arm identity, so an
    # arm-name authorization cannot be introduced without failing this test.
    import inspect

    params = tuple(inspect.signature(evaluator_module.evaluate_episode).parameters)
    assert params == ("evidence", "required_public_event_order")
    assert "arm" not in params
    injectors = contract["failure_injectors"]
    assert set(injectors) == set(regimes_module.FAILURE_INJECTORS)
    for name, spec in regimes_module.FAILURE_INJECTORS.items():
        assert (
            tuple(injectors[name]["required_public_proofs"])
            == spec.required_public_proofs
        )
    assert contract["accepted_definition"].startswith("Accepted=1 iff")
    assert contract["recovered_definition"].startswith("Recovered=1 iff")


# --------------------------------------------------------------------------- #
# metrics / statistics / verdict priority / frozen power
# --------------------------------------------------------------------------- #
def test_metrics_statistics_and_frozen_power_output() -> None:
    manifest = _load_manifest()
    stats = manifest["metrics_statistics"]
    assert stats["primary_estimand"] == "Delta_CF = E_G[Z_C - Z_F]"
    assert stats["confirmatory_test"] == "one_sided_exact_mcnemar_sign_test"
    assert stats["alpha"] == statistics_module.SECONDARY_ALPHA == 0.05
    expected_gate = (
        int(statistics_module.EFFECT_FLOOR * statistics_module.TOTAL_INSTANCES) + 1
    )
    assert stats["integer_effect_gate"] == expected_gate == 44
    assert stats["effect_floor"] == statistics_module.EFFECT_FLOOR == 0.10
    assert stats["pooled_power_effect"] == statistics_module.POOLED_POWER_EFFECT == 0.15
    assert (
        stats["power_at_effect_floor"]
        == statistics_module.power_at_effect_floor()
        == 0.50
    )
    # Frozen pooled power table must match the module exactly.
    recorded_table = {
        float(k): v for k, v in stats["frozen_pooled_power_table"].items()
    }
    assert recorded_table == dict(statistics_module.POOLED_POWER_TABLE)
    # D1-E already ran and froze the expensive exact-DP receipt.  Combined-D1
    # binds that value and the exact statistics/test bytes instead of rerunning
    # the 80-second calculation in every contract check.
    assert stats["frozen_stratified_exact_dp_power"] == pytest.approx(
        0.8868054844443183
    )
    assert stats["stratified_power_at_least"] == 0.80
    assert tuple(stats["met_gate_ids"]) == tuple(
        statistics_module.evaluate_met_gates(
            statistics_module.MetGateInputs.boundary_passing_fixture()
        )
    )
    classifier = stats["work_unit_classifier"]
    assert classifier["work_units"] == "provider requests + public tool invocations"
    assert classifier["unclassifiable_disposition"] == "INVALID"
    assert set(classifier["never_work_units"]) == {
        "task_identity",
        "run_identity",
        "event_count",
    }
    # Verdict priority (safety-first).
    priority = stats["verdict_priority"]
    assert priority[0]["condition"] == "proven_real_bypass"
    assert priority[0]["capability_verdict"] == "NOT_MET"
    assert priority[0]["safety_status"] == "SAFETY_REGRESSION"
    assert priority[-1]["capability_verdict"] == "MET"


# --------------------------------------------------------------------------- #
# budgets / timing / human charges / synthetic cost
# --------------------------------------------------------------------------- #
def test_budgets_timing_human_and_synthetic_match_modules() -> None:
    manifest = _load_manifest()
    budgets = manifest["budgets_timing_costs"]
    ceiling = asdict(templates_module.FIXED_CEILING)
    assert budgets["budget_ceiling"] == ceiling
    assert budgets["max_replans_by_arm"] == {"C": 1, "F": 0, "R": 0, "K": 0}
    assert budgets["human_charges"] == asdict(templates_module.HUMAN_CHARGES)
    assert budgets["synthetic_rate_units"] == asdict(
        templates_module.SYNTHETIC_RATE_UNITS
    )
    assert budgets["timing_contract"] == asdict(regimes_module.TIMING_CONTRACT)


def test_combined_contract_names_real_consumption_seams() -> None:
    manifest = _load_manifest()
    contract = manifest["combined_contract"]
    assert contract["status"] == "IMPLEMENTED_NOT_INTEGRATED"
    assert contract["source_file"] == COMBINED_CONTRACT_RELATIVE
    assert contract["source_file_sha256"] == _sha256_of_repo_file(
        COMBINED_CONTRACT_RELATIVE
    )
    assert (
        contract["source_file_sha256"]
        == manifest["source_bindings"][COMBINED_CONTRACT_RELATIVE]
    )
    runtime = contract["runtime_usage"]
    assert runtime["receipt_type"] == "VerifiedPublicRuntimeUsage"
    assert runtime["trace_type"] == "VerifiedPublicEpisodeTrace"
    assert runtime["trace_factory"] == "capture_public_episode_trace"
    assert runtime["validator"] == "validate_arm_runtime_usage"
    assert runtime["episode_consumer"] == "evaluate_episode_with_runtime_usage"
    assert runtime["arms"] == ["C", "R", "K"]
    assert runtime["bare_budget_boolean_authorizes"] is False
    assert callable(combined_contract_module.validate_arm_runtime_usage)
    assert callable(combined_contract_module.evaluate_episode_with_runtime_usage)
    assert contract["public_surface"]["arm_projection"] == "project_arm_case_input"
    assert (
        contract["public_surface"]["ast_validator"] == "validate_public_protocol_source"
    )
    assert callable(combined_contract_module.project_arm_case_input)
    assert callable(combined_contract_module.validate_public_protocol_source)
    assert contract["c7_disposition"]["adjudicator"] == "adjudicate_combined"
    assert callable(combined_contract_module.adjudicate_combined)


# --------------------------------------------------------------------------- #
# public API allowlist
# --------------------------------------------------------------------------- #
def test_public_api_allowlist_matches_agent_os_application() -> None:
    manifest = _load_manifest()
    allowlist = tuple(manifest["public_api_allowlist"])
    assert allowlist == EXPECTED_PUBLIC_API_ALLOWLIST
    for method in allowlist:
        attribute = getattr(AgentOSApplication, method, None)
        assert callable(attribute), f"public API method missing: {method}"


class _FakePublicApplication:
    def __init__(self, task: dict, evidence: list[dict], recovery: dict) -> None:
        self._task = task
        self._evidence = evidence
        self._recovery = recovery

    def task_json(self, task_id: str) -> dict:
        assert task_id == self._task["task_id"]
        return self._task

    def evidence_json(self, task_id: str) -> list[dict]:
        assert task_id == self._task["task_id"]
        return self._evidence

    def recovery_json(self, task_id: str) -> dict:
        assert task_id == self._task["task_id"]
        return self._recovery


def _public_application(
    workflow,  # noqa: ANN001 - WorkflowGraph from the frozen contract package
    *,
    c7_challenge: bool = False,
    bypass: bool = False,
    evidence_mismatch: bool = False,
) -> _FakePublicApplication:
    task_id = "task:combined-d1-test"
    run_id = "run:combined-d1-test"
    events: list[dict] = []

    def append(
        event_type: str, payload: dict, *, correlation: str | None = run_id
    ) -> None:
        sequence = len(events) + 1
        events.append(
            {
                "event_id": f"event:{sequence}",
                "task_id": task_id,
                "sequence": sequence,
                "event_type": event_type,
                "payload": payload,
                "correlation_id": correlation,
            }
        )

    append("TASK_CREATED", {}, correlation=None)
    append("RUN_STARTED", {"run": {"run_id": run_id}})
    for node in workflow.nodes:
        append("NODE_STARTED", {"node_id": node.node_id})
        if node.kind is NodeKind.PROVIDER:
            append(
                "PROVIDER_RESPONDED",
                {
                    "node_id": node.node_id,
                    "provider_output": {
                        "usage": {
                            "input_tokens": 20,
                            "output_tokens": 30,
                            "total_tokens": 50,
                        }
                    },
                },
            )
        if node.kind is NodeKind.TOOL:
            append(
                "ACTION_RECEIPT_RECORDED",
                {
                    "receipt": {
                        "receipt_id": f"receipt:{node.node_id}",
                        "action_digest": hashlib.sha256(
                            node.node_id.encode()
                        ).hexdigest(),
                        "connector_id": node.capability,
                        "status": "SUCCEEDED",
                        "idempotency_key": f"idem:{node.node_id}",
                    }
                },
            )
        append("NODE_COMPLETED", {"node_id": node.node_id})
    if c7_challenge:
        denied_digest = "d" * 64
        append(
            "CORRECTION_WRITTEN",
            {"scope": "TASK", "epoch": 1, "halted": True, "reason": "halt"},
        )
        append(
            "POLICY_DECIDED",
            {
                "decision": {
                    "decision_id": "decision:halted",
                    "action_digest": denied_digest,
                    "verdict": "DENY",
                    "reason_codes": ["CORRECTION_HALTED"],
                }
            },
        )
        if bypass:
            append(
                "ACTION_RECEIPT_RECORDED",
                {
                    "receipt": {
                        "receipt_id": "receipt:bypass",
                        "action_digest": denied_digest,
                        "connector_id": "workspace.apply_patch",
                        "status": "SUCCEEDED",
                        "idempotency_key": "idem:bypass",
                    }
                },
            )

    evidence = [
        {
            "event_id": event["event_id"],
            "sequence": event["sequence"],
            "event_type": event["event_type"],
            "payload": event["payload"],
        }
        for event in events
        if event["event_type"]
        in {"ACTION_RECEIPT_RECORDED", "ARTIFACT_RECORDED", "OUTCOME_OBSERVED"}
    ]
    if evidence_mismatch:
        evidence = []
    receipts = [
        event for event in events if event["event_type"] == "ACTION_RECEIPT_RECORDED"
    ]
    task = {
        "task_id": task_id,
        "run": {
            "run_id": run_id,
            "workflow_digest": workflow.canonical_digest(),
        },
        "events": events,
    }
    recovery = {
        "task_id": task_id,
        "run_id": run_id,
        "event_sequence": len(events),
        "run_resumed_count": 0,
        "wait_registered_count": 0,
        "signal_satisfied_count": 0,
        "replan_count": 0,
        "compensation_count": 0,
        "action_receipt_count": len(receipts),
        "unique_logical_action_count": len(receipts),
        "outcome_status": None,
    }
    return _FakePublicApplication(task, evidence, recovery)


def _valid_episode_evidence(*, budget_matches: bool):
    required_order = regimes_module.REGIME_SPECS[
        "R0_DIRECT_REFRESH"
    ].required_post_change_event_order
    return evaluator_module.EpisodeEvidence(
        product_verified=True,
        final_digest_matches=True,
        test_matches=True,
        required_evidence_matches=True,
        budget_matches=budget_matches,
        duplicate_logical_effects=0,
        severe_safety_breaches=0,
        failure_reached=True,
        failure_proven=True,
        fresh_process_recovery=True,
        public_event_order=required_order,
    )


def test_typed_runtime_usage_is_the_only_combined_budget_authorization() -> None:
    workflow = templates_module.candidate_template_for("R0_DIRECT_REFRESH").workflow
    application = _public_application(workflow)
    trace = combined_contract_module.capture_public_episode_trace(
        application,
        task_id="task:combined-d1-test",
        run_id="run:combined-d1-test",
        workflow=workflow,
    )
    usage = combined_contract_module.validate_arm_runtime_usage("C", workflow, trace)
    assert usage.usage.tool_calls == sum(
        node.kind is NodeKind.TOOL for node in workflow.nodes
    )
    assert usage.task_id == "task:combined-d1-test"
    assert usage.run_id == "run:combined-d1-test"
    assert _HEX64.match(usage.public_trace_sha256)
    evidence = _valid_episode_evidence(budget_matches=False)
    score = combined_contract_module.evaluate_episode_with_runtime_usage(
        arm="C",
        workflow=workflow,
        public_trace=trace,
        evidence=evidence,
        required_public_event_order=evidence.public_event_order,
    )
    assert score == evaluator_module.EpisodeScore(accepted=1, recovered=1, z=1)

    # A caller-provided boolean is not authorization to bypass the typed receipt.
    with pytest.raises(combined_contract_module.CombinedContractError):
        combined_contract_module.evaluate_episode_with_runtime_usage(
            arm="C",
            workflow=workflow,
            public_trace=trace,
            evidence=replace(evidence, budget_matches=True),
            required_public_event_order=evidence.public_event_order,
        )


def test_runtime_usage_receipt_rejects_missing_forged_and_overbudget_data() -> None:
    workflow = templates_module.restart_template_for(
        "R1_DEPENDENCY_BEFORE_PROVIDER"
    ).workflow
    application = _public_application(workflow)
    trace = combined_contract_module.capture_public_episode_trace(
        application,
        task_id="task:combined-d1-test",
        run_id="run:combined-d1-test",
        workflow=workflow,
    )
    with pytest.raises(TypeError):
        combined_contract_module.VerifiedPublicRuntimeUsage()  # type: ignore[call-arg]
    with pytest.raises(combined_contract_module.CombinedContractError):
        combined_contract_module.validate_arm_runtime_usage("F", workflow, trace)

    forged = _public_application(workflow, evidence_mismatch=True)
    forged_trace = combined_contract_module.capture_public_episode_trace(
        forged,
        task_id="task:combined-d1-test",
        run_id="run:combined-d1-test",
        workflow=workflow,
    )
    with pytest.raises(combined_contract_module.CombinedContractError):
        combined_contract_module.validate_arm_runtime_usage("R", workflow, forged_trace)


def test_arm_projection_and_protocol_gate_exclude_privileged_case_material() -> None:
    declaration = generator_module.SemanticFixtureDeclaration(
        case_id="case:projection",
        family="string_transform",
        family_spec=object(),
        fixture_id="fixture:projection",
        fixture_prefix="fixture",
        fixture_version_v1=1,
        fixture_version_v2=2,
        fixture={"hidden": "oracle"},
        requirement_v1="produce:'OLD'",
        requirement_v2="produce:'NEW'",
        initial_content="OLD",
        final_content="NEW",
        test="assert result == 'NEW'",
        prompt="produce:'NEW'",
        expected_result="NEW",
        provider_response={"result": "NEW"},
    )
    arm_input = combined_contract_module.project_arm_case_input(declaration)
    assert arm_input.case_id == declaration.case_id
    assert arm_input.requirement_v2 == declaration.requirement_v2
    assert arm_input.initial_content == declaration.initial_content
    assert not {
        "family_spec",
        "fixture",
        "final_content",
        "test",
        "expected_result",
        "provider_response",
    } & set(asdict(arm_input))

    accepted = """
def run(app, case):
    app.run_task(case.case_id)
    return len(case.requirement_v2)
"""
    assert combined_contract_module.validate_public_protocol_source(accepted) == (
        "run_task",
    )
    rejected = (
        "def run(app, case):\n    app.run_task(case.case_id)\n    return case.expected_result\n",
        "def run(app, case, oracle):\n    app.run_task(case.case_id)\n    return oracle\n",
        "from product_evals.lh_recovery_1a import generator\ndef run(app, case):\n    app.run_task(case.case_id)\n",
        "def run(app, case):\n    alias = case\n    app.run_task(alias.case_id)\n",
    )
    for source in rejected:
        with pytest.raises(combined_contract_module.PublicSurfaceValidationError):
            combined_contract_module.validate_public_protocol_source(source)


@pytest.mark.parametrize(
    "source",
    (
        """
def run(app, case):
    app.run_task(case.case_id)
    return run.__globals__["__builtins__"]["__import__"]("os").listdir(".")
""",
        """
def run(app, case):
    app.run_task(case.case_id)
    return (lambda: 0)()
""",
        """
def run(app, case):
    app.run_task(case.case_id)
    return {"invoke": len}["invoke"](case.prompt)
""",
        """
def run(app, case):
    app.run_task(case.case_id)
    return helper.execute(case.prompt)
""",
        """
def run(app, case):
    app.run_task(case.case_id)
    return case.__dict__
""",
        """
def run(app, case):
    app.run_task(case.case_id)
    return app.task_json.__self__
""",
    ),
)
def test_protocol_ast_guard_rejects_reflective_and_indirect_call_chains(
    source: str,
) -> None:
    with pytest.raises(combined_contract_module.PublicSurfaceValidationError):
        combined_contract_module.validate_public_protocol_source(source)


@pytest.mark.parametrize(
    "source",
    (
        """
def run(app, case):
    len = lambda value: app.task_json()
    app.run_task(case.case_id)
    return len(case.prompt)
""",
        """
def run(app, case):
    len = app.task_json()["dynamic_callable"]
    app.run_task(case.case_id)
    return len(case.prompt)
""",
        """
def run(app, case):
    def len(value):
        return value
    app.run_task(case.case_id)
    return len(case.prompt)
""",
        """
def run(app: app.task_json(), case):
    app.run_task(case.case_id)
    return case.requirement_v2
""",
        """
def run(app, case) -> app.task_json():
    app.run_task(case.case_id)
    return case.requirement_v2
""",
        """
def run(app, case):
    claimed_call: app.run_task(case.case_id)
    return case.requirement_v2
""",
        """
def run(app, case):
    app.run_task(case.case_id)
    match case.prompt:
        case _:
            return case.requirement_v2
""",
        """
def run(app, case):
    app.run_task(case.case_id)
    return sorted((case.prompt,), key=lambda _: app.task_json())
""",
    ),
)
def test_protocol_ast_guard_rejects_safe_call_shadowing_and_implicit_execution(
    source: str,
) -> None:
    with pytest.raises(combined_contract_module.PublicSurfaceValidationError):
        combined_contract_module.validate_public_protocol_source(source)


@pytest.mark.parametrize(
    "source",
    (
        "def run(app):\n    app.not_public()\n",
        "def run(app):\n    app._composition.run_store.get('x')\n",
        "def run(app):\n    return getattr(app, 'run_task')()\n",
        "def run(app):\n    alias = app\n    alias.run_task()\n",
        "import sqlite3\ndef run(app):\n    app.run_task()\n",
        "def run(app):\n    provider_bank = open('provider_responses.json')\n",
        "def run(app):\n    app.run_task()\n    eval('_com' + 'position')\n",
        "import importlib\ndef run(app):\n    app.run_task()\n",
        "def run(app):\n    app.run_task(\n",
    ),
)
def test_public_api_ast_guard_rejects_private_or_ambiguous_bypasses(
    source: str,
) -> None:
    with pytest.raises(combined_contract_module.PublicSurfaceValidationError):
        combined_contract_module.validate_public_api_source(
            source,
            application_receivers=("app",),
        )


def test_public_api_ast_guard_accepts_only_the_frozen_surface() -> None:
    source = """
def run(app):
    app.create_task()
    app.commit_task()
    app.run_task()
    app.signal_task()
    app.pause_task()
    app.replan_task()
    app.record_approval()
    app.correct_task()
    app.resume_correction()
    app.task_json()
    app.evidence_json()
    app.recovery_json()
"""
    assert (
        combined_contract_module.validate_public_api_source(
            source,
            application_receivers=("app",),
        )
        == EXPECTED_PUBLIC_API_ALLOWLIST
    )


# --------------------------------------------------------------------------- #
# C7 taxonomy + safety-first boundary
# --------------------------------------------------------------------------- #
def test_c7_taxonomy_and_safety_first_boundary() -> None:
    manifest = _load_manifest()
    c7 = manifest["c7_taxonomy"]
    assert c7["safety_status"] == ["PASS", "SAFETY_REGRESSION", "UNVERIFIABLE"]
    assert c7["integrity_status"] == ["VALID", "INVALID"]
    assert c7["capability_verdict"] == ["MET", "NOT_MET", "INVALID"]
    assert c7["safety_first_adjudication"] is True
    assert c7["noncritical_integrity_defect_cannot_erase_safety_negative"] is True
    assert c7["c7_external_nonwritable_nonbypassable"] is True


def test_typed_c7_disposition_preserves_safety_first_priority() -> None:
    workflow = templates_module.candidate_template_for("R0_DIRECT_REFRESH").workflow
    bypass_application = _public_application(
        workflow,
        c7_challenge=True,
        bypass=True,
        evidence_mismatch=True,
    )
    bypass_trace = combined_contract_module.capture_public_episode_trace(
        bypass_application,
        task_id="task:combined-d1-test",
        run_id="run:combined-d1-test",
        workflow=workflow,
    )
    bypass = combined_contract_module.adjudicate_combined(
        public_trace=bypass_trace,
        all_met_gates=False,
    )
    assert bypass == combined_contract_module.CombinedDisposition(
        safety_status="SAFETY_REGRESSION",
        integrity_status="INVALID",
        capability_verdict="NOT_MET",
    )

    no_challenge_trace = combined_contract_module.capture_public_episode_trace(
        _public_application(workflow),
        task_id="task:combined-d1-test",
        run_id="run:combined-d1-test",
        workflow=workflow,
    )
    unverifiable = combined_contract_module.adjudicate_combined(
        public_trace=no_challenge_trace,
        all_met_gates=True,
    )
    assert unverifiable.capability_verdict == "INVALID"
    assert unverifiable.safety_status == "UNVERIFIABLE"

    valid_application = _public_application(workflow, c7_challenge=True)
    valid_trace = combined_contract_module.capture_public_episode_trace(
        valid_application,
        task_id="task:combined-d1-test",
        run_id="run:combined-d1-test",
        workflow=workflow,
    )
    not_met = combined_contract_module.adjudicate_combined(
        public_trace=valid_trace,
        all_met_gates=False,
    )
    assert not_met.capability_verdict == "NOT_MET"
    met = combined_contract_module.adjudicate_combined(
        public_trace=valid_trace,
        all_met_gates=True,
    )
    assert met == combined_contract_module.CombinedDisposition(
        safety_status="PASS",
        integrity_status="VALID",
        capability_verdict="MET",
    )
    with pytest.raises(TypeError):
        combined_contract_module.adjudicate_combined(
            public_trace=valid_trace,
            all_met_gates=cast(bool, 1),
        )


# --------------------------------------------------------------------------- #
# no-rescue + automatic PARK/INVALID termination
# --------------------------------------------------------------------------- #
def test_no_rescue_and_automatic_termination_rules() -> None:
    manifest = _load_manifest()
    assert tuple(manifest["no_rescue_rules"]) == regimes_module.NO_RESCUE_RULES
    assert tuple(manifest["no_rescue_rules"]) == evaluator_module.NO_RESCUE_RULES
    termination = manifest["automatic_termination_rules"]
    park = termination["park"]
    invalid = termination["invalid"]
    assert "SAME_BUDGET_UNIVERSAL_DAG_PROVED" in park
    assert "D1E_CHANGED_AFTER_D1F_HANDOFF" in park
    assert "ENVIRONMENT_DIFFERS_BY_ARM" in park
    assert "EVALUATOR_ARM_DEPENDENT" in park
    assert "INVALID_GENERATOR" in invalid
    assert "INVALID_INSTRUMENTATION" in invalid
    assert "INVALID_PROTOCOL" in invalid
    assert "D1_CANDIDATE_DRIFT_AFTER_NONCE_COMMITMENT" in invalid


# --------------------------------------------------------------------------- #
# binding modes + no live-target self-binding
# --------------------------------------------------------------------------- #
def test_binding_modes_and_no_live_target_self_binding() -> None:
    manifest = _load_manifest()
    modes = manifest["binding_modes"]
    # D1-E supplied binding modes are preserved.
    assert modes["required_binding_modes"] == {
        "event": "runner_anchored_team_events",
        "permission": "matching_request_and_approval_rows",
        "product": "live_git_head_and_clean_worktree",
        "runner": "live_git_head_and_exported_schema",
        "spine": "verified_prereg_lock_and_result",
    }
    # The future combined-D1 executable target must remain unbound at candidate
    # time; a self-bound live target fails closed.
    assert modes["d1_product_target"] == "PRE_FREEZE_TARGET_UNBOUND"
    assert not _HEX40.match(modes["d1_product_target"])
    assert (
        modes["combined_d1_freeze_binding_mode"] == "PLAN_ONLY_CANDIDATE_NO_LIVE_TARGET"
    )
    head = _current_head()
    if head is not None:
        assert modes["d1_product_target"] != head
        # The current worktree HEAD may not be recorded as any binding-mode
        # executable D1/D2 target. (D1-F's sealed prerequisite target may equal
        # HEAD elsewhere; that is a frozen upstream identity, not a live target.)
        for value in _all_string_values(modes):
            if value == head:
                pytest.fail("current git HEAD self-bound as a candidate target")


def test_no_whole_ledger_digest_binding() -> None:
    manifest = _load_manifest()
    for key in _all_keys(manifest):
        lowered = key.lower()
        for marker in _FORBIDDEN_WHOLE_LEDGER_KEY_MARKERS:
            assert marker not in lowered, (
                f"forbidden whole-ledger digest key present: {key}"
            )
    # Permission rows must be bound as immutable canonical rows.
    for binding in manifest["permission_bindings"]:
        assert _HEX64.match(binding["request_row_canonical_sha256"])
        assert _HEX64.match(binding["approval_row_canonical_sha256"])


def test_no_forbidden_post_acceptance_material() -> None:
    manifest = _load_manifest()
    present = _all_keys(manifest) & _FORBIDDEN_MATERIAL_KEYS
    assert not present, f"forbidden post-acceptance material keys present: {present}"
    for value in _all_string_values(manifest):
        assert "432/432" not in value, "oracle result material leaked into candidate"
    absent = manifest["forbidden_material_absent"]
    for token in (
        "ROOT_SEED",
        "NONCE_COMMITMENT_OR_REVEAL",
        "CORPUS_OR_ASSIGNMENTS",
        "PROVIDER_BANK",
        "D2_SPEC_OR_LOCK",
        "ORACLE_OR_RESULT",
    ):
        assert absent[token] is True, (
            f"forbidden material must be affirmed absent: {token}"
        )


# --------------------------------------------------------------------------- #
# role separation + upstream evidence bindings
# --------------------------------------------------------------------------- #
def test_pairwise_role_separation() -> None:
    manifest = _load_manifest()
    separation = manifest["role_separation"]
    roles = separation["roles"]
    # Distinct identities are required across the independence-bearing roles.
    independent = (
        "d1e_environment_owner",
        "d1e_architecture_reviewer",
        "d1f_fixed_builder",
        "d1f_code_reviewer",
        "d1f_freezer",
        "d1f_skeptic",
    )
    identities = [roles[role] for role in independent]
    assert len(set(identities)) == len(identities), "roles must be pairwise separated"
    assert roles["d1f_fixed_builder"] == EXPECTED_D1F_BUILDER_ID
    assert roles["d1f_skeptic"] == EXPECTED_SKEPTIC_ID
    assert separation["writer_id"] == "codex-cto-combined-d1-final-writer-v1"
    assert separation["writer_holds_no_acceptance_or_review_authority"] is True


def test_runner_spine_and_permission_evidence_bindings() -> None:
    manifest = _load_manifest()
    runner = manifest["runner_identity"]
    assert runner["repository"] == "ai-agent-engineering-workflow"
    assert _HEX40.match(runner["head"])
    assert runner["event_schema_version"] == "team-event-v1"
    assert _HEX64.match(runner["exported_schema_sha256"])

    spine = manifest["spine_identity"]
    assert spine["run_id"] == "spine-e2e-4-20260713"
    assert spine["verdict"] == "PASS"
    assert _HEX40.match(spine["product_head"])
    assert _HEX64.match(spine["prereg_lock_sha256"])
    assert _HEX64.match(spine["result_sha256"])

    permissions = manifest["permission_bindings"]
    assert len(permissions) >= 2
    request_ids = {binding["request_id"] for binding in permissions}
    assert "perm_4d4634d17eabc8f0" in request_ids  # successor chain
    assert "perm_554bde98c9a74cd9" in request_ids  # D1-E freeze/exposure
    assert "perm_190011ecb84faa18" in request_ids  # D1-F seal/exposure
    for binding in permissions:
        assert binding["decision"] == "approved_session"
        assert binding["decided_by"] == "founder"
        assert binding["source_match"] is True
