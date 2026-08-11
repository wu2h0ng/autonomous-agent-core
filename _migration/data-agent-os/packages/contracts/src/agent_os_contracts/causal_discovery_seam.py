"""Causal Discovery Seam Contract — RR-0032 RPC contract for OS ↔ core discovery.

The OS-side contract mirroring autonomous-agent-core's DiscoveryRequest/DiscoveryResponse.
The OS calls the discovery engine over HTTP/RPC (not import — Hard Boundary #19).
Both sides implement the same versioned schema independently.

Contract version: 1.0.0 (aligned with SEAM_DISCOVERY_VERSION).
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass, asdict, field

SEAM_DISCOVERY_VERSION = "1.0.0"


@dataclass
class CausalDiscoveryRequest:
    """Request: OS sends observational data → core discovers causal structure.

    data: list of rows, each row = [feature_0, ..., feature_{n-1}].
    variable_names: optional human-readable names (for LLM orientation).
    tau: CI test threshold (0.05 = default, higher = sparser skeleton).
    use_fast_orient: True = O(|E|) scoring (<1s), False = DiBS particle search.
    use_llm: True = call external LLM for domain orientation (needs api_key).
    contract_version: semver for compat checking.
    """

    data: list[list[float]]
    variable_names: list[str] = field(default_factory=list)
    tau: float = 0.05
    use_fast_orient: bool = True
    use_llm: bool = False
    contract_version: str = SEAM_DISCOVERY_VERSION

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)


@dataclass
class CausalDiscoveryResponse:
    """Response: core returns discovered DAG + skeleton + evidence chain.

    dag: directed edge list as [[src, tgt], ...].
    skeleton: undirected edge list as [[i, j], ...].
    n_nodes: number of variables.
    confidence: overall discovery confidence [0,1].
    evidence: per-edge provenance summary.
    time_s: elapsed seconds.
    """

    dag: list[tuple[int, int]]
    skeleton: list[tuple[int, int]]
    n_nodes: int
    n_skeleton_edges: int
    n_dag_edges: int
    confidence: float
    orientation_confidence: float
    evidence: dict = field(default_factory=dict)
    time_s: float = 0.0
    contract_version: str = SEAM_DISCOVERY_VERSION
    error: str = ""

    @classmethod
    def from_json(cls, s: str) -> CausalDiscoveryResponse:
        d = json.loads(s)
        known = {
            "dag",
            "skeleton",
            "n_nodes",
            "n_skeleton_edges",
            "n_dag_edges",
            "confidence",
            "orientation_confidence",
            "evidence",
            "time_s",
            "contract_version",
            "error",
        }
        d = {k: v for k, v in d.items() if k in known}
        d["dag"] = [tuple(e) for e in d.get("dag", [])]
        d["skeleton"] = [tuple(e) for e in d.get("skeleton", [])]
        d.setdefault("orientation_confidence", 0.0)
        d.setdefault("evidence", {})
        d.setdefault("error", "")
        return CausalDiscoveryResponse(**d)

    def to_json(self) -> str:
        d = asdict(self)
        d["dag"] = [[u, v] for u, v in self.dag]
        d["skeleton"] = [[u, v] for u, v in self.skeleton]
        return json.dumps(d, sort_keys=True)


class CausalDiscoveryClient:
    """OS-side client that calls the autonomous-agent-core discovery API over HTTP.

    Per RR-0032: RPC, not library import — keeps repos separate (Hard Boundary #19).
    Core service runs on a separate process (started via `product_api.py`).

    Usage:
        client = CausalDiscoveryClient("http://localhost:8765")
        req = CausalDiscoveryRequest(data=my_data, tau=0.05)
        resp = client.discover(req)
        print(resp.dag, resp.confidence)
    """

    def __init__(self, service_url: str = "http://localhost:8765", timeout: int = 300):
        self.url = service_url.rstrip("/") + "/discover"
        self.timeout = timeout

    def discover(self, request: CausalDiscoveryRequest) -> CausalDiscoveryResponse:
        body = request.to_json().encode("utf-8")
        req = urllib.request.Request(
            self.url,
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return CausalDiscoveryResponse.from_json(resp.read().decode())
        except Exception as e:
            return CausalDiscoveryResponse(
                dag=[],
                skeleton=[],
                n_nodes=0,
                n_skeleton_edges=0,
                n_dag_edges=0,
                confidence=0.0,
                orientation_confidence=0.0,
                error=str(e),
            )
