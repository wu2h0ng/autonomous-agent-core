"""Executable arm-order integrity gates for the R-STATE recast."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Hashable, Sequence


@dataclass(frozen=True, slots=True)
class ArmOrderIntegrityContract:
    """Frozen algorithms and thresholds; not a result or run authority."""

    schema_version: str = "r-state-credit-1-arm-order-integrity-v1"
    g3_algorithm: str = "PEARSON_CHI_SQUARE_ALL_POSITION_ARM_CELLS"
    g3_alpha: float = 0.05
    g3_min_expected_count: float = 5.0
    g4_algorithm: str = "MILLER_MADOW_BIAS_ADJUSTED_NMI_MAX_OVER_AXES"
    g4_axes: tuple[str, ...] = ("family", "seed", "checkpoint")
    g4_threshold: float = 0.05
    sampling: str = "ALL_DECLARED_DEVELOPMENT_EPISODES_ALL_FOUR_CHECKPOINTS"


@dataclass(frozen=True, slots=True)
class ArmOrderIntegrityReceipt:
    g3_chi_square: float
    g3_degrees_of_freedom: int
    g3_p_value: float
    g3_expected_count: float
    g4_adjusted_nmi_by_axis: dict[str, float]
    g4_max_adjusted_nmi: float
    passed: bool


def _regularized_gamma_q(a: float, x: float) -> float:
    """Regularized upper incomplete gamma Q(a, x), stdlib-only."""

    if a <= 0 or x < 0:
        raise ValueError("gamma arguments out of range")
    if x == 0:
        return 1.0
    eps = 1e-14
    if x < a + 1:
        term = total = 1.0 / a
        ap = a
        for _ in range(10_000):
            ap += 1
            term *= x / ap
            total += term
            if abs(term) < abs(total) * eps:
                break
        p = total * math.exp(-x + a * math.log(x) - math.lgamma(a))
        return max(0.0, min(1.0, 1.0 - p))
    b = x + 1.0 - a
    c = 1.0 / 1e-300
    d = 1.0 / b
    h = d
    for index in range(1, 10_000):
        an = -index * (index - a)
        b += 2.0
        d = an * d + b
        if abs(d) < 1e-300:
            d = 1e-300
        c = b + an / c
        if abs(c) < 1e-300:
            c = 1e-300
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    q = math.exp(-x + a * math.log(x) - math.lgamma(a)) * h
    return max(0.0, min(1.0, q))


def _entropy(counts: Counter[Hashable], total: int) -> float:
    return -sum((count / total) * math.log(count / total) for count in counts.values())


def _adjusted_nmi(left: Sequence[Hashable], right: Sequence[Hashable]) -> float:
    total = len(left)
    left_counts = Counter(left)
    right_counts = Counter(right)
    joint = Counter(zip(left, right))
    h_left = _entropy(left_counts, total)
    h_right = _entropy(right_counts, total)
    if h_left == 0 or h_right == 0:
        return 0.0
    mutual_information = sum(
        (count / total)
        * math.log((count * total) / (left_counts[lvalue] * right_counts[rvalue]))
        for (lvalue, rvalue), count in joint.items()
    )
    finite_sample_bias = (
        (len(left_counts) - 1) * (len(right_counts) - 1) / (2 * total)
    )
    denominator = max(1e-15, math.sqrt(h_left * h_right) - finite_sample_bias)
    return max(0.0, (mutual_information - finite_sample_bias) / denominator)


def evaluate_arm_order_integrity(
    rows: Sequence[tuple[str, str, int, int]],
    contract: ArmOrderIntegrityContract,
) -> ArmOrderIntegrityReceipt:
    """Evaluate G3 and G4 over complete permutation/family/seed/checkpoint rows."""

    if not rows:
        raise ValueError("rows must not be empty")
    if any(len(row) != 4 for row in rows):
        raise ValueError("each row must bind permutation/family/seed/checkpoint")
    permutations = [row[0] for row in rows]
    decoded = [tuple(value.split(",")) for value in permutations]
    if any(len(order) != 4 or len(set(order)) != 4 for order in decoded):
        raise ValueError("permutation row is not a four-arm permutation")
    expected = len(rows) / 4
    counts = Counter((position, arm) for order in decoded for position, arm in enumerate(order))
    chi_square = sum(
        (counts[(position, arm)] - expected) ** 2 / expected
        for position in range(4)
        for arm in sorted(set(decoded[0]))
    )
    degrees = 12
    p_value = _regularized_gamma_q(degrees / 2, chi_square / 2)
    axes: dict[str, Sequence[Hashable]] = {
        "family": [row[1] for row in rows],
        "seed": [row[2] for row in rows],
        "checkpoint": [row[3] for row in rows],
    }
    nmis = {name: _adjusted_nmi(permutations, axes[name]) for name in contract.g4_axes}
    maximum = max(nmis.values())
    passed = (
        expected >= contract.g3_min_expected_count
        and p_value > contract.g3_alpha
        and maximum <= contract.g4_threshold
    )
    return ArmOrderIntegrityReceipt(
        g3_chi_square=chi_square,
        g3_degrees_of_freedom=degrees,
        g3_p_value=p_value,
        g3_expected_count=expected,
        g4_adjusted_nmi_by_axis=nmis,
        g4_max_adjusted_nmi=maximum,
        passed=passed,
    )
