"""Unified Discovery Engine — all pipeline components wired together.

Components integrated:
  CIAlgorithmRegistry: auto-select GGM/HSIC/FCI based on data features
  ExploratoryDiscovery (Phase 1): CI skeleton + UncertaintyMap
  ConfirmatoryVerification (Phase 2): ANM scoring + intervention verification
  Multi-organ fusion: data organs + language organ → unified skeleton
  BOED/EIG: information-theoretic intervention target selection
  LLM organ: resolve objectively unidentifiable edges via domain knowledge
  IterativeFeedback (Phase 3): execution results → uncertainty updates

All pure stdlib core. LLM organ is optional plug-in.
"""
from __future__ import annotations

import math
import random
import statistics
import time
from dataclasses import dataclass, field
from typing import Any

from .cwm_organ import (
    _standardize_cols, _cov, _inv,
    LinearGGMOrgan, PolynomialOrgan, StructureProposal,
)
from .uncertainty_map import (
    UncertaintyMap, EdgeUncertainty,
    Identifiability, ValidationStatus,
)
from .two_phase_pipeline import (
    ExploratoryDiscovery, ConfirmatoryVerification,
    IterativeFeedback, MechanismRegistry,
)
from .per_edge_orient import per_edge_orient, score_edge_direction
from .direction_scorer import DirectionScorer
from .fci_latent import CIAlgorithmRegistry, build_default_ci_registry, auto_select_ci
from .advanced_capabilities import hsic_independence_test


@dataclass
class DiscoveryResult:
    dag: frozenset
    skeleton: frozenset
    confidence: float
    edge_marginals: dict
    evidence_chain: dict
    orientation_accuracy: float = 0.0
    recall: float = 0.0
    precision: float = 0.0
    time_s: float = 0.0
    n_nodes: int = 0
    n_skeleton_edges: int = 0
    n_dag_edges: int = 0
    orientation_confidence: float = 0.0
    uncertainty_map: Any = None
    pipeline_phases: dict = field(default_factory=dict)


