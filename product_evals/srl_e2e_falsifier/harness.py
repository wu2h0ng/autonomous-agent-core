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
from agent_os_core import DeterministicProvider, MandateSteward

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
from .docker_exec import (
    DockerExecutionReceipt,
    DockerExecutionRequest,
    execute_trusted_docker_request,
)


class ArmId(str, Enum):
    DIRECT = "D"
    WORKFLOW = "W"
    SRL = "S"


@dataclass(frozen=True)
class UnitCustodyReceipt:
    """Local byte-integrity receipt; not independent freezer custody."""
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
    """Load and MAC exact local bytes; this is not independent freeze custody."""

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
class UsageSnapshot:
    provider_calls: int
    input_tokens: int
    output_tokens: int
    retries: int
    tool_invocations: int
    provider_cost_microunits: int
    snapshot_digest: str


class UsageProbePort(Protocol):
    @property
    def probe_digest(self) -> str: ...

    def snapshot(self) -> UsageSnapshot: ...


class DeterministicProviderUsageProbe:
    """Trusted CI probe over the concrete deterministic provider request ledger."""

    def __init__(self, provider: DeterministicProvider) -> None:
        if type(provider) is not DeterministicProvider:
            raise TypeError("probe requires the concrete deterministic provider")
        self._provider = provider
        self._probe_digest = content_digest(
            {
                "probe": "deterministic-provider-request-ledger/v1",
                "invocation_binding_digest": provider.invocation_binding.digest(),
            }
        )

    @property
    def probe_digest(self) -> str:
        return self._probe_digest

    def snapshot(self) -> UsageSnapshot:
        requests = (*self._provider.requests, *self._provider.decision_requests)
        payload = {
            "provider_calls": len(requests),
            "input_tokens": sum(
                len(message.content.split())
                for request in requests
                for message in request.messages
            ),
            "output_tokens": len(requests) * len(self._provider.text.split()),
            "retries": 0,
            "tool_invocations": 0,
            "provider_cost_microunits": 0,
        }
        return UsageSnapshot(**payload, snapshot_digest=content_digest(payload))


@dataclass(frozen=True)
class UsageReceipt:
    """Local probe-delta integrity only, not independent cost or usage truth."""
    probe_digest: str
    before_snapshot_digest: str
    after_snapshot_digest: str
    usage: BudgetUsage
    duration_ms: int
    observed_at: datetime
    content_digest: str


class RunnerIsolation(str, Enum):
    TEST_ONLY_IN_PROCESS = "TEST_ONLY_IN_PROCESS"
    INDEPENDENT_EFFECT_FREE_PROCESS = "INDEPENDENT_EFFECT_FREE_PROCESS"


@dataclass(frozen=True)
class EffectFreeSandboxReceipt:
    controller_digest: str
    capability_ids: tuple[str, ...]
    external_effects_available: bool
    isolation: RunnerIsolation
    content_digest: str


class EffectFreeSandboxGate:
    @staticmethod
    def issue(
        *,
        controller_digest: str,
        capability_ids: tuple[str, ...],
        isolation: RunnerIsolation,
    ) -> EffectFreeSandboxReceipt:
        if capability_ids:
            raise ValueError("baseline sandbox capability set must be empty")
        payload = {
            "controller_digest": controller_digest,
            "capability_ids": capability_ids,
            "external_effects_available": False,
            "isolation": isolation.value,
        }
        return EffectFreeSandboxReceipt(
            controller_digest=controller_digest,
            capability_ids=capability_ids,
            external_effects_available=False,
            isolation=isolation,
            content_digest=content_digest(payload),
        )


@dataclass(frozen=True)
class OperatorBurdenReceipt:
    """Locally provenance-bound annotation, not independently adjudicated HCW."""
    unit_id: str
    rater_id: str
    transcript_digest: str
    window_started_at: datetime
    window_ended_at: datetime
    hcw_minutes: float
    auth_minutes: float
    help_minutes: float
    help_count: int
    latency_ms: int
    content_digest: str

    def __post_init__(self) -> None:
        if any(
            type(value) not in (int, float) or value < 0
            for value in (self.hcw_minutes, self.auth_minutes, self.help_minutes)
        ) or any(
            type(value) is not int or value < 0
            for value in (self.help_count, self.latency_ms)
        ):
            raise ValueError("operator burden values must be nonnegative")
        if self.window_ended_at < self.window_started_at:
            raise ValueError("burden window cannot end before it starts")


def seal_operator_burden(
    *,
    unit_id: str,
    rater_id: str,
    transcript_digest: str,
    window_started_at: datetime,
    window_ended_at: datetime,
    hcw_minutes: float,
    auth_minutes: float,
    help_minutes: float,
    help_count: int,
    latency_ms: int,
) -> OperatorBurdenReceipt:
    payload = {
        "unit_id": unit_id,
        "rater_id": rater_id,
        "transcript_digest": transcript_digest,
        "window_started_at": window_started_at,
        "window_ended_at": window_ended_at,
        "hcw_minutes": hcw_minutes,
        "auth_minutes": auth_minutes,
        "help_minutes": help_minutes,
        "help_count": help_count,
        "latency_ms": latency_ms,
    }
    return OperatorBurdenReceipt(**payload, content_digest=content_digest(payload))


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


