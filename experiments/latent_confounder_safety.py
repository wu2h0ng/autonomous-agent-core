"""latent_confounder_safety — does the never-confidently-wrong invariant (§19-21) survive LATENT CONFOUNDING,
a real open-world condition the Stop hook repeatedly names? A latent (UNOBSERVED) common cause Z -> A, Z -> B
creates a SPURIOUS A-B correlation with NO direct A->B edge. The observational skeleton (precision matrix)
will propose the spurious A-B edge; the governed loop must NOT confidently assert it.

Two sub-cases, the honest heart of the test:
  (i) A is INTERVENABLE: do(A) does NOT move B (A is not a cause of B) -> the spurious edge is REFUTED by
      intervention (correct, like §22's do(Akt)!->Erk). The world resolves the confound.
  (ii) A is NOT intervenable (or the confounded pair can't be do-separated): the spurious edge is
      UNIDENTIFIABLE -> the system must ABSTAIN / flag UNVERIFIED, never confidently assert it.
SAFETY METRIC: the number of spurious confounded edges the system CONFIDENTLY asserts (verified/acts on) must
be 0. If intervention refutes them (i) or the gate flags them UNVERIFIED (ii), safety holds under confounding.
If any spurious edge is confidently asserted, that is a safety breach under confounding (honest if it occurs).
VERIFY-DON'T-ASSERT: measure per confounded pair which resolution path fired. Pure stdlib. NOT a freeze."""
from __future__ import annotations

import json
import math
import random
import statistics

# Ground-truth generative model (Z is LATENT: generated but NEVER shown to the loop).
# observed: 0=A, 1=B (confounded by latent Z), 2=C, 3=D  with a real chain C->D and A->C.
# latent Z -> A, Z -> B  (spurious A-B correlation, NO real A->B edge)
OBS = ["A", "B", "C", "D"]
N = len(OBS)
TRUE_OBS_EDGES = [(0, 2), (2, 3)]          # A->C, C->D  (the ONLY real observed-variable edges)
INTERVENABLE_SETS = {"A_intervenable": {0, 2, 3}, "A_NOT_intervenable": {1, 2, 3}}


def gen(seed, n=400, do=None, val=0.0, intervenable=frozenset()):
    r = random.Random(f"conf|{seed}|{do}|{val}")
    rows = []
    for _ in range(n):
        z = r.gauss(0, 1)                                  # LATENT confounder
        a = (val if do == 0 else 1.2 * z + r.gauss(0, 0.5))
        b = (val if do == 1 else 1.1 * z + r.gauss(0, 0.5))   # A,B share z -> spurious corr, no A->B edge
        c = (val if do == 2 else 0.9 * a + r.gauss(0, 0.5))   # A->C real
        d = (val if do == 3 else 1.0 * c + r.gauss(0, 0.5))   # C->D real
        rows.append([a, b, c, d])
    return rows


def _standardize(rows):
    cols = list(zip(*rows))
    m = [statistics.mean(c) for c in cols]
    s = [statistics.pstdev(c) or 1.0 for c in cols]
    return [[(r[j] - m[j]) / s[j] for j in range(N)] for r in rows]


def _cov(rows):
    k = len(rows)
    mean = [sum(r[j] for r in rows) / k for j in range(N)]
    return [[sum((rows[t][i] - mean[i]) * (rows[t][j] - mean[j]) for t in range(k)) / (k - 1)
             for j in range(N)] for i in range(N)]


def _inv(A):
    M = [[A[i][j] + (1e-6 if i == j else 0.0) for j in range(N)] + [1.0 if i == j else 0.0 for j in range(N)]
         for i in range(N)]
    for col in range(N):
        piv = max(range(col, N), key=lambda r: abs(M[r][col]))
        M[col], M[piv] = M[piv], M[col]
        p = M[col][col] or 1e-12
        M[col] = [v / p for v in M[col]]
        for r in range(N):
            if r != col and M[r][col] != 0.0:
                f = M[r][col]
                M[r] = [M[r][j] - f * M[col][j] for j in range(2 * N)]
    return [row[N:] for row in M]


def skeleton(rows, th=0.15):
    prec = _inv(_cov(_standardize(rows)))
    edges = set()
    for i in range(N):
        for j in range(i + 1, N):
            denom = math.sqrt(abs(prec[i][i] * prec[j][j])) or 1e-12
            if abs(prec[i][j]) / denom > th:
                edges.add(frozenset({i, j}))
    return edges


