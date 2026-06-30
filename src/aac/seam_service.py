"""Seam service — stdlib HTTP exposure of the SeamProducer (RR-0032 #1, step 1).

Wraps the reference SeamProducer (seam_contract.py) as a POST /decide JSON endpoint so the enterprise
OS can reach the governed decision brain over an RPC/service boundary (RR-0032 cast: RPC, not import;
#19 intact — the OS speaks the versioned JSON contract, no code crosses). Pure standard library
(http.server) — no third-party dependency (ENGINEERING.md). LOCAL/reference only; NOT deployed here.

The request-handling logic is the pure function ``handle_raw(body) -> body`` (testable without a socket);
``serve()`` boots a threaded HTTP server around it.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .governed_gate import DENY
from .seam_contract import (
    GovernedDecisionResponse, SeamProducer, request_from_json, to_json,
)


class SeamService:
    def __init__(self, producer: SeamProducer) -> None:
        self.producer = producer

    def handle_raw(self, body: str) -> str:
        """Parse a request JSON, run the producer, return a response JSON. Malformed input -> DENY
        (never crash, never silently allow)."""
        try:
            request = request_from_json(body)
        except (ValueError, TypeError, KeyError):
            return to_json(GovernedDecisionResponse("", DENY, None, 0.0, "malformed request", ""))
        return to_json(self.producer.handle(request))


def make_handler(service: SeamService) -> type[BaseHTTPRequestHandler]:
    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 (http.server API)
            if self.path != "/decide":
                self.send_error(404, "only POST /decide")
                return
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8") if length else ""
            try:
                out = service.handle_raw(body).encode("utf-8")
            except Exception:  # the service itself failing must not leak a stack trace
                self.send_error(500, "seam service error")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *args: Any) -> None:  # silence default stderr logging
            return

    return _Handler


def serve(producer: SeamProducer, host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    """Build (but do not start) a threaded HTTP server. Caller runs ``server.serve_forever()`` (e.g. in
    a thread) and ``server.shutdown()``. port=0 -> an OS-assigned free port (read server.server_address)."""
    return ThreadingHTTPServer((host, port), make_handler(SeamService(producer)))
