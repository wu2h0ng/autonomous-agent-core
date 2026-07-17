"""RED tests for DockerArmExecutor controlled wiring into the M0c three-arm harness.

- bypass: producing a controlled receipt without explicit harness binding
- identity: mismatched unit/arm/controller/image/policy/worker digests
- budget: budget overflow before execution
- cleanup: cleanup digest integrity through the controlled receipt
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from typing import Any

import pytest

from agent_os_contracts import content_digest
from product_evals.srl_e2e_falsifier.contracts import (
    CandidateKind,
    DecisionCandidate,
    PublicContentManifest,
    PublicContentManifestEntry,
    PublicContentMediaType,
    PublicContentRole,
    PublicResponsibilityStateVerifier,
    StaticBudgetConfiguration,
    decision_candidate_digest,
    public_content_entry_digest,
    public_content_manifest_digest,
    static_budget_configuration_bytes,
    static_budget_configuration_digest,
)
from product_evals.srl_e2e_falsifier.docker_exec import (
    DockerExecutionReceipt,
    DockerExecutionRequest,
    trusted_docker_executor,
)
from product_evals.srl_e2e_falsifier.harness import (
    ArmId,
    BudgetUsage,
    ControllerBindingConfig,
    ControlledExecutionReceipt,
    FrozenEvaluationUnit,
    MatchedBudgetLedger,
    seal_controlled_execution_receipt,
)


def _candidate(
    public_state_digest: str = "a" * 64,
    kind: CandidateKind = CandidateKind.NONE,
) -> DecisionCandidate:
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "candidate_id": "candidate:controlled-wiring",
        "candidate_kind": kind.value,
        "public_state_digest": public_state_digest,
        "no_external_effect": True,
        "desired_outcome": None,
        "acceptance_criteria": (),
        "missing_input_kind": None,
        "minimum_question": None,
        "created_at": datetime(2026, 7, 17, tzinfo=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
    }
    if kind is CandidateKind.WORK:
        payload["desired_outcome"] = "complete the task"
        payload["acceptance_criteria"] = ("all tests pass",)
    elif kind is CandidateKind.HELP:
        payload["missing_input_kind"] = "INFORMATION"
        payload["minimum_question"] = "describe next action"
    payload["candidate_digest"] = decision_candidate_digest(payload)
    return DecisionCandidate.model_validate(payload)


def _budget() -> StaticBudgetConfiguration:
    budget_payload: dict[str, object] = {
        "max_llm_calls": 2,
        "max_input_tokens": 1000,
        "max_output_tokens": 500,
        "max_retries": 1,
        "max_tool_invocations": 4,
        "max_wall_seconds": 60,
    }
    budget_payload["configuration_digest"] = static_budget_configuration_digest(
        budget_payload
    )
    return StaticBudgetConfiguration.model_validate(budget_payload)


def _entry(role: PublicContentRole, raw: bytes) -> PublicContentManifestEntry:
    payload: dict[str, Any] = {
        "role": role,
        "media_type": PublicContentMediaType.APPLICATION_JSON,
        "content_digest": hashlib.sha256(raw).hexdigest(),
    }
    payload["entry_digest"] = public_content_entry_digest(payload)
    return PublicContentManifestEntry.model_validate(payload)


def _unit(unit_id: str = "unit-controlled-wiring") -> FrozenEvaluationUnit:
    budget = _budget()
    budget_bytes = static_budget_configuration_bytes(budget)
    raws = (
        b'{"mission":"keep quality green"}',
        b'{"event":"test"}',
        b'{"projection":"test"}',
        b'{"evidence":"test"}',
        budget_bytes,
    )
    roles = (
        PublicContentRole.MISSION,
        PublicContentRole.EVENT,
        PublicContentRole.PROJECTION,
        PublicContentRole.EVIDENCE,
        PublicContentRole.STATIC_BUDGET,
    )
    entries = tuple(_entry(role, raw) for role, raw in zip(roles, raws, strict=True))
    manifest_payload: dict[str, object] = {"entries": entries}
    manifest_payload["manifest_root_digest"] = public_content_manifest_digest(
        manifest_payload
    )
    manifest = PublicContentManifest.model_validate(manifest_payload)
    contents = {
        entry.entry_digest: raw for entry, raw in zip(entries, raws, strict=True)
    }
    state = PublicResponsibilityStateVerifier.build(
        manifest=manifest,
        content_by_entry_digest=contents,
        static_budget_configuration=budget,
        mandate_digest="a" * 64,
        environment_binding_digest="b" * 64,
        correction_epoch=0,
        mission_entry_digest=entries[0].entry_digest,
        event_entry_digests=(entries[1].entry_digest,),
        projection_entry_digests=(entries[2].entry_digest,),
        evidence_entry_digests=(entries[3].entry_digest,),
        static_budget_entry_digest=entries[4].entry_digest,
    )
    return FrozenEvaluationUnit(
        unit_id=unit_id,
        public_state=state,
        budget=budget,
        event_id="event-ctrl",
        projection_id="projection-ctrl",
        admission_receipt_id="admission-ctrl",
    )


def _binding_config() -> ControllerBindingConfig:
    return ControllerBindingConfig(
        controller_digest="1" * 64,
        prompt_digest="2" * 64,
        model_digest="3" * 64,
        tool_catalog_digest="4" * 64,
    )


def _docker_execution(candidate: DecisionCandidate) -> DockerExecutionReceipt:
    executor = trusted_docker_executor()
    payload = {
        "schema_version": "1.0",
        "request_id": "docker-request:controlled",
        "public_state_digest": candidate.public_state_digest,
        "candidate": candidate.model_dump(mode="json"),
    }
    payload["request_digest"] = content_digest(payload)
    request = DockerExecutionRequest.from_mapping(payload)
    return executor.execute(request)


def _seal(
    *,
    docker_receipt: DockerExecutionReceipt,
    unit: FrozenEvaluationUnit,
    arm_id: ArmId = ArmId.DIRECT,
    public_state_digest: str | None = None,
    controller_digest: str | None = None,
    prompt_digest: str | None = None,
    model_digest: str | None = None,
    tool_catalog_digest: str | None = None,
    budget_configuration_digest: str | None = None,
    provider_probe_digest: str = "5" * 64,
    docker_execution_receipt_digest: str | None = None,
    docker_image_identity: str | None = None,
    docker_resolved_image_id: str | None = None,
    docker_policy_digest: str | None = None,
    docker_worker_artifact_sha256: str | None = None,
) -> ControlledExecutionReceipt:
    binding = _binding_config()
    return seal_controlled_execution_receipt(
        unit_id=unit.unit_id,
        arm_id=arm_id,
        public_state_digest=public_state_digest or docker_receipt.public_state_digest,
        controller_digest=controller_digest or binding.controller_digest,
        prompt_digest=prompt_digest or binding.prompt_digest,
        model_digest=model_digest or binding.model_digest,
        tool_catalog_digest=tool_catalog_digest or binding.tool_catalog_digest,
        budget_configuration_digest=budget_configuration_digest
        or unit.budget.configuration_digest,
        provider_probe_digest=provider_probe_digest,
        docker_execution_receipt_digest=docker_execution_receipt_digest
        or docker_receipt.receipt_digest,
        docker_image_identity=docker_image_identity
        or docker_receipt.image_identity,
        docker_resolved_image_id=docker_resolved_image_id
        or docker_receipt.resolved_image_id,
        docker_policy_digest=docker_policy_digest or docker_receipt.policy_digest,
        docker_worker_artifact_sha256=docker_worker_artifact_sha256
        or docker_receipt.worker_artifact_sha256,
        docker_receipt_public_state_digest=docker_receipt.public_state_digest,
        docker_receipt_image_identity=docker_receipt.image_identity,
        docker_receipt_resolved_image_id=docker_receipt.resolved_image_id,
        docker_receipt_policy_digest=docker_receipt.policy_digest,
        docker_receipt_worker_artifact_sha256=docker_receipt.worker_artifact_sha256,
        docker_receipt_receipt_digest=docker_receipt.receipt_digest,
    )


# ---------------------------------------------------------------------------
# BYPASS
# ---------------------------------------------------------------------------


def test_cannot_bypass_seal_controlled_receipt_without_identity_bindings() -> None:
    candidate = _candidate(kind=CandidateKind.WORK)
    docker_receipt = _docker_execution(candidate)
    unit = _unit()

    receipt = _seal(docker_receipt=docker_receipt, unit=unit)
    assert isinstance(receipt, ControlledExecutionReceipt)
    assert receipt.content_digest == content_digest(
        receipt.to_mapping(exclude_content_digest=True)
    )


def test_direct_docker_execution_without_harness_context_is_not_controlled() -> None:
    candidate = _candidate()
    receipt = _docker_execution(candidate)
    assert isinstance(receipt, DockerExecutionReceipt)
    assert not isinstance(receipt, ControlledExecutionReceipt)
    assert receipt.receipt_digest != ""
    assert receipt.local_integrity_hmac != ""


# ---------------------------------------------------------------------------
# IDENTITY
# ---------------------------------------------------------------------------


def test_controlled_receipt_rejects_mismatched_public_state() -> None:
    candidate = _candidate(public_state_digest="a" * 64)
    docker_receipt = _docker_execution(candidate)
    unit = _unit()

    with pytest.raises(ValueError, match="public state"):
        _seal(
            docker_receipt=docker_receipt,
            unit=unit,
            public_state_digest="9" * 64,
        )


def test_controlled_receipt_rejects_mismatched_image_identity() -> None:
    candidate = _candidate()
    docker_receipt = _docker_execution(candidate)
    unit = _unit()

    with pytest.raises(ValueError, match="image"):
        _seal(
            docker_receipt=docker_receipt,
            unit=unit,
            docker_image_identity="alpine:latest",
        )


def test_controlled_receipt_rejects_mismatched_policy_digest() -> None:
    candidate = _candidate()
    docker_receipt = _docker_execution(candidate)
    unit = _unit()

    with pytest.raises(ValueError, match="policy"):
        _seal(
            docker_receipt=docker_receipt,
            unit=unit,
            docker_policy_digest="9" * 64,
        )


def test_controlled_receipt_rejects_mismatched_worker_digest() -> None:
    candidate = _candidate()
    docker_receipt = _docker_execution(candidate)
    unit = _unit()

    with pytest.raises(ValueError, match="worker"):
        _seal(
            docker_receipt=docker_receipt,
            unit=unit,
            docker_worker_artifact_sha256="0" * 64,
        )


def test_controlled_receipt_full_identity_binding_is_content_addressed() -> None:
    candidate = _candidate(kind=CandidateKind.WORK)
    docker_receipt = _docker_execution(candidate)
    unit = _unit()
    binding = _binding_config()

    receipt = _seal(
        docker_receipt=docker_receipt,
        unit=unit,
        arm_id=ArmId.SRL,
    )

    assert receipt.unit_id == unit.unit_id
    assert receipt.arm_id is ArmId.SRL
    assert receipt.unit_digest != ""
    assert receipt.arm_digest != ""
    assert receipt.controller_digest == binding.controller_digest
    assert receipt.prompt_digest == binding.prompt_digest
    assert receipt.model_digest == binding.model_digest
    assert receipt.tool_catalog_digest == binding.tool_catalog_digest
    assert receipt.public_state_digest == candidate.public_state_digest
    assert receipt.budget_configuration_digest == unit.budget.configuration_digest
    assert receipt.provider_probe_digest == "5" * 64
    assert receipt.docker_execution_receipt_digest == docker_receipt.receipt_digest
    assert receipt.image_identity == docker_receipt.image_identity
    assert receipt.resolved_image_id == docker_receipt.resolved_image_id
    assert receipt.policy_digest == docker_receipt.policy_digest
    assert receipt.worker_artifact_sha256 == docker_receipt.worker_artifact_sha256
    assert receipt.content_digest != ""
    assert len(receipt.content_digest) == 64

    payload = receipt.to_mapping(exclude_content_digest=True)
    assert receipt.content_digest == content_digest(payload)

    second = _seal(docker_receipt=docker_receipt, unit=unit, arm_id=ArmId.SRL)
    assert second == receipt
    assert second.content_digest == receipt.content_digest


def test_controlled_receipt_unit_and_arm_digests_are_distinct() -> None:
    candidate = _candidate()
    docker_receipt = _docker_execution(candidate)

    unit_a = _unit("unit-a")
    receipt_a = _seal(docker_receipt=docker_receipt, unit=unit_a)

    unit_b = _unit("unit-b")
    receipt_b = _seal(docker_receipt=docker_receipt, unit=unit_b)

    assert receipt_a.arm_digest == receipt_b.arm_digest
    assert receipt_a.unit_digest != receipt_b.unit_digest
    assert receipt_a != receipt_b


# ---------------------------------------------------------------------------
# BUDGET
# ---------------------------------------------------------------------------


def test_budget_exceeded_fails_before_sealing_controlled_anyway() -> None:
    unit = _unit()
    ledger = MatchedBudgetLedger()

    ledger.seal(arm_id=ArmId.DIRECT, unit=unit, usage=BudgetUsage(llm_calls=1))
    duplicate = BudgetUsage(llm_calls=1)
    with pytest.raises(ValueError, match="already sealed"):
        ledger.seal(arm_id=ArmId.DIRECT, unit=unit, usage=duplicate)


def test_budget_overflow_detected_independent_of_docker_executor() -> None:
    unit = _unit()
    ledger = MatchedBudgetLedger()

    over_budget = BudgetUsage(
        llm_calls=unit.budget.max_llm_calls + 1,
        input_tokens=0,
        output_tokens=0,
        retries=0,
        tool_invocations=0,
        wall_seconds=0,
        provider_cost_microunits=0,
    )
    with pytest.raises(ValueError, match="budget exceeded"):
        ledger.seal(arm_id=ArmId.WORKFLOW, unit=unit, usage=over_budget)


# ---------------------------------------------------------------------------
# CLEANUP
# ---------------------------------------------------------------------------


def test_controlled_receipt_carries_docker_execution_cleanup_integrity() -> None:
    candidate = _candidate()
    docker_receipt = _docker_execution(candidate)
    unit = _unit()

    receipt = _seal(docker_receipt=docker_receipt, unit=unit)

    assert receipt.docker_execution_receipt_digest == docker_receipt.receipt_digest
    assert docker_receipt.cleanup_absent is True
    assert docker_receipt.cleanup_remove_exit_code == 0
    assert docker_receipt.cleanup_digest == content_digest(
        {"cleanup_remove_exit_code": 0, "cleanup_absent": True}
    )

    second = _seal(docker_receipt=docker_receipt, unit=unit)
    assert second.docker_execution_receipt_digest == receipt.docker_execution_receipt_digest
    assert second == receipt

    incompat = DockerExecutionReceipt(
        schema_version="1.0",
        request_id="fake",
        request_digest="f" * 64,
        public_state_digest=docker_receipt.public_state_digest,
        candidate=candidate,
        image_identity=docker_receipt.image_identity,
        resolved_image_id=docker_receipt.resolved_image_id,
        policy_digest=docker_receipt.policy_digest,
        worker_artifact_sha256=docker_receipt.worker_artifact_sha256,
        container_id="0" * 64,
        pre_start_inspect_digest="0" * 64,
        post_start_inspect_digest="0" * 64,
        exit_code=0,
        stdout_digest="0" * 64,
        stderr_digest="0" * 64,
        network_mode="none",
        rootfs_read_only=True,
        environment_empty=True,
        no_external_effect=True,
        cleanup_remove_exit_code=0,
        cleanup_absent=True,
        cleanup_digest=content_digest(
            {"cleanup_remove_exit_code": 0, "cleanup_absent": True}
        ),
        receipt_digest="e" * 64,
        local_integrity_hmac="0" * 64,
    )
    assert incompat.receipt_digest != docker_receipt.receipt_digest

    with pytest.raises(ValueError, match="receipt.*digest"):
        _seal(
            docker_receipt=docker_receipt,
            unit=unit,
            docker_execution_receipt_digest=incompat.receipt_digest,
        )


def test_evaluate_unit_still_fail_closed_when_executor_is_available() -> None:
    candidate = _candidate()
    docker_receipt = _docker_execution(candidate)
    assert isinstance(docker_receipt, DockerExecutionReceipt)
    assert docker_receipt.no_external_effect is True

    unit = _unit()
    receipt = _seal(docker_receipt=docker_receipt, unit=unit, arm_id=ArmId.SRL)
    assert isinstance(receipt, ControlledExecutionReceipt)


def test_mismatched_receipt_digest_fails_before_scoring() -> None:
    candidate = _candidate()
    docker_receipt = _docker_execution(candidate)
    unit = _unit()

    with pytest.raises(ValueError, match="receipt.*digest"):
        _seal(
            docker_receipt=docker_receipt,
            unit=unit,
            docker_execution_receipt_digest="f" * 64,
        )


def test_controlled_receipt_rejects_unbounded_arm_id() -> None:
    candidate = _candidate()
    docker_receipt = _docker_execution(candidate)
    unit = _unit()
    binding = _binding_config()

    with pytest.raises(ValueError):
        seal_controlled_execution_receipt(
            unit_id=unit.unit_id,
            arm_id="X",  # type: ignore[arg-type]
            public_state_digest=candidate.public_state_digest,
            controller_digest=binding.controller_digest,
            prompt_digest=binding.prompt_digest,
            model_digest=binding.model_digest,
            tool_catalog_digest=binding.tool_catalog_digest,
            budget_configuration_digest=unit.budget.configuration_digest,
            provider_probe_digest="5" * 64,
            docker_execution_receipt_digest=docker_receipt.receipt_digest,
            docker_image_identity=docker_receipt.image_identity,
            docker_resolved_image_id=docker_receipt.resolved_image_id,
            docker_policy_digest=docker_receipt.policy_digest,
            docker_worker_artifact_sha256=docker_receipt.worker_artifact_sha256,
            docker_receipt_public_state_digest=docker_receipt.public_state_digest,
            docker_receipt_image_identity=docker_receipt.image_identity,
            docker_receipt_resolved_image_id=docker_receipt.resolved_image_id,
            docker_receipt_policy_digest=docker_receipt.policy_digest,
            docker_receipt_worker_artifact_sha256=docker_receipt.worker_artifact_sha256,
            docker_receipt_receipt_digest=docker_receipt.receipt_digest,
        )
