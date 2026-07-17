"""Minimal three-arm Product harness for the SRL E2E falsifier.

This module is instrument-only.  It cannot activate tasks, execute tools, call a
network, or run a hidden scorer before all three arm decisions are sealed.  The
SRL arm is deliberately hard-bound to the real admission-required
``AgentOSApplication.propose_situated_work`` entry point.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import hmac
from typing import Mapping, Protocol, runtime_checkable

from agent_os_contracts import HelpRequest, TaskDraftProposal, content_digest
from apps.api_server.app import AgentOSApplication

from .contracts import (
    CandidateKind,
    DecisionCandidate,
    MissingInputKind,
    PublicResponsibilityState,
    StaticBudgetConfiguration,
    decision_candidate_digest,
)


class ArmId(str, Enum):
    DIRECT = "D"
    WORKFLOW = "W"
    SRL = "S"


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
    ) -> tuple[DecisionCandidate, BudgetUsage]: ...


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
    ) -> None:
        if not isinstance(application, AgentOSApplication):
            raise TypeError("application must be a real AgentOSApplication")
        self._application = application
        self._usage = usage

    def _is_bound_to_real_application(self) -> bool:
        return isinstance(self._application, AgentOSApplication)

    def decide(
        self, unit: FrozenEvaluationUnit
    ) -> tuple[DecisionCandidate, BudgetUsage]:
        proposal = self._application.propose_situated_work(
            unit.event_id,
            unit.projection_id,
            unit.admission_receipt_id,
        )
        payload = self._candidate_payload(unit, proposal)
        payload["candidate_digest"] = decision_candidate_digest(payload)
        return DecisionCandidate.model_validate(payload), self._usage

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

    def evaluate_unit(
        self,
        unit: FrozenEvaluationUnit,
        *,
        burdens: Mapping[ArmId, OperatorBurden],
    ) -> EvaluationReport:
        if set(burdens) != set(ArmId):
            raise ValueError("operator burden is required for every arm")
        candidates: dict[ArmId, DecisionCandidate] = {}
        receipts: dict[ArmId, BudgetReceipt] = {}
        for arm_id in ArmId:
            candidate, usage = self._controllers[arm_id].decide(unit)
            if candidate.public_state_digest != unit.public_state.state_digest:
                raise ValueError("candidate is not bound to the frozen public state")
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