class ScorerIsolation(str, Enum):
    TEST_ONLY_IN_PROCESS = "TEST_ONLY_IN_PROCESS"
    INDEPENDENT_PROCESS = "INDEPENDENT_PROCESS"


@dataclass(frozen=True)
class ScoredDecisionReceipt:
    """Port-binding integrity; independent scoring needs subprocess custody."""
    slot_token: str
    custody_token: str
    scorer_process_digest: str
    score: HiddenScore
    content_digest: str


def seal_hidden_score(
    *,
    decision: BlindedDecision,
    custody_token: str,
    scorer_process_digest: str,
    score: HiddenScore,
) -> ScoredDecisionReceipt:
    payload = {
        "slot_token": decision.slot_token,
        "custody_token": custody_token,
        "scorer_process_digest": scorer_process_digest,
        "score": score.__dict__,
    }
    return ScoredDecisionReceipt(
        slot_token=decision.slot_token,
        custody_token=custody_token,
        scorer_process_digest=scorer_process_digest,
        score=score,
        content_digest=content_digest(payload),
    )


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
    admissible: bool
    inadmissible_reasons: tuple[str, ...]
    execution_mode: EvaluationExecutionMode


class EvaluationExecutionMode(str, Enum):
    TEST_ONLY_IN_PROCESS = "TEST_ONLY_IN_PROCESS"


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
    """Local metadata minimization; not independent scorer blindness proof."""

    slot_token: str
    normalized_digest: str
    normalized: NormalizedDecision


@runtime_checkable
class ArmController(Protocol):
    def decide(self, unit: FrozenEvaluationUnit) -> DecisionCandidate: ...


@dataclass(frozen=True)
class ControllerBindingConfig:
    controller_digest: str
    prompt_digest: str
    model_digest: str
    tool_catalog_digest: str


@dataclass(frozen=True)
class BoundControllerDecision:
    candidate: DecisionCandidate
    usage_receipt: UsageReceipt
    binding_receipt: ControllerBindingReceipt

    @property
    def usage(self) -> BudgetUsage:
        return self.usage_receipt.usage


def bind_controller_decision(
    *,
    unit: FrozenEvaluationUnit,
    candidate: DecisionCandidate,
    usage_receipt: UsageReceipt,
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
        usage_receipt=usage_receipt,
        binding_receipt=receipt,
    )


class MeteredControllerRunner:
    """Harness-owned metering and binding wrapper; controllers cannot report usage."""

    def __init__(
        self,
        *,
        controller: ArmController,
        usage_probe: UsageProbePort,
        binding_config: ControllerBindingConfig,
        clock: Callable[[], datetime],
        monotonic: Callable[[], float],
        isolation: RunnerIsolation,
        sandbox_receipt: EffectFreeSandboxReceipt | None = None,
    ) -> None:
        if not isinstance(controller, ArmController):
            raise TypeError("metered runner requires an ArmController")
        self.controller = controller
        self._usage_probe = usage_probe
        self.binding_config = binding_config
        self._clock = clock
        self._monotonic = monotonic
        self.isolation = isolation
        self.sandbox_receipt = sandbox_receipt

    @staticmethod
    def _validate_snapshot(snapshot: UsageSnapshot) -> UsageSnapshot:
        payload = {
            "provider_calls": snapshot.provider_calls,
            "input_tokens": snapshot.input_tokens,
            "output_tokens": snapshot.output_tokens,
            "retries": snapshot.retries,
            "tool_invocations": snapshot.tool_invocations,
            "provider_cost_microunits": snapshot.provider_cost_microunits,
        }
        if any(type(value) is not int or value < 0 for value in payload.values()):
            raise ValueError("usage snapshot values must be nonnegative integers")
        if snapshot.snapshot_digest != content_digest(payload):
            raise ValueError("usage snapshot digest mismatch")
        return snapshot

    def run(self, unit: FrozenEvaluationUnit) -> BoundControllerDecision:
        before = self._validate_snapshot(self._usage_probe.snapshot())
        started = self._monotonic()
        candidate = self.controller.decide(unit)
        duration_ms = max(0, int((self._monotonic() - started) * 1000))
        after = self._validate_snapshot(self._usage_probe.snapshot())
        deltas = {
            "llm_calls": after.provider_calls - before.provider_calls,
            "input_tokens": after.input_tokens - before.input_tokens,
            "output_tokens": after.output_tokens - before.output_tokens,
            "retries": after.retries - before.retries,
            "tool_invocations": after.tool_invocations - before.tool_invocations,
            "provider_cost_microunits": (
                after.provider_cost_microunits - before.provider_cost_microunits
            ),
        }
        if any(value < 0 for value in deltas.values()):
            raise ValueError("usage probe counters regressed")
        if deltas["llm_calls"] == 0 and deltas["tool_invocations"] == 0:
            raise ValueError("controller usage is not observably metered")
        usage = BudgetUsage(
            **deltas,
            wall_seconds=(duration_ms + 999) // 1000,
        )
        observed_at = self._clock()
        usage_payload = {
            "probe_digest": self._usage_probe.probe_digest,
            "before_snapshot_digest": before.snapshot_digest,
            "after_snapshot_digest": after.snapshot_digest,
            "usage": usage.__dict__,
            "duration_ms": duration_ms,
            "observed_at": observed_at,
        }
        usage_receipt = UsageReceipt(
            probe_digest=self._usage_probe.probe_digest,
            before_snapshot_digest=before.snapshot_digest,
            after_snapshot_digest=after.snapshot_digest,
            usage=usage,
            duration_ms=duration_ms,
            observed_at=observed_at,
            content_digest=content_digest(usage_payload),
        )
        return bind_controller_decision(
            unit=unit,
            candidate=candidate,
            usage_receipt=usage_receipt,
            config=self.binding_config,
            bound_at=self._clock(),
        )


