from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock
from typing import Callable

from agent_os_contracts import (
    EnvironmentBinding,
    Mandate,
    MandateRatificationReceipt,
    MandateStatus,
    StandingMission,
    content_digest,
)

from .errors import SituationalTrustDenied
from .srl_ports import MandateRegistryPort


class InMemoryMandateRegistry(MandateRegistryPort):
    """In-memory registry of ratified Mandates and StandingMission versions."""

    durable = False

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        now: datetime | None = None,
    ) -> None:
        self._lock = RLock()
        self._mandates: dict[str, Mandate] = {}
        self._receipts: dict[str, MandateRatificationReceipt] = {}
        self._missions: dict[str, StandingMission] = {}
        self._bindings: dict[str, EnvironmentBinding] = {}
        self._assessor_policy_digests: dict[str, str] = {}
        self._clock = clock or (lambda: now or datetime.now(timezone.utc))

    def ratify_mandate(
        self, mandate: Mandate, receipt: MandateRatificationReceipt
    ) -> None:
        with self._lock:
            if mandate.mandate_id != receipt.mandate_id:
                raise SituationalTrustDenied("receipt mandate_id mismatch")
            expected_digest = content_digest(mandate)
            if receipt.mandate_digest != expected_digest:
                raise SituationalTrustDenied("receipt mandate_digest mismatch")
            if mandate.status not in {MandateStatus.RATIFIED, MandateStatus.ACTIVE}:
                raise SituationalTrustDenied("mandate is not ratified or active")
            self._mandates[mandate.mandate_id] = mandate
            self._receipts[mandate.mandate_id] = receipt
            self._assessor_policy_digests[mandate.mandate_id] = "sha256:assessor-policy"

    def get_mandate(self, mandate_id: str) -> Mandate:
        with self._lock:
            mandate = self._mandates.get(mandate_id)
            if mandate is None:
                raise SituationalTrustDenied("mandate is unavailable")
            return mandate

    def current_ratified_mission(self, mandate_id: str) -> StandingMission:
        with self._lock:
            mandate = self._mandates.get(mandate_id)
            if mandate is None:
                raise SituationalTrustDenied("mandate is unavailable")
            if mandate.status not in {MandateStatus.RATIFIED, MandateStatus.ACTIVE}:
                raise SituationalTrustDenied("mandate is not ratified or active")
            if mandate.expires_at <= self._clock():
                raise SituationalTrustDenied("mandate has expired")
            mission = self._missions.get(mandate_id)
            if mission is None:
                raise SituationalTrustDenied("standing mission is unavailable")
            expected_digest = content_digest(mandate)
            if mission.parent_mandate_digest != expected_digest:
                raise SituationalTrustDenied("standing mission parent digest mismatch")
            if mission.expires_at <= self._clock():
                raise SituationalTrustDenied("standing mission has expired")
            return mission

    def register_mission(self, mission: StandingMission) -> None:
        """Register a StandingMission for testing; not part of the public port."""
        with self._lock:
            self._missions[mission.mandate_id] = mission

    def register_binding(self, binding: EnvironmentBinding) -> None:
        """Register an exact authorized M0 environment binding."""
        with self._lock:
            mandate = self._mandates.get(binding.mandate_id)
            if mandate is None:
                raise SituationalTrustDenied("binding mandate is unavailable")
            if (
                binding.tenant_id != mandate.tenant_id
                or binding.workspace_id != mandate.workspace_id
            ):
                raise SituationalTrustDenied("binding scope mismatch")
            existing = self._bindings.get(binding.binding_id)
            if existing is not None:
                if content_digest(existing) != content_digest(binding):
                    raise SituationalTrustDenied(
                        "binding canonical digest conflicts with existing binding_id"
                    )
                return
            self._bindings[binding.binding_id] = binding

    def authorized_binding(self, binding_id: str) -> EnvironmentBinding:
        with self._lock:
            binding = self._bindings.get(binding_id)
            if binding is None:
                raise SituationalTrustDenied("authorized binding is unavailable")
            return binding

    def expected_assessor_policy_digest(self, mandate_id: str) -> str:
        with self._lock:
            if mandate_id not in self._assessor_policy_digests:
                raise SituationalTrustDenied("mandate is unavailable")
            return self._assessor_policy_digests[mandate_id]
