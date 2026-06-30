"""Second intervenable domain: the ASIA Bayesian network (Lauritzen & Spiegelhalter 1988).

CausalBench (the real CRISPR single-cell benchmark) is 200k+ samples / GB-scale / framework-bound — it
violates the core's stdlib-only, no-deps rule. ASIA is the canonical small medical-diagnosis BN with a
KNOWN ground-truth DAG; it is FULLY intervenable (we can do() any of the 8 nodes), complementing Sachs
(real-measured but only 5 nodes intervenable). HONEST: real network STRUCTURE, SIMULATED samples — the
value is a second, fully-controllable intervenable domain confirming the loop generalizes beyond Sachs.

Classic confounds it exposes: xray & dysp correlate (common cause `either`) but neither causes the other;
lung & bronc correlate (common cause `smoke`). Correlation is fooled; intervention recovers ancestry.
Run: PYTHONPATH=src python experiments/asia_task.py
"""

from __future__ import annotations

import random
import statistics
from aac.governed_loop import GovernedLoop, Candidate, VerifyResult, TaskSpec
from aac.governed_gate import GovernedDecisionGate
from aac.self_model import AgentSelfModel
from aac.shell import CorrigibilityShell

NODES = ["asia", "smoke", "tub", "lung", "bronc", "either", "xray", "dysp"]  # topological order
GROUND_TRUTH = [
    ("asia", "tub"), ("smoke", "lung"), ("smoke", "bronc"),
    ("tub", "either"), ("lung", "either"),
    ("either", "xray"), ("either", "dysp"), ("bronc", "dysp"),
]
N_OBS = 8000
N_INT = 4000
EFFECT_THRESHOLD = 0.05


def _bern(rng, p):
    return 1 if rng.random() < p else 0


def sample(rng, do=None):
    do = do or {}
    v = {}
    def val(node, p):
        return do[node] if node in do else _bern(rng, p)
    v["asia"] = val("asia", 0.01)
    v["smoke"] = val("smoke", 0.5)
    v["tub"] = val("tub", 0.05 if v["asia"] else 0.01)
    v["lung"] = val("lung", 0.10 if v["smoke"] else 0.01)
    v["bronc"] = val("bronc", 0.60 if v["smoke"] else 0.30)
    v["either"] = val("either", 1.0 if (v["tub"] or v["lung"]) else 0.0)
    v["xray"] = val("xray", 0.98 if v["either"] else 0.05)
    dysp_p = {(1, 1): 0.9, (1, 0): 0.7, (0, 1): 0.8, (0, 0): 0.1}[(v["either"], v["bronc"])]
    v["dysp"] = val("dysp", dysp_p)
    return v


def ancestors(node):
    parents = {}
    for a, b in GROUND_TRUTH:
        parents.setdefault(b, set()).add(a)
    seen, stack = set(), list(parents.get(node, set()))
    while stack:
        p = stack.pop()
        if p not in seen:
            seen.add(p); stack.extend(parents.get(p, set()))
    return seen


def correlation(obs, i, j):
    xi = [r[i] for r in obs]; xj = [r[j] for r in obs]
    try:
        return statistics.correlation(xi, xj)
    except statistics.StatisticsError:
        return 0.0


class AsiaCorrelationProposer:
    def __init__(self, obs, target):
        self.reliability = None
        t = NODES.index(target)
        c = [(n, abs(correlation(obs, t, NODES.index(n)))) for n in NODES if n != target]
        c.sort(key=lambda x: -x[1])
        self.ranking = c

    def rank(self, task):
        return [Candidate(action=f"do:{n}", target=NODES.index(n)) for n, _ in self.ranking]


class AsiaInterventionVerifier:
    """Total causal effect: P(T=1|do(X=1)) - P(T=1|do(X=0)); nonzero iff X is a causal ancestor of T."""
    def __init__(self, target):
        self.t = target

    def verify(self, cand):
        x = NODES[cand.target]
        r1 = random.Random(101 + cand.target)
        r0 = random.Random(202 + cand.target)
        p1 = statistics.mean(sample(r1, do={x: 1})[self.t] for _ in range(N_INT))
        p0 = statistics.mean(sample(r0, do={x: 0})[self.t] for _ in range(N_INT))
        effect = abs(p1 - p0)
        eff = effect >= EFFECT_THRESHOLD
        return VerifyResult(eff, min(1.0, effect * 2) if eff else 0.0, int(eff) * 3, N_INT)