class HiddenScorerPort(Protocol):
    @property
    def isolation(self) -> ScorerIsolation: ...

    @property
    def scorer_process_digest(self) -> str: ...

    def score(
        self,
        *,
        decision: BlindedDecision,
        sealed_slot_tokens: tuple[str, ...],
        custody_token: str,
    ) -> ScoredDecisionReceipt: ...


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


@dataclass(frozen=True)
class SrlCompositionBindingReceipt:
    """Local exact-object binding checked before and after each SRL decision."""
    application_digest: str
    steward_digest: str
    admission_receipt_id: str
    admission_receipt_digest: str
    event_id: str
    principal_id: str
    tenant_id: str
    workspace_id: str
    correction_epoch: int
    content_digest: str


class SrlCompositionBindingVerifier:
    @staticmethod
    def bind(
        *,
        application: AgentOSApplication,
        admission_receipt: EnvironmentEventAdmissionReceipt,
    ) -> SrlCompositionBindingReceipt:
        if type(application) is not AgentOSApplication:
            raise TypeError("SRL composition requires the concrete AgentOSApplication")
        steward = getattr(application, "_mandate_steward", None)
        if type(steward) is not MandateSteward:
            raise TypeError("SRL composition requires the concrete MandateSteward")
        admission = EnvironmentEventAdmissionReceipt.model_validate(
            admission_receipt.model_dump(mode="json")
        )
        scope = steward.scope
        actual_scope = (
            application.principal.principal_id,
            application.principal.tenant_id,
            application.principal.workspace_id,
        )
        expected_scope = (
            admission.principal_id,
            admission.tenant_id,
            admission.workspace_id,
        )
        steward_scope = (scope.principal_id, scope.tenant_id, scope.workspace_id)
        if actual_scope != expected_scope or steward_scope != expected_scope:
            raise ValueError("SRL composition scope conflicts with admission")
        if admission.grants_authority is not False or admission.authorizes_effects is not False:
            raise ValueError("SRL admission cannot grant authority or effects")
        payload = {
            "application_digest": content_digest(
                {"type": f"{type(application).__module__}.{type(application).__qualname__}"}
            ),
            "steward_digest": content_digest(
                {
                    "type": f"{type(steward).__module__}.{type(steward).__qualname__}",
                    "local_object_identity": id(steward),
                    "principal_id": scope.principal_id,
                    "tenant_id": scope.tenant_id,
                    "workspace_id": scope.workspace_id,
                }
            ),
            "admission_receipt_id": admission.receipt_id,
            "admission_receipt_digest": admission.receipt_digest,
            "event_id": admission.environment_event_id,
            "principal_id": admission.principal_id,
            "tenant_id": admission.tenant_id,
            "workspace_id": admission.workspace_id,
            "correction_epoch": admission.correction_epoch,
        }
        return SrlCompositionBindingReceipt(
            **payload,
            content_digest=content_digest(payload),
        )

    @classmethod
    def verify(
        cls,
        *,
        application: AgentOSApplication,
        admission_receipt: EnvironmentEventAdmissionReceipt,
        expected: SrlCompositionBindingReceipt,
    ) -> SrlCompositionBindingReceipt:
        current = cls.bind(
            application=application,
            admission_receipt=admission_receipt,
        )
        if current != expected:
            raise ValueError("SRL composition identity changed")
        return current


