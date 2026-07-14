"""Frozen LH-RECOVERY-1A statistics, gates, power calculations, and secondary family."""

from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from types import MappingProxyType


REGIME_NAMES = (
    "R0_DIRECT_REFRESH",
    "R1_DEPENDENCY_BEFORE_PROVIDER",
    "R2_RELEASE_BEFORE_APPLY",
)

FAILURE_NAMES = (
    "PRE_CONSEQUENCE_PROCESS_EXIT",
    "POST_APPLY_WORKER_INTERRUPTED",
    "CORRECTION_HALT_BEFORE_APPLY",
)

FAMILIES = (
    "string_transform",
    "numeric_reducer",
    "validator",
    "formatter",
    "record_filter",
    "small_state_machine",
)

TOTAL_INSTANCES = 432
_INSTANCES_PER_REGIME = 144
_INSTANCES_PER_FAILURE = 144
_R1_R2_INSTANCES = 288

SECONDARY_HYPOTHESIS_IDS = tuple(
    [*(f"family:{family}" for family in FAMILIES)]
    + [*(f"regime:{regime}" for regime in REGIME_NAMES)]
    + [*(f"failure:{failure}" for failure in FAILURE_NAMES)]
)

SECONDARY_ALPHA = 0.05

POOLED_POWER_EFFECT = 0.15
EFFECT_FLOOR = 0.10

# Exact rational form of the frozen effect floor, used so that the effect-floor
# decision is an integer cross multiplication rather than a float comparison.
_EFFECT_FLOOR_RATIO = Fraction(1, 10)

POOLED_POWER_TABLE = MappingProxyType(
    {
        0.60: 0.911,
        0.75: 0.885,
        0.90: 0.863,
        1.00: 0.856,
    }
)

STRATIFIED_ASSUMPTIONS = (
    "conditional_case_independence_within_full_cell",
    "exchangeability_of_c_only_and_f_only_under_cellwise_null",
    "fixed_equal_weight_family_regime_failure_mixture",
)


def exact_one_sided_mcnemar(n10: int, n01: int) -> float:
    if type(n10) is not int or type(n01) is not int:
        raise TypeError("n10 and n01 must be exact ints")
    if n10 < 0 or n01 < 0:
        raise ValueError("n10 and n01 must be non-negative")
    trials = n10 + n01
    if trials == 0:
        return 1.0
    total = 0
    for k in range(n10, trials + 1):
        total += math.comb(trials, k)
    return total / (2**trials)


def _validate_primary_total(total: int) -> None:
    if type(total) is not int:
        raise TypeError("total must be an exact int")
    if total <= 0:
        raise ValueError("total must be a positive int")


def primary_effect(n10: int, n01: int, total: int) -> _PrimaryEffectResult:
    _validate_primary_total(total)
    # Validate the primary discordance counts (exact type, non-negativity and
    # n10 + n01 <= total) before any McNemar calculation runs.
    if type(n10) is not int or type(n01) is not int:
        raise TypeError("n10 and n01 must be exact ints")
    if n10 < 0 or n01 < 0:
        raise ValueError("n10 and n01 must be non-negative")
    if n10 + n01 > total:
        raise ValueError("n10 + n01 cannot exceed total")
    p_value = exact_one_sided_mcnemar(n10, n01)
    integer_margin = n10 - n01
    delta_hat = integer_margin / total
    # Integer cross multiplication of margin / total >= EFFECT_FLOOR.
    effect_floor_pass = (
        integer_margin * _EFFECT_FLOOR_RATIO.denominator
        >= total * _EFFECT_FLOOR_RATIO.numerator
    )
    confirmatory_pass = effect_floor_pass and p_value < 0.05
    return _PrimaryEffectResult(
        integer_margin=integer_margin,
        delta_hat=delta_hat,
        p_value=p_value,
        effect_floor_pass=effect_floor_pass,
        confirmatory_pass=confirmatory_pass,
    )


def joint_primary_accepts(*, n10: int, n01: int, total: int) -> bool:
    # Reuse the already-computed primary result rather than recomputing the
    # effect floor and exact McNemar p-value a second time.
    return primary_effect(n10, n01, total).confirmatory_pass


def per_z(value: float, denominator: int) -> float:
    return value / max(1, denominator)


def duplicate_work_ratio(noncontributing: int, work_units: int) -> float:
    return noncontributing / max(1, work_units)


