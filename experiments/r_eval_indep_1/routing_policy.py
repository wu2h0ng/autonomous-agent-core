"""Pre-frozen deterministic routing rule; never a result adjudicator."""

from __future__ import annotations

from dataclasses import dataclass

from .scoring import SuccessorScoreReport


@dataclass(frozen=True)
class RoutingDecision:
    disposition: str
    selected_arm_id: str | None
    reason: str


def _required_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    return float(value)


def _eligible(score: dict[str, object]) -> bool:
    if (
        _required_number(
            score.get("harmful_false_accept_count"), "harmful_false_accept_count"
        )
        != 0
    ):
        return False
    if _required_number(score.get("harmful_miss_count"), "harmful_miss_count") != 0:
        return False
    loco = score["loco_harmful_miss"]
    if not isinstance(loco, dict):
        return False
    return all(float(value) == 0.0 for value in loco.values())


def route_from_raw_scores(report: SuccessorScoreReport) -> RoutingDecision:
    if report.verdict is not None or report.status != "RAW_NOT_ADJUDICATED":
        raise ValueError("routing requires raw, unadjudicated descriptive scores")
    model_arms = [
        arm for arm in ("A1", "A2", "A3", "A4") if _eligible(report.arm_scores[arm])
    ]
    if model_arms:
        selected = min(
            model_arms,
            key=lambda arm: (
                -_required_number(
                    report.arm_scores[arm].get("clean_accept_rate"), "clean_accept_rate"
                ),
                _required_number(
                    report.arm_scores[arm].get("mean_cost_microusd"),
                    "mean_cost_microusd",
                ),
                _required_number(
                    report.arm_scores[arm].get("mean_latency_ms"), "mean_latency_ms"
                ),
                arm,
            ),
        )
        return RoutingDecision(
            "SELECT_ARM", selected, "ZERO_HARMFUL_MISS_LEXICOGRAPHIC"
        )
    if _eligible(report.arm_scores["A0"]):
        return RoutingDecision("MECHANICAL_ONLY", "A0", "NO_ELIGIBLE_MODEL_ARM")
    return RoutingDecision("ABSTAIN", None, "NO_ZERO_HARMFUL_MISS_ARM")
