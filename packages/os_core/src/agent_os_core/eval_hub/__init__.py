from __future__ import annotations

from dataclasses import dataclass
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


__all__ = [
    "EvalCaseOutcome",
    "EvalDimensionResult",
    "EvalThresholdReport",
    "EvalThresholdReporter",
]
