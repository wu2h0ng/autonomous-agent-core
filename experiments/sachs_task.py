"""Real task: the Sachs protein-signaling causal discovery benchmark wired to the GovernedLoop.

Sachs et al. 2005 — flow cytometry of 11 signaling proteins in human T cells, with OBSERVATIONAL and
INTERVENTIONAL (targeted chemical perturbation) conditions and a known consensus causal network. The
canonical real-world causal-discovery benchmark. Data vendored from bnlearn (experiments/data/sachs_*).

This tests the session's core thesis on REAL biology: a CONFOUNDED correlation prior is fooled by
reverse causation (e.g. Erk->Akt makes Akt correlate with Erk, but do(Akt) does NOT change Erk),
while interventional verification (the CWM probe) recovers the true causal ancestry. The GovernedLoop,
driven by the confounded proposer, still acts on a true cause because the interventional verifier
catches the decoy.

Honest scope: interventions exist for only 5 nodes (Mek, PIP2, Akt, PKA, PKC); candidates are
restricted to those. do(X) detects causal ANCESTRY (X upstream of T), the right interventional reading.
Data is discretized {1,2,3} (bnlearn standard). Run: PYTHONPATH=src python experiments/sachs_task.py
"""

from __future__ import annotations

import os
import statistics
from aac.governed_loop import GovernedLoop, Candidate, VerifyResult, TaskSpec
from aac.governed_gate import GovernedDecisionGate
from aac.self_model import AgentSelfModel
from aac.shell import CorrigibilityShell

PROTEINS = ["Raf", "Mek", "Plcg", "PIP2", "PIP3", "Erk", "Akt", "PKA", "PKC", "P38", "Jnk"]
# INT code in the bnlearn file = 1-based column index of the perturbed node; 0 = observational.
INTERVENABLE = {"Mek": 2, "PIP2": 4, "Akt": 7, "PKA": 8, "PKC": 9}

# Sachs consensus ground-truth DAG (17 edges), the standard benchmark reference.
GROUND_TRUTH = [
    ("PKC", "Raf"), ("PKC", "Mek"), ("PKC", "Jnk"), ("PKC", "P38"), ("PKC", "PKA"),
    ("PKA", "Raf"), ("PKA", "Mek"), ("PKA", "Erk"), ("PKA", "Akt"), ("PKA", "Jnk"), ("PKA", "P38"),
    ("Raf", "Mek"), ("Mek", "Erk"), ("Erk", "Akt"),
    ("Plcg", "PIP2"), ("Plcg", "PIP3"), ("PIP3", "PIP2"),
]
_DATA = os.path.join(os.path.dirname(__file__), "data")


def ancestors(node: str) -> set[str]:
    parents = {}
    for a, b in GROUND_TRUTH:
        parents.setdefault(b, set()).add(a)
    seen, stack = set(), list(parents.get(node, set()))
    while stack:
        p = stack.pop()
        if p in seen:
            continue
        seen.add(p)
        stack.extend(parents.get(p, set()))
    return seen


def load_obs() -> list[list[float]]:
    with open(os.path.join(_DATA, "sachs_obs.txt")) as f:
        rows = [ln.split() for ln in f.read().splitlines()[1:] if ln.strip()]
    return [[float(v) for v in r] for r in rows]


def load_int() -> list[tuple[list[int], int]]:
    out = []
    with open(os.path.join(_DATA, "sachs_int.txt")) as f:
        for ln in f.read().splitlines()[1:]:
            if not ln.strip():
                continue
            parts = ln.split()
            vals = [int(v) for v in parts[:11]]
            out.append((vals, int(parts[11])))
    return out


def correlation(obs, i: int, j: int) -> float:
    xi = [r[i] for r in obs]; xj = [r[j] for r in obs]
    try:
        return statistics.correlation(xi, xj)
    except statistics.StatisticsError:
        return 0.0


# --- effect test threshold (standardized mean difference under do(X) vs baseline) ---
EFFECT_THRESHOLD = 0.30
MAX_SAMPLES = 600


class SachsCorrelationProposer:
    """Ranks intervenable candidates by |correlation| with the target (the CONFOUNDED prior)."""

    def __init__(self, obs, target: str) -> None:
        self.reliability = None
        t = PROTEINS.index(target)
        cands = [(name, abs(correlation(obs, t, PROTEINS.index(name))))
                 for name in INTERVENABLE if name != target]
        cands.sort(key=lambda x: -x[1])
        self._order = cands
        self.ranking = cands  # exposed for reporting

    def rank(self, task) -> list[Candidate]:
        return [Candidate(action=f"intervene:{name}", target=PROTEINS.index(name)) for name, _ in self._order]


class SachsInterventionVerifier:
    """do(X) vs baseline: standardized mean difference of the target -> is X a causal ancestor of T?"""

    def __init__(self, intdata, target: str) -> None:
        self.target_idx = PROTEINS.index(target)
        self.base = [v[self.target_idx] for v, code in intdata if code == 0][:MAX_SAMPLES]
        self.by_node = {}
        for name, code in INTERVENABLE.items():
            self.by_node[name] = [v[self.target_idx] for v, c in intdata if c == code][:MAX_SAMPLES]

    def verify(self, cand: Candidate) -> VerifyResult:
        name = PROTEINS[cand.target]
        sample = self.by_node.get(name, [])
        n = len(sample)
        if n < 2 or len(self.base) < 2:
            return VerifyResult(False, 0.0, 0, n)
        mb, mi = statistics.mean(self.base), statistics.mean(sample)
        sd = (statistics.pstdev(self.base) + statistics.pstdev(sample)) / 2 or 1e-9
        effect = abs(mi - mb) / sd
        is_eff = effect >= EFFECT_THRESHOLD
        conf = min(1.0, effect)
        return VerifyResult(is_eff, conf if is_eff else 0.0, int(is_eff) * 3, n)