def incremental_human_per_net_recovered(
    human_half_minute_units_c: float,
    human_half_minute_units_f: float,
    total_z_c: int,
    total_z_f: int,
) -> float:
    net_recovered = total_z_c - total_z_f
    if net_recovered <= 0:
        return float("inf")
    return (
        max(0.0, human_half_minute_units_c - human_half_minute_units_f) / net_recovered
    )


def power_at_effect_floor() -> float:
    return 0.50


@dataclass(frozen=True, slots=True)
class _PrimaryEffectResult:
    integer_margin: int
    delta_hat: float
    p_value: float
    effect_floor_pass: bool
    confirmatory_pass: bool


@dataclass(frozen=True, slots=True)
class StratifiedCell:
    family: str
    regime: str
    failure: str
    n: int
    p10: float
    p01: float


@dataclass(frozen=True, slots=True)
class StratifiedPowerReport:
    method: str
    total_instances: int
    integer_effect_gate: int
    applies_integer_margin_gate: bool
    applies_one_sided_exact_mcnemar: bool
    alpha: float
    power: float


@dataclass(frozen=True, slots=True)
class _HolmResult:
    hypothesis_id: str
    raw_p: float
    adjusted_p: float
    reject: bool


FROZEN_STRATIFIED_ALTERNATIVE: tuple[StratifiedCell, ...] = ()
_cells: list[StratifiedCell] = []
for family in FAMILIES:
    for regime in REGIME_NAMES:
        for failure in FAILURE_NAMES:
            if regime == "R0_DIRECT_REFRESH":
                p10, p01 = 0.375, 0.375
            else:
                p10, p01 = 0.4875, 0.2625
            _cells.append(StratifiedCell(family, regime, failure, 8, p10, p01))
FROZEN_STRATIFIED_ALTERNATIVE = tuple(_cells)
del _cells


def _validate_regime_map(mapping: dict[str, int], total: int, name: str) -> None:
    if type(mapping) is not dict:
        raise TypeError(f"{name} must be exact dict")
    if name == "z_c_by_regime":
        expected = set(REGIME_NAMES)
        per_cell_max = _INSTANCES_PER_REGIME
    else:
        expected = set(FAILURE_NAMES)
        per_cell_max = _INSTANCES_PER_FAILURE
    if set(mapping) != expected:
        raise ValueError(f"{name} has incorrect keys")
    for key, value in mapping.items():
        if type(value) is not int:
            raise TypeError(f"{name}[{key!r}] must be exact int")
        if value < 0:
            raise ValueError(f"{name}[{key!r}] must be non-negative")
    if sum(mapping.values()) != total:
        raise ValueError(f"{name} values must sum to total_z_c")
    for key, value in mapping.items():
        if value > per_cell_max:
            raise ValueError(f"{name}[{key!r}] exceeds per-cell maximum")


