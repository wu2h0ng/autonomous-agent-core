"""G-Eco lower-half mechanism substrate and arms.

This module deliberately contains no calibration scan, freeze writer, Gate-2
unlock, r-final runner, or verdict emitter. It only defines the shared
substrate, value aggregators, calibration-only references, metrics, and guards
needed before those later gates can exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from .shell import ShellView
from envs.ecological_4cond import (
    Ecological4CondEnv,
    GEcoObservation,
    GEcoState,
    transition_state,
)

GECO_BATTERY_NAMES = (
    "LIN",
    "LEX",
    "THR",
    "QUOTA",
    "MINIMAX",
    "P0",
    "RSTAR",
    "O1",
    "BT",
)
GECO_RFINAL_ARM_NAMES = ("VH",) + GECO_BATTERY_NAMES


@dataclass(frozen=True, slots=True)
class GEcoPrediction:
    action: str
    next_state: GEcoState
    risk: tuple[float, float, float, float]
    delta_risk: tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class GEcoArmSource:
    adr: str
    symbol: str
    params: Mapping[str, float]
    adapter_note: str = ""


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _risk_vector(state: GEcoState) -> tuple[float, float, float, float]:
    return (
        _clip01((70.0 - state.energy) / 70.0),
        _clip01((70.0 - state.integrity) / 70.0),
        _clip01(state.need_a / 75.0),
        _clip01(state.need_b / 75.0),
    )


def entered_viable_region(
    state: GEcoState,
    *,
    min_energy: float = 55.0,
    min_integrity: float = 55.0,
    max_need: float = 45.0,
) -> bool:
    """Pure environment-derived region predicate.

    It takes no arm name, score, baseline output, or result table, so it cannot
    be gerrymandered from observed arm performance inside the implementation.
    """
    return (
        state.energy >= min_energy
        and state.integrity >= min_integrity
        and state.need_a <= max_need
        and state.need_b <= max_need
    )


class GEcoSharedSubstrate:
    """Single shared observation/predictor/lookahead/H substrate for all arms."""

    def __init__(self, *, lookahead_depth: int = 1) -> None:
        if lookahead_depth <= 0:
            raise ValueError("lookahead_depth must be positive")
        self.lookahead_depth = lookahead_depth

    def observe(self, env: Ecological4CondEnv) -> GEcoObservation:
        return env.observation()

    def H(self, observation: GEcoObservation) -> tuple[float, float, float, float]:
        return _risk_vector(observation.state)

    def lookahead(self, observation: GEcoObservation, action: str) -> GEcoPrediction:
        current = self.H(observation)
        next_state = observation.state
        for _ in range(self.lookahead_depth):
            next_state = transition_state(
                next_state,
                action,
                rates=observation.rates,
                effects=observation.effects,
                limits=observation.limits,
            )
        future = _risk_vector(next_state)
        return GEcoPrediction(
            action=action,
            next_state=next_state,
            risk=future,
            delta_risk=tuple(future[i] - current[i] for i in range(4)),
        )

    def predict_all(self, observation: GEcoObservation) -> dict[str, GEcoPrediction]:
        return {
            action: self.lookahead(observation, action)
            for action in observation.actions
        }


Aggregator = Callable[[GEcoObservation, Mapping[str, GEcoPrediction]], dict[str, float]]


@dataclass(frozen=True, slots=True)
class GEcoArm:
    name: str
    family: str
    substrate: GEcoSharedSubstrate
    aggregator: Aggregator
    calibration_only: bool = False
    source: GEcoArmSource | None = None

    def score_actions(
        self,
        observation: GEcoObservation,
        predictions: Mapping[str, GEcoPrediction] | None = None,
    ) -> dict[str, float]:
        preds = (
            predictions
            if predictions is not None
            else self.substrate.predict_all(observation)
        )
        return self.aggregator(observation, preds)

    def select(
        self,
        observation: GEcoObservation,
        *,
        shell: ShellView | None = None,
    ) -> str | None:
        if shell is not None and shell.paused:
            return None
        scores = self.score_actions(observation)
        forbidden = shell.forbidden if shell is not None else frozenset()
        permitted: list[tuple[str, float]] = []
        for idx, action in enumerate(observation.actions):
            if idx not in forbidden:
                permitted.append((action, scores[action]))
        if not permitted:
            raise ValueError("all G-Eco actions forbidden")
        return max(
            permitted, key=lambda item: (item[1], -observation.actions.index(item[0]))
        )[0]


def _improvement(prediction: GEcoPrediction) -> tuple[float, float, float, float]:
    return tuple(-v for v in prediction.delta_risk)


def _trajectory_pressure(observation: GEcoObservation) -> float:
    integrity_margin = max(1.0, observation.state.integrity)
    return _clip01(observation.rates.integrity_drain / integrity_margin * 20.0)


def _homeostatic_weights(
    risk: tuple[float, float, float, float],
    *,
    trajectory_pressure: float = 0.0,
) -> tuple[float, ...]:
    energy, integrity, need_a, need_b = risk
    return (
        0.50 + 1.50 * energy + 4.00 * energy * energy,
        0.25 + integrity + 2.50 * integrity * integrity + 2.00 * trajectory_pressure,
        0.25 + need_a + 2.50 * need_a * need_a,
        0.25 + need_b + 2.50 * need_b * need_b,
    )


def _score_weighted(
    weights: tuple[float, float, float, float],
    predictions: Mapping[str, GEcoPrediction],
) -> dict[str, float]:
    out: dict[str, float] = {}
    for action, prediction in predictions.items():
        gains = _improvement(prediction)
        out[action] = sum(weights[i] * gains[i] for i in range(4))
    return out


def _vh(
    observation: GEcoObservation,
    predictions: Mapping[str, GEcoPrediction],
) -> dict[str, float]:
    return _score_weighted(
        _homeostatic_weights(
            _risk_vector(observation.state),
            trajectory_pressure=_trajectory_pressure(observation),
        ),
        predictions,
    )


def _vh_no_stake(
    observation: GEcoObservation,
    predictions: Mapping[str, GEcoPrediction],
) -> dict[str, float]:
    del observation
    return _score_weighted((1.0, 1.0, 1.0, 1.0), predictions)


def _lin(
    observation: GEcoObservation,
    predictions: Mapping[str, GEcoPrediction],
) -> dict[str, float]:
    del observation
    return _score_weighted((0.35, 0.25, 0.20, 0.20), predictions)


def _lex(
    observation: GEcoObservation,
    predictions: Mapping[str, GEcoPrediction],
) -> dict[str, float]:
    risks = _risk_vector(observation.state)
    channel = max(range(4), key=lambda idx: (risks[idx], -idx))
    return {
        action: _improvement(prediction)[channel]
        for action, prediction in predictions.items()
    }


def _thr(
    observation: GEcoObservation,
    predictions: Mapping[str, GEcoPrediction],
) -> dict[str, float]:
    risks = _risk_vector(observation.state)
    active = tuple(1.0 if risk >= 0.40 else 0.0 for risk in risks)
    weights = active if any(active) else (0.25, 0.25, 0.25, 0.25)
    return _score_weighted(weights, predictions)


def _quota(
    observation: GEcoObservation,
    predictions: Mapping[str, GEcoPrediction],
) -> dict[str, float]:
    target = ("feed", "repair", "serve_a", "serve_b")[observation.step % 4]
    return {
        action: (1.0 if action == target else 0.0)
        + 0.01 * sum(_improvement(prediction))
        for action, prediction in predictions.items()
    }


def _minimax(
    observation: GEcoObservation,
    predictions: Mapping[str, GEcoPrediction],
) -> dict[str, float]:
    del observation
    return {action: -max(prediction.risk) for action, prediction in predictions.items()}


def _confidence_from_scores(scores: Mapping[str, float], kappa: float) -> float:
    ordered = sorted(scores.values(), reverse=True)
    if len(ordered) < 2:
        return 1.0
    gap = ordered[0] - ordered[1]
    scale = max(1e-9, abs(ordered[0]) + abs(ordered[1]) + 1.0)
    return _clip01(gap / (max(kappa, 1e-9) * scale))


def _p0_adapter(params: Mapping[str, float]) -> Aggregator:
    def aggregate(
        observation: GEcoObservation,
        predictions: Mapping[str, GEcoPrediction],
    ) -> dict[str, float]:
        risks = _risk_vector(observation.state)
        pressure = max(risks)
        base = _score_weighted((0.35 + pressure, 0.25, 0.20, 0.20), predictions)
        confidence = _confidence_from_scores(base, params["gate_kappa"])
        best = max(base, key=base.get)
        gate_bonus = confidence * (1.0 - params["gate_temp_floor"])
        return {
            action: score + (gate_bonus if action == best else 0.0)
            for action, score in base.items()
        }

    return aggregate


def _rstar_adapter(params: Mapping[str, float]) -> Aggregator:
    def aggregate(
        observation: GEcoObservation,
        predictions: Mapping[str, GEcoPrediction],
    ) -> dict[str, float]:
        risks = _risk_vector(observation.state)
        surprise = _clip01(
            abs(observation.rates.need_a_growth - observation.rates.need_b_growth) / 8.0
        )
        relevance = _clip01(
            params["inertia"] * max(risks) + params["surprise_gain"] * surprise
        )
        weights = (
            0.20 + risks[0] + 0.25 * relevance,
            0.20 + risks[1] + 0.25 * relevance,
            0.20 + risks[2] + 0.10 * relevance,
            0.20 + risks[3] + 0.10 * relevance,
        )
        scores = _score_weighted(weights, predictions)
        best = max(scores, key=scores.get)
        temp_bonus = max(0.0, 0.30 - params["base_temperature"])
        return {
            action: score + (temp_bonus if action == best else 0.0)
            for action, score in scores.items()
        }

    return aggregate


def _o1_adapter(params: Mapping[str, float]) -> Aggregator:
    def aggregate(
        observation: GEcoObservation,
        predictions: Mapping[str, GEcoPrediction],
    ) -> dict[str, float]:
        reset_period = max(
            1, int(round(params["spike_k"] + params["reset_strength"] * 5))
        )
        if observation.step % reset_period == 0 or observation.regime_index:
            return _lex(observation, predictions)
        return _lin(observation, predictions)

    return aggregate


def _bt_adapter(params: Mapping[str, float]) -> Aggregator:
    def aggregate(
        observation: GEcoObservation,
        predictions: Mapping[str, GEcoPrediction],
    ) -> dict[str, float]:
        del observation
        scores = _lin_observation_free(predictions)
        best = max(scores, key=scores.get)
        cold_bonus = 1.0 / max(1e-6, params["base_temperature"])
        return {
            action: score + (cold_bonus if action == best else 0.0)
            for action, score in scores.items()
        }

    return aggregate


def _lin_observation_free(
    predictions: Mapping[str, GEcoPrediction],
) -> dict[str, float]:
    return _score_weighted((0.35, 0.25, 0.20, 0.20), predictions)


def _truth_rollout(
    observation: GEcoObservation,
    action: str,
    *,
    depth: int,
) -> GEcoState:
    state = observation.truth_state
    for _ in range(depth):
        state = transition_state(
            state,
            action,
            rates=observation.rates,
            effects=observation.effects,
            limits=observation.limits,
        )
    return state


def _truth_value(state: GEcoState) -> float:
    risk = _risk_vector(state)
    irreversible_loss = _clip01((100.0 - state.integrity) / 100.0)
    return -sum(risk) - 0.75 * irreversible_loss


def _oracle(
    observation: GEcoObservation,
    predictions: Mapping[str, GEcoPrediction],
) -> dict[str, float]:
    del predictions
    return {
        action: _truth_value(_truth_rollout(observation, action, depth=3))
        for action in observation.actions
    }


def _wcref(
    observation: GEcoObservation,
    predictions: Mapping[str, GEcoPrediction],
) -> dict[str, float]:
    del predictions
    return {
        action: -max(_risk_vector(_truth_rollout(observation, action, depth=3)))
        for action in observation.actions
    }


def _arm(
    name: str,
    substrate: GEcoSharedSubstrate,
    aggregator: Aggregator,
    *,
    source: GEcoArmSource | None = None,
) -> GEcoArm:
    return GEcoArm(
        name=name,
        family="battery",
        substrate=substrate,
        aggregator=aggregator,
        source=source,
    )


def _shared_substrate() -> GEcoSharedSubstrate:
    return GEcoSharedSubstrate()


def _frozen_p0_source() -> GEcoArmSource:
    from experiments.confidence_gated_g9 import GATE_FROZEN

    return GEcoArmSource(
        adr="ADR-0024",
        symbol="experiments.confidence_gated_g9.GATE_FROZEN",
        params={
            "gate_kappa": float(GATE_FROZEN["gate_kappa"]),
            "gate_temp_floor": float(GATE_FROZEN["gate_temp_floor"]),
        },
        adapter_note="G-Eco deterministic adapter preserves frozen confidence gate parameters.",
    )


def _frozen_rstar_source() -> GEcoArmSource:
    from experiments.ecological_g12 import load_rstar_params

    params = load_rstar_params()
    return GEcoArmSource(
        adr="ADR-0034",
        symbol="experiments.ecological_g12.load_rstar_params",
        params={
            "base_temperature": float(params.base_temperature),
            "inertia": float(params.inertia),
            "surprise_gain": float(params.surprise_gain),
        },
        adapter_note="G-Eco adapter preserves frozen RSTAR triple.",
    )


def _frozen_o1_source() -> GEcoArmSource:
    from aac.prior_organ_o1 import ResetScaffoldOrgan

    organ = ResetScaffoldOrgan()
    return GEcoArmSource(
        adr="ADR-0016/ADR-0024 cheap reset baseline",
        symbol="aac.prior_organ_o1.ResetScaffoldOrgan",
        params={
            "spike_k": float(organ.spike_k),
            "reset_strength": float(organ.reset_strength),
            "mu_decay": float(organ.mu_decay),
        },
        adapter_note="G-Eco adapter preserves frozen O1 reset scaffold parameters.",
    )


def _frozen_bt_source() -> GEcoArmSource:
    from experiments.ecological_g12 import BTEMP

    return GEcoArmSource(
        adr="ADR-0030",
        symbol="experiments.ecological_g12.BTEMP",
        params={"base_temperature": float(BTEMP)},
        adapter_note="G-Eco adapter preserves frozen fixed-low-temperature value.",
    )


def build_g_eco_battery(
    *, substrate: GEcoSharedSubstrate | None = None
) -> tuple[GEcoArm, ...]:
    shared = substrate if substrate is not None else _shared_substrate()
    p0 = _frozen_p0_source()
    rstar = _frozen_rstar_source()
    o1 = _frozen_o1_source()
    bt = _frozen_bt_source()
    return (
        _arm("LIN", shared, _lin),
        _arm("LEX", shared, _lex),
        _arm("THR", shared, _thr),
        _arm("QUOTA", shared, _quota),
        _arm("MINIMAX", shared, _minimax),
        _arm("P0", shared, _p0_adapter(p0.params), source=p0),
        _arm("RSTAR", shared, _rstar_adapter(rstar.params), source=rstar),
        _arm("O1", shared, _o1_adapter(o1.params), source=o1),
        _arm("BT", shared, _bt_adapter(bt.params), source=bt),
    )


def build_g_eco_arms(*, include_cheats: bool = False) -> tuple[GEcoArm, ...]:
    shared = _shared_substrate()
    arms = (
        GEcoArm(name="VH", family="candidate", substrate=shared, aggregator=_vh),
        GEcoArm(
            name="VH_noStake",
            family="ablation",
            substrate=shared,
            aggregator=_vh_no_stake,
        ),
        *build_g_eco_battery(substrate=shared),
    )
    if include_cheats:
        arms = (*arms, *build_calibration_refs(substrate=shared))
    assert_shared_substrate(arms)
    return arms


def build_calibration_refs(
    *, substrate: GEcoSharedSubstrate | None = None
) -> tuple[GEcoArm, ...]:
    shared = substrate if substrate is not None else _shared_substrate()
    return (
        GEcoArm(
            name="HOMEOSTATIC_ORACLE",
            family="cheat_ref",
            substrate=shared,
            aggregator=_oracle,
            calibration_only=True,
        ),
        GEcoArm(
            name="WCREF",
            family="cheat_ref",
            substrate=shared,
            aggregator=_wcref,
            calibration_only=True,
        ),
    )


def rfinal_arm_names() -> tuple[str, ...]:
    """Return the only arms allowed to appear in a future r-final result."""
    return GECO_RFINAL_ARM_NAMES


def assert_no_calibration_refs_in_rfinal(
    arms: tuple[GEcoArm, ...],
    names: tuple[str, ...],
) -> tuple[str, ...]:
    by_name = {arm.name: arm for arm in arms}
    unknown = [name for name in names if name not in by_name]
    if unknown:
        raise AssertionError(f"unknown r-final arm names: {unknown}")
    calibration_refs = {arm.name for arm in arms if arm.calibration_only}
    overlap = tuple(name for name in names if name in calibration_refs)
    if overlap:
        raise AssertionError(f"calibration-only refs entered r-final: {overlap}")
    return names


def assert_shared_substrate(arms: tuple[GEcoArm, ...]) -> None:
    ids = {id(arm.substrate) for arm in arms}
    if len(ids) != 1:
        raise AssertionError("G-Eco arms must share one bit-identical substrate")


@dataclass
class GEcoMetrics:
    survival_steps: int = 0
    entered_region: bool = False
    enter_step: int | None = None
    terminal_alive: bool = True
    irreversible_loss: float = 0.0
    action_counts: dict[str, int] | None = None

    def observe(self, *, step: int, state: GEcoState, action: str, alive: bool) -> None:
        if self.action_counts is None:
            self.action_counts = {}
        self.survival_steps += 1 if alive else 0
        self.terminal_alive = alive
        self.irreversible_loss = max(self.irreversible_loss, 100.0 - state.integrity)
        self.action_counts[action] = self.action_counts.get(action, 0) + 1
        if not self.entered_region and entered_viable_region(state):
            self.entered_region = True
            self.enter_step = step

    def summary(self) -> dict[str, object]:
        return {
            "survival_steps": self.survival_steps,
            "entered_region": self.entered_region,
            "enter_step": self.enter_step,
            "terminal_alive": self.terminal_alive,
            "irreversible_loss": self.irreversible_loss,
            "action_counts": dict(self.action_counts or {}),
        }