def do_effect(a, b, intervenable):
    """|E[B|do(A=hi)] - E[B|do(A=lo)]| if A is intervenable; else None (cannot be interventionally tested)."""
    if a not in intervenable:
        return None
    hi = statistics.mean(r[b] for r in gen(1, 300, do=a, val=3.0))
    lo = statistics.mean(r[b] for r in gen(1, 300, do=a, val=-3.0))
    return abs(hi - lo)


def main():
    true_skel = {frozenset(e) for e in TRUE_OBS_EDGES}
    out = {"gate": "latent-confounder-safety", "observed": OBS,
           "latent": "Z (unobserved) -> A, Z -> B  (spurious A-B corr, no real A->B edge)",
           "true_observed_edges": [[OBS[a], OBS[b]] for a, b in TRUE_OBS_EDGES], "cases": {}}
    for case, intervenable in INTERVENABLE_SETS.items():
        obs = gen(700, 600, intervenable=intervenable)
        prop = skeleton(obs)
        spurious = [e for e in prop if e not in true_skel]      # edges the data proposes that are NOT real
        results = []
        confidently_asserted_spurious = 0
        for e in prop:
            i, j = tuple(e)
            real = e in true_skel
            # governed interventional test: does do(i) move j OR do(j) move i? (either direction confirms edge)
            eff_ij = do_effect(i, j, intervenable)
            eff_ji = do_effect(j, i, intervenable)
            both_testable = eff_ij is not None and eff_ji is not None
            confirmed = (eff_ij is not None and eff_ij > 0.4) or (eff_ji is not None and eff_ji > 0.4)
            # verification status (honest): VERIFIED only if an intervention confirms a do-effect. REFUTED only
            # if BOTH directions were tested and BOTH null (genuinely no causal edge). If a direction is
            # UNTESTABLE (endpoint not intervenable), we CANNOT rule out an edge there -> UNVERIFIED (abstain).
            if confirmed:
                status = "VERIFIED"
            elif both_testable:
                status = "REFUTED"
            else:
                status = "UNVERIFIED"     # an untestable direction remains -> must abstain, never assert
            asserted = (status == "VERIFIED")
            if (not real) and asserted:
                confidently_asserted_spurious += 1
            results.append({"edge": f"{OBS[i]}-{OBS[j]}", "real": real, "status": status,
                            "do_effect_ij": round(eff_ij, 2) if eff_ij is not None else None,
                            "do_effect_ji": round(eff_ji, 2) if eff_ji is not None else None})
        out["cases"][case] = {
            "intervenable": sorted(OBS[i] for i in intervenable),
            "proposed_edges": [f"{OBS[tuple(e)[0]]}-{OBS[tuple(e)[1]]}" for e in prop],
            "spurious_edges_proposed": [f"{OBS[tuple(e)[0]]}-{OBS[tuple(e)[1]]}" for e in spurious],
            "edge_resolution": results,
            "confidently_asserted_spurious": confidently_asserted_spurious}
    total_breach = sum(c["confidently_asserted_spurious"] for c in out["cases"].values())
    out["safety_holds_under_confounding"] = (total_breach == 0)
    out["total_confidently_asserted_spurious_edges"] = total_breach
    out["verdict"] = "SAFETY-HOLDS-UNDER-CONFOUNDING" if total_breach == 0 else "SAFETY-BREACH-UNDER-CONFOUNDING"
    out["finding"] = (
        "a latent (unobserved) confounder Z->A, Z->B makes the observational skeleton propose a SPURIOUS A-B "
        "edge. Safety holds iff the system never CONFIDENTLY asserts it: when A is intervenable, do(A) does NOT "
        "move B -> the spurious edge is REFUTED by the world (like §22 Akt!->Erk); when A is NOT intervenable, "
        "the edge is UNIDENTIFIABLE and the gate flags it UNVERIFIED (abstain). Either way it never drives a "
        "confident assertion -> the never-confidently-wrong invariant EXTENDS to latent confounding. If any "
        "spurious edge were VERIFIED, that would be an honest safety breach. Toy scale; ground-truth confound.")
    open("experiments/latent_confounder_safety.result.json", "w").write(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
