"""ADR-0048 Adaptive-verify-or-escalate: the corrected architecture (fixes the ADR-0047 frontier hole).

The fixed-half HYBRID silently TRUSTED the un-tested tail -> missed true causes when the LLM was
unreliable (ADR-0047). The fix, which is the logical consequence of the founder's own governance
principle ("only act on VERIFIED findings"): verify in the LLM's ranked order with an ADAPTIVE stop
(patience), then ESCALATE the un-verified tail to a human instead of silently trusting it.

Result we test: ADAPTIVE keeps causes-found = 2/2 at ALL reliabilities (correctness restored),
paying an adaptive cost (cheap verify + small escalation when the LLM is reliable; more when not),
and never silently fails like fixed-half. Simulated LLM reliability p; hang-proof, instant.

Run: PYTHONPATH=src python experiments/architecture_adaptive.py
"""

from __future__ import annotations

import random

D_VALUES = (6, 12, 24)
P_VALUES = (1.0, 0.9, 0.7, 0.5, 0.3)
K_CAUSES = 2
K_DECOYS = 2
PATIENCE = 2
SEEDS = tuple(range(200))


def sim_rank(D, causes, decoys, p, rng):
    score = {}
    for i in range(D):
        n = rng.random()
        if i in causes:
            score[i] = (2.0 + n) if rng.random() < p else n
        elif i in decoys:
            score[i] = 1.5 + n
        else:
            score[i] = n
    return sorted(range(D), key=lambda i: -score[i])


def run(D, p, seed):
    rng = random.Random(seed * 131 + D * 7 + int(p * 100))
    idx = list(range(D)); rng.shuffle(idx)
    causes = set(idx[:K_CAUSES]); decoys = set(idx[K_CAUSES:K_CAUSES + K_DECOYS])
    order = sim_rank(D, causes, decoys, p, rng)

    # FIXED-HALF (broken): verify top half, TRUST tail
    half = max(K_CAUSES, D // 2)
    fixed_found = len(causes & set(order[:half]))
    fixed_verify = half
    fixed_escal = 0

    # ADAPTIVE: verify in order with patience-stop; ESCALATE the un-verified tail (never trust it)
    consec = 0
    verified_causal = set()
    i = 0
    while i < len(order):
        k = order[i]
        if k in causes:                       # interventional verify (deterministic here)
            verified_causal.add(k); consec = 0
        else:
            consec += 1
        i += 1
        if consec >= PATIENCE:
            break
    tail = order[i:]                          # un-verified remainder
    adaptive_verify = i
    adaptive_escal = 1 if tail else 0         # hand the tail to the human (one escalation event)
    tail_causes = causes & set(tail)          # the human catches any cause in the tail
    adaptive_found = len(verified_causal | tail_causes)

    # CALIBRATED: the reliability signal is whether the LLM's MOST-CONFIDENT (top-ranked) knobs verify
    # as causal. Probe the top few; if the top is filled by NON-causal knobs ranked above the causes
    # (an inversion) or the probe finds NOTHING, the LLM's confidence is miscalibrated -> escalate the
    # tail. If the causes sit cleanly at the very top -> trust the tail (low interaction). Honest cost:
    # a small miss at MARGINAL p (a cause sits just beyond a clean-looking probe).
    probe = min(D, 2 * K_CAUSES + PATIENCE)
    probed = order[:probe]
    found_ranks = [r for r, k in enumerate(probed) if k in causes]
    if found_ranks:
        last_cause = max(found_ranks)
        inversion = any(probed[r] not in causes for r in range(last_cause))  # a decoy ranked above a cause
        reliable = not inversion
    else:
        reliable = False                       # found nothing in the LLM's top picks -> distrust
    cal_tail = order[probe:]
    cal_verify = probe
    if reliable:                               # trust the tail as cause-free (no human)
        cal_escal = 0
        cal_found = len(found_ranks)
    else:                                      # miscalibrated LLM -> escalate the tail
        cal_escal = 1 if cal_tail else 0
        cal_found = len(found_ranks) + len(causes & set(cal_tail))

    # PURE-B: verify everything
    pureb_found = K_CAUSES
    pureb_verify = D

    return {
        "fx_found": fixed_found, "fx_verify": fixed_verify, "fx_escal": fixed_escal,
        "ad_found": adaptive_found, "ad_verify": adaptive_verify, "ad_escal": adaptive_escal,
        "cal_found": cal_found, "cal_verify": cal_verify, "cal_escal": cal_escal,
        "pb_found": pureb_found, "pb_verify": pureb_verify,
    }


def main():
    print(f"ADR-0048 adaptive-verify-or-escalate  D={D_VALUES} p={P_VALUES} patience={PATIENCE} seeds={len(SEEDS)}")
    for D in D_VALUES:
        print(f"\n=== D={D} (PURE-B verifies all {D}; correctness target = 2.0 causes) ===")
        print(f"  {'p':>4} | {'FIXED':>6} | {'ADAPT':>6} | {'CALIB':>6} || {'CAL escal':>9} (interaction)")
        for p in P_VALUES:
            rows = [run(D, p, s) for s in SEEDS]
            n = len(rows)
            a = lambda k: sum(r[k] for r in rows) / n
            print(f"  {p:>4.1f} | {a('fx_found'):>6.2f} | {a('ad_found'):>6.2f} | {a('cal_found'):>6.2f} || {a('cal_escal'):>9.2f}")
    print("\n=== READING (causes-found / 2; CALIB escal = human touches per task) ===")
    print("  FIXED: silently drops below 2.0 as p falls -- the frontier hole (trusts the un-verified tail).")
    print("  ADAPT: 2.00 at all p -- always escalates the tail (correct but ~1 human touch every task).")
    print("  CALIB: escalation ADAPTS (0.3->0.6, rising as the LLM gets less reliable -> real autonomy when")
    print("         the LLM earns trust). But NOT a clean 2.00: it trades interaction for a residual miss,")
    print("         WORST in the MARGINAL zone (p~0.5 dips below p=0.3) -- 'looks reliable but isn't' is the")
    print("         danger band. CALIB beats FIXED everywhere but never reaches ADAPT's guaranteed 2.00.")
    print("  => the real design space is a TRILEMMA {correctness, autonomy(low escal), efficiency(low verify)}:")
    print("     FIXED sacrifices correctness; ADAPT sacrifices autonomy; PURE-B sacrifices efficiency (verify all D);")
    print("     CALIB navigates it by spending human touches only when the LLM has earned distrust.")


if __name__ == "__main__":
    main()
