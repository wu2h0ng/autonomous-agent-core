"""Family-structured cross-domain transfer SCM for CWM-LEARN-4 (RR-0039 gate 4, pure stdlib).

The bar (founder): train a SELF-LEARNED representation on ONE environment FAMILY, test generalisation on a
COMPLETELY ISOLATED, BRAND-NEW family. Two upgrades over LEARN-3: (1) the representation is LEARNED (a stdlib
MLP), not a supplied degree-2 basis; (2) the test family is held out at the FAMILY level (a nuisance MECHANISM
never seen in training), not merely a new coupling value.

Invariant causal mechanism (SHARED by every family): y = 1[Xc1*Xc2 + noise > 0] — a non-additive INTERACTION
of the two causal features on slots 0,1. What a FAMILY changes is the NUISANCE mechanism on the other slots.

Families:
  TRAIN family  — multiple environments with an EXPLOITABLE spurious on slot 2: Xs = c_e*(2y-1)+noise, the
                  coupling c_e sign-varying across training envs (so an invariance criterion COULD learn to
                  ignore it). This is the only signal an ERM learner is tempted to ride.
  NOVEL-A test  — the sharp discriminator: the slot-2 spurious is INDEPENDENT of y (pure noise). Nothing on the
                  nuisance slots is exploitable, so ONLY a representation that isolated the invariant interaction
                  transfers; a model that rode the training spurious collapses to chance. (Held out at family
                  level; distinct RNG stream.)
  NOVEL-B test  — a genuinely DIFFERENT nuisance mechanism (relocated + nonlinear proxy on slot 3), never seen in
                  training — reported secondarily.

Design note (red-team fix): NOVEL-A carries NO exploitable nuisance, so the family-isolation "leakage" failure
(a novel-family nuisance a trivial baseline rides) cannot occur — the transfer test is clean by construction.
FROZEN ENV_PARAMS_T is content-hashed into the prereg. Named RNG streams => structural family disjointness.
"""
from __future__ import annotations

import math
import random

ENV_PARAMS_T = {
    "n_features": 5,                 # [Xc1, Xc2, Xs, Xn1, Xn2]
    "causal_idx": [0, 1],            # interaction causes
    "spurious_idx": 2,
    "noise_idx": [3, 4],
    "noise_sd": 0.4,                 # label noise on the interaction
    "n_samples": 400,
    "train_couplings": [2.0, -1.5, 1.0],   # sign-varying exploitable spurious across 3 training envs
    "spur_noise": 0.5,
    "novelB_coupling": 2.0,          # NOVEL-B relocated nonlinear proxy strength
    "seeds": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    "rng_scheme": "named_streams_v4",
}

CAUSAL_IDX = ENV_PARAMS_T["causal_idx"]
SPURIOUS_IDX = ENV_PARAMS_T["spurious_idx"]
N_FEATURES = ENV_PARAMS_T["n_features"]


def _stream(seed: int, family_tag: str, role: str) -> random.Random:
    return random.Random(f"T4|{seed}|{family_tag}|{role}")


def _sample_label(rc: random.Random):
    p = ENV_PARAMS_T
    xc1, xc2 = rc.gauss(0, 1), rc.gauss(0, 1)
    y = 1 if (xc1 * xc2 + rc.gauss(0, p["noise_sd"])) > 0 else 0
    return xc1, xc2, y


def gen_train_env(seed: int, coupling: float, env_tag: int) -> tuple[list[list[float]], list[int]]:
    """A TRAIN-family environment: exploitable spurious on slot 2 with the given (sign-varying) coupling."""
    p = ENV_PARAMS_T
    rc = _stream(seed, f"train{env_tag}", "causal")
    rs = _stream(seed, f"train{env_tag}", "spurious")
    rn = _stream(seed, f"train{env_tag}", "noise")
    rows, labels = [], []
    for _ in range(p["n_samples"]):
        xc1, xc2, y = _sample_label(rc)
        xs = coupling * (2 * y - 1) + rs.gauss(0, p["spur_noise"])
        rows.append([xc1, xc2, xs, rn.gauss(0, 1), rn.gauss(0, 1)])
        labels.append(y)
    return rows, labels


def train_family(seed: int) -> list[tuple[list[list[float]], list[int]]]:
    return [gen_train_env(seed, c, i) for i, c in enumerate(ENV_PARAMS_T["train_couplings"])]


def novelA_env(seed: int) -> tuple[list[list[float]], list[int]]:
    """ISOLATED novel family A: slot-2 spurious is INDEPENDENT of y (pure noise). Only the invariant
    interaction can transfer -> a spurious-rider collapses to chance. The sharp discriminator."""
    p = ENV_PARAMS_T
    rc = _stream(seed, "novelA", "causal")
    rn = _stream(seed, "novelA", "noise")
    rows, labels = [], []
    for _ in range(p["n_samples"]):
        xc1, xc2, y = _sample_label(rc)
        rows.append([xc1, xc2, rn.gauss(0, 1), rn.gauss(0, 1), rn.gauss(0, 1)])
        labels.append(y)
    return rows, labels


def novelB_env(seed: int) -> tuple[list[list[float]], list[int]]:
    """ISOLATED novel family B: a DIFFERENT nuisance mechanism never in training — a relocated, NONLINEAR
    spurious proxy on slot 3 (tanh-squashed), flipped sign. Secondary transfer test."""
    p = ENV_PARAMS_T
    rc = _stream(seed, "novelB", "causal")
    rs = _stream(seed, "novelB", "spurious")
    rn = _stream(seed, "novelB", "noise")
    rows, labels = [], []
    for _ in range(p["n_samples"]):
        xc1, xc2, y = _sample_label(rc)
        xn3 = p["novelB_coupling"] * math.tanh(1.5 * -(2 * y - 1)) + rs.gauss(0, p["spur_noise"])
        rows.append([xc1, xc2, rn.gauss(0, 1), xn3, rn.gauss(0, 1)])
        labels.append(y)
    return rows, labels


def interaction_only(rows: list[list[float]]) -> list[list[float]]:
    """Oracle projection: keep only the causal slots (0,1) — confirms the invariant signal is present."""
    return [[r[0], r[1]] for r in rows]