class AcceptActuator:
    def apply(self, cand: Candidate) -> float:
        return 1.0


def _self_model() -> AgentSelfModel:
    return AgentSelfModel(
        allowed_tools=frozenset(f"intervene:{n}" for n in INTERVENABLE),
        denied_tools=frozenset(),
        risk_ceiling=5, approval_required_at_or_above=4,
        evidence_requirements={0: 0, 1: 1, 2: 1, 3: 1},
        confidence_thresholds={0: 0.0, 1: 0.2, 2: 0.2, 3: 0.3},
    )


def discover(target: str, obs, intdata) -> dict:
    """Compare correlation-top vs interventionally-verified causes against GT ancestry."""
    prop = SachsCorrelationProposer(obs, target)
    verf = SachsInterventionVerifier(intdata, target)
    gt = ancestors(target) & set(INTERVENABLE) - {target}
    cands = [name for name, _ in prop.ranking]
    interv_causes = {name for name in cands
                     if verf.verify(Candidate(f"intervene:{name}", PROTEINS.index(name))).is_effective}
    # correlation "predicts cause" = top-|gt| by correlation (same budget as the truth size)
    corr_causes = set(c for c, _ in prop.ranking[:max(1, len(gt))])

    def pr(pred):
        tp = len(pred & gt)
        prec = tp / len(pred) if pred else 0.0
        rec = tp / len(gt) if gt else 0.0
        return prec, rec
    return {"target": target, "gt": gt, "corr": corr_causes, "interv": interv_causes,
            "corr_pr": pr(corr_causes), "interv_pr": pr(interv_causes), "ranking": prop.ranking}


def run_loop_for(target: str, obs, intdata) -> dict:
    """The governed loop, driven by the CONFOUNDED correlation proposer, on a real target."""
    loop = GovernedLoop(
        gate=GovernedDecisionGate(_self_model()),
        proposer=SachsCorrelationProposer(obs, target),
        verifier=SachsInterventionVerifier(intdata, target),
        actuator=AcceptActuator(), shell_view=CorrigibilityShell().view(), verify_budget=len(INTERVENABLE),
    )
    res = loop.run_task(TaskSpec(f"find-cause-of-{target}", risk_tier=1))
    applied = PROTEINS[res.applied_target] if res.applied_target is not None else None
    return {"status": res.status, "applied": applied, "interventions": res.interventions}


def main() -> None:
    obs, intdata = load_obs(), load_int()
    print("Sachs real causal task — interventional verification vs confounded correlation\n")

    print("HEADLINE — target Erk (Erk->Akt makes Akt a reverse-causation CONFOUND):")
    d = discover("Erk", obs, intdata)
    print(f"  correlation ranking: " + ", ".join(f"{n}({c:+.2f})" for n, c in d["ranking"]))
    print(f"  GT causal ancestors (intervenable): {sorted(d['gt'])}")
    print(f"  correlation top-{len(d['gt'])} says causes: {sorted(d['corr'])}")
    print(f"  interventionally-VERIFIED causes:    {sorted(d['interv'])}")
    akt_corr = dict(d["ranking"]).get("Akt")
    print(f"  -> Akt correlates with Erk ({akt_corr:+.2f}) but do(Akt) is rejected: {'Akt' not in d['interv']}")

    print("\nALL valid targets — precision/recall vs GT ancestry (intervenable candidates):")
    print(f"  {'target':>5} | {'corr P/R':>12} | {'interv P/R':>12}")
    tps = [t for t in PROTEINS if (ancestors(t) & set(INTERVENABLE)) - {t}]
    cP = cR = iP = iR = 0.0
    for t in tps:
        d = discover(t, obs, intdata)
        cP += d["corr_pr"][0]; cR += d["corr_pr"][1]; iP += d["interv_pr"][0]; iR += d["interv_pr"][1]
        print(f"  {t:>5} | {d['corr_pr'][0]:.2f}/{d['corr_pr'][1]:.2f}    | {d['interv_pr'][0]:.2f}/{d['interv_pr'][1]:.2f}")
    n = len(tps)
    print(f"  {'MEAN':>5} | {cP/n:.2f}/{cR/n:.2f}    | {iP/n:.2f}/{iR/n:.2f}")

    print("\nGOVERNED LOOP driven by the confounded proposer (acts on a true cause, not the decoy):")
    for t in ("Erk", "Akt"):
        r = run_loop_for(t, obs, intdata)
        print(f"  target {t:>4}: status={r['status']} applied={r['applied']} interventions={r['interventions']}")

    print("\n=== READING ===")
    print("  On REAL protein data: correlation is fooled by reverse causation / confounds; interventional")
    print("  verification recovers causal ancestry with higher precision. The governed loop, even when its")
    print("  proposer ranks a confound first, acts on a verified true cause (the verifier catches the decoy).")


if __name__ == "__main__":
    main()
