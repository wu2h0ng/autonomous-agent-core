"""Product API Server — causal discovery as a REST service.

Pure stdlib http.server + JSON. Endpoints:
  POST /discover  — run causal discovery on uploaded data
  GET  /health    — server status

Usage:
  PYTHONPATH=src python -m aac.product_api [--port 8080]
  curl -X POST http://localhost:8080/discover -H "Content-Type: application/json" \
       -d '{"data": [[1,2],[3,4],...], "tau": 0.05}'
"""
from __future__ import annotations

import json
import time
import traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

from .product_engine import ProductDiscoveryEngine


class DiscoveryAPI(BaseHTTPRequestHandler):
    engine = None  # lazy init

    def do_GET(self):
        if self.path == "/health":
            self._json(200, {"status": "ok", "engine": "ProductDiscoveryEngine"})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/discover":
            self._json(404, {"error": "use POST /discover"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            data = body.get("data")
            if not data or not isinstance(data, list) or not data[0]:
                self._json(400, {"error": "missing 'data' field (list of rows)"})
                return
            tau = float(body.get("tau", 0.05))
            n_particles = int(body.get("n_particles", 30))
            seed = int(body.get("seed", 42))

            if DiscoveryAPI.engine is None or DiscoveryAPI.engine.tau != tau:
                DiscoveryAPI.engine = ProductDiscoveryEngine(
                    skeleton_tau=tau, n_particles=n_particles, seed=seed,
                )
            result = DiscoveryAPI.engine.discover(data)
            self._json(200, {
                "n_nodes": result.n_nodes,
                "n_skeleton_edges": result.n_skeleton_edges,
                "n_dag_edges": result.n_dag_edges,
                "dag": [[u, v] for u, v in result.dag],
                "skeleton": [[u, v] for u, v in result.skeleton],
                "confidence": result.confidence,
                "orientation_confidence": result.orientation_confidence,
                "evidence": result.evidence_chain,
                "time_s": result.time_s,
            })
        except Exception as e:
            self._json(500, {"error": str(e), "trace": traceback.format_exc()})

    def _json(self, code, data):
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass  # silent


def main():
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    server = HTTPServer(("0.0.0.0", port), DiscoveryAPI)
    print(f"ProductDiscoveryEngine API on http://localhost:{port}")
    print(f"  POST /discover  — run causal discovery")
    print(f"  GET  /health    — server status")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