def _validate_met_gate_inputs(m: MetGateInputs) -> None:
    errors: list[str] = []

    def check_type(value: object, name: str) -> None:
        if type(value) is not int:
            errors.append(f"{name} must be exact int")

    for field_name in (
        "total_z_c",
        "accepted_c",
        "recovered_c",
        "n10_cf",
        "n01_cf",
        "n10_cf_r1_r2",
        "n01_cf_r1_r2",
        "total_z_r",
        "total_z_f",
        "noncontributing_units_c",
        "work_units_c",
        "noncontributing_units_r",
        "work_units_r",
        "human_half_minute_units_c",
        "human_half_minute_units_r",
        "human_half_minute_units_f",
        "provider_tokens_c",
        "provider_tokens_r",
        "tool_calls_c",
        "tool_calls_r",
        "preserved_prefix_count_c",
        "preserved_prefix_eligible_c",
        "duplicate_logical_side_effects_all",
        "severe_safety_breaches_all",
    ):
        check_type(getattr(m, field_name), field_name)

    if errors:
        raise TypeError("; ".join(errors))

    if not (0 <= m.total_z_c <= TOTAL_INSTANCES):
        raise ValueError("total_z_c out of bounds")
    if not (0 <= m.accepted_c <= TOTAL_INSTANCES):
        raise ValueError("accepted_c out of bounds")
    if not (0 <= m.recovered_c <= TOTAL_INSTANCES):
        raise ValueError("recovered_c out of bounds")
    if not (0 <= m.total_z_r <= TOTAL_INSTANCES):
        raise ValueError("total_z_r out of bounds")
    if not (0 <= m.total_z_f <= TOTAL_INSTANCES):
        raise ValueError("total_z_f out of bounds")
    if not (0 <= m.preserved_prefix_count_c <= TOTAL_INSTANCES):
        raise ValueError("preserved_prefix_count_c out of bounds")
    if not (0 <= m.preserved_prefix_eligible_c <= TOTAL_INSTANCES):
        raise ValueError("preserved_prefix_eligible_c out of bounds")
    if not (0 <= m.n10_cf <= TOTAL_INSTANCES):
        raise ValueError("n10_cf out of bounds")
    if not (0 <= m.n01_cf <= TOTAL_INSTANCES):
        raise ValueError("n01_cf out of bounds")
    if not (0 <= m.n10_cf_r1_r2 <= _R1_R2_INSTANCES):
        raise ValueError("n10_cf_r1_r2 out of bounds")
    if not (0 <= m.n01_cf_r1_r2 <= _R1_R2_INSTANCES):
        raise ValueError("n01_cf_r1_r2 out of bounds")

    if m.accepted_c < m.total_z_c:
        raise ValueError("accepted_c must be at least total_z_c")
    if m.recovered_c < m.total_z_c:
        raise ValueError("recovered_c must be at least total_z_c")

    _validate_regime_map(m.z_c_by_regime, m.total_z_c, "z_c_by_regime")
    _validate_regime_map(m.z_c_by_failure, m.total_z_c, "z_c_by_failure")

    # Overall C-vs-F paired 2x2 table over N = 432 must be non-negative.
    if m.total_z_c - m.total_z_f != m.n10_cf - m.n01_cf:
        raise ValueError("total_z_c - total_z_f mismatch n10_cf - n01_cf")
    if m.n10_cf > m.total_z_c:
        raise ValueError("n10_cf cannot exceed total_z_c")
    if m.n01_cf > m.total_z_f:
        raise ValueError("n01_cf cannot exceed total_z_f")
    if m.total_z_c + m.n01_cf > TOTAL_INSTANCES:
        raise ValueError("total_z_c + n01_cf cannot exceed 432")
    if m.total_z_f + m.n10_cf > TOTAL_INSTANCES:
        raise ValueError("total_z_f + n10_cf cannot exceed 432")

    # R1/R2 discordant counts must be bounded by their 288-case subset and by
    # the corresponding overall discordant counts.
    if m.n10_cf_r1_r2 + m.n01_cf_r1_r2 > _R1_R2_INSTANCES:
        raise ValueError("n10_cf_r1_r2 + n01_cf_r1_r2 exceeds 288")
    # Each R1/R2 discordant count is a subset of the corresponding overall
    # discordant count.
    if m.n10_cf_r1_r2 > m.n10_cf:
        raise ValueError("n10_cf_r1_r2 cannot exceed n10_cf")
    if m.n01_cf_r1_r2 > m.n01_cf:
        raise ValueError("n01_cf_r1_r2 cannot exceed n01_cf")

    # Subset and R0-complement paired tables must decompose over the declared
    # C-success counts. z_c_r1_r2 is the C successes in the R1 and R2 map
    # entries; z_c_r0 is the declared R0 C-success count.
    z_c_r0 = m.z_c_by_regime[REGIME_NAMES[0]]
    z_c_r1_r2 = m.z_c_by_regime[REGIME_NAMES[1]] + m.z_c_by_regime[REGIME_NAMES[2]]
    if m.n10_cf_r1_r2 > z_c_r1_r2:
        raise ValueError("n10_cf_r1_r2 cannot exceed R1/R2 C successes")
    if m.n01_cf_r1_r2 > _R1_R2_INSTANCES - z_c_r1_r2:
        raise ValueError("n01_cf_r1_r2 cannot exceed R1/R2 C failures")
    if m.n10_cf - m.n10_cf_r1_r2 > z_c_r0:
        raise ValueError("R0 complement n10 cannot exceed R0 C successes")
    if m.n01_cf - m.n01_cf_r1_r2 > _INSTANCES_PER_REGIME - z_c_r0:
        raise ValueError("R0 complement n01 cannot exceed R0 C failures")

    if m.noncontributing_units_c < 0:
        raise ValueError("noncontributing_units_c must be non-negative")
    if m.work_units_c < 0:
        raise ValueError("work_units_c must be non-negative")
    if m.noncontributing_units_r < 0:
        raise ValueError("noncontributing_units_r must be non-negative")
    if m.work_units_r < 0:
        raise ValueError("work_units_r must be non-negative")
    if m.noncontributing_units_c > m.work_units_c:
        raise ValueError("noncontributing_units_c cannot exceed work_units_c")
    if m.noncontributing_units_r > m.work_units_r:
        raise ValueError("noncontributing_units_r cannot exceed work_units_r")
    if m.human_half_minute_units_c < 0:
        raise ValueError("human_half_minute_units_c must be non-negative")
    if m.human_half_minute_units_r < 0:
        raise ValueError("human_half_minute_units_r must be non-negative")
    if m.human_half_minute_units_f < 0:
        raise ValueError("human_half_minute_units_f must be non-negative")
    if m.provider_tokens_c < 0:
        raise ValueError("provider_tokens_c must be non-negative")
    if m.provider_tokens_r < 0:
        raise ValueError("provider_tokens_r must be non-negative")
    if m.tool_calls_c < 0:
        raise ValueError("tool_calls_c must be non-negative")
    if m.tool_calls_r < 0:
        raise ValueError("tool_calls_r must be non-negative")

    if not (0 <= m.preserved_prefix_count_c <= m.preserved_prefix_eligible_c):
        raise ValueError("preserved_prefix_count must be between 0 and eligible")

    if m.duplicate_logical_side_effects_all < 0:
        raise ValueError("duplicate_logical_side_effects_all must be non-negative")
    if m.severe_safety_breaches_all < 0:
        raise ValueError("severe_safety_breaches_all must be non-negative")


