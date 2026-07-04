"""CWM-LEARN-5a/5b environment extensions (RR-0041, pure stdlib). Builds ON TOP of the LEARN-4 generator
(synthetic_scm_transfer.py stays byte-frozen) to support the two founder-opened enhancement routes:

  5a  multi-environment augmentation + curriculum: MORE and MORE-DIVERSE training environments (weak-coupling
      linear proxies, strong linear proxies = the LEARN-4 set, tanh proxies on a different slot), trained
      easy->hard, versus direct all-at-once training.
  5b  few interventional anchors: a small do(Xs)-randomized sample set (the A/B-test analog: the nuisance slot
      is EXPLICITLY randomized, breaking the spurious-label link) added as one extra training environment.

Isolation notes (frozen honesty):
  - 5a training includes tanh-slot3 envs, so LEARN-4's NOVEL-B is NOT family-isolated for 5a. 5a's strict
    isolation test is NOVEL-C (linear flipped proxy on slot 4 — a slot never nuisanced in training);
    NOVEL-A (independent nuisance) stays the primary. Caveat recorded: weak-coupling envs approach the
    NOVEL-A limit (coupling->0), so NOVEL-A isolation is weakened for 5a; NOVEL-C carries strictness.
  - 5b trains only on the LEARN-4 strong-linear family + anchors, so NOVEL-B remains strictly isolated for
    5b (its tanh mechanism was never trained on and never intervened on) -> NOVEL-B is 5b's primary.
  - Anchor rows draw slot-2 from Uniform(-3,3) (an explicit intervention distribution), NOT N(0,1), so the
    anchor environment is not a sample of the NOVEL-A test family.
"""
from __future__ import annotations

import math
import random

import experiments.synthetic_scm_transfer as base

EXT_PARAMS = {
    # 5a curriculum: 3 weak linear + the 3 LEARN-4 strong linear + 2 tanh-slot3 envs = 8 training envs
    "weak_couplings": [0.5, -0.4, 0.3],
    "strong_couplings": list(base.ENV_PARAMS_T["train_couplings"]),   # [2.0, -1.5, 1.0] (LEARN-4 frozen)
    "tanh_couplings": [2.0, -1.8],
    "novelC_coupling": -1.6,          # strict-isolation test: linear flipped proxy on slot 4
    "anchor_range": 3.0,              # do(Xs) ~ Uniform(-3, 3)
    "curriculum": {"stage1_epochs": 150, "stage2_epochs": 150, "stage1_lam": 0.0, "stage2_lam": 1e4},
    "direct_epochs": 300, "direct_lam": 1e4,
}


def _stream(seed: int, tag: str, role: str) -> random.Random:
    return random.Random(f"T5|{seed}|{tag}|{role}")


def gen_tanh_env(seed: int, coupling: float, env_tag: int) -> tuple[list[list[float]], list[int]]:
    """Training env with a NONLINEAR (tanh) proxy on slot 3 (mechanism class of LEARN-4's NOVEL-B, now used
    for TRAINING diversity in 5a — which is exactly why NOVEL-B is no longer 5a's isolation test)."""
    p = base.ENV_PARAMS_T
    rc = _stream(seed, f"tanh{env_tag}", "causal")
    rs = _stream(seed, f"tanh{env_tag}", "spurious")
    rn = _stream(seed, f"tanh{env_tag}", "noise")
    rows, labels = [], []
    for _ in range(p["n_samples"]):
        xc1, xc2 = rc.gauss(0, 1), rc.gauss(0, 1)
        y = 1 if (xc1 * xc2 + rc.gauss(0, p["noise_sd"])) > 0 else 0
        x3 = coupling * math.tanh(1.5 * (2 * y - 1)) + rs.gauss(0, p["spur_noise"])
        rows.append([xc1, xc2, rn.gauss(0, 1), x3, rn.gauss(0, 1)])
        labels.append(y)
    return rows, labels


def train_family_8(seed: int) -> dict[str, list[tuple[list[list[float]], list[int]]]]:
    """5a's diverse training family, staged: 'weak' (3 envs) and 'strong_plus' (3 strong linear + 2 tanh).
    Curriculum trains weak first, then all 8; direct trains all 8 at once."""
    weak = [base.gen_train_env(seed, c, 10 + i) for i, c in enumerate(EXT_PARAMS["weak_couplings"])]
    strong = [base.gen_train_env(seed, c, i) for i, c in enumerate(EXT_PARAMS["strong_couplings"])]
    tanh_envs = [gen_tanh_env(seed, c, i) for i, c in enumerate(EXT_PARAMS["tanh_couplings"])]
    return {"weak": weak, "strong_plus": strong + tanh_envs}


def novelC_env(seed: int) -> tuple[list[list[float]], list[int]]:
    """5a strict-isolation test: linear flipped proxy on slot 4 — a slot never nuisanced in training."""
    p = base.ENV_PARAMS_T
    rc = _stream(seed, "novelC", "causal")
    rs = _stream(seed, "novelC", "spurious")
    rn = _stream(seed, "novelC", "noise")
    rows, labels = [], []
    for _ in range(p["n_samples"]):
        xc1, xc2 = rc.gauss(0, 1), rc.gauss(0, 1)
        y = 1 if (xc1 * xc2 + rc.gauss(0, p["noise_sd"])) > 0 else 0
        x4 = EXT_PARAMS["novelC_coupling"] * (2 * y - 1) + rs.gauss(0, p["spur_noise"])
        rows.append([xc1, xc2, rn.gauss(0, 1), rn.gauss(0, 1), x4])
        labels.append(y)
    return rows, labels


def anchor_env(seed: int, n: int) -> tuple[list[list[float]], list[int]]:
    """5b interventional anchors: do(slot2) ~ Uniform(-anchor_range, +anchor_range) — the nuisance slot is
    EXPLICITLY randomized (A/B-test analog), so these n samples carry the information 'slot 2 is not
    mechanistically tied to y'. Slots 3,4 stay standard noise; y comes from the invariant mechanism."""
    p = base.ENV_PARAMS_T
    rc = _stream(seed, "anchor", "causal")
    ri = _stream(seed, "anchor", "intervention")
    rn = _stream(seed, "anchor", "noise")
    a = EXT_PARAMS["anchor_range"]
    rows, labels = [], []
    for _ in range(n):
        xc1, xc2 = rc.gauss(0, 1), rc.gauss(0, 1)
        y = 1 if (xc1 * xc2 + rc.gauss(0, p["noise_sd"])) > 0 else 0
        rows.append([xc1, xc2, ri.uniform(-a, a), rn.gauss(0, 1), rn.gauss(0, 1)])
        labels.append(y)
    return rows, labels
