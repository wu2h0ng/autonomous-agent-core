"""Interaction-structured environment-shift SCM for CWM-LEARN-3 (RR-0039 gate 3, pure stdlib).

The bar (founder): a MORE COMPLEX self-built mechanism must beat the statistical baseline on STRUCTURE
THE LINEAR INVARIANCE PRINCIPLE CANNOT NAME. Here the invariant causal signal is a NON-ADDITIVE
INTERACTION Xc1*Xc2 (each component's linear marginal is ~0), so LEARN-2's raw-feature sign-consistency
filter is blind to it; and the shifting spurious signal is carried by a coordinate with NO sign-stable
degree-2 image, so it cannot survive an invariance filter over a degree-2 CROSS-product basis.

Design frozen by the cwm-learn-3-design workflow (Builder A/B + Skeptic C -> synthesis -> 5-lens red-team
-> packet). Key structural fixes the red-team forced (all at the generator level, not prose):
  - independent-latent spurious (NOT shared-latent): a shared latent u makes the SELF-SQUARE Xs^2 carry a
    class signal with coefficient b_e^2 that is ALWAYS positive regardless of the sign flip -> it survives
    the invariance filter and cushions the capacity gate. Discarded.
  - the degree-2 basis EXCLUDES self-squares (cross-products i<j only), removing Xs1^2/Xs2^2 at the
    representation level, not by hoping regularization suppresses them.
  - a_lin=0.30 (not 0.5): keeps the honest linear decoy Xc3 below the linear-ceiling gate (<0.62 OOD).
  - train couplings are a 2-positive / 2-negative split (not a single flip env): a spurious coordinate
    must be sign-stable across a 2-vs-2 split to survive; single-env sign luck is eliminated.
  - named independent RNG streams per (env, role): train/test row-disjointness is STRUCTURAL (audit A6).

FROZEN ENV_PARAMS_L3 is content-hashed into the prereg; chosen from first principles pre-freeze, never
tuned post-peek. Full rationale + pre-freeze audits A1-A6 in docs/pre_spec/CWM-LEARN-3.DESIGN-PACKET.
"""
from __future__ import annotations

import random

# ---- FROZEN environment parameters (hashed into the prereg; never tuned post-peek) ----
ENV_PARAMS_L3 = {
    "n_causal_xor": 2,          # Xc1, Xc2 — interaction causes (product drives y; ~0 linear marginal each)
    "n_causal_lin": 1,          # Xc3 — honest invariant linear decoy (sub-ceiling)
    "n_spurious": 2,            # Xs1 (flipping class channel), Xs2 (independent decoy)
    "n_noise": 2,               # Xn1, Xn2
    "a_xor": 2.2,               # interaction strength (dominates the target)
    "a_lin": 0.30,              # linear-decoy strength (Xc3-only Bayes AUC ~= 0.567 < 0.62 ceiling)
    "noise_sd": 1.0,
    "spur_noise": 1.0,
    "spurious_strength_cap": 2.8,      # |train coupling| ceiling (self-squares excluded, so no Xs^2 bound needed)
    "n_samples": 800,
    # 2-vs-2 sign split (our per-env filter + LEARN-2 arm both reliably drop Xs1) BUT with a clearly NON-ZERO
    # pooled mean (+0.55) so pooling does NOT cancel the confound in the capacity-matched baseline — otherwise
    # the C5 capacity-confound test is vacuous (pre-freeze A5 on calibration seeds proved a near-zero mean
    # leaves the baseline robust OOD, Δ_B≈0.017 << 0.05; corrected from first principles, scored seeds unseen).
    "train_couplings": [2.8, 2.4, -1.7, -1.3],   # 2-vs-2 sign split; pooled mean +0.55 (strong, non-canceling)
    "test_coupling": -1.6,             # held-out shift (negative regime; not equal to any train coupling)
    "indist_ref_coupling": 1.6,        # C5 in-dist reference (train sign regime, same |magnitude| as OOD)
    "noshift_coupling": 1.5,           # C1 no-shift parity only
    "balance_band": [0.4, 0.6],        # label-prevalence guard
    "basis": "degree2_cross_only",     # i<j pairwise products, NO self-squares
    "seeds": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    "rng_scheme": "named_streams_v3",
}

# environment tags -> distinct RNG streams (structural train/test disjointness, audit A6)
_TAG_TRAIN = [0, 1, 2, 3]
_TAG_TEST = 99
_TAG_INDIST_REF = 88     # C5 in-distribution reference (train sign regime)
_TAG_NOSHIFT_BASE = 70   # C1 parity envs 70..73 (+ test 77)


