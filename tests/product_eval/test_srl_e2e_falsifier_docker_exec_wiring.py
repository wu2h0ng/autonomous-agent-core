"""RED tests for DockerArmExecutor controlled wiring into the M0c three-arm harness.

- bypass: producing a controlled receipt without explicit harness binding
- identity: mismatched unit/arm/controller/image/policy/worker digests
- budget: budget overflow before execution
- cleanup: cleanup digest integrity through the controlled receipt
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any

import pytest

from agent_os_contracts import content_digest
from product_evals.srl_e2e_falsifier.contracts import (
    CandidateKind,
    ControllerBindingReceipt,
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
from product_evals.srl_e2e_falsifier import docker_exec as docker_exec_module
from product_evals.srl_e2e_falsifier.harness import (
    ArmId,
    BoundControllerDecision,
    BudgetReceipt,
    BudgetUsage,
    ControllerBindingConfig,
    ControlledExecutionReceipt,
    FrozenEvaluationUnit,
    MatchedBudgetLedger,
    UsageReceipt,
    execute_and_seal_controlled_arm,
    seal_controlled_execution_receipt,
)
from tests.product_eval.test_srl_e2e_harness import _real_srl_controller


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


def _bound_decision(
    unit: FrozenEvaluationUnit,
    candidate: DecisionCandidate,
) -> BoundControllerDecision:
    config = _binding_config()
    usage = BudgetUsage(llm_calls=1, input_tokens=7, output_tokens=3)
    observed_at = datetime(2026, 7, 17, tzinfo=timezone.utc)
    usage_payload = {
        "probe_digest": "5" * 64,
        "before_snapshot_digest": "6" * 64,
        "after_snapshot_digest": "7" * 64,
        "usage": usage.__dict__,
        "duration_ms": 12,
        "observed_at": observed_at,
    }
    usage_receipt = UsageReceipt(
        probe_digest="5" * 64,
        before_snapshot_digest="6" * 64,
        after_snapshot_digest="7" * 64,
        usage=usage,
        duration_ms=12,
        observed_at=observed_at,
        content_digest=content_digest(usage_payload),
    )
    binding_payload = {
        "schema_version": "1.0",
        "public_state_digest": unit.public_state.state_digest,
        "controller_digest": config.controller_digest,
        "prompt_digest": config.prompt_digest,
        "model_digest": config.model_digest,
        "tool_catalog_digest": config.tool_catalog_digest,
        "budget_configuration_digest": unit.budget.configuration_digest,
        "trigger_digest": (
            unit.custody_receipt.manifest_digest
            if unit.custody_receipt is not None
            else "8" * 64
        ),
        "candidate_digest": candidate.candidate_digest,
        "bound_at": observed_at,
        "authority_granted": False,
        "external_effects_authorized": False,
    }
    binding_digest = content_digest(binding_payload)
    binding_receipt = ControllerBindingReceipt.model_validate(
        {
            **binding_payload,
            "receipt_id": f"controller-binding:{binding_digest}",
            "content_digest": binding_digest,
        }
    )
    return BoundControllerDecision(
        candidate=candidate,
        usage_receipt=usage_receipt,
        binding_receipt=binding_receipt,
    )


def _execution_bindings(
    unit: FrozenEvaluationUnit,
    arm_id: ArmId = ArmId.DIRECT,
) -> tuple[BoundControllerDecision, BudgetReceipt]:
    candidate = _candidate(unit.public_state.state_digest, CandidateKind.WORK)
    decision = _bound_decision(unit, candidate)
    budget = MatchedBudgetLedger().seal(
        arm_id=arm_id,
        unit=unit,
        usage=decision.usage,
    )
    return decision, budget


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


def test_local_docker_and_controlled_receipts_remain_proposal_only() -> None:
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


# ---------------------------------------------------------------------------
# REAL EXECUTE-AND-SEAL WIRING
# ---------------------------------------------------------------------------


def test_execute_and_seal_ignores_overridden_factory_instance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, unit, _, loader = _real_srl_controller(tmp_path)
    decision, budget = _execution_bindings(unit, ArmId.SRL)
    compromised = trusted_docker_executor()
    monkeypatch.setattr(
        compromised,
        "execute",
        lambda request: (_ for _ in ()).throw(AssertionError("instance dispatch used")),
    )

    controlled = execute_and_seal_controlled_arm(
        unit_loader=loader,
        unit=unit,
        arm_id=ArmId.SRL,
        decision=decision,
        budget_receipt=budget,
        provider_probe_digest=decision.usage_receipt.probe_digest,
    )

    binding = decision.binding_receipt
    assert controlled.unit_digest == content_digest(
        {"unit_id": unit.unit_id, "public_state_digest": unit.public_state.state_digest}
    )
    assert controlled.docker_execution_receipt_digest != ""
    assert controlled.controller_digest == binding.controller_digest
    assert controlled.budget_configuration_digest == budget.budget_configuration_digest
    assert controlled.provider_probe_digest == decision.usage_receipt.probe_digest


def test_execute_and_seal_propagates_docker_os_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, unit, _, loader = _real_srl_controller(tmp_path)
    decision, budget = _execution_bindings(unit)
    calls = 0
    real_docker_run = docker_exec_module._docker_run

    def fail_create(args: list[str], *, timeout: int = 10) -> Any:
        nonlocal calls
        if args[:2] == ["docker", "create"]:
            calls += 1
            raise RuntimeError("docker OS seam failed")
        return real_docker_run(args, timeout=timeout)

    monkeypatch.setattr(docker_exec_module, "_docker_run", fail_create)

    with pytest.raises(RuntimeError, match="docker OS seam failed"):
        execute_and_seal_controlled_arm(
            unit_loader=loader,
            unit=unit,
            arm_id=ArmId.DIRECT,
            decision=decision,
            budget_receipt=budget,
            provider_probe_digest=decision.usage_receipt.probe_digest,
        )
    assert calls == 1


@pytest.mark.parametrize("drift", ["none", "mac", "unit", "trigger"])
def test_execute_and_seal_rejects_custody_drift_before_docker(
    tmp_path: Path,
    drift: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, loaded_unit, _, loader = _real_srl_controller(tmp_path)
    unit = loaded_unit
    if drift == "none":
        unit = _unit()
    elif drift == "mac":
        assert unit.custody_receipt is not None
        unit = replace(
            unit,
            custody_receipt=replace(unit.custody_receipt, custody_mac="0" * 64),
        )
    elif drift == "unit":
        unit = replace(unit, event_id="event-drifted")
    decision, budget = _execution_bindings(loaded_unit)
    if drift == "trigger":
        decision = replace(
            decision,
            binding_receipt=decision.binding_receipt.model_copy(
                update={"trigger_digest": "9" * 64}
            ),
        )
    calls = 0

    def unexpected_docker(args: list[str], *, timeout: int = 10) -> Any:
        nonlocal calls
        calls += 1
        raise AssertionError("custody drift reached Docker")

    monkeypatch.setattr(docker_exec_module, "_docker_run", unexpected_docker)
    with pytest.raises(ValueError, match="custody|binding"):
        execute_and_seal_controlled_arm(
            unit_loader=loader,
            unit=unit,
            arm_id=ArmId.DIRECT,
            decision=decision,
            budget_receipt=budget,
            provider_probe_digest=decision.usage_receipt.probe_digest,
        )
    assert calls == 0


@pytest.mark.parametrize("drift", ["budget", "provider", "binding"])
def test_execute_and_seal_rejects_binding_drift_before_executor_call(
    tmp_path: Path,
    drift: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, unit, _, loader = _real_srl_controller(tmp_path)
    decision, budget = _execution_bindings(unit)
    provider_probe_digest = decision.usage_receipt.probe_digest
    if drift == "budget":
        budget = replace(budget, unit_id="other-unit")
    elif drift == "provider":
        provider_probe_digest = "9" * 64
    else:
        decision = replace(
            decision,
            binding_receipt=decision.binding_receipt.model_copy(
                update={"public_state_digest": "9" * 64}
            ),
        )
    calls = 0

    def unexpected_create(args: list[str], *, timeout: int = 10) -> Any:
        nonlocal calls
        calls += 1
        raise AssertionError("binding drift reached Docker OS seam")

    monkeypatch.setattr(docker_exec_module, "_docker_run", unexpected_create)

    with pytest.raises(ValueError, match="binding|receipt integrity"):
        execute_and_seal_controlled_arm(
            unit_loader=loader,
            unit=unit,
            arm_id=ArmId.DIRECT,
            decision=decision,
            budget_receipt=budget,
            provider_probe_digest=provider_probe_digest,
        )
    assert calls == 0


def test_trusted_receipt_ceiling_rejects_raw_identity_drift() -> None:
    candidate = _candidate()
    receipt = _docker_execution(candidate)
    docker_exec_module.verify_trusted_docker_receipt_ceiling(receipt)
    with pytest.raises(ValueError, match="trusted Docker policy ceiling"):
        docker_exec_module.verify_trusted_docker_receipt_ceiling(
            replace(receipt, policy_digest="9" * 64)
        )
