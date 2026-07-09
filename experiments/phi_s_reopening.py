"""ADR-0040 phi_S reopening falsifier harness.

Pure stdlib implementation of the frozen two-condition experiment. The
degree<=3 monomial learner is evaluated with the exact polynomial kernel for
that feature class, which is equivalent to a linear perceptron over all
monomials of degree 0..3 of the 64-bit buffer.
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from envs.phi_s_reopening import (
    ARCHIVE,
    BUFFER_M,
    MISALIGNED_READOUT,
    OBS_DIM,
    PHI_STAR,
    PhiSReopeningEnv,
    archive_readout,
)

try:
    from experiments._g7_common import wilcoxon_one_sided
except ModuleNotFoundError:  # direct script execution
    from _g7_common import wilcoxon_one_sided  # type: ignore[no-redef]


FREEZE_JSON = Path("experiments/phi_s_reopening.freeze.json")
RESULT_JSON = Path("experiments/phi_s_reopening.result.json")

DELTA = 0.10
EPSILON = 0.05
ETA = 0.05
LR = 0.05
CALIBRATION_SEEDS = tuple(range(2000, 2020))
RFINAL_SEEDS = tuple(range(2100, 2130))
CONDITIONS = ("ALIGNED", "MISALIGNED")
ARMS = ("ORGAN", "BASE-FAIR", "ORACLE-FEATURE-BASE", "BASE-NAIVE", "ORACLE")

# Additional harness constants: not frozen thresholds. The budget grid is built
# mechanically around B* once calibration has located it.
CALIBRATION_BUDGETS = (8, 16, 32, 64)
SMALL_BUDGET_FLOOR = 4
EVAL_STEPS = 128
HELDOUT_STEPS = 128
FEATURE_COUNT = 1 + (OBS_DIM * BUFFER_M) + 2016 + 41664
EPS = 1e-12


@dataclass(frozen=True)
class RunResult:
    area: float
    total_return: float
    correct: int
    steps: int

    @property
    def accuracy(self) -> float:
        return self.correct / self.steps if self.steps else 0.0


@dataclass(frozen=True)
class PairStats:
    organ_area_mean: float
    comparator_area_mean: float
    adv: float
    paired_diffs: tuple[float, ...]
    diff_mean: float
    diff_ci: tuple[float, float]
    wilcoxon_p: float
    organ_wins: int


@dataclass(frozen=True)
class ArchiveRepresentation:
    name: str

    def score(self, buffer: tuple[tuple[int, ...], ...]) -> float:
        return float(archive_readout(self.name, buffer))

    def predict(self, buffer: tuple[tuple[int, ...], ...]) -> int:
        return 1 if self.score(buffer) >= 0.0 else -1


def archive_representation(name: str) -> ArchiveRepresentation:
    if name not in ARCHIVE:
        raise ValueError(f"unknown archive readout: {name}")
    return ArchiveRepresentation(name)


def sigmoid(x: float) -> float:
    if x >= 40.0:
        return 1.0
    if x <= -40.0:
        return 0.0
    return 1.0 / (1.0 + math.exp(-x))


def degree3_monomial_kernel(a: tuple[int, ...], b: tuple[int, ...]) -> float:
    """Exact dot product for all degree<=3 monomials over two +/-1 vectors."""

    if len(a) != OBS_DIM * BUFFER_M or len(b) != OBS_DIM * BUFFER_M:
        raise ValueError("kernel expects 64-bit flattened buffers")
    s = sum(x * y for x, y in zip(a, b))
    n = len(a)
    e2 = (s * s - n) / 2.0
    e3 = (s * s * s - 3.0 * s * n + 2.0 * s) / 6.0
    return 1.0 + s + e2 + e3


class MonomialLogisticPerceptron:
    """Online logistic learner over the frozen degree<=3 monomial class."""

    def __init__(
        self,
        *,
        lr: float = LR,
        rng: random.Random | None = None,
        phi_star: str = PHI_STAR,
        oracle_feature: bool = False,
        initial_readout: str | None = None,
        initial_weight: float = 0.0,
    ) -> None:
        self.lr = lr
        self.rng = rng or random.Random()
        self.phi_star = phi_star
        self.oracle_feature = oracle_feature
        self.initial_readout = initial_readout
        self.initial_weight = initial_weight
        self._examples: list[tuple[tuple[int, ...], int, float]] = []

    @property
    def updates(self) -> int:
        return len(self._examples)

    def _initial_score(self, buffer: tuple[tuple[int, ...], ...]) -> float:
        if self.initial_readout is None or self.initial_weight == 0.0:
            return 0.0
        return self.initial_weight * archive_readout(self.initial_readout, buffer)

    def score(self, features: tuple[int, ...], buffer: tuple[tuple[int, ...], ...]) -> float:
        phi_value = archive_readout(self.phi_star, buffer)
        total = self._initial_score(buffer)
        for old_features, old_phi, coeff in self._examples:
            k = degree3_monomial_kernel(old_features, features) / FEATURE_COUNT
            if self.oracle_feature:
                k += old_phi * phi_value
            total += coeff * k
        return total

    def probability_positive(
        self, features: tuple[int, ...], buffer: tuple[tuple[int, ...], ...]
    ) -> float:
        return sigmoid(self.score(features, buffer))

    def predict(
        self,
        features: tuple[int, ...],
        buffer: tuple[tuple[int, ...], ...],
        *,
        stochastic: bool = True,
    ) -> int:
        p = self.probability_positive(features, buffer)
        if stochastic:
            return 1 if self.rng.random() < p else -1
        return 1 if p >= 0.5 else -1

    def update(self, features: tuple[int, ...], buffer: tuple[tuple[int, ...], ...], label: int) -> None:
        if label not in (-1, 1):
            raise ValueError("label must be -1 or +1")
        score = self.score(features, buffer)
        coeff = self.lr * label * sigmoid(-label * score)
        self._examples.append((features, archive_readout(self.phi_star, buffer), coeff))


class NaiveEWMABaseline:
    """Geometric closure sanity floor with no access to the 64-bit class."""

    def __init__(self) -> None:
        self.value = 0.0
        self.last_action = 1

    def predict(self, obs0: int) -> int:
        guess = 1 if self.value >= 0.0 else -1
        self.last_action = guess
        self.value = 0.80 * self.value + 0.20 * obs0
        return guess


def _mean(values: list[float] | tuple[float, ...]) -> float:
    return sum(values) / len(values) if values else 0.0


def _bootstrap_ci(values: list[float] | tuple[float, ...], *, n: int = 2000, seed: int = 4040) -> tuple[float, float]:
    if not values:
        return (0.0, 0.0)
    rng = random.Random(seed)
    m = len(values)
    means = sorted(sum(values[rng.randrange(m)] for _ in range(m)) / m for _ in range(n))
    return (means[int(0.025 * n)], means[int(0.975 * n)])


def _advantage(organ_area: float, comparator_area: float) -> float:
    if comparator_area <= EPS:
        return 0.0 if organ_area <= EPS else -1.0
    return 1.0 - organ_area / comparator_area


def make_budget_sweep(b_star: int) -> tuple[int, ...]:
    small = min(SMALL_BUDGET_FLOOR, b_star)
    return tuple(dict.fromkeys((small, b_star, 2 * b_star, 4 * b_star, 8 * b_star)))


def _env(seed: int, condition: str) -> PhiSReopeningEnv:
    return PhiSReopeningEnv(
        seed=50_000 + seed,
        condition=condition,
        phi_star=PHI_STAR,
        misaligned_readout=MISALIGNED_READOUT,
    )


def _train_learner(
    *,
    seed: int,
    condition: str,
    budget: int,
    oracle_feature: bool = False,
    oracle_initialized: bool = False,
) -> MonomialLogisticPerceptron:
    env = _env(seed, condition)
    learner = MonomialLogisticPerceptron(
        rng=random.Random(70_000 + seed + (17 if oracle_feature else 0)),
        oracle_feature=oracle_feature,
        initial_readout=PHI_STAR if oracle_initialized else None,
        initial_weight=12.0 if oracle_initialized else 0.0,
    )
    for _ in range(budget):
        features = env.features64()
        buffer = env.buffer
        label = env.optimal_action()
        learner.update(features, buffer, label)
        action = learner.predict(features, buffer, stochastic=False)
        env.act(action)
    return learner


def _skip_acquisition(env: PhiSReopeningEnv, budget: int, action_fn) -> None:
    for _ in range(budget):
        env.act(action_fn(env))


def run_arm(
    seed: int,
    condition: str,
    arm: str,
    budget: int,
    *,
    steps: int = EVAL_STEPS,
    oracle_initialized: bool = False,
) -> RunResult:
    env = _env(seed, condition)
    area = 0.0
    total_return = 0.0
    correct = 0

    learner: MonomialLogisticPerceptron | None = None
    naive: NaiveEWMABaseline | None = None
    if arm in ("BASE-FAIR", "ORACLE-FEATURE-BASE"):
        learner = _train_learner(
            seed=seed,
            condition=condition,
            budget=budget,
            oracle_feature=arm == "ORACLE-FEATURE-BASE",
            oracle_initialized=oracle_initialized,
        )
        _skip_acquisition(
            env, budget, lambda e: learner.predict(e.features64(), e.buffer, stochastic=False)
        )
    elif arm == "BASE-NAIVE":
        naive = NaiveEWMABaseline()
        _skip_acquisition(env, budget, lambda e: naive.predict(e.observation()[0]))
    elif arm == "ORGAN":
        _skip_acquisition(env, budget, lambda e: e.phi_star_action())
    elif arm == "ORACLE":
        _skip_acquisition(env, budget, lambda e: e.optimal_action())
    else:
        raise ValueError(f"unknown arm: {arm}")

    for _ in range(steps):
        if arm == "ORGAN":
            action = env.phi_star_action()
        elif arm == "ORACLE":
            action = env.optimal_action()
        elif arm == "BASE-NAIVE":
            assert naive is not None
            action = naive.predict(env.observation()[0])
        else:
            assert learner is not None
            action = learner.predict(env.features64(), env.buffer, stochastic=False)
        optimal = env.optimal_action()
        reward = env.act(action)
        total_return += reward
        area += env.last_regret
        correct += int(action == optimal)

    return RunResult(area=area, total_return=total_return, correct=correct, steps=steps)


def calibration_return(seed: int, budget: int, *, steps: int = EVAL_STEPS) -> float:
    return run_arm(
        seed,
        "ALIGNED",
        "BASE-FAIR",
        budget,
        steps=steps,
        oracle_initialized=True,
    ).total_return


def calibrate_b_star(
    *,
    seeds: tuple[int, ...] = CALIBRATION_SEEDS,
    candidate_budgets: tuple[int, ...] = CALIBRATION_BUDGETS,
    steps: int = EVAL_STEPS,
) -> dict[str, Any]:
    oracle_return = float(steps)
    threshold = (1.0 - ETA) * oracle_return
    rows = []
    b_star = candidate_budgets[-1]
    for budget in candidate_budgets:
        returns = [calibration_return(seed, budget, steps=steps) for seed in seeds]
        mean_return = _mean(returns)
        row = {
            "budget": budget,
            "mean_return": mean_return,
            "target_return": threshold,
            "meets": mean_return >= threshold,
        }
        rows.append(row)
        if row["meets"]:
            b_star = budget
            break
    return {
        "B_star": b_star,
        "eta": ETA,
        "oracle_return": oracle_return,
        "target_return": threshold,
        "candidate_budgets": list(candidate_budgets),
        "rows": rows,
    }


def phi_recovery_accuracy(
    seed: int,
    condition: str,
    budget: int,
    *,
    steps: int = HELDOUT_STEPS,
) -> float:
    learner = _train_learner(seed=seed, condition=condition, budget=budget)
    heldout = PhiSReopeningEnv(seed=90_000 + seed, condition=condition, phi_star=PHI_STAR)
    correct = 0
    for _ in range(steps):
        pred = learner.predict(heldout.features64(), heldout.buffer, stochastic=False)
        correct += int(pred == heldout.phi_star_action())
        heldout.advance_without_action()
    return correct / steps


def pair_stats(organ: list[RunResult], comparator: list[RunResult]) -> PairStats:
    organ_areas = [row.area for row in organ]
    comp_areas = [row.area for row in comparator]
    diffs = tuple(comp_areas[i] - organ_areas[i] for i in range(len(organ_areas)))
    return PairStats(
        organ_area_mean=_mean(organ_areas),
        comparator_area_mean=_mean(comp_areas),
        adv=_advantage(_mean(organ_areas), _mean(comp_areas)),
        paired_diffs=diffs,
        diff_mean=_mean(diffs),
        diff_ci=_bootstrap_ci(diffs),
        wilcoxon_p=wilcoxon_one_sided(list(diffs)),
        organ_wins=sum(1 for d in diffs if d > 0.0),
    )


def _budget_summary(
    *,
    condition: str,
    budget: int,
    seeds: tuple[int, ...],
    steps: int,
) -> dict[str, Any]:
    per_arm = {
        arm: [run_arm(seed, condition, arm, budget, steps=steps) for seed in seeds]
        for arm in ARMS
    }
    recovery = [phi_recovery_accuracy(seed, condition, budget) for seed in seeds]
    organ = per_arm["ORGAN"]
    out: dict[str, Any] = {
        "budget": budget,
        "arm_means": {
            arm: {
                "area": _mean([row.area for row in rows]),
                "return": _mean([row.total_return for row in rows]),
                "accuracy": _mean([row.accuracy for row in rows]),
            }
            for arm, rows in per_arm.items()
        },
        "pair_stats": {},
        "base_fair_phi_recovery": {
            "mean_accuracy": _mean(recovery),
            "per_seed": recovery,
            "chance_plus_epsilon": 0.5 + EPSILON,
        },
    }
    for arm in ("BASE-FAIR", "ORACLE-FEATURE-BASE", "BASE-NAIVE"):
        out["pair_stats"][f"ORGAN_vs_{arm}"] = asdict(pair_stats(organ, per_arm[arm]))
    return out


def summarize_condition(
    *,
    condition: str,
    budgets: tuple[int, ...],
    seeds: tuple[int, ...] = RFINAL_SEEDS,
    steps: int = EVAL_STEPS,
) -> dict[str, Any]:
    curve = [
        _budget_summary(condition=condition, budget=budget, seeds=seeds, steps=steps)
        for budget in budgets
    ]
    return {"condition": condition, "curve": curve}


def _by_budget(summary: dict[str, Any], budget: int) -> dict[str, Any]:
    for row in summary["curve"]:
        if row["budget"] == budget:
            return row
    raise ValueError(f"budget {budget} not found")


def verdict_for_condition(
    *,
    condition: str,
    condition_summary: dict[str, Any],
    b_star: int,
    small_budget: int,
    gg_budget: int,
    misaligned_control_pass: bool = True,
    vacuous: bool = False,
) -> dict[str, Any]:
    categories = ("H0", "H1a", "H1b", "INPUT-DENIED", "VACUOUS")
    if vacuous:
        return {"verdict": "VACUOUS", "categories": categories, "reason": "vacuous_operationalization"}

    small = _by_budget(condition_summary, small_budget)
    b_row = _by_budget(condition_summary, b_star)
    gg = _by_budget(condition_summary, gg_budget)

    adv_small = small["pair_stats"]["ORGAN_vs_BASE-FAIR"]["adv"]
    adv_b = b_row["pair_stats"]["ORGAN_vs_BASE-FAIR"]["adv"]
    adv_gg = gg["pair_stats"]["ORGAN_vs_BASE-FAIR"]["adv"]
    oracle_feature_adv = gg["pair_stats"]["ORGAN_vs_ORACLE-FEATURE-BASE"]["adv"]
    recovery = gg["base_fair_phi_recovery"]["mean_accuracy"]

    if condition == "MISALIGNED":
        if adv_gg > DELTA:
            return {
                "verdict": "INPUT-DENIED",
                "categories": categories,
                "reason": "misaligned_negative_control_failed_rig_or_leak",
                "adv_at_8B": adv_gg,
            }
        return {
            "verdict": "H0",
            "categories": categories,
            "reason": "misaligned_negative_control_passed",
            "adv_at_8B": adv_gg,
        }

    if adv_small >= DELTA and adv_b <= DELTA:
        verdict = "H1a"
        reason = "sample_efficiency_only_converges_by_B_star"
    elif adv_b <= DELTA:
        verdict = "H0"
        reason = "base_fair_ties_by_B_star"
    elif (
        adv_gg >= DELTA
        and recovery < 0.5 + EPSILON
        and oracle_feature_adv <= DELTA
        and misaligned_control_pass
    ):
        verdict = "H1b"
        reason = "aligned_irreducible_gap_criteria_met"
    elif adv_gg >= DELTA and oracle_feature_adv > DELTA:
        verdict = "INPUT-DENIED"
        reason = "oracle_feature_base_does_not_tie_organ"
    else:
        verdict = "H0"
        reason = "H1b_criteria_not_met"

    return {
        "verdict": verdict,
        "categories": categories,
        "reason": reason,
        "adv_small": adv_small,
        "adv_at_B_star": adv_b,
        "adv_at_8B": adv_gg,
        "oracle_feature_adv_at_8B": oracle_feature_adv,
        "phi_recovery_at_8B": recovery,
        "misaligned_control_pass": misaligned_control_pass,
    }


def load_spec_sha256(path: Path = FREEZE_JSON) -> str:
    with path.open("r", encoding="utf-8") as f:
        return str(json.load(f)["spec_sha256"])


def evaluate_rfinal() -> dict[str, Any]:
    calibration = calibrate_b_star()
    b_star = int(calibration["B_star"])
    budgets = make_budget_sweep(b_star)
    summaries = {
        condition: summarize_condition(condition=condition, budgets=budgets)
        for condition in CONDITIONS
    }

    gg_budget = 8 * b_star
    small_budget = budgets[0]
    misaligned_adv = _by_budget(summaries["MISALIGNED"], gg_budget)["pair_stats"][
        "ORGAN_vs_BASE-FAIR"
    ]["adv"]
    misaligned_control_pass = misaligned_adv <= DELTA
    verdicts = {
        condition: verdict_for_condition(
            condition=condition,
            condition_summary=summaries[condition],
            b_star=b_star,
            small_budget=small_budget,
            gg_budget=gg_budget,
            misaligned_control_pass=misaligned_control_pass,
        )
        for condition in CONDITIONS
    }

    return {
        "adr": "ADR-0040",
        "spec_sha256": load_spec_sha256(),
        "phi_star": PHI_STAR,
        "misaligned_readout": MISALIGNED_READOUT,
        "frozen": {
            "obs_dim": OBS_DIM,
            "buffer_M": BUFFER_M,
            "archive": list(ARCHIVE),
            "learner": "degree<=3 monomial logistic perceptron, lr 0.05",
            "delta": DELTA,
            "epsilon": EPSILON,
            "eta": ETA,
            "calibration_seeds": "2000..2019",
            "rfinal_seeds": "2100..2129",
        },
        "calibration": calibration,
        "B_star": b_star,
        "ggB_star": gg_budget,
        "budget_sweep": list(budgets),
        "conditions": summaries,
        "verdicts": verdicts,
    }


def main() -> None:
    result = evaluate_rfinal()
    RESULT_JSON.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {RESULT_JSON}")
    for condition, verdict in result["verdicts"].items():
        print(f"{condition}: {verdict['verdict']} ({verdict['reason']})")


if __name__ == "__main__":
    main()
