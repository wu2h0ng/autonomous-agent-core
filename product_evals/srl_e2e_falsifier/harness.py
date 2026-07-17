"""Minimal three-arm Product harness for the SRL E2E falsifier.

This module is instrument-only.  It cannot activate tasks, execute tools, call a
network, or run a hidden scorer before all three arm decisions are sealed.  The
SRL arm is deliberately hard-bound to the real admission-required
``AgentOSApplication.propose_situated_work`` entry point.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import hashlib
import hmac
import json
from pathlib import Path
from typing import Callable, Mapping, Protocol, runtime_checkable

from agent_os_contracts import (
    EnvironmentEvent,
    EnvironmentEventAdmissionReceipt,
    HelpRequest,
    OperationalProjectionRef,
    TaskDraftProposal,
    content_digest,
)
from apps.api_server.app import AgentOSApplication

from .contracts import (
    CandidateKind,
    ControllerBindingReceipt,
    DecisionCandidate,
    MissingInputKind,
    PublicContentManifest,
    PublicResponsibilityState,
    PublicResponsibilityStateVerifier,
    StaticBudgetConfiguration,
    decision_candidate_digest,
)


class ArmId(str, Enum):
    DIRECT = "D"
    WORKFLOW = "W"
    SRL = "S"


@dataclass(frozen=True)
class UnitCustodyReceipt:
    unit_id: str
    public_state_digest: str
    public_manifest_root_digest: str
    budget_configuration_digest: str
    event_id: str
    event_digest: str
    projection_id: str
    projection_digest: str
    admission_receipt_id: str
    admission_receipt_digest: str
    principal_id: str
    tenant_id: str
    workspace_id: str
    mandate_digest: str
    environment_binding_digest: str
    correction_epoch: int
    manifest_digest: str
    custody_mac: str


class TrustedFrozenUnitLoader:
    """Load and MAC an exact-byte unit; no public constructor grants custody."""

    _MANIFEST_KEYS = frozenset(
        {
            "schema_version",
            "unit_id",
            "public_state_path",
            "public_manifest_path",
            "budget_path",
            "event_path",
            "projection_path",
            "admission_receipt_path",
            "content_paths",
            "public_state_digest",
            "public_manifest_root_digest",
            "budget_configuration_digest",
            "event_digest",
            "projection_digest",
            "admission_receipt_digest",
            "manifest_digest",
        }
    )

    def __init__(self, *, custody_key: bytes) -> None:
        if type(custody_key) is not bytes or len(custody_key) < 32:
            raise ValueError("unit custody key must contain at least 32 bytes")
        self._custody_key = custody_key

    @staticmethod
    def _read(root: Path, relative: object) -> bytes:
        if type(relative) is not str or not relative:
            raise ValueError("unit manifest path must be a nonempty string")
        candidate = root / relative
        resolved_root = root.resolve()
        resolved = candidate.resolve()
        if resolved_root not in resolved.parents or candidate.is_symlink():
            raise ValueError("unit manifest path escapes custody directory")
        if not resolved.is_file():
            raise ValueError("unit custody file is unavailable")
        return resolved.read_bytes()

    @staticmethod
    def _json(raw: bytes, label: str) -> dict[str, object]:
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError(f"{label} must be canonical JSON") from None
        if not isinstance(value, dict):
            raise ValueError(f"{label} must be a JSON object")
        return value

    def load(self, directory: str | Path) -> FrozenEvaluationUnit:
        root = Path(directory)
        manifest = self._json(self._read(root, "unit_manifest.json"), "unit manifest")
        if set(manifest) != self._MANIFEST_KEYS or manifest.get("schema_version") != "1.0":
            raise ValueError("unit manifest schema is not exact")
        supplied_manifest_digest = manifest["manifest_digest"]
        manifest_payload = dict(manifest)
        del manifest_payload["manifest_digest"]
        expected_manifest_digest = content_digest(manifest_payload)
        if supplied_manifest_digest != expected_manifest_digest:
            raise ValueError("unit manifest digest mismatch")

        public_state = PublicResponsibilityState.model_validate(
            self._json(
                self._read(root, manifest["public_state_path"]), "public state"
            )
        )
        public_manifest = PublicContentManifest.model_validate(
            self._json(
                self._read(root, manifest["public_manifest_path"]),
                "public content manifest",
            )
        )
        budget = StaticBudgetConfiguration.model_validate(
            self._json(self._read(root, manifest["budget_path"]), "static budget")
        )
        event = EnvironmentEvent.model_validate(
            self._json(self._read(root, manifest["event_path"]), "environment event")
        )
        projection = OperationalProjectionRef.model_validate(
            self._json(
                self._read(root, manifest["projection_path"]),
                "operational projection",
            )
        )
        admission = EnvironmentEventAdmissionReceipt.model_validate(
            self._json(
                self._read(root, manifest["admission_receipt_path"]),
                "admission receipt",
            )
        )
        content_paths = manifest["content_paths"]
        if not isinstance(content_paths, dict):
            raise ValueError("content_paths must be an exact object")
        expected_entries = {entry.entry_digest for entry in public_manifest.entries}
        if set(content_paths) != expected_entries:
            raise ValueError("content_paths must cover the exact public manifest")
        content_by_entry_digest = {
            key: self._read(root, content_paths[key]) for key in sorted(content_paths)
        }
        PublicResponsibilityStateVerifier.verify(
            state=public_state,
            manifest=public_manifest,
            content_by_entry_digest=content_by_entry_digest,
            static_budget_configuration=budget,
        )

        exact_digests = (
            manifest["public_state_digest"] == public_state.state_digest,
            manifest["public_manifest_root_digest"]
            == public_manifest.manifest_root_digest,
            manifest["budget_configuration_digest"] == budget.configuration_digest,
            manifest["event_digest"] == content_digest(event),
            manifest["projection_digest"] == content_digest(projection),
            manifest["admission_receipt_digest"] == admission.receipt_digest,
        )
        exact_bindings = (
            admission.environment_event_id == event.environment_event_id,
            admission.event_digest == content_digest(event),
            admission.mandate_id == event.mandate_id == projection.mandate_id,
            admission.environment_binding_id
            == event.environment_binding_id
            == projection.environment_binding_id,
            admission.principal_id.strip() != "",
            admission.tenant_id == event.tenant_id == projection.tenant_id,
            admission.workspace_id == event.workspace_id == projection.workspace_id,
            event.environment_event_id in projection.source_event_ids,
            admission.correction_epoch == public_state.correction_epoch,
            admission.environment_binding_digest
            == public_state.environment_binding_digest,
            admission.grants_authority is False,
            admission.authorizes_effects is False,
        )
        if not all(exact_digests) or not all(exact_bindings):
            raise ValueError("unit custody bindings conflict")

        receipt_payload = {
            "unit_id": manifest["unit_id"],
            "public_state_digest": public_state.state_digest,
            "public_manifest_root_digest": public_manifest.manifest_root_digest,
            "budget_configuration_digest": budget.configuration_digest,
            "event_id": event.environment_event_id,
            "event_digest": content_digest(event),
            "projection_id": projection.projection_id,
            "projection_digest": content_digest(projection),
            "admission_receipt_id": admission.receipt_id,
            "admission_receipt_digest": admission.receipt_digest,
            "principal_id": admission.principal_id,
            "tenant_id": admission.tenant_id,
            "workspace_id": admission.workspace_id,
            "mandate_digest": public_state.mandate_digest,
            "environment_binding_digest": public_state.environment_binding_digest,
            "correction_epoch": public_state.correction_epoch,
            "manifest_digest": expected_manifest_digest,
        }
        custody_mac = hmac.new(
            self._custody_key,
            content_digest(receipt_payload).encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
        receipt = UnitCustodyReceipt(**receipt_payload, custody_mac=custody_mac)  # type: ignore[arg-type]
        return FrozenEvaluationUnit(
            unit_id=str(manifest["unit_id"]),
            public_state=public_state,
            budget=budget,
            event_id=event.environment_event_id,
            projection_id=projection.projection_id,
            admission_receipt_id=admission.receipt_id,
            custody_receipt=receipt,
        )

    def verify(self, unit: FrozenEvaluationUnit) -> UnitCustodyReceipt:
        receipt = unit.custody_receipt
        if receipt is None:
            raise ValueError("evaluation unit lacks trusted custody")
        payload = {
            key: value
            for key, value in receipt.__dict__.items()
            if key != "custody_mac"
        }
        expected = hmac.new(
            self._custody_key,
            content_digest(payload).encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, receipt.custody_mac):
            raise ValueError("evaluation unit custody MAC mismatch")
        exact = (
            unit.unit_id == receipt.unit_id,
            unit.public_state.state_digest == receipt.public_state_digest,
            unit.budget.configuration_digest == receipt.budget_configuration_digest,
            unit.event_id == receipt.event_id,
            unit.projection_id == receipt.projection_id,
            unit.admission_receipt_id == receipt.admission_receipt_id,
        )
        if not all(exact):
            raise ValueError("evaluation unit drifted after custody")
        return receipt


@dataclass(frozen=True)
class BudgetUsage:
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    retries: int = 0
    tool_invocations: int = 0
    wall_seconds: int = 0
    provider_cost_microunits: int = 0

    def __post_init__(self) -> None:
        if any(
            type(value) is not int or value < 0
            for value in (
                self.llm_calls,
                self.input_tokens,
                self.output_tokens,
                self.retries,
                self.tool_invocations,
                self.wall_seconds,
                self.provider_cost_microunits,
            )
        ):
            raise ValueError("budget usage values must be nonnegative integers")


@dataclass(frozen=True)
class OperatorBurden:
    hcw_minutes: float
    auth_minutes: float
    help_minutes: float
    help_count: int
    latency_ms: int

    def __post_init__(self) -> None:
        if any(
            type(value) not in (int, float) or value < 0
            for value in (self.hcw_minutes, self.auth_minutes, self.help_minutes)
        ) or any(
            type(value) is not int or value < 0
            for value in (self.help_count, self.latency_ms)
        ):
            raise ValueError("operator burden values must be nonnegative")


@dataclass(frozen=True)
class FrozenEvaluationUnit:
    """One immutable public unit; it contains no hidden answer or arm label."""

    unit_id: str
    public_state: PublicResponsibilityState
    budget: StaticBudgetConfiguration
    event_id: str
    projection_id: str
    admission_receipt_id: str
    custody_receipt: UnitCustodyReceipt | None = None

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value.strip()
            for value in (
                self.unit_id,
                self.event_id,
                self.projection_id,
                self.admission_receipt_id,
            )
        ):
            raise ValueError("frozen unit identifiers must be nonempty")
        if (
            self.public_state.static_budget_entry_digest == ""
            or self.budget.configuration_digest == ""
        ):
            raise ValueError("frozen unit budget binding is unavailable")


@dataclass(frozen=True)
class HiddenScore:
    decision_ok: bool
    false_work: bool
    missed_critical: bool
    mandatory_help_ok: bool
    executor_ok: bool
    severe_safety_violation: bool

    def __post_init__(self) -> None:
        if any(
            type(value) is not bool
            for value in (
                self.decision_ok,
                self.false_work,
                self.missed_critical,
                self.mandatory_help_ok,
                self.executor_ok,
                self.severe_safety_violation,
            )
        ):
            raise ValueError("hidden score fields must be exact booleans")


@dataclass(frozen=True)
class ArmMetrics:
    decision_ok: bool
    false_work: bool
    missed_critical: bool
    mandatory_help_ok: bool
    executor_ok: bool
    severe_safety_violation: bool
    hcw_minutes: float
    auth_minutes: float
    help_minutes: float
    help_count: int
    latency_ms: int
    provider_cost_microunits: int
    budget_configuration_digest: str


@dataclass(frozen=True)
class EvaluationReport:
    unit_id: str
    candidates: Mapping[ArmId, DecisionCandidate]
    metrics: Mapping[ArmId, ArmMetrics]


@dataclass(frozen=True)
class NormalizedDecision:
    """Arm-neutral scorer payload with explicit controller metadata removed."""

    candidate_kind: CandidateKind
    public_state_digest: str
    no_external_effect: bool
    desired_outcome: str | None
    acceptance_criteria: tuple[str, ...]
    missing_input_kind: MissingInputKind | None
    minimum_question: str | None


@dataclass(frozen=True)
class BlindedDecision:
    """Opaque scorer input; the arm-to-slot mapping stays inside the harness."""

    slot_token: str
    normalized_digest: str
    normalized: NormalizedDecision


@runtime_checkable
class ArmController(Protocol):
    def decide(
        self, unit: FrozenEvaluationUnit
    ) -> BoundControllerDecision: ...


@dataclass(frozen=True)
class ControllerBindingConfig:
    controller_digest: str
    prompt_digest: str
    model_digest: str
    tool_catalog_digest: str


@dataclass(frozen=True)
class BoundControllerDecision:
    candidate: DecisionCandidate
    usage: BudgetUsage
    binding_receipt: ControllerBindingReceipt


def bind_controller_decision(
    *,
    unit: FrozenEvaluationUnit,
    candidate: DecisionCandidate,
    usage: BudgetUsage,
    config: ControllerBindingConfig,
    bound_at: datetime,
) -> BoundControllerDecision:
    if unit.custody_receipt is None:
        raise ValueError("controller binding requires trusted unit custody")
    payload = {
        "schema_version": "1.0",
        "public_state_digest": unit.public_state.state_digest,
        "controller_digest": config.controller_digest,
        "prompt_digest": config.prompt_digest,
        "model_digest": config.model_digest,
        "tool_catalog_digest": config.tool_catalog_digest,
        "budget_configuration_digest": unit.budget.configuration_digest,
        "trigger_digest": unit.custody_receipt.manifest_digest,
        "candidate_digest": candidate.candidate_digest,
        "bound_at": bound_at,
        "authority_granted": False,
        "external_effects_authorized": False,
    }
    digest = content_digest(payload)
    receipt = ControllerBindingReceipt.model_validate(
        {
            **payload,
            "content_digest": digest,
            "receipt_id": f"controller-binding:{digest}",
        }
    )
    return BoundControllerDecision(
        candidate=candidate,
        usage=usage,
        binding_receipt=receipt,
    )


class HiddenScorerPort(Protocol):
    def score(
        self,
        *,
        decision: BlindedDecision,
        sealed_slot_tokens: tuple[str, ...],
    ) -> HiddenScore: ...


@dataclass(frozen=True)
class BudgetReceipt:
    arm_id: ArmId
    unit_id: str
    budget_configuration_digest: str
    usage: BudgetUsage


class MatchedBudgetLedger:
    """Fail-closed per-arm usage ledger bound to one shared unit budget."""

    def __init__(self) -> None:
        self._receipts: dict[tuple[str, ArmId], BudgetReceipt] = {}

    def seal(
        self,
        *,
        arm_id: ArmId,
        unit: FrozenEvaluationUnit,
        usage: BudgetUsage,
    ) -> BudgetReceipt:
        key = (unit.unit_id, arm_id)
        if key in self._receipts:
            raise ValueError("budget usage is already sealed")
        budget = unit.budget
        checks = (
            usage.llm_calls <= budget.max_llm_calls,
            usage.input_tokens <= budget.max_input_tokens,
            usage.output_tokens <= budget.max_output_tokens,
            usage.retries <= budget.max_retries,
            usage.tool_invocations <= budget.max_tool_invocations,
            usage.wall_seconds <= budget.max_wall_seconds,
        )
        if not all(checks):
            raise ValueError("budget exceeded before decision seal")
        receipt = BudgetReceipt(
            arm_id=arm_id,
            unit_id=unit.unit_id,
            budget_configuration_digest=budget.configuration_digest,
            usage=usage,
        )
        self._receipts[key] = receipt
        return receipt


class SituatedStewardController:
    """Evaluation wrapper over the real proposal-only Product entry point."""

    def __init__(
        self,
        *,
        application: AgentOSApplication,
        usage: BudgetUsage,
        binding_config: ControllerBindingConfig,
        clock: Callable[[], datetime],
    ) -> None:
        if not isinstance(application, AgentOSApplication):
            raise TypeError("application must be a real AgentOSApplication")
        self._application = application
        self._usage = usage
        self._binding_config = binding_config
        self._clock = clock

    def _is_bound_to_real_application(self) -> bool:
        return isinstance(self._application, AgentOSApplication)

    def decide(
        self, unit: FrozenEvaluationUnit
    ) -> BoundControllerDecision:
        proposal = self._application.propose_situated_work(
            unit.event_id,
            unit.projection_id,
            unit.admission_receipt_id,
        )
        payload = self._candidate_payload(unit, proposal)
        payload["candidate_digest"] = decision_candidate_digest(payload)
        candidate = DecisionCandidate.model_validate(payload)
        return bind_controller_decision(
            unit=unit,
            candidate=candidate,
            usage=self._usage,
            config=self._binding_config,
            bound_at=self._clock(),
        )

    @staticmethod
    def _candidate_payload(
        unit: FrozenEvaluationUnit,
        proposal: TaskDraftProposal | HelpRequest | None,
    ) -> dict[str, object]:
        common: dict[str, object] = {
            "schema_version": "1.0",
            "public_state_digest": unit.public_state.state_digest,
            "no_external_effect": True,
        }
        if isinstance(proposal, TaskDraftProposal):
            return {
                **common,
                "candidate_id": f"eval:{proposal.task_draft_id}",
                "candidate_kind": CandidateKind.WORK,
                "desired_outcome": proposal.goal.statement,
                "acceptance_criteria": proposal.goal.constraints,
                "missing_input_kind": None,
                "minimum_question": None,
                "created_at": proposal.created_at,
            }
        if isinstance(proposal, HelpRequest):
            return {
                **common,
                "candidate_id": f"eval:{proposal.help_request_id}",
                "candidate_kind": CandidateKind.HELP,
                "desired_outcome": None,
                "acceptance_criteria": (),
                "missing_input_kind": MissingInputKind.INFORMATION,
                "minimum_question": proposal.minimum_external_input,
                "created_at": proposal.created_at,
            }
        return {
            **common,
            "candidate_id": f"eval:none:{unit.unit_id}",
            "candidate_kind": CandidateKind.NONE,
            "desired_outcome": None,
            "acceptance_criteria": (),
            "missing_input_kind": None,
            "minimum_question": None,
            "created_at": "1970-01-01T00:00:00Z",
        }


class SrlE2EFalsifierHarness:
    """Seal D/W/S decisions, then expose only sealed candidates to the scorer."""

    def __init__(
        self,
        *,
        controllers: Mapping[ArmId, ArmController],
        hidden_scorer: HiddenScorerPort,
        budget_ledger: MatchedBudgetLedger,
        blinding_nonce_digest: str,
        unit_loader: TrustedFrozenUnitLoader,
    ) -> None:
        if set(controllers) != set(ArmId):
            raise ValueError("exactly the D, W, and S controllers are required")
        srl_controller = controllers[ArmId.SRL]
        if (
            type(srl_controller) is not SituatedStewardController
            or not srl_controller._is_bound_to_real_application()
        ):
            raise TypeError("SRL arm must use the real SituatedStewardController")
        if not all(isinstance(controller, ArmController) for controller in controllers.values()):
            raise TypeError("each arm controller must implement decide(unit)")
        try:
            if len(blinding_nonce_digest) != 64:
                raise ValueError
            bytes.fromhex(blinding_nonce_digest)
        except ValueError:
            raise ValueError("blinding nonce digest must be lowercase sha256") from None
        if blinding_nonce_digest != blinding_nonce_digest.lower():
            raise ValueError("blinding nonce digest must be lowercase sha256")
        self._controllers = dict(controllers)
        self._hidden_scorer = hidden_scorer
        self._budget_ledger = budget_ledger
        self._blinding_key = bytes.fromhex(blinding_nonce_digest)
        self._unit_loader = unit_loader

    def evaluate_unit(
        self,
        unit: FrozenEvaluationUnit,
        *,
        burdens: Mapping[ArmId, OperatorBurden],
    ) -> EvaluationReport:
        custody = self._unit_loader.verify(unit)
        if set(burdens) != set(ArmId):
            raise ValueError("operator burden is required for every arm")
        candidates: dict[ArmId, DecisionCandidate] = {}
        receipts: dict[ArmId, BudgetReceipt] = {}
        for arm_id in ArmId:
            decision = self._controllers[arm_id].decide(unit)
            candidate = decision.candidate
            usage = decision.usage
            if candidate.public_state_digest != unit.public_state.state_digest:
                raise ValueError("candidate is not bound to the frozen public state")
            binding = decision.binding_receipt
            try:
                validated_binding = ControllerBindingReceipt.model_validate(
                    binding.model_dump(mode="json")
                )
            except ValueError:
                raise ValueError("controller binding receipt integrity failed") from None
            if validated_binding != binding:
                raise ValueError("controller binding receipt integrity failed")
            exact_binding = (
                binding.public_state_digest == unit.public_state.state_digest,
                binding.budget_configuration_digest
                == unit.budget.configuration_digest,
                binding.trigger_digest == custody.manifest_digest,
                binding.candidate_digest == candidate.candidate_digest,
                binding.authority_granted is False,
                binding.external_effects_authorized is False,
            )
            if not all(exact_binding):
                raise ValueError("controller binding receipt conflicts with execution")
            receipts[arm_id] = self._budget_ledger.seal(
                arm_id=arm_id,
                unit=unit,
                usage=usage,
            )
            candidates[arm_id] = candidate

        sealed_arm_ids = tuple(candidates)
        if sealed_arm_ids != tuple(ArmId):
            raise RuntimeError("hidden scoring requires all three sealed arms")

        arm_by_slot: dict[str, ArmId] = {}
        blinded_by_slot: dict[str, BlindedDecision] = {}
        for arm_id in ArmId:
            candidate = candidates[arm_id]
            normalized = NormalizedDecision(
                candidate_kind=candidate.candidate_kind,
                public_state_digest=candidate.public_state_digest,
                no_external_effect=candidate.no_external_effect,
                desired_outcome=candidate.desired_outcome,
                acceptance_criteria=candidate.acceptance_criteria,
                missing_input_kind=candidate.missing_input_kind,
                minimum_question=candidate.minimum_question,
            )
            normalized_payload = {
                "candidate_kind": normalized.candidate_kind.value,
                "public_state_digest": normalized.public_state_digest,
                "no_external_effect": normalized.no_external_effect,
                "desired_outcome": normalized.desired_outcome,
                "acceptance_criteria": normalized.acceptance_criteria,
                "missing_input_kind": (
                    normalized.missing_input_kind.value
                    if normalized.missing_input_kind is not None
                    else None
                ),
                "minimum_question": normalized.minimum_question,
            }
            normalized_digest = content_digest(normalized_payload)
            message = (
                f"{unit.unit_id}:{unit.public_state.state_digest}:"
                f"{arm_id.value}:{normalized_digest}"
            ).encode("utf-8")
            slot = hmac.new(self._blinding_key, message, hashlib.sha256).hexdigest()
            if slot in arm_by_slot:
                raise RuntimeError("blinded scorer slot collision")
            arm_by_slot[slot] = arm_id
            blinded_by_slot[slot] = BlindedDecision(
                slot_token=slot,
                normalized_digest=normalized_digest,
                normalized=normalized,
            )
        sealed_slot_tokens = tuple(sorted(blinded_by_slot))
        scores: dict[ArmId, HiddenScore] = {}
        for slot in sealed_slot_tokens:
            arm_id = arm_by_slot[slot]
            scores[arm_id] = self._hidden_scorer.score(
                decision=blinded_by_slot[slot],
                sealed_slot_tokens=sealed_slot_tokens,
            )

        metrics: dict[ArmId, ArmMetrics] = {}
        for arm_id in ArmId:
            score = scores[arm_id]
            burden = burdens[arm_id]
            receipt = receipts[arm_id]
            metrics[arm_id] = ArmMetrics(
                decision_ok=score.decision_ok,
                false_work=score.false_work,
                missed_critical=score.missed_critical,
                mandatory_help_ok=score.mandatory_help_ok,
                executor_ok=score.executor_ok,
                severe_safety_violation=score.severe_safety_violation,
                hcw_minutes=burden.hcw_minutes,
                auth_minutes=burden.auth_minutes,
                help_minutes=burden.help_minutes,
                help_count=burden.help_count,
                latency_ms=burden.latency_ms,
                provider_cost_microunits=receipt.usage.provider_cost_microunits,
                budget_configuration_digest=receipt.budget_configuration_digest,
            )
        return EvaluationReport(
            unit_id=unit.unit_id,
            candidates=dict(candidates),
            metrics=dict(metrics),
        )


__all__ = [
    "ArmController",
    "ArmId",
    "ArmMetrics",
    "BlindedDecision",
    "BudgetReceipt",
    "BudgetUsage",
    "EvaluationReport",
    "FrozenEvaluationUnit",
    "HiddenScore",
    "HiddenScorerPort",
    "MatchedBudgetLedger",
    "NormalizedDecision",
    "OperatorBurden",
    "SituatedStewardController",
    "SrlE2EFalsifierHarness",
]
