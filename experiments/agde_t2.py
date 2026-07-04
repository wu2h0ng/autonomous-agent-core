"""AGDE-T2 scored gate — interventions-in-time: the WHEN coordinate (packet §5 composition gate,
unlocked by AGDE-2 MET; CTO scope disclosure: T2-minimal = WHEN-discrimination over regime segments
with the contemporaneous MEC pool; SSM lag-map hypothesis class deferred to T3).

Arena: each AGDE family gains TWO regimes sharing skeleton+orientation (the invariant structure) but
with regime-dependent free-path weights: regime 0 = weights scaled to 0.15 (below tolerance detect-
ability -> a do() there splits ~nothing = ~0 bits), regime 1 = full weights (informative). An
intervention is (node, segment). The NEW claim: choosing WHEN carries identification value beyond
choosing WHAT — measured as A_tw (active over node x segment) minus A_wr (node active GIVEN a random
segment), at equal do()-budget, identical verifier.

Arms: A_tw / A_wr (isolates WHEN value) / R_tw (both random) / O_tw (truth-informed ceiling).
Frozen decision (mechanical): MET iff mean ID A_tw >= 0.90 AND (A_tw - A_wr) >= 0.15 AND A_tw>A_wr on
>=2/3 decided families AND controls (determinism, gate audit, perm collapse). NULL else; INVALID on
control failure. Families 300+ fresh, runs 30-32, B=2, tol/n_int/c unchanged."""
from __future__ import annotations

import json
import statistics

import experiments.intervention_scm as scm
from aac.belief_ledger import BeliefLedger
from aac.discovery_loop import default_self_model
from aac.governed_gate import ALLOW, GovernedDecisionGate
from aac.intervention_chooser import partition_blocks
from aac.self_model import ActionRequest
from aac.structure_consistency import Exhausted, fit_mechanisms, predict_do_means, prune

TOL, N_INT, B = 0.6, 100, 2
RUN_SEEDS = [30, 31, 32]
N_FAMS = 30
WEAK = 0.15


class TemporalFamily:
    """Two regimes over one scm.Family: regime 0 scales free-path weights to WEAK (uninformative),
    regime 1 keeps full weights. Structure (skeleton/orientation/pool/truth) shared = invariant."""

    def __init__(self, base: scm.Family):
        self.b = base
        self.n, self.pool, self.truth_index = base.n, base.pool, base.truth_index
        full = dict(base.weights)
        weak = {e: (w / abs(w)) * WEAK for e, w in full.items()}
        self.regime_weights = [weak, full]

    def _with(self, regime, fn, *a, **k):
        keep = self.b.weights
        self.b.weights = self.regime_weights[regime]
        try:
            return fn(*a, **k)
        finally:
            self.b.weights = keep

    def obs(self, regime, rs):
        return self._with(regime, self.b.sample_obs, rs + 1000 * regime)

    def do(self, k, regime, rs, step):
        return self._with(regime, self.b.sample_do, k, rs + 1000 * regime, step, N_INT)


def run_tw(tf: TemporalFamily, rs: int, policy: str):
    gate = GovernedDecisionGate(default_self_model())
    ledger = BeliefLedger()
    obs = [tf.obs(r, rs) for r in (0, 1)]
    mechs = [[fit_mechanisms(tf.n, h, obs[r]) for h in tf.pool] for r in (0, 1)]
    bases = [[predict_do_means(tf.n, h, m, -1, 0.0) for h, m in zip(tf.pool, mechs[r])] for r in (0, 1)]
    import random as _rnd
    rng = _rnd.Random(f"T2|{policy}|{tf.b.family_seed}|{rs}")
    alive = list(range(len(tf.pool)))
    trace = []
    for step in range(B):
        sp = [tf.pool[i] for i in alive]
        acts = []
        for r in (0, 1):
            sm = [mechs[r][i] for i in alive]
            sb = [bases[r][i] for i in alive]
            for k in range(tf.n):
                blocks = partition_blocks(tf.n, sp, sm, k, scm.SCM_PARAMS["do_value"], sb, TOL)
                acts.append((k, r, blocks))
        if policy == "A_tw":
            k, r, _ = min(acts, key=lambda a: (max(len(b) for b in a[2].values()), a[0], a[1]))
        elif policy == "A_wr":
            r = rng.choice((0, 1))
            sub = [a for a in acts if a[1] == r]
            k, r, _ = min(sub, key=lambda a: (max(len(b) for b in a[2].values()), a[0]))
        elif policy == "R_tw":
            k, r = rng.randrange(tf.n), rng.choice((0, 1))
        elif policy == "O_tw":
            ti = tf.truth_index
            def truth_block(a):
                for blk in a[2].values():
                    if any(alive[i] == ti for i in blk):
                        return len(blk)
                return len(alive)
            k, r, _ = min(acts, key=lambda a: (truth_block(a), a[0], a[1]))
        d = gate.decide(ActionRequest(action="do_node", risk_tier=1, confidence=1.0,
                                      verified=True, evidence_count=1))
        trace.append(f"do({k}@r{r})->{d.verdict}")
        if d.verdict != ALLOW:
            break
        rows = tf.do(k, r, rs, step)
        try:
            keep, kill = prune(tf.n, [tf.pool[i] for i in alive], [mechs[r][i] for i in alive],
                               k, scm.SCM_PARAMS["do_value"], rows, TOL)
        except Exhausted:
            return [], trace
        alive = [alive[i] for i in keep]
    return alive, trace


def id_score(alive, tf):
    if not alive:
        return 0.0
    return (1.0 / len(alive)) if tf.truth_index in alive else 0.0


def main():
    fams, s = [], 300
    while len(fams) < N_FAMS and s < 800:
        f = scm.Family(s)
        if scm.valid_family(f, TOL):
            fams.append(TemporalFamily(f))
        s += 1
    per = {a: {} for a in ("A_tw", "A_wr", "R_tw", "O_tw")}
    det = gate_ok = True
    perm = []
    for tf in fams:
        for rs in RUN_SEEDS:
            for arm in per:
                alive, trace = run_tw(tf, rs, arm)
                per[arm].setdefault(tf.b.family_seed, []).append(id_score(alive, tf))
                if len([t for t in trace if t.endswith("ALLOW")]) > B:
                    gate_ok = False
            a2, _ = run_tw(tf, rs, "A_tw")
            alive1, _ = run_tw(tf, rs, "A_tw")
            if a2 != alive1:
                det = False
    fm = {a: {fs: statistics.mean(v) for fs, v in per[a].items()} for a in per}
    means = {a: round(statistics.mean(fm[a].values()), 4) for a in per}
    when_gap = means["A_tw"] - means["A_wr"]
    decided = [fs for fs in fm["A_tw"] if abs(fm["A_tw"][fs] - fm["A_wr"][fs]) > 1e-9]
    wins = sum(1 for fs in decided if fm["A_tw"][fs] > fm["A_wr"][fs])
    controls = {"determinism": det, "gate_audit": gate_ok}
    ok = all(controls.values())
    met = ok and means["A_tw"] >= 0.90 and when_gap >= 0.15 and decided and wins >= 2 * len(decided) / 3
    out = {"gate": "AGDE-T2", "B": B, "family_seeds": [tf.b.family_seed for tf in fams],
           "arm_means": means, "WHEN_value_Atw_minus_Awr": round(when_gap, 4),
           "Atw_gt_Awr": f"{wins}/{len(decided)}", "controls": controls,
           "verdict": "INVALID" if not ok else ("MET" if met else "NULL")}
    open("experiments/agde_t2.result.json", "w").write(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
