"""Environment-shift SCM for CWM-LEARN-2 (RR-0039 §5, pure-stdlib).

The gate asks the load-bearing question behind the founder's steer ("intelligence on OUR OWN built
model, not the borrowed LLM"): can our learned model GENERALISE UNDER DISTRIBUTION SHIFT better than
a statistical baseline, by exploiting cross-environment invariance (the causal signal)?

Task = invariant prediction under shift (Peters/ICP, Arjovsky/IRM setting), NOT ancestry discrimination.
An earlier ancestry framing was discarded before any scored run because it collapsed to either an
intervention-detection leak (detecting do(X) via ANY invariant downstream, not target-specific) or a
known-NULL (clean interventional target-shift is already causal and transfers) — see CWM-LEARN-2 prereg
§design-rationale. Predicting a target from covariates under a sign-flipping spurious proxy is the
canonical shift where a causal/invariant model can beat a statistical one, in EITHER direction honestly.

Structural model (per environment e with spurious coupling b_e):
    causal covariates  X_c ~ N(0,1)             (invariant causes of the target)
    target             T   = causal_coeff * sum(X_c) + noise ;  y = 1[T > 0]
    spurious proxies   X_s = b_e * T + noise      (CHILDREN of T; their coupling b_e FLIPS across envs)
    noise covariates   X_n ~ N(0,1)             (pure distractors)
Features (for predicting y) = [X_c..., X_s..., X_n...]; T and y are the label, never a feature.

  - a statistical predictor keys on X_s (strongest in-env signal, |b| large) -> NEGATIVE-transfers when
    b flips sign in the held-out env;
  - an invariance predictor keeps only stable-sign features -> keeps X_c, drops X_s and X_n -> robust.

FROZEN env parameters live in ENV_PARAMS (content-hashed into the prereg lock; no post-peek shopping).
Design chosen from first principles BEFORE any scored run: (a) spurious present in every env, (b) pooled
coupling mean NON-ZERO so naive pooling does not trivially cancel it, (c) >=1 sign flip in training so an
invariance test CAN detect non-invariance, (d) test coupling of flipped sign, held out of the train set.
"""
from __future__ import annotations

import random

# ---- FROZEN environment parameters (hashed into the prereg; never tuned post-peek) ----
ENV_PARAMS = {
    "n_causal": 2,        # invariant causes of the target
    "n_spurious": 2,      # proxies of the target with environment-varying coupling
    "n_noise": 2,         # pure distractors
    "causal_coeff": 1.1,  # invariant structural coefficient (same in every environment)
    "noise_sd": 1.0,
    "n_samples": 400,     # samples per environment
    # environment axis: training envs differ ONLY in spurious coupling b_e; the invariant causal core
    # is identical. Non-zero pooled mean (+0.95) so pooling does NOT trivially cancel the confound; one
    # clear sign flip so a stability test CAN drop the spurious; held-out test coupling of flipped sign.
    "train_couplings": [2.5, 1.5, 2.0, -2.2],   # 4 training environments; pooled mean = +0.95
    "test_coupling": -1.65,                       # held-out shift (flipped sign, not in the train set)
    "noshift_coupling": 2.0,                       # no-shift parity control: every env shares this coupling
}


def _feature_layout():
    p = ENV_PARAMS
    causal = list(range(0, p["n_causal"]))
    spurious = list(range(p["n_causal"], p["n_causal"] + p["n_spurious"]))
    noise = list(range(p["n_causal"] + p["n_spurious"],
                       p["n_causal"] + p["n_spurious"] + p["n_noise"]))
    return causal, spurious, noise


CAUSAL_IDX, SPURIOUS_IDX, NOISE_IDX = _feature_layout()
N_FEATURES = len(CAUSAL_IDX) + len(SPURIOUS_IDX) + len(NOISE_IDX)


def gen_env(seed: int, spurious_c: float) -> tuple[list[list[float]], list[int]]:
    """One environment defined by its spurious coupling `spurious_c`. Returns (feature_rows, labels).
    The causal mechanism (causal_coeff on X_c -> T) is identical for every environment."""
    p = ENV_PARAMS
    rng = random.Random(seed * 7919 + int(round(spurious_c * 1000)) + 101)
    rows, labels = [], []
    for _ in range(p["n_samples"]):
        xc = [rng.gauss(0.0, 1.0) for _ in range(p["n_causal"])]
        t_cont = p["causal_coeff"] * sum(xc) + rng.gauss(0.0, p["noise_sd"])
        y = 1 if t_cont > 0.0 else 0
        xs = [spurious_c * t_cont + rng.gauss(0.0, p["noise_sd"]) for _ in range(p["n_spurious"])]
        xn = [rng.gauss(0.0, 1.0) for _ in range(p["n_noise"])]
        rows.append(xc + xs + xn)
        labels.append(y)
    return rows, labels


def train_envs(seed: int, no_shift: bool = False) -> list[tuple[list[list[float]], list[int]]]:
    """The frozen list of training environments. no_shift=True replaces the sign-varying couplings with a
    single repeated coupling (parity control: the spurious becomes invariant, is NOT filtered, and the
    invariance arm's OOD advantage should vanish)."""
    p = ENV_PARAMS
    couplings = ([p["noshift_coupling"]] * len(p["train_couplings"])) if no_shift else p["train_couplings"]
    return [gen_env(seed + 1000 * i, c) for i, c in enumerate(couplings)]


def test_env(seed: int, no_shift: bool = False) -> tuple[list[list[float]], list[int]]:
    """The held-out test environment. no_shift=True keeps the training coupling (parity control)."""
    p = ENV_PARAMS
    c = p["noshift_coupling"] if no_shift else p["test_coupling"]
    return gen_env(seed + 500000, c)
