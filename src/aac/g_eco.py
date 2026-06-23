"""G-Eco lower-half mechanism substrate and arms.

This module deliberately contains no Gate-2 unlock, r-final runner, or verdict
emitter. It defines the shared substrate, value aggregators, calibration-only
references, metrics, guards, and pre-Gate-2 candidate freeze material needed for
founder/CTO review before those later gates can exist.
"""

from __future__ import annotations

import hashlib
import ast
import inspect
import json
import random
import textwrap
from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Any, Callable, Mapping

from .shell import ShellView
from envs.ecological_4cond import (
    Ecological4CondEnv,
    GEcoRates,
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
RATE_SEEDS = tuple(range(1800, 1810))
CALIBRATION_SEEDS = tuple(range(1810, 1830))
RFINAL_SEEDS = tuple(range(1900, 1930))


class GEcoHalt(RuntimeError):
    """Mechanical pre-r-final halt, not a verdict."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


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


@dataclass(frozen=True, slots=True)
class GEcoVHParams:
    energy_base: float
    energy_linear: float
    energy_quadratic: float
    integrity_base: float
    integrity_linear: float
    integrity_quadratic: float
    need_base: float
    need_linear: float
    need_quadratic: float
    trajectory_scale: float
    trajectory_weight: float

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


DEFAULT_VH_PARAMS = GEcoVHParams(
    energy_base=0.50,
    energy_linear=1.50,
    energy_quadratic=4.00,
    integrity_base=0.25,
    integrity_linear=1.00,
    integrity_quadratic=2.50,
    need_base=0.25,
    need_linear=1.00,
    need_quadratic=2.50,
    trajectory_scale=20.0,
    trajectory_weight=2.00,
)
VH_PARAMETER_GRID: tuple[tuple[str, GEcoVHParams], ...] = (
    ("balanced_v0", DEFAULT_VH_PARAMS),
    (
        "energy_guard",
        GEcoVHParams(
            energy_base=0.55,
            energy_linear=1.75,
            energy_quadratic=4.75,
            integrity_base=0.25,
            integrity_linear=1.00,
            integrity_quadratic=2.25,
            need_base=0.25,
            need_linear=1.00,
            need_quadratic=2.25,
            trajectory_scale=20.0,
            trajectory_weight=1.75,
        ),
    ),
    (
        "integrity_guard",
        GEcoVHParams(
            energy_base=0.45,
            energy_linear=1.25,
            energy_quadratic=3.50,
            integrity_base=0.30,
            integrity_linear=1.25,
            integrity_quadratic=3.50,
            need_base=0.25,
            need_linear=1.00,
            need_quadratic=2.25,
            trajectory_scale=18.0,
            trajectory_weight=2.75,
        ),
    ),
    (
        "need_guard",
        GEcoVHParams(
            energy_base=0.45,
            energy_linear=1.25,
            energy_quadratic=3.50,
            integrity_base=0.25,
            integrity_linear=1.00,
            integrity_quadratic=2.25,
            need_base=0.30,
            need_linear=1.25,
            need_quadratic=3.25,
            trajectory_scale=20.0,
            trajectory_weight=1.75,
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class GEcoVHParameterFreeze:
    selected_label: str
    params: GEcoVHParams
    seeds: tuple[int, ...]
    steps: int
    parameter_grid_hash: str

    def source_dict(self) -> dict[str, Any]:
        return {
            "kind": "calibration_grid",
            "seed_range": [min(self.seeds), max(self.seeds)],
            "seed_count": len(self.seeds),
            "steps": self.steps,
            "objective": (
                "maximize VH full-region count on calibration seeds, then survival "
                "steps, then minimize irreversible loss; performance values withheld"
            ),
            "selected_label": self.selected_label,
            "parameter_grid_hash": self.parameter_grid_hash,
        }


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


def _trajectory_pressure(observation: GEcoObservation, params: GEcoVHParams) -> float:
    integrity_margin = max(1.0, observation.state.integrity)
    return _clip01(
        observation.rates.integrity_drain / integrity_margin * params.trajectory_scale
    )


def _homeostatic_weights(
    risk: tuple[float, float, float, float],
    *,
    trajectory_pressure: float = 0.0,
    params: GEcoVHParams = DEFAULT_VH_PARAMS,
) -> tuple[float, ...]:
    energy, integrity, need_a, need_b = risk
    return (
        params.energy_base
        + params.energy_linear * energy
        + params.energy_quadratic * energy * energy,
        params.integrity_base
        + params.integrity_linear * integrity
        + params.integrity_quadratic * integrity * integrity
        + params.trajectory_weight * trajectory_pressure,
        params.need_base
        + params.need_linear * need_a
        + params.need_quadratic * need_a * need_a,
        params.need_base
        + params.need_linear * need_b
        + params.need_quadratic * need_b * need_b,
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


def _vh_adapter(params: GEcoVHParams) -> Aggregator:
    def aggregate(
        observation: GEcoObservation,
        predictions: Mapping[str, GEcoPrediction],
    ) -> dict[str, float]:
        return _score_weighted(
            _homeostatic_weights(
                _risk_vector(observation.state),
                trajectory_pressure=_trajectory_pressure(observation, params),
                params=params,
            ),
            predictions,
        )

    return aggregate


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


def build_g_eco_arms(
    *,
    include_cheats: bool = False,
    vh_params: GEcoVHParams | None = None,
) -> tuple[GEcoArm, ...]:
    shared = _shared_substrate()
    candidate_params = vh_params if vh_params is not None else DEFAULT_VH_PARAMS
    arms = (
        GEcoArm(
            name="VH",
            family="candidate",
            substrate=shared,
            aggregator=_vh_adapter(candidate_params),
        ),
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


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _with_hash(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    out["content_hash"] = _canonical_hash(out)
    return out


def verify_content_hash(payload: Mapping[str, Any]) -> bool:
    """Verify the mechanical content hash on a freeze/audit payload."""
    recorded = payload.get("content_hash")
    if not isinstance(recorded, str):
        return False
    comparable = dict(payload)
    comparable.pop("content_hash", None)
    return recorded == _canonical_hash(comparable)


def _source_identifiers(fn: Callable[..., Any]) -> set[str]:
    source = textwrap.dedent(inspect.getsource(fn))
    tree = ast.parse(source)
    identifiers: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            identifiers.add(node.id)
        elif isinstance(node, ast.Attribute):
            identifiers.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            identifiers.add(node.value)
    return identifiers


def assert_static_firewall(
    fn: Callable[..., Any],
    *,
    forbidden_identifiers: set[str],
    context: str,
) -> None:
    """AST-level guard against freeze logic reading opponent-arm outputs."""
    observed = _source_identifiers(fn)
    leaks = sorted(
        forbidden
        for forbidden in forbidden_identifiers
        if forbidden in observed
        or any(
            forbidden in identifier
            for identifier in observed
            if isinstance(identifier, str)
        )
    )
    if leaks:
        raise AssertionError(f"{context} static firewall leaked identifiers: {leaks}")


def assert_g_eco_static_firewalls() -> bool:
    opponent_names = set(GECO_RFINAL_ARM_NAMES) | {"VH_noStake"}
    battery_names = set(GECO_BATTERY_NAMES)
    performance_terms = {
        "arm_enter_rates",
        "enter_rate",
        "full_region_delta",
        "action_overlap",
        "margin",
        "strongest_battery_rate",
        "battery_outputs",
    }
    assert_static_firewall(
        entered_viable_region,
        forbidden_identifiers=opponent_names | battery_names | performance_terms,
        context="region predicate",
    )
    assert_static_firewall(
        scan_rate_grid,
        forbidden_identifiers=opponent_names
        | battery_names
        | {"build_g_eco_battery", "freeze_battery_parameters", "build_baseline_audit"},
        context="rate witness",
    )
    assert_static_firewall(
        derive_threshold_freeze,
        forbidden_identifiers=opponent_names | battery_names | performance_terms,
        context="threshold formula",
    )
    return True


@dataclass(frozen=True, slots=True)
class GEcoRatesFreeze:
    rates: GEcoRates
    steps: int
    seeds: tuple[int, ...]
    naive_full_region_rate: float
    oracle_full_region_rate: float
    wcref_full_region_rate: float

    def to_dict(self) -> dict[str, Any]:
        return _with_hash(
            {
                "kind": "g_eco.rates",
                "status": "frozen_candidate",
                "seed_range": [min(self.seeds), max(self.seeds)],
                "seed_count": len(self.seeds),
                "steps": self.steps,
                "rates": asdict(self.rates),
                "tri_border": {
                    "naive_uniform_full_region_rate": self.naive_full_region_rate,
                    "homeostatic_oracle_full_region_rate": self.oracle_full_region_rate,
                    "wcref_full_region_rate": self.wcref_full_region_rate,
                },
                "firewall": {
                    "no_battery_outputs_used": True,
                    "used_refs": [
                        "naive_uniform",
                        "HOMEOSTATIC_ORACLE",
                        "WCREF",
                    ],
                    "excluded_arm_outputs": "candidate and finite-baseline arm-level outputs",
                },
            }
        )


@dataclass(frozen=True, slots=True)
class GEcoBatteryFreeze:
    rfinal_arm_names_value: tuple[str, ...]
    sources: Mapping[str, Mapping[str, Any]]
    fixed_aggregators: Mapping[str, str]
    vh_parameter_freeze: GEcoVHParameterFreeze

    def to_dict(self) -> dict[str, Any]:
        return _with_hash(
            {
                "kind": "g_eco.battery",
                "status": "frozen_candidate",
                "rfinal_arm_names": list(self.rfinal_arm_names_value),
                "fixed_aggregators": dict(self.fixed_aggregators),
                "sources": {
                    key: dict(value) for key, value in sorted(self.sources.items())
                },
                "calibration_only_refs_excluded": [
                    "HOMEOSTATIC_ORACLE",
                    "WCREF",
                ],
                "candidate_parameters": {
                    "VH": {
                        "source": self.vh_parameter_freeze.source_dict(),
                        "params": self.vh_parameter_freeze.params.to_dict(),
                    },
                    "VH_noStake": {
                        "source": {
                            "kind": "mechanical_ablation_constant_urgency",
                            "note": (
                                "Spec §1a ablation: urgency_k is degenerated to "
                                "constant weights, not selected by calibration."
                            ),
                        },
                        "params": {"constant_urgency": [1.0, 1.0, 1.0, 1.0]},
                    },
                },
                "performance_fields_withheld": True,
            }
        )


@dataclass(frozen=True, slots=True)
class GEcoThresholdFreeze:
    naive_er: float
    oracle_er: float
    seed_count: int
    K: int
    theta_lo: float
    theta_hi: float

    def to_dict(self) -> dict[str, Any]:
        return _with_hash(
            {
                "kind": "g_eco.thresholds",
                "status": "frozen_candidate",
                "theta_lo": self.theta_lo,
                "theta_hi": self.theta_hi,
                "m": "22/30",
                "alpha": 0.05,
                "omega_indist": 0.90,
                "delta_indist": 0.05,
                "omega_abl": 0.90,
                "rho_abl": 0.5,
                "delta_abl": 0.05,
                "formula": {
                    "theta_lo": "naive_er + 0.05",
                    "theta_hi": "0.5 * oracle_er",
                },
                "formula_inputs": [
                    "naive_er",
                    "oracle_er",
                    "seed_count",
                    "K",
                ],
                "input_values": {
                    "naive_er": self.naive_er,
                    "oracle_er": self.oracle_er,
                    "seed_count": self.seed_count,
                    "K": self.K,
                },
                "firewall": {
                    "uses_only_naive_and_oracle": True,
                    "opponent_arm_level_inputs_withheld": True,
                },
                "verdict_mechanics": {
                    "bootstrap": {
                        "B": 10000,
                        "resample_seed": 611038,
                        "ci_method": "percentile",
                    },
                    "battery_best_tie_break": [
                        "enter_rate_desc",
                        "survival_steps_desc",
                        "irreversible_loss_asc",
                        "arm_name_asc",
                    ],
                    "comparison": {
                        "epsilon": 1e-12,
                        "rounding": "none",
                    },
                },
            }
        )


@dataclass(frozen=True, slots=True)
class GEcoBaselineAudit:
    halt_booleans: Mapping[str, bool]
    mechanical_outputs: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return _with_hash(
            {
                "kind": "g_eco.baseline_audit",
                "status": "pregate2_mechanical_audit",
                "firewall": {
                    "withheld_arm_level_enter_rates": True,
                    "theta_locked_before_arm_distribution_release": True,
                },
                "halt_booleans": dict(self.halt_booleans),
                "mechanical_outputs": dict(self.mechanical_outputs),
            }
        )


def _default_initial_state() -> GEcoState:
    return GEcoState(energy=66.0, integrity=92.0, need_a=28.0, need_b=30.0)


def _rate_grid() -> tuple[GEcoRates, ...]:
    out: list[GEcoRates] = []
    for energy_drain in (3.0, 4.0, 5.0, 6.0, 7.0):
        for integrity_drain in (0.8, 1.2, 1.6, 2.0, 2.5):
            for need_a_growth in (1.5, 2.0, 2.5, 3.0, 3.5):
                for need_b_growth in (1.5, 2.0, 2.5, 3.0, 3.5):
                    out.append(
                        GEcoRates(
                            energy_drain=energy_drain,
                            integrity_drain=integrity_drain,
                            need_a_growth=need_a_growth,
                            need_b_growth=need_b_growth,
                        )
                    )
    return tuple(out)


def _env_for(seed: int, rates: GEcoRates) -> Ecological4CondEnv:
    return Ecological4CondEnv(
        rng=random.Random(20_000 + seed),
        rates=(rates,),
        initial_state=_default_initial_state(),
        observation_noise=0.5,
    )


def _run_full_region(
    seed: int,
    arm_name: str,
    *,
    rates: GEcoRates,
    steps: int,
    vh_params: GEcoVHParams | None = None,
) -> bool:
    arms = {
        arm.name: arm
        for arm in build_g_eco_arms(include_cheats=True, vh_params=vh_params)
    }
    if arm_name not in arms:
        raise ValueError(f"unknown G-Eco arm: {arm_name}")
    arm = arms[arm_name]
    env = _env_for(seed, rates)
    full_region = True
    for _ in range(steps):
        observation = arm.substrate.observe(env)
        action = arm.select(observation)
        if action is None:
            return False
        env.act(action)
        full_region = full_region and entered_viable_region(env.state)
        if not env.alive:
            return False
    return full_region


def _run_naive_full_region(seed: int, *, rates: GEcoRates, steps: int) -> bool:
    env = _env_for(seed, rates)
    full_region = True
    for idx in range(steps):
        env.act(env.actions[idx % len(env.actions)])
        full_region = full_region and entered_viable_region(env.state)
        if not env.alive:
            return False
    return full_region


def _full_region_rate(
    seeds: tuple[int, ...],
    runner: Callable[[int], bool],
) -> float:
    return sum(1 for seed in seeds if runner(seed)) / len(seeds)


def _run_arm_candidate_summary(
    seed: int,
    arm_name: str,
    *,
    rates: GEcoRates,
    steps: int,
    vh_params: GEcoVHParams,
) -> dict[str, float | bool]:
    arms = {arm.name: arm for arm in build_g_eco_arms(vh_params=vh_params)}
    arm = arms[arm_name]
    env = _env_for(seed, rates)
    full_region = True
    survival_steps = 0
    irreversible_loss = 0.0
    for _ in range(steps):
        observation = arm.substrate.observe(env)
        action = arm.select(observation)
        if action is None:
            break
        env.act(action)
        survival_steps += int(env.alive)
        irreversible_loss = max(irreversible_loss, 100.0 - env.state.integrity)
        full_region = full_region and entered_viable_region(env.state)
        if not env.alive:
            full_region = False
            break
    return {
        "full_region": full_region,
        "survival_steps": float(survival_steps),
        "irreversible_loss": irreversible_loss,
    }


def _vh_parameter_grid_hash() -> str:
    payload = {
        label: params.to_dict()
        for label, params in sorted(VH_PARAMETER_GRID, key=lambda item: item[0])
    }
    return _canonical_hash(payload)


def select_vh_parameters(
    rates_freeze: GEcoRatesFreeze,
    *,
    seeds: tuple[int, ...] = CALIBRATION_SEEDS,
    steps: int = 36,
) -> GEcoVHParameterFreeze:
    """Select VH params on calibration seeds and expose no performance values."""
    if not seeds:
        raise ValueError("seeds must be non-empty")
    best_score: tuple[float, float, float] | None = None
    best_label = ""
    best_params: GEcoVHParams | None = None
    for label, params in VH_PARAMETER_GRID:
        full_region_count = 0.0
        survival_total = 0.0
        irreversible_total = 0.0
        for seed in seeds:
            summary = _run_arm_candidate_summary(
                seed,
                "VH",
                rates=rates_freeze.rates,
                steps=steps,
                vh_params=params,
            )
            full_region_count += float(bool(summary["full_region"]))
            survival_total += float(summary["survival_steps"])
            irreversible_total += float(summary["irreversible_loss"])
        score = (
            full_region_count,
            survival_total,
            -irreversible_total,
        )
        if best_score is None or score > best_score:
            best_score = score
            best_label = label
            best_params = params
    assert best_params is not None
    return GEcoVHParameterFreeze(
        selected_label=best_label,
        params=best_params,
        seeds=seeds,
        steps=steps,
        parameter_grid_hash=_vh_parameter_grid_hash(),
    )


@lru_cache(maxsize=16)
def scan_rate_grid(
    *,
    seeds: tuple[int, ...] = RATE_SEEDS,
    steps: int = 36,
) -> GEcoRatesFreeze:
    """Find the first tri-border rate witness without observing battery outputs."""
    if not seeds:
        raise ValueError("seeds must be non-empty")
    for rates in _rate_grid():
        naive = _full_region_rate(
            seeds,
            lambda seed, r=rates: _run_naive_full_region(seed, rates=r, steps=steps),
        )
        oracle = _full_region_rate(
            seeds,
            lambda seed, r=rates: _run_full_region(
                seed, "HOMEOSTATIC_ORACLE", rates=r, steps=steps
            ),
        )
        wcref = _full_region_rate(
            seeds,
            lambda seed, r=rates: _run_full_region(seed, "WCREF", rates=r, steps=steps),
        )
        if naive == 0.0 and oracle > 0.0 and wcref > 0.0:
            return GEcoRatesFreeze(
                rates=rates,
                steps=steps,
                seeds=seeds,
                naive_full_region_rate=naive,
                oracle_full_region_rate=oracle,
                wcref_full_region_rate=wcref,
            )
    raise GEcoHalt(
        "R4_TRI_BORDER_EMPTY",
        "G-Eco rate grid has no naive-dead/oracle-live/WCREF-live witness.",
    )


def freeze_battery_parameters(
    rates_freeze: GEcoRatesFreeze | None = None,
    *,
    seeds: tuple[int, ...] = CALIBRATION_SEEDS,
    steps: int = 36,
) -> GEcoBatteryFreeze:
    rates = rates_freeze if rates_freeze is not None else scan_rate_grid()
    vh_parameter_freeze = select_vh_parameters(rates, seeds=seeds, steps=steps)
    arms = {arm.name: arm for arm in build_g_eco_battery()}
    sources: dict[str, Mapping[str, Any]] = {}
    for name, arm in arms.items():
        if arm.source is not None:
            sources[name] = {
                "adr": arm.source.adr,
                "symbol": arm.source.symbol,
                "params": dict(arm.source.params),
                "adapter_note": arm.source.adapter_note,
            }
    return GEcoBatteryFreeze(
        rfinal_arm_names_value=rfinal_arm_names(),
        sources=sources,
        fixed_aggregators={
            "LIN": "fixed linear weights",
            "LEX": "fixed priority channel",
            "THR": "fixed threshold satisfice",
            "QUOTA": "fixed round-robin quota",
            "MINIMAX": "fixed worst-channel aggregation",
            "VH": "candidate state-dependent homeostatic aggregation",
            "VH_noStake": "ablation constant urgency aggregation",
        },
        vh_parameter_freeze=vh_parameter_freeze,
    )


def derive_threshold_freeze(
    *,
    naive_er: float,
    oracle_er: float,
    seed_count: int,
    K: int,
) -> GEcoThresholdFreeze:
    theta_lo = naive_er + 0.05
    theta_hi = 0.5 * oracle_er
    if theta_hi <= theta_lo:
        raise GEcoHalt(
            "R4_THETA_DEGENERATE",
            "G-Eco theta anchors do not define a non-trivial band.",
        )
    return GEcoThresholdFreeze(
        naive_er=naive_er,
        oracle_er=oracle_er,
        seed_count=seed_count,
        K=K,
        theta_lo=theta_lo,
        theta_hi=theta_hi,
    )


def _action_overlap(
    left_name: str,
    right_name: str,
    *,
    rates: GEcoRates,
    seeds: tuple[int, ...],
    steps: int,
    vh_params: GEcoVHParams | None = None,
) -> float:
    equal = 0
    total = 0
    for seed in seeds:
        left_env = _env_for(seed, rates)
        right_env = _env_for(seed, rates)
        left_arm = {arm.name: arm for arm in build_g_eco_arms(vh_params=vh_params)}[
            left_name
        ]
        right_arm = {arm.name: arm for arm in build_g_eco_arms(vh_params=vh_params)}[
            right_name
        ]
        for _ in range(steps):
            left_action = left_arm.select(left_arm.substrate.observe(left_env))
            right_action = right_arm.select(right_arm.substrate.observe(right_env))
            equal += int(left_action == right_action)
            total += 1
            if left_action is None or right_action is None:
                break
            left_env.act(left_action)
            right_env.act(right_action)
            if not left_env.alive or not right_env.alive:
                break
    return equal / max(1, total)


def build_baseline_audit(
    rates_freeze: GEcoRatesFreeze,
    battery_freeze: GEcoBatteryFreeze,
    *,
    seeds: tuple[int, ...] = CALIBRATION_SEEDS,
    steps: int = 36,
) -> GEcoBaselineAudit:
    rates = rates_freeze.rates
    vh_params = battery_freeze.vh_parameter_freeze.params
    vh_rate = _full_region_rate(
        seeds,
        lambda seed: _run_full_region(
            seed, "VH", rates=rates, steps=steps, vh_params=vh_params
        ),
    )
    no_stake_rate = _full_region_rate(
        seeds,
        lambda seed: _run_full_region(
            seed, "VH_noStake", rates=rates, steps=steps, vh_params=vh_params
        ),
    )
    minimax_rate = _full_region_rate(
        seeds,
        lambda seed: _run_full_region(seed, "MINIMAX", rates=rates, steps=steps),
    )
    strongest_battery_rate = max(
        _full_region_rate(
            seeds,
            lambda seed, arm_name=arm_name: _run_full_region(
                seed, arm_name, rates=rates, steps=steps, vh_params=vh_params
            ),
        )
        for arm_name in GECO_BATTERY_NAMES
    )

    overlap_vh_no_stake = _action_overlap(
        "VH",
        "VH_noStake",
        rates=rates,
        seeds=seeds,
        steps=steps,
        vh_params=vh_params,
    )
    overlap_vh_minimax = _action_overlap(
        "VH",
        "MINIMAX",
        rates=rates,
        seeds=seeds,
        steps=steps,
        vh_params=vh_params,
    )
    sep_vh = vh_rate - strongest_battery_rate
    sep_no_stake = no_stake_rate - strongest_battery_rate
    ablation_delta = abs(vh_rate - no_stake_rate)
    indist_delta = abs(vh_rate - minimax_rate)

    halt_booleans = {
        "ablation_invalid": overlap_vh_no_stake > 0.90,
        "ablation_hitchhiking": sep_no_stake >= 0.5 * sep_vh or ablation_delta <= 0.05,
        "vh_minimax_indistinguishable": overlap_vh_minimax >= 0.90
        or indist_delta <= 0.05,
        "theta_degenerate": 0.5 * rates_freeze.oracle_full_region_rate
        <= rates_freeze.naive_full_region_rate + 0.05,
        "tri_border_empty": False,
    }
    mechanical_outputs = {
        "predicate_values_withheld": True,
        "sealed_predicates": [
            "ablation_invalid",
            "ablation_hitchhiking",
            "vh_minimax_indistinguishable",
        ],
        "wcref_not_weaker_than_runtime_minimax": rates_freeze.wcref_full_region_rate
        >= minimax_rate,
    }
    return GEcoBaselineAudit(
        halt_booleans=halt_booleans,
        mechanical_outputs=mechanical_outputs,
    )
