"""Parity-lag falsifier, CLEAN re-prereg (large-lag only) — isolates the long-memory readout.

Follows the INCONCLUSIVE first prereg (experiments/parity_lag_falsifier.py, gap 0.445 < TAU
0.50): the original mixed lags 1..8, and EWMA/last_x LEAKED the small-lag bits (k=1 exact;
k=2,3 partial), so the cheap baseline reached ~75% and the gap stayed under TAU. That
INCONCLUSIVE verdict stands and is NOT reinterpreted.

This is a FRESH pre-registration that removes the confound by restricting the lag to k in
{5,6,7,8}. There the EWMA weight on x_{t-k} is <= 0.5^5 ~ 0.03 (negligible) and last_x (k=1)
is excluded -- so the cheap summary class carries no useful information about the lag-k bit.
The DECISION RULE and THRESHOLDS are UNCHANGED from the first prereg (the only edit is the env
lag range; this is design-cleaning, not goalpost-moving):

  gap = mean_reward(rich) - mean_reward(baseline) on the post-learning tail.
    gap <= EPS=0.10  -> FORECLOSURE: cheap class complete even for a long-memory high-order
                        readout; the thin readout is STRUCTURAL (SD4/ADR-0037 negative answer).
    gap >= TAU=0.50  -> ARTIFACT: cheap class INCOMPLETE for a long-memory high-order readout;
                        C6 permits a richer (bounded-memory) readout it cannot carry; the 12
                        reductions were SCOPED to low-order/short-memory envs; enrich-S REOPENS
                        (winning lever = MEMORY, scoped -- NOT world-models; see caveat below).

HONEST CAVEAT (pre-registered, unchanged): the richer readout is a BOUNDED BUFFER = memory
(R-CSL-1's axis). An ARTIFACT verdict refutes "C6 forces thin readout regardless of reward"
but the winning mechanism is memory scoped to high-order rewards, NOT a vindication of
world-models/belief-organs. Pure stdlib; C6-clean (bounded-memory observation-policies only).
"""
from __future__ import annotations

import random

LAG_MIN = 5
LAG_MAX = 8
K_BUF = LAG_MAX          # buffer depth the rich readout keeps
LAG_PERIOD = 50
STEPS = 30000
SEEDS = tuple(range(6))
EPS = 0.10               # UNCHANGED from the first prereg
TAU = 0.50               # UNCHANGED from the first prereg
EWMA_ALPHA = 0.5


def make_stream(seed: int, steps: int) -> list[tuple[int, int, int]]:
    rng = random.Random(seed)
    hist: list[int] = []
    k = LAG_MIN
    stream: list[tuple[int, int, int]] = []
    for t in range(steps):
        if t % LAG_PERIOD == 0:
            k = rng.randint(LAG_MIN, LAG_MAX)
        x = rng.randint(0, 1)
        xk = hist[-k] if len(hist) >= k else 0
        stream.append((x, k, x ^ xk))
        hist.append(x)
    return stream


def _feat_baseline(x, k, hist, ewma, last_x, last_a):
    win = hist[-K_BUF:]
    occ = 1 if (win and sum(win) > len(win) / 2) else 0
    return (x, k, round(ewma, 1), occ, last_x, last_a)


def _feat_rich(x, k, hist, ewma, last_x, last_a):
    xk = hist[-k] if len(hist) >= k else 0
    return (x, k, xk)


def run_learner(stream, feat_fn, *, seed: int) -> float:
    rng = random.Random(90000 + seed)
    table: dict[tuple, list[list[float]]] = {}
    hist: list[int] = []
    last_a = 0
    ewma = 0.5
    rewards: list[float] = []
    n = len(stream)
    explore_until = int(0.6 * n)
    for t, (x, k, astar) in enumerate(stream):
        bucket = feat_fn(x, k, hist, ewma, hist[-1] if hist else 0, last_a)
        slot = table.setdefault(bucket, [[0.0, 0], [0.0, 0]])
        if t < explore_until or rng.random() < 0.05:
            a = rng.randint(0, 1)
        else:
            a0 = slot[0][0] / slot[0][1] if slot[0][1] else 0.0
            a1 = slot[1][0] / slot[1][1] if slot[1][1] else 0.0
            a = 0 if a0 >= a1 else 1
        r = 1.0 if a == astar else -1.0
        slot[a][0] += r
        slot[a][1] += 1
        rewards.append(r)
        ewma = (1 - EWMA_ALPHA) * ewma + EWMA_ALPHA * x
        hist.append(x)
        last_a = a
    tail = rewards[int(0.8 * n):]
    return sum(tail) / len(tail)


def main() -> None:
    print(f"Parity-lag CLEAN re-prereg (large-lag {LAG_MIN}..{LAG_MAX}) | seeds={len(SEEDS)} steps={STEPS}")
    print("frozen summary baseline vs bounded-buffer rich readout; EPS/TAU unchanged from prereg-1\n")
    print(f"{'seed':>4} | {'baseline':>9} {'rich':>9} {'gap':>7}")
    gaps = []
    for s in SEEDS:
        stream = make_stream(s, STEPS)
        b = run_learner(stream, _feat_baseline, seed=s)
        r = run_learner(stream, _feat_rich, seed=s)
        gaps.append(r - b)
        print(f"{s:>4} | {b:>9.3f} {r:>9.3f} {r - b:>7.3f}")
    mean_gap = sum(gaps) / len(gaps)
    print(f"\nmean gap (rich - baseline): {mean_gap:.3f}   [EPS={EPS}, TAU={TAU}]")
    if mean_gap <= EPS:
        verdict = ("FORECLOSURE -> cheap class complete even for a long-memory high-order readout; "
                   "thin readout STRUCTURAL (SD4/ADR-0037 negative answer-shape).")
    elif mean_gap >= TAU:
        verdict = ("ARTIFACT -> cheap class INCOMPLETE for a long-memory high-order readout; C6 "
                   "permits a richer bounded-memory readout it cannot carry. The 12 reductions were "
                   "SCOPED to low-order/short-memory envs; enrich-S REOPENS (winning lever = MEMORY, "
                   "scoped to high-order rewards -- NOT world-models; pre-registered caveat).")
    else:
        verdict = "INCONCLUSIVE -> gap between EPS and TAU."
    print("\nVERDICT (pre-registered, cheap falsifier; NOT a Route-C verdict): " + verdict)


if __name__ == "__main__":
    main()