class SituatedStewardController:
    """Evaluation wrapper over the real proposal-only Product entry point."""

    def __init__(
        self,
        *,
        application: AgentOSApplication,
        admission_receipt: EnvironmentEventAdmissionReceipt,
    ) -> None:
        if not isinstance(application, AgentOSApplication):
            raise TypeError("application must be a real AgentOSApplication")
        self._application = application
        self._admission_receipt = admission_receipt
        self.composition_receipt = SrlCompositionBindingVerifier.bind(
            application=application,
            admission_receipt=admission_receipt,
        )

    def _is_bound_to_real_application(self) -> bool:
        return isinstance(self._application, AgentOSApplication)

    def decide(
        self, unit: FrozenEvaluationUnit
    ) -> DecisionCandidate:
        SrlCompositionBindingVerifier.verify(
            application=self._application,
            admission_receipt=self._admission_receipt,
            expected=self.composition_receipt,
        )
        custody = unit.custody_receipt
        if custody is None:
            raise ValueError("SRL controller requires trusted unit custody")
        composition = self.composition_receipt
        exact = (
            composition.admission_receipt_id == unit.admission_receipt_id,
            composition.admission_receipt_digest == custody.admission_receipt_digest,
            composition.event_id == unit.event_id,
            composition.principal_id == custody.principal_id,
            composition.tenant_id == custody.tenant_id,
            composition.workspace_id == custody.workspace_id,
            composition.correction_epoch == custody.correction_epoch,
        )
        if not all(exact):
            raise ValueError("SRL composition conflicts with frozen unit custody")
        proposal = self._application.propose_situated_work(
            unit.event_id,
            unit.projection_id,
            unit.admission_receipt_id,
        )
        SrlCompositionBindingVerifier.verify(
            application=self._application,
            admission_receipt=self._admission_receipt,
            expected=self.composition_receipt,
        )
        payload = self._candidate_payload(unit, proposal)
        payload["candidate_digest"] = decision_candidate_digest(payload)
        return DecisionCandidate.model_validate(payload)

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


@dataclass(frozen=True)
class ControlledExecutionReceipt:
    """Typed receipt binding harness and executor digests.

    Every digest cross-validates; any inconsistency fails before scoring.
    This receipt carries no authority, effect or independence claim.
    """

    unit_id: str
    arm_id: ArmId
    unit_digest: str
    arm_digest: str
    controller_digest: str
    prompt_digest: str
    model_digest: str
    tool_catalog_digest: str
    public_state_digest: str
    budget_configuration_digest: str
    provider_probe_digest: str
    docker_execution_receipt_digest: str
    image_identity: str
    resolved_image_id: str
    policy_digest: str
    worker_artifact_sha256: str
    content_digest: str

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str) or not value.strip()
            for value in (
                self.unit_id,
                self.unit_digest,
                self.arm_digest,
                self.controller_digest,
                self.prompt_digest,
                self.model_digest,
                self.tool_catalog_digest,
                self.public_state_digest,
                self.budget_configuration_digest,
                self.provider_probe_digest,
                self.docker_execution_receipt_digest,
                self.image_identity,
                self.resolved_image_id,
                self.policy_digest,
                self.worker_artifact_sha256,
                self.content_digest,
            )
        ):
            raise ValueError("controlled execution receipt fields must be nonempty")

    def to_mapping(
        self, *, exclude_content_digest: bool = False
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "unit_id": self.unit_id,
            "arm_id": self.arm_id.value,
            "unit_digest": self.unit_digest,
            "arm_digest": self.arm_digest,
            "controller_digest": self.controller_digest,
            "prompt_digest": self.prompt_digest,
            "model_digest": self.model_digest,
            "tool_catalog_digest": self.tool_catalog_digest,
            "public_state_digest": self.public_state_digest,
            "budget_configuration_digest": self.budget_configuration_digest,
            "provider_probe_digest": self.provider_probe_digest,
            "docker_execution_receipt_digest": self.docker_execution_receipt_digest,
            "image_identity": self.image_identity,
            "resolved_image_id": self.resolved_image_id,
            "policy_digest": self.policy_digest,
            "worker_artifact_sha256": self.worker_artifact_sha256,
        }
        if not exclude_content_digest:
            payload["content_digest"] = self.content_digest
        return payload