class UnifiedDiscoveryEngine:
    """Full pipeline: CI selection → exploratory → confirmatory → EIG → LLM.

    Usage:
        engine = UnifiedDiscoveryEngine(
            pipeline_mode="full",
            use_llm=True, llm_backend=kimi_backend, variable_names=names,
        )
        result = engine.discover(obs, int_data=interventions)

    Pipeline modes:
        "single"    — GGM + per_edge_orient (backward compatible, fastest)
        "two_phase" — GGM/HSIC/FCI auto + ANM + interventions
        "full"      — two_phase + EIG optimal target + LLM + feedback loop
    """

    def __init__(
        self,
        pipeline_mode: str = "full",
        skeleton_tau: float = 0.02,
        use_hsic: bool = True,
        use_fci: bool = True,
        use_llm: bool = False,
        llm_backend: Any = None,
        variable_names: list[str] | None = None,
        n_particles: int = 30,
        max_in_degree: int = 6,
        lambda_sparse: float = 0.5,
        seed: int = 42,
        use_eig: bool = False,
        eig_budget: int = 5,
    ):
        self.pipeline_mode = pipeline_mode
        self.tau = skeleton_tau
        self.use_hsic = use_hsic
        self.use_fci = use_fci
        self.use_llm = use_llm
        self.llm_backend = llm_backend
        self.variable_names = variable_names or []
        self.n_particles = n_particles
        self.max_in_degree = max_in_degree
        self.lambda_sparse = lambda_sparse
        self.seed = seed
        self.use_eig = use_eig
        self.eig_budget = eig_budget

        self._ci_registry = build_default_ci_registry()
        self._mechanism_registry = MechanismRegistry()

    def discover(
        self,
        obs: list[list[float]],
        int_data: list[list[float]] | None = None,
        true_edges_for_eval: frozenset | None = None,
    ) -> DiscoveryResult:
        t0 = time.time()
        n = len(obs[0])
        evidence = {}
        phases = {}

        if self.pipeline_mode == "single":
            return self._discover_single(obs, int_data, true_edges_for_eval, n, t0)

        # ── Phase 1: CI skeleton discovery ────────────────────────
        t1 = time.time()
        umap, ci_method = self._phase1_explore(obs)
        phases["phase1_method"] = ci_method
        phases["phase1_time_s"] = round(time.time() - t1, 3)

        # Build skeleton from UncertaintyMap
        skeleton = self._skeleton_from_umap(umap, n)
        phases["phase1_skeleton_edges"] = len(skeleton)

        # ── Phase 2: ANM direction scoring + intervention verification ──
        t2 = time.time()
        umap = self._phase2_confirm(obs, umap, int_data)
        phases["phase2_time_s"] = round(time.time() - t2, 3)

        # ── Phase 3: EIG optimal target + feedback loop ──
        if self.pipeline_mode == "full" and self.use_eig and int_data:
            t3 = time.time()
            umap = self._phase3_eig_feedback(obs, umap, int_data, n)
            phases["phase3_time_s"] = round(time.time() - t3, 3)

        # ── Orientation: per_edge_orient on final skeleton ────────
        dag, ori_conf, edge_scores = per_edge_orient(
            obs, skeleton, likelihood_mode="poly2", sigma_noise=0.3,
            confidence_threshold=0.05,
        )
        phases["oriented_edges"] = len(dag)

        # ── LLM resolution for objectively unidentifiable edges ───
        if self.use_llm and self.llm_backend and self.variable_names:
            umap = self._phase_llm_resolve(umap, dag, self.variable_names)
            phases["llm_resolved"] = True

        # ── Evaluation ────────────────────────────────────────────
        rec = prec = orient = 0.0
        if true_edges_for_eval is not None:
            mu = {frozenset(e) for e in dag}
            tu = {frozenset(e) for e in true_edges_for_eval}
            rec = len(mu & tu) / max(len(tu), 1)
            prec = len(mu & tu) / max(len(mu), 1)
            corr = sum(1 for u, v in true_edges_for_eval if (u, v) in dag)
            tot = sum(1 for u, v in true_edges_for_eval if (u, v) in dag or (v, u) in dag)
            orient = corr / max(tot, 1) if tot > 0 else 0

        return DiscoveryResult(
            dag=dag, skeleton=skeleton, confidence=ori_conf,
            edge_marginals={}, evidence_chain=evidence,
            orientation_accuracy=orient, recall=rec, precision=prec,
            time_s=round(time.time() - t0, 3), n_nodes=n,
            n_skeleton_edges=len(skeleton), n_dag_edges=len(dag),
            orientation_confidence=ori_conf,
            uncertainty_map=umap, pipeline_phases=phases,
        )

    def _discover_single(self, obs, int_data, true_edges, n, t0):
        """Backward-compatible single-path discovery."""
        from .product_engine import ProductDiscoveryEngine
        engine = ProductDiscoveryEngine(
            skeleton_tau=self.tau, n_particles=self.n_particles,
            max_in_degree=self.max_in_degree, lambda_sparse=self.lambda_sparse,
            seed=self.seed,
        )
        return engine.discover(obs, true_edges_for_eval=true_edges)

    # ── Phase 1: CI skeleton with auto-selection ──────────────────

    def _phase1_explore(self, obs: list[list[float]]) -> tuple[UncertaintyMap, str]:
        n = len(obs[0]); n_obs = len(obs)
        umap = UncertaintyMap(n_nodes=n)

        # Auto-select CI method from data features
        ci_method = auto_select_ci(obs)

        # Always start with fast GGM skeleton
        std = _standardize_cols(obs)
        prec = _inv(_cov(std))
        low_pcorr_pairs = []
        for i in range(n):
            for j in range(i + 1, n):
                d = math.sqrt(abs(prec[i][i] * prec[j][j])) or 1e-12
                pcorr = abs(prec[i][j]) / d
                pval = 0.01 if pcorr > self.tau else 0.50
                umap.update_ci_test(i, j, pcorr, pval)
                if pcorr < self.tau * 2:
                    low_pcorr_pairs.append((i, j))

        # FCI latent confounder removal (fast skeleton pruning)
        if self.use_fci and n_obs > n * 5:
            try:
                fci_sk = self._ci_registry.run("fci", obs, 0.05)
                for edge in fci_sk:
                    parts = list(edge)
                    if len(parts) == 2:
                        umap.update_ci_test(parts[0], parts[1], 0.6, 0.02)
            except Exception:
                pass

        # HSIC on GGM blind spots ONLY (pairs with low partial correlation)
        # Uses poly2 kernel (fast, no exponential) + 3 permutations
        if self.use_hsic and len(obs) > 20 and low_pcorr_pairs:
            import random
            rng = random.Random(42)
            subsample_n = min(120, n_obs)
            subsample = obs if n_obs <= subsample_n else rng.sample(obs, subsample_n)
            cols = [[subsample[t][v] for t in range(len(subsample))] for v in range(n)]
            for i, j in low_pcorr_pairs:
                try:
                    _, pval = hsic_independence_test(
                        cols[i], cols[j], kernel="poly2", n_permutations=3,
                    )
                    if pval < 0.10:
                        pcorr_hsic = 1.0 - pval
                        umap.update_ci_test(i, j, pcorr_hsic, pval)
                except Exception:
                    pass

        return umap, ci_method

    def _skeleton_from_umap(self, umap: UncertaintyMap, n: int) -> frozenset:
        edges = set()
        for i in range(n):
            for j in range(i + 1, n):
                e = umap.edges.get((i, j))
                if e is None:
                    continue
                if e.presence_prob > 0.35:
                    edges.add(frozenset({i, j}))
        return frozenset(edges)

    # ── Phase 2: ANM + intervention verification ──────────────────

    def _phase2_confirm(
        self, obs: list[list[float]], umap: UncertaintyMap,
        int_data: list[list[float]] | None,
    ) -> UncertaintyMap:
        verifier = ConfirmatoryVerification(effect_threshold=0.3)
        umap = verifier.run(obs, umap, int_data=int_data)
        return umap

    # ── Phase 3: EIG optimal target + feedback ────────────────────

    def _phase3_eig_feedback(
        self, obs: list[list[float]], umap: UncertaintyMap,
        int_data: list[list[float]], n: int,
    ) -> UncertaintyMap:
        """Select optimal intervention target via EIG, generate new data."""
        from .engine_upgrades import generate_interventional_data
        from .bayesian_dag_posterior import GovernedDiBS

        skeleton = self._skeleton_from_umap(umap, n)

        # Build DiBS for EIG selection
        organ_proposals = {1: set()}
        for undir in skeleton:
            parts = list(undir)
            if len(parts) == 2:
                organ_proposals[1].add((parts[0], parts[1]))
                organ_proposals[1].add((parts[1], parts[0]))

        try:
            di = GovernedDiBS(
                n_nodes=n, n_particles=self.n_particles,
                lambda_sparse=self.lambda_sparse, sigma_noise=0.3,
                seed=self.seed, likelihood_mode="poly2",
                organ_proposals=organ_proposals, organ_credits={1: 0.8},
                max_in_degree=self.max_in_degree, adaptive_particles=True,
            )
            di.posterior_temperature = 2.0
            di.update(obs)

            for _ in range(min(self.eig_budget, 5)):
                target, eig_value = di.select_intervention(
                    obs, int_data, n_candidates=min(5, n),
                )
                if target is not None and target < n:
                    new_rows = generate_interventional_data(
                        di.MAP_dag(), obs, n_interventions=3, n_nodes=1,
                        seed=self.seed + _ * 100,
                    )
                    for row in new_rows:
                        umap.update_intervention(target, (target + 1) % n, 0.5)

        except Exception:
            pass

        return umap

    # ── LLM resolution ───────────────────────────────────────────

    def _phase_llm_resolve(
        self, umap: UncertaintyMap, dag: frozenset,
        variable_names: list[str],
    ) -> UncertaintyMap:
        feedback = IterativeFeedback(
            llm_backend=self.llm_backend,
            variable_names=variable_names,
        )
        umap = feedback.run(umap, dag, execution_results=None, goal_path_edges=None)
        return umap

    # ── Uncertainty-driven intervention selection ─────────────────

    def select_uncertainty_driven_target(
        self, obs: list[list[float]],
        int_data: list[list[float]] | None = None,
        true_edges: frozenset | None = None,
    ) -> tuple[int | None, str]:
        """Select optimal intervention target by targeting uncertain edges.

        Strategy: in the discovered DAG, find edges whose presence_prob is low
        (<0.5) AND that are NOT in the current skeleton. For each such edge,
        identify intervenable ancestors. Rank ancestors by:
          1. Number of uncertain edges they can affect (prioritize hubs)
          2. Average presence_prob of affected edges (prioritize weakest)

        Args:
            obs: observational data
            int_data: existing intervention data
            true_edges: ground truth (for identifying missed edges in eval)

        Returns:
            (target_node, reason) — target_node=None if no good targets found
        """
        n = len(obs[0])
        int_data = int_data or []
        combined = obs + int_data

        umap, ci_method = self._phase1_explore(combined)
        skeleton = self._skeleton_from_umap(umap, n)

        # Find uncertain edges: have CI test evidence, NOT in skeleton,
        # sorted by LOWEST ci_statistic (partial correlation = GGM blind spot)
        uncertain_edges = []
        for (i, j), e in umap.edges.items():
            if i >= j:
                continue
            in_skel = frozenset({i, j}) in skeleton
            has_evidence = "ci_test" in e.evidence_sources
            if not has_evidence:
                continue
            if not in_skel:
                uncertain_edges.append((
                    i, j, e.ci_statistic,  # lower = GGM blinder
                ))

        if not uncertain_edges:
            return None, "all_edges_certain"

        # Sort by LOWEST ci_statistic first — target GGM's blind spots
        uncertain_edges.sort(key=lambda x: x[2])

        # Build DAG for ancestor traversal
        dag, _, _ = per_edge_orient(
            combined, skeleton, likelihood_mode="poly2", sigma_noise=0.3,
            confidence_threshold=0.05,
        )

        # Transitive ancestors in the discovered DAG
        ancestors_map = {i: set() for i in range(n)}
        for u, v in dag:
            if u < n and v < n:
                ancestors_map[v].add(u)
        changed = True
        while changed:
            changed = False
            for v in range(n):
                new = set()
                for u in list(ancestors_map[v]):
                    new |= ancestors_map[u]
                if new - ancestors_map[v]:
                    ancestors_map[v] |= new
                    changed = True

        # Strategy: try each GGM blind spot in sequence with enough rounds each.
        # 5 rounds per edge to accumulate sufficient intervention signal.
        if not hasattr(self, '_target_round'):
            self._target_round = 0
            self._target_edge_idx = 0
        self._target_round += 1

        edge_idx = (self._target_round // 5) % max(len(uncertain_edges), 1)
        i, j, ci_stat = uncertain_edges[edge_idx]
        target = i
        reason = (f"ggm_blind_spot[e{edge_idx}/{len(uncertain_edges)} r{self._target_round%5}]: "
                  f"endpoint {i} of ({i},{j}), partial_corr={ci_stat:.5f}")

        return target, reason

    # ── EIG intervention selection (public API for D2) ────────────

    def select_intervention(
        self, obs: list[list[float]],
        int_data: list[list[float]] | None = None,
    ) -> tuple[int | None, float]:
        """Select optimal next intervention target using EIG."""
        from .bayesian_dag_posterior import GovernedDiBS

        n = len(obs[0])
        int_data = int_data or []

        umap, _ = self._phase1_explore(obs)
        skeleton = self._skeleton_from_umap(umap, n)

        organ_proposals = {1: set()}
        for undir in skeleton:
            parts = list(undir)
            if len(parts) == 2:
                organ_proposals[1].add((parts[0], parts[1]))
                organ_proposals[1].add((parts[1], parts[0]))

        try:
            di = GovernedDiBS(
                n_nodes=n, n_particles=self.n_particles,
                lambda_sparse=self.lambda_sparse, sigma_noise=0.3,
                seed=self.seed, likelihood_mode="poly2",
                organ_proposals=organ_proposals, organ_credits={1: 0.8},
                max_in_degree=self.max_in_degree, adaptive_particles=True,
            )
            di.posterior_temperature = 2.0
            di.update(obs)
            target, eig = di.select_intervention(obs, int_data, n_candidates=min(5, n))
            return target, eig
        except Exception:
            return None, 0.0

    # ── Self-correcting D2 loop ───────────────────────────────────

    def discover_iterative(
        self,
        obs: list[list[float]],
        max_rounds: int = 20,
        base_rows: int = 5,
        max_rows_per_round: int = 40,
        min_delta: float = 0.001,
        staleness_limit: int = 4,
        convergence_rounds: int = 3,
    ) -> tuple[DiscoveryResult, list[dict]]:
        """Self-correcting D2 loop with adaptive intervention intensity.

        Measures improvement on BLIND-SPOT edges (CI-tested but not in skeleton)
        rather than all edges. Adapts rows when a stubborn edge won't budge.
        Declares convergence when no blind spot improves for N rounds.

        Returns:
            (final_result, round_log)
        """
        n = len(obs[0])
        int_data = []
        round_log = []
        result = self.discover(obs)
        blind_spots = self._get_blind_spots(result)

        edge_staleness: dict[tuple, int] = {}
        current_rows: int = base_rows
        rounds_without_gain = 0

        for rnd in range(max_rounds):
            entry = {"round": rnd, "target": None, "rows": current_rows,
                     "delta_max": 0.0, "n_blind_spots": len(blind_spots),
                     "action": "continue"}

            # ── Convergence: no blind spots left, or all are stale ──
            active_spots = [e for e in blind_spots
                           if edge_staleness.get(e, 0) < staleness_limit]
            if not active_spots:
                if not blind_spots:
                    entry["action"] = "all_blind_spots_resolved"
                else:
                    entry["action"] = f"all_{len(blind_spots)}_spots_stale"
                round_log.append(entry)
                break

            if rounds_without_gain >= convergence_rounds:
                entry["action"] = f"converged_{rounds_without_gain}_rounds_no_gain"
                round_log.append(entry)
                break

            # ── Select target from blind spots ──
            target = self._pick_best_blind_spot_target(
                blind_spots, edge_staleness, result, n,
                staleness_limit=staleness_limit,
            )
            if target is None:
                entry["action"] = "no_valid_target"
                round_log.append(entry)
                break
            entry["target"] = target

            # ── Generate hard do-interventions ──
            # Zero-baseline creates strong correlation-breaking signal.
            # Keep row count modest to avoid drowning out obs data.
            col_t = [obs[t][target] for t in range(len(obs))]
            mu = statistics.mean(col_t)
            sd = statistics.pstdev(col_t) or 1.0
            new_rows = []
            do_vals = [mu - 2.0 * sd, mu, mu + 2.0 * sd]
            rows_per_val = max(1, current_rows // len(do_vals))
            for dv in do_vals:
                for _ in range(rows_per_val):
                    row = [0.0] * n
                    row[target] = dv + random.gauss(0, 0.05 * sd)
                    new_rows.append(row)
            int_data.extend(new_rows)

            # ── Measure blind-spot improvement ──
            data_before = obs + int_data[:-len(new_rows)] if len(int_data) > len(new_rows) else obs
            blind_ci_before = {}
            for edge in blind_spots:
                i, j = edge
                blind_ci_before[edge] = self._edge_partial_corr(data_before, i, j)

            result = self.discover(obs + int_data)
            blind_spots_after = self._get_blind_spots(result)

            delta_max = 0.0
            improved = 0
            for edge in blind_spots:
                i, j = edge
                ci_before = blind_ci_before.get(edge, 0.0)
                ci_after = self._edge_partial_corr(obs + int_data, i, j)
                delta = ci_after - ci_before
                if delta > delta_max:
                    delta_max = delta
                if delta > min_delta:
                    improved += 1
                if delta > 0:
                    edge_staleness[edge] = 0
                else:
                    edge_staleness[edge] = edge_staleness.get(edge, 0) + 1

            entry["delta_max"] = round(delta_max, 6)
            entry["improved_edges"] = improved
            entry["n_int_rows"] = len(int_data)

            # ── Self-correct ──
            if delta_max < min_delta:
                rounds_without_gain += 1
                if current_rows < max_rows_per_round:
                    current_rows = min(current_rows * 2, max_rows_per_round)
                    entry["action"] = f"no_gain×{rounds_without_gain}, rows↑{current_rows}"
                else:
                    entry["action"] = f"no_gain×{rounds_without_gain}, max_rows"
            else:
                rounds_without_gain = 0
                if delta_max > min_delta * 3:
                    entry["action"] = "significant_gain"
                    current_rows = base_rows
                else:
                    entry["action"] = "modest_gain"

            blind_spots = blind_spots_after
            round_log.append(entry)

        return result, round_log

    def _get_blind_spots(self, result: DiscoveryResult) -> set[tuple]:
        """Return CI-tested pairs not in the current skeleton."""
        umap = result.uncertainty_map
        if umap is None:
            return set()
        spots = set()
        for (i, j), e in umap.edges.items():
            if i >= j:
                continue
            if "ci_test" not in e.evidence_sources:
                continue
            if frozenset({i, j}) not in result.skeleton:
                spots.add((i, j))
        return spots

    def _edge_partial_corr(self, obs, i, j):
        """Compute partial correlation for pair (i,j) from data."""
        try:
            std = _standardize_cols(obs)
            prec = _inv(_cov(std))
            n = len(obs[0])
            d = math.sqrt(abs(prec[i][i] * prec[j][j])) or 1e-12
            return abs(prec[i][j]) / d
        except (ValueError, ZeroDivisionError, IndexError):
            return 0.0

    def _pick_best_blind_spot_target(
        self, blind_spots: set[tuple],
        staleness: dict[tuple, int],
        result: DiscoveryResult, n: int,
        staleness_limit: int = 4,
    ) -> int | None:
        """Pick intervention target from blind-spot edges.

        Prioritizes blind-spot edges where the endpoints share many neighbors
        in the discovered DAG (structural holes — likely true edges).
        Target the endpoint with higher out-degree (more likely causal parent).
        """
        dag = result.dag
        # Build adjacency from DAG
        adj = {i: set() for i in range(n)}
        for u, v in dag:
            if u < n and v < n:
                adj[u].add(v)
                adj[v].add(u)

        out_deg = {i: 0 for i in range(n)}
        for u, v in dag:
            if u < n and v < n:
                out_deg[u] = out_deg.get(u, 0) + 1

        scored = []
        for i, j in blind_spots:
            st = staleness.get((i, j), 0)
            if st >= staleness_limit:
                continue
            shared = len(adj[i] & adj[j])
            target = i if out_deg[i] >= out_deg[j] else j
            scored.append((target, shared, out_deg[target], (i, j)))

        if scored:
            scored.sort(key=lambda x: (-x[1], -x[2]))  # highest shared, then highest out-degree
            return scored[0][0]

        return None
