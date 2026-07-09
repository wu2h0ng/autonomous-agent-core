"""5e-2 semantic compositional arena: reliability engineering, failure driven by a KNOWLEDGE-MOTIVATED
depth-2 composition of THREE named causes — combined mechanical+thermal stress, NEGATED when a protection
mechanism is engaged. A domain expert (LLM) can propose this composition from the NAMES; a finite base-form
menu cannot enumerate the composition; anonymized screeners see no semantics. Env-flipping spurious symptom."""
from __future__ import annotations

import math
import random

# 12 features; indices 0/1/2 are the three true causes (named), 3 = spurious symptom, rest distractors
NAMES = [
    "mechanical_stress_mpa", "thermal_load_c", "protection_relay_margin",   # 0,1,2 causal
    "alarm_event_rate",                                                     # 3 spurious symptom
    "paint_thickness_um", "warehouse_zone_id", "operator_shift_index", "cable_length_m",
    "ambient_humidity_pct", "firmware_minor_version", "label_print_density", "badge_swipe_count",
]
CAUSAL = (0, 1, 2)
SPUR = 3
P = {"n": 12, "n_env": 3, "rows": 300, "noise": 0.5, "beta": 1.8, "spur_c": [1.5, -1.2, 0.9]}


def true_failure(x, causal=CAUSAL):
    # combined stress[0]*stress[1] (product, tanh-saturated), sign FLIPPED when guard[2] is engaged.
    # `causal` selects which three feature indices carry the true 3-way structure (condition B relabels it).
    stress, thermal, protection = x[causal[0]], x[causal[1]], x[causal[2]]
    return math.tanh(2.0 * stress * thermal) * (1.0 if protection < 0.3 else -1.0)


def gen(seed, env_i, causal=CAUSAL, spur=SPUR):
    r = random.Random(f"5e2sem|{seed}|{env_i}|{causal}")
    rows, ys = [], []
    for _ in range(P["rows"]):
        x = [r.gauss(0, 1) for _ in range(P["n"])]
        y = 1 if (P["beta"] * true_failure(x, causal) + r.gauss(0, P["noise"])) > 0 else 0
        x[spur] += P["spur_c"][env_i] * (2 * y - 1) + r.gauss(0, 0.8)   # symptom flips across envs
        rows.append(x); ys.append(y)
    return rows, ys


def prompt():
    return ("You are a senior reliability engineer. Equipment units fail (binary outcome: unit_failed). "
            "Recorded variables (each measured per unit):\n"
            + "\n".join(f"- {n}" for n in sorted(NAMES)) +
            "\n\nPropose up to 8 candidate FUNCTIONAL-FORM EXPRESSIONS whose value most plausibly drives "
            "failure — you MAY compose (products, saturations, thresholds/gates, negations). Use variable "
            "tokens x0..x11 where xI is the I-th variable in the ORIGINAL (unsorted) list you will be given "
            "below. Allowed functions: tanh, abs, min, max, sign, step (step(z)=1 if z>0 else 0), relu, "
            "sqrt, exp, log1p; operators + - * / ** ; and 'A if COND else B'.\n\nORIGINAL index order:\n"
            + "\n".join(f"x{i} = {n}" for i, n in enumerate(NAMES)) +
            '\n\nOutput STRICT JSON only: {"expressions": ["expr1", "expr2", ...]}')


if __name__ == "__main__":
    print(prompt())
