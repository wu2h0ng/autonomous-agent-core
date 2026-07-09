"""Parity-lag falsifier — the structural-vs-artifact crux (pre-registered).

Tests the closure-completeness lemma behind the integration judge's claimed STRUCTURAL
FORECLOSURE (docs/research/thin-readout-law-and-structural-vs-artifact-crux-2026-06-28.md):

  Is the control readout in the closure of {EWMA, occupancy, recency, last-action, V}
  REGARDLESS of reward order (structural, forced by C6), or only when the reward is
  low-order (artifact of the envs the program tested)?

PRE-REGISTRATION (frozen BEFORE running; do not edit after seeing results):
- ENV (high-order reward, |A|=2, C6-clean): each step emits a fresh random bit x_t and an
  observable slow lag-selector k_t in 1..K_MAX (changes every LAG_PERIOD steps). The optimal
  action is a* = x_t XOR x_{t-k_t} (parity of the current bit and the bit k_t steps back).
  Reward +1 if a==a* else -1 -> a DISCRETE CLIFF (paid regret of a wrong parity = 2, bounded
  away from 0; this closes candidate-12's "errors only where regret->0" escape).
- FROZEN BASELINE feature class (the cheap low-order closure that reduced the prior 12 -- NO
  raw history buffer): (x_t, k_t, EWMA-bin of x, occupancy-bit of x over the last K_MAX,
  last observation x_{t-1}, last action). Both policies LEARN the best action per feature
  bucket from reward feedback (a fair online learner); the ONLY difference is the feature class.
- RICH candidate feature class (a BOUNDED-memory, C6-clean readout): (x_t, k_t, x_{t-k_t}) --
  i.e. it buffers the last K_MAX bits and reads the specific lag-k bit.
- DECISION RULE: gap = mean_reward(rich) - mean_reward(baseline) on the post-learning tail.
    gap <= EPS  -> FORECLOSURE: the cheap class is complete even under a high-order reward;
                   the thin readout is STRUCTURAL (the SD4/ADR-0037 negative answer-shape).
    gap >= TAU  -> ARTIFACT: the cheap class is INCOMPLETE under a high-order reward; C6
                   permits a richer readout it cannot carry; the 12 reductions were SCOPED to
                   low-order-reward envs and the enrich-S question REOPENS.
- HONEST CAVEAT (pre-registered): the richer readout here is a BOUNDED BUFFER = memory
  (R-CSL-1's axis). So an ARTIFACT verdict refutes "C6 forces thin readout regardless of
  reward" but the winning lever is MEMORY scoped to high-order rewards -- NOT a vindication of
  world-models/belief-organs. A FORECLOSURE verdict would be the stronger (impossibility) result.

Pure stdlib. C6-clean: both policies are bounded-memory observation-policies (no oracle, no
forbidden action, no estimate injected into a privileged control surface).
"""
from __future__ import annotations

import random

K_MAX = 8
LAG_PERIOD = 50
STEPS = 30000
SEEDS = tuple(range(6))
EPS = 0.10   # foreclosure threshold
TAU = 0.50   # artifact threshold (non-vanishing)
EWMA_ALPHA = 0.5


def make_stream(seed: int, steps: int) -> list[tuple[int, int, int]]:
    rng = random.Random(seed)
    hist: list[int] = []
    k = 1
    stream: list[tuple[int, int, int]] = []
    for t in range(steps):
        if t % LAG_PERIOD == 0:
            k = rng.randint(1, K_MAX)
        x = rng.randint(0, 1)
        xk = hist[-k] if len(hist) >= k else 0   # bit k steps back (before appending x_t)
        stream.append((x, k, x ^ xk))
        hist.append(x)
    return stream


def _feat_baseline(x, k, hist, ewma, last_x, last_a):
    win = hist[-K_MAX:]
    occ = 1 if (win and sum(win) > len(win) / 2) else 0
    return (x, k, round(ewma, 1), occ, last_x, last_a)


def _feat_rich(x, k, hist, ewma, last_x, last_a):
    xk = hist[-k] if len(hist) >= k else 0
    return (x, k, xk)


def run_learner(stream, feat_fn, *, seed: int) -> float:
    """Fair online learner: best action per frozen-feature bucket from reward feedback."""
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
    print(f"Parity-lag falsifier | seeds={len(SEEDS)} steps={STEPS} K_MAX={K_MAX} reward-cliff=+1/-1")
    print("the FROZEN cheap baseline vs a BOUNDED-buffer rich readout on a HIGH-ORDER (XOR-at-lag) reward\n")
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
        verdict = ("FORECLOSURE -> the cheap feature class is complete even under a high-order "
                   "reward; the thin readout is STRUCTURAL (SD4/ADR-0037 negative answer-shape).")
    elif mean_gap >= TAU:
        verdict = ("ARTIFACT -> the cheap feature class is INCOMPLETE under a high-order reward; "
                   "C6 permits a richer (bounded-memory) readout it cannot carry. The 12 reductions "
                   "were SCOPED to low-order-reward envs; enrich-S REOPENS (winning lever = MEMORY, "
                   "scoped to high-order rewards -- NOT world-models; see pre-registered caveat).")
    else:
        verdict = "INCONCLUSIVE -> gap between EPS and TAU; refine before any disposition."
    print("\nVERDICT (pre-registered, cheap falsifier; NOT a Route-C verdict): " + verdict)


if __name__ == "__main__":
    main()
