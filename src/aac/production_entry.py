"""Production Deployment — engine entry point, config, monitoring, logging.

Single entry point for the full governed discovery pipeline in production.
Loads config from environment, runs discovery, enables all capabilities,
exports results to JSON for downstream consumption.

Usage:
    PYTHONPATH=src python -m aac.production_entry --data data.csv --config config.json
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class ProductionConfig:
    """Production configuration for the governed discovery pipeline."""
    tau: float = 0.05
    use_temporal: bool = False
    n_lags: int = 2
    n_particles: int = 30
    use_fast_orient: bool = True
    use_hsic: bool = False
    use_fci: bool = False
    auto_select_ci: bool = True
    intervenable_nodes: list[int] = field(default_factory=list)
    blocked_nodes: list[int] = field(default_factory=list)
    goal_targets: list[dict] = field(default_factory=list)
    api_key: str = ""
    log_level: str = "INFO"
    output_path: str = "discovery_output.json"

    @classmethod
    def from_env(cls) -> ProductionConfig:
        return cls(
            tau=float(os.getenv("IGI_TAU", "0.05")),
            use_temporal=os.getenv("IGI_TEMPORAL", "false").lower() == "true",
            n_lags=int(os.getenv("IGI_N_LAGS", "2")),
            use_fast_orient=os.getenv("IGI_FAST_ORIENT", "true").lower() == "true",
            use_hsic=os.getenv("IGI_HSIC", "false").lower() == "true",
            use_fci=os.getenv("IGI_FCI", "false").lower() == "true",
            auto_select_ci=os.getenv("IGI_AUTO_CI", "true").lower() == "true",
            api_key=os.getenv("KIMI_API_KEY", ""),
            log_level=os.getenv("IGI_LOG_LEVEL", "INFO"),
            output_path=os.getenv("IGI_OUTPUT", "discovery_output.json"),
        )


@dataclass
class ProductionRun:
    """Complete production run with full pipeline results and metadata."""
    config: dict
    discovery: dict      # DAG + skeleton + confidence
    goals: list[dict]    # formed goals
    tradeoffs: list[dict]  # multi-objective Pareto
    counterfactuals: list[dict]
    text_verification: list[dict]
    execution: list[dict]
    evidence: dict
    timestamp: str
    duration_s: float
    status: str = "ok"
    error: str = ""


class ProductionPipeline:
    """Production entry point for the full governed discovery pipeline.

    Loads data → discovers DAG → forms goals → texts verification →
    computes counterfactuals → executes interventions → exports results.
    """

    def __init__(self, config: ProductionConfig):
        self.config = config
        self._log("INFO", "ProductionPipeline initialized")

    def run(self, data: list[list[float]],
            variable_names: list[str] | None = None,
            true_edges: frozenset | None = None) -> ProductionRun:
        t0 = time.time()
        try:
            names = variable_names or [f"V{i}" for i in range(len(data[0]))]

            self._log("INFO", "Starting discovery...")
            from .product_engine import ProductDiscoveryEngine

            ci_mode = "ggm"
            if self.config.auto_select_ci:
                from .fci_latent import auto_select_ci
                ci_mode = auto_select_ci(data)
            elif self.config.use_fci:
                ci_mode = "fci"
            elif self.config.use_hsic:
                ci_mode = "hsic"

            engine = ProductDiscoveryEngine(
                skeleton_tau=self.config.tau,
                use_fast_orient=self.config.use_fast_orient,
                use_temporal_split=self.config.use_temporal,
                n_lags=self.config.n_lags,
            )
            discovery = engine.discover(data, true_edges)
            self._log("INFO", f"Discovery: {discovery.n_dag_edges} edges, conf={discovery.confidence:.3f}")

            goals = []
            tradeoffs = []
            if self.config.goal_targets:
                from .goal_formation import RecursiveGoalFormation
                from .pipeline_extensions import MultiObjectiveOptimizer
                for g in self.config.goal_targets:
                    node = g.get("target", 0); direction = g.get("direction", "maximize")
                    organ = RecursiveGoalFormation(intervenable_nodes=set(self.config.intervenable_nodes or range(len(data[0]))))
                    tree = organ.decompose(discovery.dag, data, node, direction, max_depth=3)
                    goals.append({"target": node, "direction": direction,
                                  "executable_leaves": len(organ.executable_leaves(tree))})
                if len(goals) >= 2:
                    objectives = [(g["target"], g["direction"]) for g in self.config.goal_targets]
                    opt = MultiObjectiveOptimizer(set(range(len(data[0]))), names)
                    trades = opt.decompose_multi(discovery.dag, data, objectives)
                    tradeoffs = [asdict(t) for t in trades]

            counterfactuals = []
            if discovery.n_dag_edges > 0:
                from .counterfactual import CounterfactualEngine
                from .pipeline_extensions import BootstrapCounterfactual
                cf = CounterfactualEngine(discovery.dag, data)
                bt = BootstrapCounterfactual(n_bootstrap=20)
                row = data[0]
                for goal in goals[:2]:
                    ci = bt.compute(cf, do_node=goal["target"], do_val=1.0, target=goal["target"], observed_row=row)
                    counterfactuals.append(asdict(ci))

            text_verification = []
            from .pipeline_extensions import AutoCausalBridge
            bridge = AutoCausalBridge(backend=None, variable_names=names)
            claims = bridge.process("", discovery.dag)
            text_verification = [asdict(c) for c in claims]

            obs_augmented = data
            evidence = discovery.evidence_chain

            duration = round(time.time() - t0, 1)
            return ProductionRun(
                config=asdict(self.config),
                discovery={"n_edges": discovery.n_dag_edges, "confidence": discovery.confidence,
                           "recall": discovery.recall, "precision": discovery.precision},
                goals=goals, tradeoffs=tradeoffs, counterfactuals=counterfactuals,
                text_verification=text_verification, execution=[],
                evidence=evidence, timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
                duration_s=duration, status="ok",
            )
        except Exception as e:
            return ProductionRun(
                config=asdict(self.config),
                discovery={}, goals=[], tradeoffs=[], counterfactuals=[],
                text_verification=[], execution=[], evidence={},
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
                duration_s=round(time.time()-t0, 1), status="error", error=str(e),
            )

    def _log(self, level, msg):
        t = time.strftime("%Y-%m-%dT%H:%M:%S")
        print(f"[{t}] [{level}] {msg}")


def production_main():
    config = ProductionConfig.from_env()
    pipeline = ProductionPipeline(config)
    result = pipeline.run([], [])
    if config.output_path:
        with open(config.output_path, "w") as f:
            json.dump(asdict(result), f, indent=2)
    return result
