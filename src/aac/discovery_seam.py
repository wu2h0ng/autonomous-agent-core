"""Causal Discovery Seam — RR-0032 contract for OS ↔ core causal discovery.

Counterpart to seam_contract.py's SeamProducer: instead of action governance
(ALLOW/DENY), this seam handles causal structure discovery requests.

OS sends: DiscoveryRequest (observational data + options)
Core returns: DiscoveryResponse (DAG + skeleton + confidence + evidence chain)

Contract version: 1.0.0 (semver, aligned with SEAM_CONTRACT_VERSION 1.x)
Wire format: JSON, no cross-repo imports (Hard Boundary #19).

Usage (OS side — pseudo):
    req = DiscoveryRequest.from_data(obs_rows, tau=0.05, use_llm=True)
    resp = seam.discover(req)
    print(resp.dag, resp.confidence, resp.evidence)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field
from typing import Optional

from .product_engine import ProductDiscoveryEngine
from .cwm_organ import _standardize_cols, _cov, _inv
from .language_orientation_organ import LanguageOrientationOrgan
from .llm_organ import LLMAPIBackend

SEAM_DISCOVERY_VERSION = "1.0.0"


@dataclass
class DiscoveryRequest:
    """Causal discovery request from the enterprise OS.

    data: list of rows, each row = [feature_0, ..., feature_{n-1}]. Float values.
    variable_names: optional human-readable names per column (for LLM orientation).
    tau: CI test threshold for GGM skeleton (0.05 = default, higher = sparser).
    n_particles: DiBS particle count for orientation (30 = default).
    use_fast_orient: True = O(|E|) per-edge scoring (<1s), False = DiBS (>30s).
    use_llm: True = call external LLM for biology/domain orientation proposals.
    llm_api_key: required if use_llm=True.
    contract_version: semver for compat checking.
    """
    data: list[list[float]]
    variable_names: list[str] = field(default_factory=list)
    tau: float = 0.05
    n_particles: int = 30
    use_fast_orient: bool = True
    use_llm: bool = False
    llm_api_key: str = ""
    contract_version: str = SEAM_DISCOVERY_VERSION

    @classmethod
    def from_json(cls, s: str) -> DiscoveryRequest:
        d = json.loads(s)
        return DiscoveryRequest(**d)

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)


@dataclass
class DiscoveryResponse:
    """Causal discovery response returned to the enterprise OS.

    dag: directed edge list as [[src, tgt], ...].
    skeleton: undirected edge list as [[i, j], ...].
    n_nodes: number of variables.
    n_skeleton_edges: size of undirected skeleton.
    n_dag_edges: size of directed output.
    confidence: overall discovery confidence [0,1].
    orientation_confidence: fraction of edges confidently oriented.
    evidence: per-edge provenance summary.
    edge_marginals: per-direction probability estimates.
    recall: if ground truth supplied for evaluation (0.0 if unknown).
    precision: if ground truth supplied (0.0 if unknown).
    time_s: elapsed seconds.
    contract_version: semver.
    """
    dag: list[tuple[int, int]]
    skeleton: list[tuple[int, int]]
    n_nodes: int
    n_skeleton_edges: int
    n_dag_edges: int
    confidence: float
    orientation_confidence: float
    evidence: dict
    edge_marginals: dict
    recall: float = 0.0
    precision: float = 0.0
    time_s: float = 0.0
    contract_version: str = SEAM_DISCOVERY_VERSION

    def to_json(self) -> str:
        d = asdict(self)
        d["dag"] = [[u, v] for u, v in self.dag]
        d["skeleton"] = [[u, v] for u, v in self.skeleton]
        return json.dumps(d, sort_keys=True)

    @classmethod
    def from_json(cls, s: str) -> DiscoveryResponse:
        return DiscoveryResponse(**json.loads(s))


@dataclass
class DiscoverySeam:
    """RR-0032 seam producer for causal discovery.

    DiscoveryRequest -> ProductDiscoveryEngine -> DiscoveryResponse.
    Follows the same contract pattern as SeamProducer (seam_contract.py)
    but for the discovery pipeline instead of action governance.

    llm_api_key: global API key for LLM orientation (set at seam init,
                  never logged or stored in responses).
    llm_api_url: endpoint for LLM API calls.
    llm_model: model name for LLM API calls.
    """

    llm_api_key: str = ""
    llm_api_url: str = "https://api.kimi.com/coding/v1/chat/completions"
    llm_model: str = "kimi-k2.6"

    def discover(self, request: DiscoveryRequest) -> DiscoveryResponse:
        if request.contract_version.split(".")[0] != SEAM_DISCOVERY_VERSION.split(".")[0]:
            return DiscoveryResponse(
                dag=[], skeleton=[], n_nodes=0, n_skeleton_edges=0, n_dag_edges=0,
                confidence=0.0, orientation_confidence=0.0, evidence={}, edge_marginals={},
            )

        engine = ProductDiscoveryEngine(
            skeleton_tau=request.tau,
            n_particles=request.n_particles,
            use_fast_orient=request.use_fast_orient,
        )
        obs = request.data
        result = engine.discover(obs)

        evidence = result.evidence_chain
        marginals = {
            f"{k[0]},{k[1]}": v for k, v in result.edge_marginals.items()
        } if result.edge_marginals else {}

        if request.use_llm and request.llm_api_key and request.variable_names:
            try:
                backend = LLMAPIBackend(
                    api_url=self.llm_api_url,
                    api_key=request.llm_api_key,
                    model=self.llm_model,
                )
                organ = LanguageOrientationOrgan(backend, request.variable_names)
                proposals = organ.propose_orientation(result.skeleton)
                evidence["llm_proposals"] = len(proposals)
            except Exception:
                evidence["llm_error"] = "LLM call failed"

        return DiscoveryResponse(
            dag=[(u, v) for u, v in result.dag],
            skeleton=[(u, v) for u, v in result.skeleton],
            n_nodes=result.n_nodes,
            n_skeleton_edges=result.n_skeleton_edges,
            n_dag_edges=result.n_dag_edges,
            confidence=result.confidence,
            orientation_confidence=result.orientation_confidence,
            evidence=evidence,
            edge_marginals=marginals,
            recall=result.recall,
            precision=result.precision,
            time_s=result.time_s,
        )


def serve_discovery(request_json: str, api_key: str = "") -> str:
    """One-shot discovery: parse JSON request → discover → return JSON response."""
    req = DiscoveryRequest.from_json(request_json)
    seam = DiscoverySeam(llm_api_key=api_key)
    resp = seam.discover(req)
    return resp.to_json()