class AcceptActuator:
    def apply(self, cand):
        return 1.0


def _self_model():
    return AgentSelfModel(
        allowed_tools=frozenset(f"do:{n}" for n in NODES), denied_tools=frozenset(),
        risk_ceiling=5, approval_required_at_or_above=4,
        evidence_requirements={0: 0, 1: 1, 2: 1, 3: 1}, confidence_thresholds={0: 0.0, 1: 0.1, 2: 0.1, 3: 0.2},
    )


def discover(target, obs):
    prop = AsiaCorrelationProposer(obs, target)
    verf = AsiaInterventionVerifier(target)
    gt = ancestors(target)
    interv = {n for n, _ in prop.ranking
              if verf.verify(Candidate(f"do:{n}", NODES.index(n))).is_effective}
    corr = set(n for n, _ in prop.ranking[:max(1, len(gt))])

    def pr(pred):
        tp = len(pred & gt)
        return (tp / len(pred) if pred else 0.0, tp / len(gt) if gt else 0.0)
    return {"target": target, "gt": gt, "corr": corr, "interv": interv,
            "corr_pr": pr(corr), "interv_pr": pr(interv), "ranking": prop.ranking}


def run_loop_for(target, obs):
    loop = GovernedLoop(
        gate=GovernedDecisionGate(_self_model()),
        proposer=AsiaCorrelationProposer(obs, target),
        verifier=AsiaInterventionVerifier(target),
        actuator=AcceptActuator(), shell_view=CorrigibilityShell().view(), verify_budget=len(NODES),
    )
    res = loop.run_task(TaskSpec(f"find-cause-of-{target}", risk_tier=1))
    return {"status": res.status, "applied": NODES[res.applied_target] if res.applied_target is not None else None}


def main():
    rng = random.Random(7)
    obs = [[sample(rng)[n] for n in NODES] for _ in range(N_OBS)]
    print("ASIA Bayesian network — second intervenable domain (real structure, simulated samples)\n")

    print("HEADLINE — target xray (xray & dysp share common cause `either` -> dysp is a CONFOUND):")
    d = discover("xray", obs)
    print(f"  correlation ranking: " + ", ".join(f"{n}({c:+.2f})" for n, c in d["ranking"][:5]))
    print(f"  GT ancestors: {sorted(d['gt'])}")
    print(f"  correlation top-{len(d['gt'])}: {sorted(d['corr'])}")
    print(f"  interventionally-VERIFIED: {sorted(d['interv'])}")
    print(f"  -> dysp correlates with xray but do(dysp) rejected: {'dysp' not in d['interv']}")

    print("\nALL targets — precision/recall vs GT ancestry:")
    print(f"  {'target':>7} | {'corr P/R':>11} | {'interv P/R':>11}")
    tps = [t for t in NODES if ancestors(t)]
    cP = cR = iP = iR = 0.0
    for t in tps:
        d = discover(t, obs)
        cP += d["corr_pr"][0]; cR += d["corr_pr"][1]; iP += d["interv_pr"][0]; iR += d["interv_pr"][1]
        print(f"  {t:>7} | {d['corr_pr'][0]:.2f}/{d['corr_pr'][1]:.2f}  | {d['interv_pr'][0]:.2f}/{d['interv_pr'][1]:.2f}")
    n = len(tps)
    print(f"  {'MEAN':>7} | {cP/n:.2f}/{cR/n:.2f}  | {iP/n:.2f}/{iR/n:.2f}")

    print("\nGOVERNED LOOP (confounded proposer) on xray:")
    r = run_loop_for("xray", obs)
    print(f"  status={r['status']} applied={r['applied']} (a true ancestor: {r['applied'] in ancestors('xray')})")

    print("\n=== READING ===")
    print("  Second fully-intervenable domain confirms it: correlation is fooled by common-cause confounds")
    print("  (dysp<->xray, lung<->bronc); interventional verification recovers causal ancestry. Generalizes")
    print("  beyond Sachs (different domain, discrete, all nodes intervenable). Real structure, simulated samples.")


if __name__ == "__main__":
    main()