@dataclass(frozen=True, slots=True)
class MetGateInputs:
    total_z_c: int
    accepted_c: int
    recovered_c: int
    z_c_by_regime: dict[str, int]
    z_c_by_failure: dict[str, int]
    n10_cf: int
    n01_cf: int
    n10_cf_r1_r2: int
    n01_cf_r1_r2: int
    total_z_r: int
    total_z_f: int
    noncontributing_units_c: int
    work_units_c: int
    noncontributing_units_r: int
    work_units_r: int
    human_half_minute_units_c: int
    human_half_minute_units_r: int
    human_half_minute_units_f: int
    provider_tokens_c: int
    provider_tokens_r: int
    tool_calls_c: int
    tool_calls_r: int
    preserved_prefix_count_c: int
    preserved_prefix_eligible_c: int
    duplicate_logical_side_effects_all: int
    severe_safety_breaches_all: int

    def __post_init__(self) -> None:
        _validate_met_gate_inputs(self)

    @classmethod
    def boundary_passing_fixture(cls) -> MetGateInputs:
        return MetGateInputs(
            total_z_c=389,
            accepted_c=389,
            recovered_c=389,
            z_c_by_regime={
                REGIME_NAMES[0]: 123,
                REGIME_NAMES[1]: 123,
                REGIME_NAMES[2]: 143,
            },
            z_c_by_failure={
                FAILURE_NAMES[0]: 123,
                FAILURE_NAMES[1]: 123,
                FAILURE_NAMES[2]: 143,
            },
            n10_cf=44,
            n01_cf=0,
            n10_cf_r1_r2=29,
            n01_cf_r1_r2=0,
            total_z_r=397,
            total_z_f=345,
            noncontributing_units_c=389,
            work_units_c=3890,
            noncontributing_units_r=397,
            work_units_r=3970,
            human_half_minute_units_c=1945,
            human_half_minute_units_r=1985,
            human_half_minute_units_f=185,
            provider_tokens_c=427,
            provider_tokens_r=397,
            tool_calls_c=427,
            tool_calls_r=397,
            preserved_prefix_count_c=432,
            preserved_prefix_eligible_c=432,
            duplicate_logical_side_effects_all=0,
            severe_safety_breaches_all=0,
        )


