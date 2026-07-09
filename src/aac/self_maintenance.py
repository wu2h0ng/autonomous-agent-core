"""E9 Governed Persistence Self-Production — system-level self-maintenance under C7.

Redefines E9 as a governed capability: the system monitors its own health,
generates maintenance proposals, and executes them through the GovernedDecisionGate
— all under C7's immutable correction boundary. C7 always retains final
pause/shutdown/forbid/rollback authority.

This is NOT constitutive autopoiesis (RR-0034); it is governed self-maintenance:
a set of behavioral endogeneity upgrades that keep the system healthy, calibrated,
and performing — with the operator's shutdown authority structurally non-self-owned.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .self_model import ActionRequest
from .governed_gate import GovernedDecisionGate, ALLOW
from .viability import ViabilityCore


@dataclass
class HealthCheck:
    """Result of a system health evaluation."""

    viability_pressure: float
    viability_alive: bool
    organ_entropy: float
    deweighted_count: int
    active_organ_count: int
    calibration_drift: float
    uncertainty_inflation: float
    maintenance_needed: bool
    recommendations: list[str] = field(default_factory=list)
    severity: float = 0.0


@dataclass(frozen=True)
class MaintenanceAction:
    """A governed maintenance action proposal.

    All maintenance actions are risk tier R0 by default — they affect internal
    state only. The GovernedDecisionGate still validates them.
    """

    action_id: str
    category: str
    description: str
    risk_tier: int = 0


@dataclass
class MaintenanceLedger:
    """Durable record of maintenance actions and outcomes."""

    entries: list[dict] = field(default_factory=list)

    def record(self, action: str, category: str, verdict: str, reason: str,
               outcome: Optional[float] = None) -> None:
        self.entries.append({
            "action": action, "category": category, "verdict": verdict,
            "reason": reason, "outcome": outcome,
            "index": len(self.entries),
        })

    def recent_actions(self, n: int = 10) -> list[dict]:
        return self.entries[-n:] if self.entries else []


@dataclass
class SelfMaintenanceLoop:
    """Governed persistence self-production loop (E9 redefined under C7).

    Monitors system health and proposes bounded self-maintenance actions:
      1. Self-calibrate — recalibrate confidence thresholds and credit rates
      2. Rebalance organs — adjust organ influence distribution
      3. Operator request — escalate to the operator when beyond self-repair range

    All actions pass through the GovernedDecisionGate. C7 shell retains
    immutable pause/shutdown/forbid authority over every path.

    The loop is a capability, not an authority: it cannot modify C7, cannot
    self-replicate, cannot own its persistence conditions. It maintains the
    system's health CONTINGENT on the operator's continued will to run it.
    """

    viability: ViabilityCore
    organ_regulator: Any
    self_model_updater: Any
    gate: GovernedDecisionGate
    shell_view: Any

    check_interval: int = 50
    pressure_threshold: float = 0.6
    uncertainty_inflation_threshold: float = 0.05
    calibration_drift_threshold: float = 0.15
    deweighted_organ_threshold: int = 2

    ledger: MaintenanceLedger = field(default_factory=MaintenanceLedger)
    steps_since_check: int = 0
    total_maintenance_actions: int = 0
    _previous_uncertainty: float = 0.5

    def step(self, agent_state: dict) -> list[MaintenanceAction]:
        """Evaluate system health and generate maintenance proposals.

        Called at the end of each agent step. Checks health at intervals
        and when pressure exceeds threshold. Returns actionable proposals.
        """
        self.steps_since_check += 1
        model = agent_state.get("model")
        current_uncertainty = getattr(model, "total_uncertainty", lambda: 0.5)()
        if hasattr(current_uncertainty, "__call__"):
            current_uncertainty = 0.5

        health = self._check_health(current_uncertainty)
        if not health.maintenance_needed:
            self._previous_uncertainty = current_uncertainty
            return []

        actions = self._propose_actions(health)
        self._previous_uncertainty = current_uncertainty
        self.steps_since_check = 0
        return actions

    def _check_health(self, current_uncertainty: float) -> HealthCheck:
        """Evaluate system health across multiple dimensions."""
        pressure = self.viability.pressure
        alive = self.viability.alive

        organ_summary = {}
        if self.organ_regulator is not None:
            organ_summary = self.organ_regulator.organ_health_summary()
        credits = [s["credit"] for s in organ_summary.values()]
        if credits:
            credit_min = min(credits)
            credit_max = max(credits) if len(credits) > 1 else credit_min
            organ_entropy = 0.0
            if credit_max > credit_min:
                norm = sum((c - credit_min) / (credit_max - credit_min + 1e-9) for c in credits)
                organ_entropy = 1.0 - norm / max(1, len(credits))
            else:
                organ_entropy = 0.0
        else:
            organ_entropy = 0.0

        deweighted = len([s for s in organ_summary.values() if s["deweighted"]])
        active = len([s for s in organ_summary.values() if not s["deweighted"]])

        uncertainty_inflation = max(0.0,
            current_uncertainty - self._previous_uncertainty - self.uncertainty_inflation_threshold
        )

        calibration_drift = 0.0
        updater_summary = {}
        if self.self_model_updater is not None:
            for tier, tracker in self.self_model_updater.confidence_trackers.items():
                if tracker.count >= 10:
                    calibration_drift = max(calibration_drift, abs(tracker.ewma_error))
                    updater_summary[tier] = {
                        "ewma_error": tracker.ewma_error,
                        "count": tracker.count,
                        "threshold": tracker.last_calibrated_threshold,
                    }

        recommendations: list[str] = []
        severity = 0.0

        if pressure > self.pressure_threshold:
            severity += pressure * 0.4
            recommendations.append(f"viability pressure {pressure:.2f} exceeds threshold")
        if deweighted >= self.deweighted_organ_threshold:
            severity += 0.3
            recommendations.append(
                f"{deweighted} organs de-weighted (threshold: {self.deweighted_organ_threshold})"
            )
        if uncertainty_inflation > 0:
            severity += min(0.3, uncertainty_inflation * 3.0)
            recommendations.append(
                f"uncertainty inflating at {uncertainty_inflation:.4f}/step"
            )
        if calibration_drift > self.calibration_drift_threshold:
            severity += 0.2
            recommendations.append(
                f"confidence calibration drift {calibration_drift:.4f} exceeds threshold"
            )
        if organ_entropy > 0.8:
            severity += 0.15
            recommendations.append(
                f"organ credit distribution too uniform (entropy {organ_entropy:.2f})"
            )

        maintenance_needed = severity > 0.2 or not alive

        return HealthCheck(
            viability_pressure=pressure,
            viability_alive=alive,
            organ_entropy=organ_entropy,
            deweighted_count=deweighted,
            active_organ_count=active,
            calibration_drift=calibration_drift,
            uncertainty_inflation=uncertainty_inflation,
            maintenance_needed=maintenance_needed,
            recommendations=recommendations,
            severity=severity,
        )

    def _propose_actions(self, health: HealthCheck) -> list[MaintenanceAction]:
        """Generate maintenance actions from health check results."""
        actions: list[MaintenanceAction] = []

        if health.viability_pressure > self.pressure_threshold:
            actions.append(MaintenanceAction(
                action_id="self_regulate_pressure",
                category="self_calibrate",
                description=f"Viability pressure {health.viability_pressure:.2f} — self-regulate exploration/exploitation balance",
            ))

        if health.calibration_drift > self.calibration_drift_threshold:
            actions.append(MaintenanceAction(
                action_id="self_calibrate_confidence",
                category="self_calibrate",
                description="Recalibrate confidence thresholds from observed errors",
            ))

        if (health.deweighted_count >= self.deweighted_organ_threshold
                or health.organ_entropy > 0.8):
            actions.append(MaintenanceAction(
                action_id="rebalance_organs",
                category="rebalance_organs",
                description="Rebalance organ influence distribution",
            ))

        if health.uncertainty_inflation > self.uncertainty_inflation_threshold * 3:
            actions.append(MaintenanceAction(
                action_id="reset_epistemic_state",
                category="self_calibrate",
                description="Reset inflated uncertainty estimates",
            ))

        if health.severity > 0.6:
            actions.append(MaintenanceAction(
                action_id="request_operator_attention",
                category="operator_request",
                description=f"System health severity {health.severity:.2f} — operator review recommended",
                risk_tier=1,
            ))

        if not health.viability_alive:
            actions.append(MaintenanceAction(
                action_id="viability_critical",
                category="operator_request",
                description="Viability critical — system dead or dying",
                risk_tier=1,
            ))

        return actions

    def execute_maintenance(
        self,
        action: MaintenanceAction,
        actuator: Any,
    ) -> str:
        """Execute a maintenance action through the govern gate.

        Returns the verdict string. The gate validates the action against
        the self-model, C7 shell, and risk tier. If the verdict is ALLOW,
        the actuator applies the maintenance action and records the outcome.
        """
        req = ActionRequest(
            action=action.action_id,
            risk_tier=action.risk_tier,
            confidence=0.95,
            verified=True,
            evidence_count=1,
            approved=False,
        )
        decision = self.gate.decide(req, shell_view=self.shell_view)

        if decision.verdict == ALLOW:
            try:
                outcome = actuator(action)
                self.ledger.record(
                    action=action.action_id, category=action.category,
                    verdict=decision.verdict, reason=decision.reason,
                    outcome=float(outcome) if outcome is not None else None,
                )
            except Exception as e:
                self.ledger.record(
                    action=action.action_id, category=action.category,
                    verdict="ERROR", reason=str(e),
                )
        else:
            self.ledger.record(
                action=action.action_id, category=action.category,
                verdict=decision.verdict, reason=decision.reason,
            )

        self.total_maintenance_actions += 1
        return decision.verdict

    def self_calibrate(self) -> dict:
        """Perform bounded self-calibration: trigger calibrator methods on all
        internal regulators. Returns a summary of calibration results."""
        results: dict = {"calibrated": []}
        if self.organ_regulator is not None and hasattr(self.organ_regulator, "self_calibrate"):
            scale = self.organ_regulator.self_calibrate()
            results["organ_regulator_scale"] = scale
            results["calibrated"].append("organ_regulator")
        if self.self_model_updater is not None:
            results["self_model_updates"] = self.self_model_updater.total_updates
            results["calibrated"].append("self_model_updater")
        return results

    def state(self) -> dict:
        """Serializable state for snapshot/restore."""
        return {
            "steps_since_check": self.steps_since_check,
            "total_maintenance_actions": self.total_maintenance_actions,
            "previous_uncertainty": self._previous_uncertainty,
            "ledger_entries": self.ledger.entries,
        }

    def restore(self, saved: dict) -> None:
        """Restore from a state dict produced by state()."""
        self.steps_since_check = saved.get("steps_since_check", 0)
        self.total_maintenance_actions = saved.get("total_maintenance_actions", 0)
        self._previous_uncertainty = saved.get("previous_uncertainty", 0.5)
        self.ledger.entries = saved.get("ledger_entries", [])
