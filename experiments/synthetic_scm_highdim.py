"""High-dimensional semi-synthetic SCM for CWM-LEARN-5e (RR-0041; design: CWM-LEARN-5E.DESIGN-2026-07-04).

p >> n regime where exhaustive degree-2 enumeration + invariance selection is expected to DEGRADE while a
small pruned candidate set stays in the LEARN-3-validated p << n regime. 60 raw features -> 60 + C(60,2) =
1,830 cross2 coordinates vs 400 samples/env.

Structure (anonymous indices for the pilot; the preregistered NAME SCHEMA maps onto these for the LLM phase):
  true interaction pairs: (0,1) (2,3) (4,5) (6,7), beta_xor = 1.2 each (invariant across envs)
  true linear terms:      8, 9 with beta_lin = 0.8       (invariant)
  spurious channels:      10..17 — children of y, per-env coefficient with SIGN FLIPS across the 4 training
                          envs (frozen sign table), fresh draw in the OOD test env
  dense weak correlation: every feature loads 0.3 on one global latent factor (worsens dilution)
  everything else:        noise features
Deterministic per (seed, env_tag) via named RNG streams. Pilot uses seeds 100.. (disjoint from any scored set).
"""
from __future__ import annotations

import random

HD_PARAMS = {
    "n_raw": 60,
    "true_pairs": [[0, 1], [2, 3], [4, 5], [6, 7]],
    "beta_xor": 1.2,
    "true_linear": [8, 9],
    "beta_lin": 0.8,
    "spurious": list(range(10, 18)),          # 8 channels
    "spur_strength": 1.6,
    "spur_noise": 0.8,
    # per-env sign pattern for the 8 spurious channels across the 4 training envs (frozen; each channel
    # flips at least once across envs so sign-consistency CAN reject it)
    "spur_signs": [
        [+1, +1, -1, -1], [-1, +1, +1, -1], [+1, -1, +1, -1], [-1, -1, +1, +1],
        [+1, -1, -1, +1], [-1, +1, -1, +1], [+1, +1, +1, -1], [-1, -1, -1, +1],
    ],
    "test_signs": [-1, +1, -1, +1, -1, +1, -1, +1],   # fresh OOD pattern
    "global_load": 0.3,
    "noise_sd": 1.0,
    "n_train": 400,
    "n_test": 2000,
    "n_envs": 4,
}


def _stream(seed: int, tag: str) -> random.Random:
    return random.Random(f"HD5e|{seed}|{tag}")


def _gen(seed: int, tag: str, n: int, signs: list[int],
         true_pairs=None, true_linear=None) -> tuple[list[list[float]], list[int]]:
    """true_pairs/true_linear override the frozen defaults — condition-B (incongruent) generation for the
    5e knowledge control: same schema/names, arbitrary true structure (frozen pre-proposal, see prereg)."""
    p = HD_PARAMS
    tp = p["true_pairs"] if true_pairs is None else true_pairs
    tl = p["true_linear"] if true_linear is None else true_linear
    rng = _stream(seed, tag + ("" if true_pairs is None else "|B"))
    rows, labels = [], []
    for _ in range(n):
        g = rng.gauss(0, 1)
        x = [p["global_load"] * g + rng.gauss(0, 1) for _ in range(p["n_raw"])]
        t = sum(p["beta_xor"] * x[a] * x[b] for a, b in tp)
        t += sum(p["beta_lin"] * x[k] for k in tl)
        y = 1 if (t + rng.gauss(0, p["noise_sd"])) > 0 else 0
        for ci, k in enumerate(p["spurious"]):
            x[k] += signs[ci] * p["spur_strength"] * (2 * y - 1) + rng.gauss(0, p["spur_noise"])
        rows.append(x)
        labels.append(y)
    return rows, labels


def train_envs_hd(seed: int, true_pairs=None, true_linear=None) -> list[tuple[list[list[float]], list[int]]]:
    p = HD_PARAMS
    return [_gen(seed, f"env{e}", p["n_train"], [p["spur_signs"][c][e] for c in range(len(p["spurious"]))],
                 true_pairs, true_linear)
            for e in range(p["n_envs"])]


def test_env_hd(seed: int, true_pairs=None, true_linear=None) -> tuple[list[list[float]], list[int]]:
    return _gen(seed, "test", HD_PARAMS["n_test"], HD_PARAMS["test_signs"], true_pairs, true_linear)


def expand_pairs(rows: list[list[float]], pairs: list[list[int]]) -> list[list[float]]:
    """Pre-expand candidate pair columns onto raw rows (arms feed basis='raw' on the expanded rows, so every
    arm runs the IDENTICAL validated verifier — design §3)."""
    return [r + [r[a] * r[b] for a, b in pairs] for r in rows]