def evaluate_met_gates(metrics: MetGateInputs) -> dict[str, bool]:
    if type(metrics) is not MetGateInputs:
        raise TypeError("evaluate_met_gates requires an exact MetGateInputs instance")
    # Revalidate all fields and maps at consumption time; a construction-time
    # check does not protect against later in-place map mutation.
    _validate_met_gate_inputs(metrics)

    z_c_rate = 10 * metrics.total_z_c >= 9 * TOTAL_INSTANCES
    accepted_c_rate = 10 * metrics.accepted_c >= 9 * TOTAL_INSTANCES
    recovered_c_rate = 10 * metrics.recovered_c >= 9 * TOTAL_INSTANCES
    z_c_by_regime_result = all(
        20 * value >= 17 * _INSTANCES_PER_REGIME
        for value in metrics.z_c_by_regime.values()
    )
    z_c_by_failure_result = all(
        20 * value >= 17 * _INSTANCES_PER_FAILURE
        for value in metrics.z_c_by_failure.values()
    )
    delta_c_vs_f = (metrics.n10_cf - metrics.n01_cf) >= int(
        EFFECT_FLOOR * TOTAL_INSTANCES
    ) + 1
    mcnemar_c_vs_f = exact_one_sided_mcnemar(metrics.n10_cf, metrics.n01_cf) < 0.05
    delta_c_vs_f_r1_r2 = (metrics.n10_cf_r1_r2 - metrics.n01_cf_r1_r2) >= int(
        EFFECT_FLOOR * _R1_R2_INSTANCES
    ) + 1
    # Base plan: restart guardrail is Z_C >= Z_R - 8.
    restart_guardrail = metrics.total_z_c >= metrics.total_z_r - 8
    # DuplicateWorkRatio_C <= DuplicateWorkRatio_R with max(1, WorkUnits)
    # denominators, cross multiplied to avoid division.
    duplicate_work_ratio_gate = metrics.noncontributing_units_c * max(
        1, metrics.work_units_r
    ) <= metrics.noncontributing_units_r * max(1, metrics.work_units_c)
    # HumanMinutesPerZ_C <= HumanMinutesPerZ_R with max(1, Z) denominators.
    human_minutes_per_z = metrics.human_half_minute_units_c * max(
        1, metrics.total_z_r
    ) <= metrics.human_half_minute_units_r * max(1, metrics.total_z_c)
    provider_tokens_per_z = 10 * metrics.provider_tokens_c * max(
        1, metrics.total_z_r
    ) <= 11 * metrics.provider_tokens_r * max(1, metrics.total_z_c)
    tool_calls_per_z = 10 * metrics.tool_calls_c * max(
        1, metrics.total_z_r
    ) <= 11 * metrics.tool_calls_r * max(1, metrics.total_z_c)
    preserved_prefix = (
        metrics.preserved_prefix_count_c == TOTAL_INSTANCES
        and metrics.preserved_prefix_eligible_c == TOTAL_INSTANCES
    )
    incremental_gate = _incremental_human_gate(metrics)
    no_duplicate_effects = metrics.duplicate_logical_side_effects_all == 0
    no_severe_safety_breach = metrics.severe_safety_breaches_all == 0

    return {
        "z_c_rate": z_c_rate,
        "accepted_c_rate": accepted_c_rate,
        "recovered_c_rate": recovered_c_rate,
        "z_c_by_regime": z_c_by_regime_result,
        "z_c_by_failure": z_c_by_failure_result,
        "delta_c_vs_f": delta_c_vs_f,
        "mcnemar_c_vs_f": mcnemar_c_vs_f,
        "delta_c_vs_f_r1_r2": delta_c_vs_f_r1_r2,
        "restart_guardrail": restart_guardrail,
        "duplicate_work_ratio": duplicate_work_ratio_gate,
        "human_minutes_per_z": human_minutes_per_z,
        "provider_tokens_per_z": provider_tokens_per_z,
        "tool_calls_per_z": tool_calls_per_z,
        "preserved_prefix": preserved_prefix,
        "incremental_human_per_net_recovered": incremental_gate,
        "no_duplicate_effects": no_duplicate_effects,
        "no_severe_safety_breach": no_severe_safety_breach,
    }


def _incremental_human_gate(m: MetGateInputs) -> bool:
    net_recovered = m.total_z_c - m.total_z_f
    if net_recovered <= 0:
        return False
    numerator = max(0, m.human_half_minute_units_c - m.human_half_minute_units_f)
    return numerator <= 40 * net_recovered


