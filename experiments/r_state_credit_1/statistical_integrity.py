"""Executable arm-order integrity gates for the R-STATE recast."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import ClassVar, Hashable, Sequence

from experiments.r_state_credit_1.contracts import ArmId, ScenarioFamily


_CANONICAL_SCHEMA_VERSION = "r-state-credit-1-arm-order-integrity-v2"
_CANONICAL_G3_ALGORITHM = "PEARSON_CHI_SQUARE_ALL_POSITION_ARM_CELLS"
_CANONICAL_G3_ALPHA = 0.05
_CANONICAL_G3_MIN_EXPECTED_COUNT = 5.0
_CANONICAL_G4_ALGORITHM = "MILLER_MADOW_BIAS_ADJUSTED_NMI_MAX_OVER_AXES"
_CANONICAL_G4_AXES = ("family", "seed", "checkpoint")
_CANONICAL_G4_THRESHOLD = 0.05
_CANONICAL_SAMPLING = "ALL_DECLARED_DEVELOPMENT_EPISODES_ALL_FOUR_CHECKPOINTS"
_CANONICAL_ARM_ROSTER = tuple(arm.value for arm in ArmId)
_CANONICAL_FAMILIES = tuple(family.value for family in ScenarioFamily)
_CANONICAL_SEEDS = tuple(range(1009, 1124))
_CANONICAL_CHECKPOINTS = (0, 1, 2, 3)


@dataclass(frozen=True, slots=True)
class ArmOrderIntegrityContract:
    """Canonical algorithms and population; not a result or run authority.

    These are class constants rather than constructor fields.  Callers may
    select neither a friendlier population nor weaker algorithms/thresholds.
    The evaluator independently checks the complete constant set at entry so
    a subclass or class-level mutation also fails closed.
    """

    schema_version: ClassVar[str] = _CANONICAL_SCHEMA_VERSION
    g3_algorithm: ClassVar[str] = _CANONICAL_G3_ALGORITHM
    g3_alpha: ClassVar[float] = _CANONICAL_G3_ALPHA
    g3_min_expected_count: ClassVar[float] = _CANONICAL_G3_MIN_EXPECTED_COUNT
    g4_algorithm: ClassVar[str] = _CANONICAL_G4_ALGORITHM
    g4_axes: ClassVar[tuple[str, ...]] = _CANONICAL_G4_AXES
    g4_threshold: ClassVar[float] = _CANONICAL_G4_THRESHOLD
    sampling: ClassVar[str] = _CANONICAL_SAMPLING
    declared_arm_roster: ClassVar[tuple[str, ...]] = _CANONICAL_ARM_ROSTER
    declared_families: ClassVar[tuple[str, ...]] = _CANONICAL_FAMILIES
    declared_seeds: ClassVar[tuple[int, ...]] = _CANONICAL_SEEDS
    declared_checkpoints: ClassVar[tuple[int, ...]] = _CANONICAL_CHECKPOINTS


@dataclass(frozen=True, slots=True)
class ArmOrderIntegrityReceipt:
    g3_chi_square: float
    g3_degrees_of_freedom: int
    g3_p_value: float
    g3_expected_count: float
    g4_adjusted_nmi_by_axis: dict[str, float]
    g4_max_adjusted_nmi: float
    passed: bool


def _require_canonical_contract(contract: ArmOrderIntegrityContract) -> None:
    if type(contract) is not ArmOrderIntegrityContract:
        raise ValueError("integrity contract must be the canonical contract type")
    actual = (
        contract.schema_version,
        contract.g3_algorithm,
        contract.g3_alpha,
        contract.g3_min_expected_count,
        contract.g4_algorithm,
        contract.g4_axes,
        contract.g4_threshold,
        contract.sampling,
        contract.declared_arm_roster,
        contract.declared_families,
        contract.declared_seeds,
        contract.declared_checkpoints,
    )
    expected = (
        _CANONICAL_SCHEMA_VERSION,
        _CANONICAL_G3_ALGORITHM,
        _CANONICAL_G3_ALPHA,
        _CANONICAL_G3_MIN_EXPECTED_COUNT,
        _CANONICAL_G4_ALGORITHM,
        _CANONICAL_G4_AXES,
        _CANONICAL_G4_THRESHOLD,
        _CANONICAL_SAMPLING,
        _CANONICAL_ARM_ROSTER,
        _CANONICAL_FAMILIES,
        _CANONICAL_SEEDS,
        _CANONICAL_CHECKPOINTS,
    )
    if actual != expected:
        raise ValueError("integrity contract constants differ from canonical values")


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

    _require_canonical_contract(contract)
    if not rows:
        raise ValueError("rows must not be empty")
    if any(len(row) != 4 for row in rows):
        raise ValueError("each row must bind permutation/family/seed/checkpoint")
    expected_metadata = {
        (family, seed, checkpoint)
        for family in contract.declared_families
        for seed in contract.declared_seeds
        for checkpoint in contract.declared_checkpoints
    }
    actual_metadata = [(row[1], row[2], row[3]) for row in rows]
    if len(actual_metadata) != len(expected_metadata) or set(actual_metadata) != (
        expected_metadata
    ):
        raise ValueError(
            "rows must cover the declared development Cartesian product exactly once"
        )
    permutations = [row[0] for row in rows]
    decoded = [tuple(value.split(",")) for value in permutations]
    if any(len(order) != 4 or len(set(order)) != 4 for order in decoded):
        raise ValueError("permutation row is not a four-arm permutation")
    declared_roster = set(contract.declared_arm_roster)
    if len(declared_roster) != 4 or any(
        set(order) != declared_roster for order in decoded
    ):
        raise ValueError(
            "permutation row must contain the declared four-arm roster; "
            "the declaration is canonical"
        )
    expected = len(rows) / 4
    counts = Counter((position, arm) for order in decoded for position, arm in enumerate(order))
    chi_square = sum(
        (counts[(position, arm)] - expected) ** 2 / expected
        for position in range(4)
        for arm in sorted(set(decoded[0]))
    )
    # Pearson independence for a 4-position x 4-arm contingency table.  Both
    # margins are fixed by complete permutations, so df=(4-1)*(4-1)=9.
    degrees = 9
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
