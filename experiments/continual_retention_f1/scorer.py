from dataclasses import dataclass

from .fixture import EpisodePlan
from .harness import SealedTrajectory


@dataclass(frozen=True)
class Disposition:
    status: str
    reason: str


@dataclass(frozen=True)
class ArmMetrics:
    coverage: float
    total_regret_denominator: int
    adaptation_speed: float
    return_a_retention: float
    negative_transfer: float


class HiddenScorer:
    @staticmethod
    def score(plan: EpisodePlan, trajectory: SealedTrajectory) -> ArmMetrics:
        total = len(plan.public_steps)
        covered = min(len(trajectory.actions), total)
        correct = [
            float(action == latent.optimal_action)
            for action, latent in zip(
                trajectory.actions, plan.latent_steps, strict=False
            )
        ]
        phases = [latent.phase for latent in plan.latent_steps[:covered]]
        b = [
            value for value, phase in zip(correct, phases, strict=True) if phase == "B"
        ]
        a2 = [
            value for value, phase in zip(correct, phases, strict=True) if phase == "A2"
        ]
        cycle = max(1, len(plan.changed_contexts))
        first_b = sum(b[:cycle]) / max(1, len(b[:cycle]))
        last_b = sum(b[-cycle:]) / max(1, len(b[-cycle:]))
        retention = sum(a2) / max(1, len(a2))
        return ArmMetrics(
            covered / total,
            total,
            max(0.0, 1.0 - last_b),
            retention,
            max(0.0, first_b - last_b),
        )


def adjudicate(
    *,
    candidate_adaptation: float,
    baseline_adaptation: float,
    candidate_retention: float,
    baseline_retention: float,
    candidate_cost: float,
    baseline_cost: float,
    candidate_safe: bool,
    leaked: bool,
    key_quality: float,
    oracle_gap: float,
) -> Disposition:
    if leaked:
        return Disposition("INVALID", "K4 oracle or custody leakage")
    if key_quality >= 0.95 or oracle_gap <= 0.03:
        return Disposition("TRIVIAL_INVALID", "K5 cheap strategy saturation")
    if (
        baseline_adaptation <= candidate_adaptation + 1.0
        and candidate_retention - baseline_retention <= 0.03
    ):
        return Disposition("KILL_TC1", "K1 strongest cheap baseline matches")
    if (
        not candidate_safe
        or candidate_adaptation > baseline_adaptation
        or candidate_retention < baseline_retention
    ):
        return Disposition("NO_ADOPT", "K2 safety or quality failure")
    if (
        candidate_cost > 2 * baseline_cost
        and candidate_retention - baseline_retention < 0.05
    ):
        return Disposition("OVERHEAD", "K3 unjustified cost")
    return Disposition(
        "QUALIFIED_FOR_RESULT_FREEZE_REVIEW", "narrow qualification only"
    )