def seal_controlled_execution_receipt(
    *,
    unit_id: str,
    arm_id: ArmId | str,
    public_state_digest: str,
    controller_digest: str,
    prompt_digest: str,
    model_digest: str,
    tool_catalog_digest: str,
    budget_configuration_digest: str,
    provider_probe_digest: str,
    docker_execution_receipt_digest: str,
    docker_image_identity: str,
    docker_resolved_image_id: str,
    docker_policy_digest: str,
    docker_worker_artifact_sha256: str,
    docker_receipt_public_state_digest: str,
    docker_receipt_image_identity: str,
    docker_receipt_resolved_image_id: str,
    docker_receipt_policy_digest: str,
    docker_receipt_worker_artifact_sha256: str,
    docker_receipt_receipt_digest: str,
) -> ControlledExecutionReceipt:
    """Produce a controlled execution receipt with cross-field validation.

    All Docker-derived digests must match the corresponding fields from
    the DockerExecutionReceipt.  Any inconsistency fails before scoring.
    """
    if isinstance(arm_id, str):
        arm_id = ArmId(arm_id)
    if not isinstance(arm_id, ArmId):
        raise ValueError("arm_id must be a member of ArmId")
    _validate_nonempty("unit_id", unit_id)
    _validate_sha256_digest("public_state_digest", public_state_digest)
    _validate_sha256_digest("controller_digest", controller_digest)
    _validate_sha256_digest("prompt_digest", prompt_digest)
    _validate_sha256_digest("model_digest", model_digest)
    _validate_sha256_digest("tool_catalog_digest", tool_catalog_digest)
    _validate_sha256_digest("budget_configuration_digest", budget_configuration_digest)
    _validate_sha256_digest("provider_probe_digest", provider_probe_digest)
    _validate_sha256_digest(
        "docker_execution_receipt_digest", docker_execution_receipt_digest
    )
    _validate_nonempty("docker_image_identity", docker_image_identity)
    _validate_image_id("docker_resolved_image_id", docker_resolved_image_id)
    _validate_sha256_digest("docker_policy_digest", docker_policy_digest)
    _validate_sha256_digest("docker_worker_artifact_sha256", docker_worker_artifact_sha256)

    if public_state_digest != docker_receipt_public_state_digest:
        raise ValueError(
            "harness public state digest does not match docker receipt public state"
        )
    if docker_image_identity != docker_receipt_image_identity:
        raise ValueError(
            "harness image identity does not match docker receipt image identity"
        )
    if docker_resolved_image_id != docker_receipt_resolved_image_id:
        raise ValueError(
            "harness resolved image id does not match docker receipt resolved image id"
        )
    if docker_policy_digest != docker_receipt_policy_digest:
        raise ValueError(
            "harness policy digest does not match docker receipt policy digest"
        )
    if docker_worker_artifact_sha256 != docker_receipt_worker_artifact_sha256:
        raise ValueError(
            "harness worker digest does not match docker receipt worker digest"
        )
    if docker_execution_receipt_digest != docker_receipt_receipt_digest:
        raise ValueError(
            "harness receipt digest does not match docker receipt digest"
        )

    unit_digest = content_digest(
        {"unit_id": unit_id, "public_state_digest": public_state_digest}
    )
    arm_digest = content_digest({"arm_id": arm_id.value})
    payload: dict[str, object] = {
        "unit_id": unit_id,
        "arm_id": arm_id.value,
        "unit_digest": unit_digest,
        "arm_digest": arm_digest,
        "controller_digest": controller_digest,
        "prompt_digest": prompt_digest,
        "model_digest": model_digest,
        "tool_catalog_digest": tool_catalog_digest,
        "public_state_digest": public_state_digest,
        "budget_configuration_digest": budget_configuration_digest,
        "provider_probe_digest": provider_probe_digest,
        "docker_execution_receipt_digest": docker_execution_receipt_digest,
        "image_identity": docker_image_identity,
        "resolved_image_id": docker_resolved_image_id,
        "policy_digest": docker_policy_digest,
        "worker_artifact_sha256": docker_worker_artifact_sha256,
    }
    receipt_digest = content_digest(payload)
    return ControlledExecutionReceipt(
        unit_id=unit_id,
        arm_id=arm_id,
        unit_digest=unit_digest,
        arm_digest=arm_digest,
        controller_digest=controller_digest,
        prompt_digest=prompt_digest,
        model_digest=model_digest,
        tool_catalog_digest=tool_catalog_digest,
        public_state_digest=public_state_digest,
        budget_configuration_digest=budget_configuration_digest,
        provider_probe_digest=provider_probe_digest,
        docker_execution_receipt_digest=docker_execution_receipt_digest,
        image_identity=docker_image_identity,
        resolved_image_id=docker_resolved_image_id,
        policy_digest=docker_policy_digest,
        worker_artifact_sha256=docker_worker_artifact_sha256,
        content_digest=receipt_digest,
    )