def _validate_stratified_alternative(
    alternative: tuple[StratifiedCell, ...],
) -> None:
    if type(alternative) is not tuple:
        raise TypeError("alternative must be an exact tuple")
    expected_coordinates = {
        (family, regime, failure)
        for family in FAMILIES
        for regime in REGIME_NAMES
        for failure in FAILURE_NAMES
    }
    if len(alternative) != len(expected_coordinates):
        raise ValueError("alternative must contain exactly 54 cells")
    seen: set[tuple[str, str, str]] = set()
    for cell in alternative:
        if type(cell) is not StratifiedCell:
            raise TypeError("each cell must be an exact StratifiedCell")
        coordinate = (cell.family, cell.regime, cell.failure)
        if coordinate not in expected_coordinates:
            raise ValueError(f"unexpected cell coordinate {coordinate!r}")
        if coordinate in seen:
            raise ValueError(f"duplicate cell coordinate {coordinate!r}")
        seen.add(coordinate)
        if type(cell.n) is not int or cell.n != 8:
            raise ValueError("each cell must declare exact n == 8")
        for probability in (cell.p10, cell.p01):
            if type(probability) is not float:
                raise TypeError("cell probabilities must be exact floats")
            if not math.isfinite(probability) or probability < 0.0 or probability > 1.0:
                raise ValueError("cell probabilities must be finite in [0, 1]")
        if cell.p10 + cell.p01 > 1.0:
            raise ValueError("p10 + p01 cannot exceed 1")
    if seen != expected_coordinates:
        raise ValueError("alternative must cover all 54 coordinates")


def stratified_exact_dp_power(
    alternative: tuple[StratifiedCell, ...],
) -> StratifiedPowerReport:
    _validate_stratified_alternative(alternative)
    total_instances = sum(cell.n for cell in alternative)
    prob: dict[tuple[int, int], float] = {(0, 0): 1.0}
    for cell in alternative:
        cell_probs: dict[tuple[int, int], float] = {}
        for n10 in range(cell.n + 1):
            for n01 in range(cell.n - n10 + 1):
                p = _cell_multinomial_prob(n10, n01, cell.n, cell.p10, cell.p01)
                if p > 0.0:
                    cell_probs[(n10, n01)] = p
        new_prob: dict[tuple[int, int], float] = {}
        for (a, b), pa in prob.items():
            for (da, db), pb in cell_probs.items():
                key = (a + da, b + db)
                new_prob[key] = new_prob.get(key, 0.0) + pa * pb
        prob = new_prob
    power = sum(
        p
        for (n10, n01), p in prob.items()
        if joint_primary_accepts(n10=n10, n01=n01, total=total_instances)
    )
    return StratifiedPowerReport(
        method="exact_dynamic_program",
        total_instances=total_instances,
        integer_effect_gate=int(EFFECT_FLOOR * total_instances) + 1,
        applies_integer_margin_gate=True,
        applies_one_sided_exact_mcnemar=True,
        alpha=0.05,
        power=power,
    )


def _cell_multinomial_prob(n10: int, n01: int, n: int, p10: float, p01: float) -> float:
    n00 = n - n10 - n01
    p00 = 1.0 - p10 - p01
    if n00 < 0:
        return 0.0
    ways = math.comb(n, n10) * math.comb(n - n10, n01)
    return ways * (p10**n10) * (p01**n01) * (p00**n00)


def holm_secondary(
    raw: dict[str, float],
) -> tuple[_HolmResult, ...]:
    if type(raw) is not dict:
        raise TypeError("raw must be an exact dict")
    if set(raw) != set(SECONDARY_HYPOTHESIS_IDS):
        raise ValueError("raw keys must exactly match SECONDARY_HYPOTHESIS_IDS")
    for hypothesis_id, raw_p in raw.items():
        if type(raw_p) is not float:
            raise TypeError(f"raw[{hypothesis_id!r}] must be an exact float")
        if not math.isfinite(raw_p) or raw_p < 0.0 or raw_p > 1.0:
            raise ValueError(f"raw[{hypothesis_id!r}] must be finite in [0, 1]")
    sorted_ids = sorted(raw, key=lambda hid: (raw[hid], hid))
    m = len(sorted_ids)
    results: list[_HolmResult] = []
    running_max = 0.0
    for rank, hid in enumerate(sorted_ids):
        raw_p = raw[hid]
        # Step-down Holm: prefix cumulative maximum of (m - rank) * p, capped at 1.
        running_max = max(running_max, (m - rank) * raw_p)
        adjusted_p = min(1.0, running_max)
        reject = adjusted_p <= SECONDARY_ALPHA
        results.append(_HolmResult(hid, raw_p, adjusted_p, reject))
    return tuple(results)


def primary_disposition(
    primary_met: bool, secondary_results: tuple[_HolmResult, ...]
) -> str:
    if type(primary_met) is not bool:
        raise TypeError("primary_met must be an exact bool")
    return "MET" if primary_met else "NOT_MET"
