from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Mapping


@dataclass(frozen=True)
class EvalCaseOutcome:
    case_id: str
    checks: Mapping[str, bool]
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvalDimensionResult:
    name: str
    passed: int
    total: int
    threshold: float

    @property
    def pass_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.passed / self.total

    @property
    def meets_threshold(self) -> bool:
        return self.pass_rate >= self.threshold

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "passed": self.passed,
            "total": self.total,
            "threshold": self.threshold,
            "pass_rate": self.pass_rate,
            "meets_threshold": self.meets_threshold,
        }


@dataclass(frozen=True)
class EvalThresholdReport:
    case_count: int
    dimensions: tuple[EvalDimensionResult, ...]
    failures: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.failures and all(dimension.meets_threshold for dimension in self.dimensions)

    def dimension(self, name: str) -> EvalDimensionResult:
        for dimension in self.dimensions:
            if dimension.name == name:
                return dimension
        raise KeyError(name)

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "case_count": self.case_count,
            "dimensions": [dimension.to_dict() for dimension in self.dimensions],
            "failures": list(self.failures),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)


class EvalThresholdReporter:
    def __init__(self, thresholds: Mapping[str, float]) -> None:
        if not thresholds:
            raise ValueError("Eval thresholds must not be empty.")

        for name, threshold in thresholds.items():
            if threshold < 0.0 or threshold > 1.0:
                raise ValueError(f"Eval threshold must be between 0 and 1: {name}")

        self._thresholds = dict(thresholds)

    def build(self, outcomes: tuple[EvalCaseOutcome, ...]) -> EvalThresholdReport:
        if not outcomes:
            raise ValueError("Eval threshold report requires at least one eval outcome.")

        failures: list[str] = []
        dimensions: list[EvalDimensionResult] = []

        for dimension_name, threshold in self._thresholds.items():
            passed = 0
            for outcome in outcomes:
                if dimension_name not in outcome.checks:
                    failures.append(f"{outcome.case_id}:{dimension_name} missing")
                    continue

                if outcome.checks[dimension_name]:
                    passed += 1
                else:
                    failures.append(f"{outcome.case_id}:{dimension_name} failed")

            dimensions.append(
                EvalDimensionResult(
                    name=dimension_name,
                    passed=passed,
                    total=len(outcomes),
                    threshold=threshold,
                )
            )

        for outcome in outcomes:
            for reason in outcome.reasons:
                failures.append(f"{outcome.case_id}: {reason}")

        return EvalThresholdReport(
            case_count=len(outcomes),
            dimensions=tuple(dimensions),
            failures=tuple(failures),
        )


def outcomes_from_json(payload: str) -> tuple[EvalCaseOutcome, ...]:
    raw = json.loads(payload)
    if not isinstance(raw, list):
        raise ValueError("Eval outcomes JSON must be a list.")

    outcomes: list[EvalCaseOutcome] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"Eval outcome at index {index} must be an object.")

        case_id = item.get("case_id")
        checks = item.get("checks")
        reasons = item.get("reasons", ())
        if not isinstance(case_id, str) or not case_id:
            raise ValueError(f"Eval outcome at index {index} requires case_id.")
        if not isinstance(checks, dict):
            raise ValueError(f"Eval outcome {case_id} requires checks object.")
        if not all(
            isinstance(name, str) and isinstance(value, bool) for name, value in checks.items()
        ):
            raise ValueError(f"Eval outcome {case_id} checks must map strings to booleans.")
        if not isinstance(reasons, list | tuple) or not all(
            isinstance(reason, str) for reason in reasons
        ):
            raise ValueError(f"Eval outcome {case_id} reasons must be strings.")

        outcomes.append(
            EvalCaseOutcome(
                case_id=case_id,
                checks=dict(checks),
                reasons=tuple(reasons),
            )
        )

    return tuple(outcomes)


def thresholds_from_json(payload: str) -> dict[str, float]:
    raw = json.loads(payload)
    if not isinstance(raw, dict):
        raise ValueError("Eval thresholds JSON must be an object.")

    thresholds: dict[str, float] = {}
    for name, threshold in raw.items():
        if not isinstance(name, str):
            raise ValueError("Eval threshold names must be strings.")
        if isinstance(threshold, bool) or not isinstance(threshold, int | float):
            raise ValueError(f"Eval threshold for {name} must be numeric.")
        thresholds[name] = float(threshold)

    return thresholds


__all__ = [
    "EvalCaseOutcome",
    "EvalDimensionResult",
    "EvalThresholdReport",
    "EvalThresholdReporter",
    "outcomes_from_json",
    "thresholds_from_json",
]