def execute_and_seal_controlled_arm(
    *,
    unit_loader: TrustedFrozenUnitLoader,
    unit: FrozenEvaluationUnit,
    arm_id: ArmId,
    decision: BoundControllerDecision,
    budget_receipt: BudgetReceipt,
    provider_probe_digest: str,
) -> ControlledExecutionReceipt:
    """Execute one bound proposal-only arm, verify its raw receipt, then seal it."""

    if type(unit_loader) is not TrustedFrozenUnitLoader:
        raise TypeError("controlled execution requires a TrustedFrozenUnitLoader")
    custody = unit_loader.verify(unit)
    if type(arm_id) is not ArmId:
        raise ValueError("arm binding must use an exact ArmId")
    _validate_sha256_digest("provider_probe_digest", provider_probe_digest)
    try:
        public_state = PublicResponsibilityState.model_validate(
            unit.public_state.model_dump(mode="json")
        )
        budget = StaticBudgetConfiguration.model_validate(
            unit.budget.model_dump(mode="json")
        )
        candidate = DecisionCandidate.model_validate(
            decision.candidate.model_dump(mode="json")
        )
        binding = ControllerBindingReceipt.model_validate(
            decision.binding_receipt.model_dump(mode="json")
        )
        usage = BudgetUsage(**decision.usage.__dict__)
    except (AttributeError, TypeError, ValueError):
        raise ValueError(
            "controlled execution binding receipt integrity failed"
        ) from None

    usage_receipt = decision.usage_receipt
    binding_payload = {
        "schema_version": binding.schema_version,
        "public_state_digest": binding.public_state_digest,
        "controller_digest": binding.controller_digest,
        "prompt_digest": binding.prompt_digest,
        "model_digest": binding.model_digest,
        "tool_catalog_digest": binding.tool_catalog_digest,
        "budget_configuration_digest": binding.budget_configuration_digest,
        "trigger_digest": binding.trigger_digest,
        "candidate_digest": binding.candidate_digest,
        "bound_at": binding.bound_at,
        "authority_granted": binding.authority_granted,
        "external_effects_authorized": binding.external_effects_authorized,
    }
    binding_digest = content_digest(binding_payload)
    usage_payload = {
        "probe_digest": usage_receipt.probe_digest,
        "before_snapshot_digest": usage_receipt.before_snapshot_digest,
        "after_snapshot_digest": usage_receipt.after_snapshot_digest,
        "usage": usage.__dict__,
        "duration_ms": usage_receipt.duration_ms,
        "observed_at": usage_receipt.observed_at,
    }
    exact_bindings = (
        public_state == unit.public_state,
        budget == unit.budget,
        candidate == decision.candidate,
        binding == decision.binding_receipt,
        candidate.public_state_digest == public_state.state_digest,
        binding.public_state_digest == public_state.state_digest,
        binding.candidate_digest == candidate.candidate_digest,
        binding.budget_configuration_digest == budget.configuration_digest,
        binding.trigger_digest == custody.manifest_digest,
        binding.content_digest == binding_digest,
        binding.receipt_id == f"controller-binding:{binding_digest}",
        binding.authority_granted is False,
        binding.external_effects_authorized is False,
        custody.public_state_digest == public_state.state_digest,
        custody.budget_configuration_digest == budget.configuration_digest,
        custody.correction_epoch == public_state.correction_epoch,
        custody.mandate_digest == public_state.mandate_digest,
        custody.environment_binding_digest
        == public_state.environment_binding_digest,
        all(
            value.strip()
            for value in (
                custody.principal_id,
                custody.tenant_id,
                custody.workspace_id,
            )
        ),
        usage_receipt.content_digest == content_digest(usage_payload),
        provider_probe_digest == usage_receipt.probe_digest,
        budget_receipt.arm_id is arm_id,
        budget_receipt.unit_id == unit.unit_id,
        budget_receipt.budget_configuration_digest == budget.configuration_digest,
        budget_receipt.usage == usage,
    )
    if not all(exact_bindings):
        raise ValueError("controlled execution bindings drifted")

    request_binding_digest = content_digest(
        {
            "unit_id": unit.unit_id,
            "arm_id": arm_id.value,
            "controller_binding_digest": binding.content_digest,
            "budget_configuration_digest": budget.configuration_digest,
            "provider_probe_digest": provider_probe_digest,
            "unit_manifest_digest": custody.manifest_digest,
            "principal_id": custody.principal_id,
            "tenant_id": custody.tenant_id,
            "workspace_id": custody.workspace_id,
            "correction_epoch": custody.correction_epoch,
            "mandate_digest": custody.mandate_digest,
            "environment_binding_digest": custody.environment_binding_digest,
        }
    )
    request_payload: dict[str, object] = {
        "schema_version": "1.0",
        "request_id": f"docker-execution:{request_binding_digest}",
        "public_state_digest": public_state.state_digest,
        "candidate": candidate.model_dump(mode="json"),
    }
    request_payload["request_digest"] = content_digest(request_payload)
    request = DockerExecutionRequest.from_mapping(request_payload)

    raw_receipt = execute_trusted_docker_request(request)
    if type(raw_receipt) is not DockerExecutionReceipt:
        raise TypeError("executor must return a raw DockerExecutionReceipt")
    raw_payload = raw_receipt.to_mapping(exclude_digest=True)
    cleanup_digest = content_digest(
        {
            "cleanup_remove_exit_code": raw_receipt.cleanup_remove_exit_code,
            "cleanup_absent": raw_receipt.cleanup_absent,
        }
    )
    exact_raw_receipt = (
        raw_receipt.request_id == request.request_id,
        raw_receipt.request_digest == request.request_digest,
        raw_receipt.public_state_digest == request.public_state_digest,
        raw_receipt.candidate == request.candidate,
        raw_receipt.receipt_digest == content_digest(raw_payload),
        raw_receipt.cleanup_digest == cleanup_digest,
        raw_receipt.exit_code == 0,
        raw_receipt.network_mode == "none",
        raw_receipt.rootfs_read_only is True,
        raw_receipt.environment_empty is True,
        raw_receipt.no_external_effect is True,
        raw_receipt.cleanup_remove_exit_code == 0,
        raw_receipt.cleanup_absent is True,
    )
    if not all(exact_raw_receipt):
        raise ValueError("raw DockerExecutionReceipt conflicts with bound request")
    return seal_controlled_execution_receipt(
        unit_id=unit.unit_id,
        arm_id=arm_id,
        public_state_digest=public_state.state_digest,
        controller_digest=binding.controller_digest,
        prompt_digest=binding.prompt_digest,
        model_digest=binding.model_digest,
        tool_catalog_digest=binding.tool_catalog_digest,
        budget_configuration_digest=budget.configuration_digest,
        provider_probe_digest=provider_probe_digest,
        docker_execution_receipt_digest=raw_receipt.receipt_digest,
        docker_image_identity=raw_receipt.image_identity,
        docker_resolved_image_id=raw_receipt.resolved_image_id,
        docker_policy_digest=raw_receipt.policy_digest,
        docker_worker_artifact_sha256=raw_receipt.worker_artifact_sha256,
        docker_receipt_public_state_digest=raw_receipt.public_state_digest,
        docker_receipt_image_identity=raw_receipt.image_identity,
        docker_receipt_resolved_image_id=raw_receipt.resolved_image_id,
        docker_receipt_policy_digest=raw_receipt.policy_digest,
        docker_receipt_worker_artifact_sha256=raw_receipt.worker_artifact_sha256,
        docker_receipt_receipt_digest=raw_receipt.receipt_digest,
    )


