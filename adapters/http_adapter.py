"""HTTP webhook adapter for the RealDataInterventionEnv protocol.

This adapter lives outside the core runtime.  It fetches observational batches via
HTTP GET and POSTs intervention proposals to an external webhook.  The external
system owns the actuator and must return the post-intervention sample in its
response body.  The core never executes an action directly.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass
class HTTPInterventionAdapter:
    """Read observations and stage interventions over HTTP.

    Args:
        n_nodes: number of observed variables.
        observed_variables: human-readable variable names.
        allowed_handles: node indices that may be intervened upon.
        safe_value_ranges: per-node ``(min, max)`` value bounds.
        observe_url: URL that returns a JSON array of observation rows.
        intervene_url: URL that accepts a JSON ``{"node": int, "value": float}``
            payload and returns a JSON array representing one sample.
        timeout: request timeout in seconds.
        ground_truth_edges: optional ground-truth DAG for evaluation only.
    """

    n_nodes: int
    observed_variables: list[str]
    allowed_handles: set[int]
    safe_value_ranges: dict[int, tuple[float, float]]
    observe_url: str
    intervene_url: str
    timeout: float = 5.0
    ground_truth_edges: set[tuple[int, int]] | None = None

    def observe(self, n_samples: int) -> list[list[float]]:
        """GET observation rows from ``observe_url`` as JSON."""
        url = f"{self.observe_url}?n_samples={n_samples}"
        data = self._request("GET", url, body=None)
        rows = self._parse_rows(data)
        if len(rows) < n_samples:
            raise ValueError(
                f"observe endpoint returned {len(rows)} rows, requested {n_samples}"
            )
        return rows[-n_samples:]

    def intervene(self, do_node: int, do_value: float) -> list[float] | None:
        """POST intervention proposal to ``intervene_url`` and parse the sample."""
        payload = json.dumps({"node": do_node, "value": do_value}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        try:
            data = self._request("POST", self.intervene_url, body=payload, headers=headers)
        except urllib.error.HTTPError as exc:
            # A 4xx/5xx response means the external system refused or failed.
            return None
        sample = self._parse_sample(data)
        if sample is None:
            return None
        return sample

    def structural_hamming_distance(
        self, predicted: set[tuple[int, int]]
    ) -> int | None:
        if self.ground_truth_edges is None:
            return None
        truth = self.ground_truth_edges
        return len((truth - predicted) | (predicted - truth))

    def _request(
        self,
        method: str,
        url: str,
        body: bytes | None,
        headers: dict[str, str] | None = None,
    ) -> bytes:
        req = urllib.request.Request(url, data=body, method=method)
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return resp.read()

    def _parse_rows(self, data: bytes) -> list[list[float]]:
        obj = json.loads(data.decode("utf-8"))
        if not isinstance(obj, list):
            raise ValueError("observe endpoint must return a JSON list of rows")
        rows: list[list[float]] = []
        for row in obj:
            if not isinstance(row, list) or len(row) != self.n_nodes:
                continue
            try:
                rows.append([float(v) for v in row])
            except (TypeError, ValueError):
                continue
        return rows

    def _parse_sample(self, data: bytes) -> list[float] | None:
        try:
            obj = json.loads(data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        if isinstance(obj, dict) and "sample" in obj:
            obj = obj["sample"]
        if not isinstance(obj, list) or len(obj) != self.n_nodes:
            return None
        try:
            return [float(v) for v in obj]
        except (TypeError, ValueError):
            return None