def _stream(base_seed: int, env_tag: int, role: str) -> random.Random:
    """Named, independent RNG stream per (seed, env, role). String seed => collision-free, and different
    env_tag => disjoint rows across train (0..3) vs test (99) vs refs (audit A6)."""
    return random.Random(f"L3|{base_seed}|{env_tag}|{role}")


def _n_features() -> int:
    p = ENV_PARAMS_L3
    return p["n_causal_xor"] + p["n_causal_lin"] + p["n_spurious"] + p["n_noise"]


# frozen feature layout: [Xc1, Xc2, Xc3, Xs1, Xs2, Xn1, Xn2]
CAUSAL_XOR_IDX = [0, 1]
CAUSAL_LIN_IDX = [2]
SPURIOUS_IDX = [3, 4]
NOISE_IDX = [5, 6]
INTERACTION_PAIR = (0, 1)
N_FEATURES = _n_features()


def gen_env_l3(base_seed: int, spurious_c: float, env_tag: int,
               a_xor: float | None = None, a_lin: float | None = None) -> tuple[list[list[float]], list[int]]:
    """One environment. spurious_c sets the flipping class channel on Xs1; env_tag selects the RNG stream.
    a_xor/a_lin override the frozen strengths (for the causal-ablation control C2 and the pure-interaction
    positive control C4). Returns (feature_rows, labels). T_cont and y are label-only, never features."""
    p = ENV_PARAMS_L3
    ax = p["a_xor"] if a_xor is None else a_xor
    al = p["a_lin"] if a_lin is None else a_lin
    rc = _stream(base_seed, env_tag, "causal")
    rs = _stream(base_seed, env_tag, "spurious")
    rn = _stream(base_seed, env_tag, "noise")
    rows, labels = [], []
    for _ in range(p["n_samples"]):
        xc1, xc2, xc3 = rc.gauss(0, 1), rc.gauss(0, 1), rc.gauss(0, 1)
        t_cont = ax * (xc1 * xc2) + al * xc3 + rc.gauss(0, p["noise_sd"])
        y = 1 if t_cont > 0.0 else 0
        s = spurious_c * (2 * y - 1)                       # class-linked spurious; sign = sign(spurious_c)
        xs1 = s + rs.gauss(0, p["spur_noise"])             # Xs1 carries the flipping linear class channel
        xs2 = rs.gauss(0, 1)                               # Xs2: independent decoy, NO class signal
        xn1, xn2 = rn.gauss(0, 1), rn.gauss(0, 1)
        rows.append([xc1, xc2, xc3, xs1, xs2, xn1, xn2])
        labels.append(y)
    return rows, labels


def train_envs_l3(seed: int, no_shift: bool = False) -> list[tuple[list[list[float]], list[int]]]:
    """The 4 frozen training environments (2-vs-2 sign split). no_shift=True (C1 parity) makes every env
    share one coupling so the spurious no longer flips."""
    p = ENV_PARAMS_L3
    if no_shift:
        return [gen_env_l3(seed, p["noshift_coupling"], _TAG_NOSHIFT_BASE + i) for i in range(4)]
    return [gen_env_l3(seed, c, _TAG_TRAIN[i]) for i, c in enumerate(p["train_couplings"])]


def test_env_l3(seed: int, no_shift: bool = False) -> tuple[list[list[float]], list[int]]:
    """Held-out shifted test env (test_coupling). no_shift=True keeps the parity coupling."""
    p = ENV_PARAMS_L3
    if no_shift:
        return gen_env_l3(seed, p["noshift_coupling"], _TAG_NOSHIFT_BASE + 7)
    return gen_env_l3(seed, p["test_coupling"], _TAG_TEST)


def indist_ref_env_l3(seed: int) -> tuple[list[list[float]], list[int]]:
    """C5 in-distribution reference: TRAIN sign regime (+1.6), same |magnitude| as the OOD test (-1.6).
    The only difference from test_env_l3 is the spurious SIGN flip -> the C5 drop measures the flip alone."""
    return gen_env_l3(seed, ENV_PARAMS_L3["indist_ref_coupling"], _TAG_INDIST_REF)


def interaction_only_env_l3(seed: int, env_tag: int) -> tuple[list[list[float]], list[int]]:
    """C4 pure-interaction split: spurious_c=0 (Xs1 becomes pure noise), so the label is driven only by
    the interaction + the Xc3 decoy. Used to prove the mechanism CAN capture the interaction (C4a) and
    that a linear arm CANNOT (C4b)."""
    return gen_env_l3(seed, 0.0, env_tag)