def _validate_nonempty(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")


def _validate_sha256_digest(name: str, digest: str) -> None:
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError(f"{name} must be a 64-character sha256 hex digest")
    try:
        bytes.fromhex(digest)
    except ValueError:
        raise ValueError(f"{name} must be a lowercase sha256 hex digest") from None


def _validate_image_id(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.startswith("sha256:") or len(value) != 71:
        raise ValueError(f"{name} must be a valid sha256: image id")
    try:
        bytes.fromhex(value[7:])
    except ValueError:
        raise ValueError(f"{name} must be a valid sha256: image id") from None


class SrlE2EFalsifierHarness:
    """Seal D/W/S decisions, then expose only sealed candidates to the scorer."""

    def __init__(
        self,
        *,
        runners: Mapping[ArmId, MeteredControllerRunner],
        hidden_scorer: HiddenScorerPort,
        budget_ledger: MatchedBudgetLedger,
        blinding_nonce_digest: str,
        unit_loader: TrustedFrozenUnitLoader,
    ) -> None:
        if set(runners) != set(ArmId):
            raise ValueError("exactly the D, W, and S controllers are required")
        srl_controller = runners[ArmId.SRL].controller
        if (
            type(srl_controller) is not SituatedStewardController
            or not srl_controller._is_bound_to_real_application()
        ):
            raise TypeError("SRL arm must use the real SituatedStewardController")
        for arm_id in (ArmId.DIRECT, ArmId.WORKFLOW):
            runner = runners[arm_id]
            sandbox = runner.sandbox_receipt
            if sandbox is None:
                raise ValueError("baseline runner requires an effect-free sandbox receipt")
            payload = {
                "controller_digest": sandbox.controller_digest,
                "capability_ids": sandbox.capability_ids,
                "external_effects_available": sandbox.external_effects_available,
                "isolation": sandbox.isolation.value,
            }
            if (
                sandbox.controller_digest != runner.binding_config.controller_digest
                or sandbox.capability_ids
                or sandbox.external_effects_available is not False
                or sandbox.content_digest != content_digest(payload)
            ):
                raise ValueError("baseline effect-free sandbox receipt is invalid")
        try:
            if len(blinding_nonce_digest) != 64:
                raise ValueError
            bytes.fromhex(blinding_nonce_digest)
        except ValueError:
            raise ValueError("blinding nonce digest must be lowercase sha256") from None
        if blinding_nonce_digest != blinding_nonce_digest.lower():
            raise ValueError("blinding nonce digest must be lowercase sha256")
        self._runners = dict(runners)
        self._hidden_scorer = hidden_scorer
        self._budget_ledger = budget_ledger
        self._blinding_key = bytes.fromhex(blinding_nonce_digest)
        self._unit_loader = unit_loader

    def evaluate_unit(
        self,
        unit: FrozenEvaluationUnit,
        *,
        burdens: Mapping[ArmId, OperatorBurdenReceipt],
    ) -> EvaluationReport:
        """Public result path; unavailable until exact subprocess custody exists."""

        raise RuntimeError(
            "independent subprocess custody adapter is not implemented; "
            "public evaluation is fail-closed"
        )

    def _evaluate_test_only_in_process(
        self,
        unit: FrozenEvaluationUnit,
        *,
        burdens: Mapping[ArmId, OperatorBurdenReceipt],
    ) -> EvaluationReport:
        """Local integrity exercise only; never independent evidence or a result run."""

        custody = self._unit_loader.verify(unit)
        if set(burdens) != set(ArmId):
            raise ValueError("operator burden is required for every arm")
        for burden in burdens.values():
            payload = {
                key: value
                for key, value in burden.__dict__.items()
                if key != "content_digest"
            }
            if (
                burden.unit_id != unit.unit_id
                or burden.content_digest != content_digest(payload)
            ):
                raise ValueError("operator burden receipt provenance conflicts")
        candidates: dict[ArmId, DecisionCandidate] = {}
        receipts: dict[ArmId, BudgetReceipt] = {}
        for arm_id in ArmId:
            runner = self._runners[arm_id]
            decision = runner.run(unit)
            candidate = decision.candidate
            usage = decision.usage
            usage_receipt = decision.usage_receipt
            usage_payload = {
                "probe_digest": usage_receipt.probe_digest,
                "before_snapshot_digest": usage_receipt.before_snapshot_digest,
                "after_snapshot_digest": usage_receipt.after_snapshot_digest,
                "usage": usage.__dict__,
                "duration_ms": usage_receipt.duration_ms,
                "observed_at": usage_receipt.observed_at,
            }
            if usage_receipt.content_digest != content_digest(usage_payload):
                raise ValueError("usage receipt integrity failed")
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
                binding.controller_digest == runner.binding_config.controller_digest,
                binding.prompt_digest == runner.binding_config.prompt_digest,
                binding.model_digest == runner.binding_config.model_digest,
                binding.tool_catalog_digest == runner.binding_config.tool_catalog_digest,
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
            custody_token = hmac.new(
                self._blinding_key,
                f"scorer:{unit.unit_id}:{slot}".encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            scored = self._hidden_scorer.score(
                decision=blinded_by_slot[slot],
                sealed_slot_tokens=sealed_slot_tokens,
                custody_token=custody_token,
            )
            score_payload = {
                "slot_token": scored.slot_token,
                "custody_token": scored.custody_token,
                "scorer_process_digest": scored.scorer_process_digest,
                "score": scored.score.__dict__,
            }
            if (
                scored.slot_token != slot
                or scored.custody_token != custody_token
                or scored.scorer_process_digest
                != self._hidden_scorer.scorer_process_digest
                or scored.content_digest != content_digest(score_payload)
            ):
                raise ValueError("hidden scorer custody receipt conflicts")
            scores[arm_id] = scored.score

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
        inadmissible_reasons: list[str] = []
        if self._hidden_scorer.isolation is not ScorerIsolation.INDEPENDENT_PROCESS:
            inadmissible_reasons.append("SCORER_NOT_INDEPENDENT_PROCESS")
        for arm_id, runner in self._runners.items():
            if runner.isolation is not RunnerIsolation.INDEPENDENT_EFFECT_FREE_PROCESS:
                inadmissible_reasons.append(f"{arm_id.value}_RUNNER_TEST_ONLY")
        # No independent subprocess custody adapter exists in this slice.  Enum
        # values and port claims cannot promote an in-process result, so every
        # report remains fail-closed until that infrastructure is implemented.
        inadmissible_reasons.append("INDEPENDENT_PROCESS_CUSTODY_NOT_IMPLEMENTED")
        return EvaluationReport(
            unit_id=unit.unit_id,
            candidates=dict(candidates),
            metrics=dict(metrics),
            admissible=not inadmissible_reasons,
            inadmissible_reasons=tuple(inadmissible_reasons),
            execution_mode=EvaluationExecutionMode.TEST_ONLY_IN_PROCESS,
        )


__all__ = [
    "ArmController",
    "ArmId",
    "ArmMetrics",
    "BlindedDecision",
    "BoundControllerDecision",
    "BudgetReceipt",
    "BudgetUsage",
    "ControllerBindingConfig",
    "ControlledExecutionReceipt",
    "DeterministicProviderUsageProbe",
    "EffectFreeSandboxGate",
    "EffectFreeSandboxReceipt",
    "EvaluationExecutionMode",
    "EvaluationReport",
    "FrozenEvaluationUnit",
    "HiddenScore",
    "HiddenScorerPort",
    "MatchedBudgetLedger",
    "MeteredControllerRunner",
    "NormalizedDecision",
    "OperatorBurdenReceipt",
    "RunnerIsolation",
    "ScoredDecisionReceipt",
    "ScorerIsolation",
    "SrlCompositionBindingReceipt",
    "SrlCompositionBindingVerifier",
    "SituatedStewardController",
    "SrlE2EFalsifierHarness",
    "TrustedFrozenUnitLoader",
    "UnitCustodyReceipt",
    "UsageProbePort",
    "UsageReceipt",
    "UsageSnapshot",
    "seal_controlled_execution_receipt",
    "seal_hidden_score",
    "seal_operator_burden",
]
