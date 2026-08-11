"""OS-side REFERENCE governed-decision seam service (RR-0032 #1 remote side — rehearsal + CI target).

A pure-stdlib HTTP ``POST /decide`` server that GOVERNS the OS-supplied ``verified_candidates`` per the
shared seam contract (v1.1 "OS verifies -> core governs"): it does NOT re-run verification (the remote
side has no OS data/cohorts); it only applies the tighten-only governance tree over what the OS already
verified. This is the OS's own reference implementation of the REMOTE contract side — it imports NO
``autonomous-agent-core`` code (Hard Boundary #19). The production research brain (``aac.seam_service``)
is a drop-in that speaks the same versioned JSON.

Used by the S3 cross-process integration test (always-green, no external repo) and as a local rehearsal
target for ``RemoteGovernanceDecisionClient``. Run standalone:

    PYTHONPATH=packages/contracts/src python examples/reference_seam_service.py --port 0
"""

from __future__ import annotations

import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from agent_os_contracts.governance_decision_seam import (
    ALLOW,
    DENY,
    ESCALATE,
    SEAM_CONTRACT_VERSION,
    VERIFY_MORE,
    GovernanceDecisionRequest,
    GovernanceDecisionResponse,
    request_from_json,
    response_to_json,
)

_RISK_ORDER = {"R0": 0, "R1": 1, "R2": 2, "R3": 3, "R4": 4, "R5": 5}


def _audit_ref(task_id: str, verdict: str, chosen: str | None, reason: str) -> str:
    blob = f"{task_id}|{verdict}|{chosen}|{reason}".encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def govern(
    req: GovernanceDecisionRequest,
    *,
    approval_tier: int = 4,
    confidence_floor: float = 0.2,
) -> GovernanceDecisionResponse:
    """Tighten-only governance over OS-supplied ``verified_candidates`` — never re-verifies, never
    auto-allows an unverified candidate. Mirrors the five invariants of the reference
    ``LocalGovernanceDecisionClient`` (contract version, C7 upstream, verify-before-act, high-stakes
    escalation, resolving audit_ref), but reads the OS's verification instead of running its own."""

    def resp(
        verdict: str, chosen: str | None, conf: float, reason: str
    ) -> GovernanceDecisionResponse:
        return GovernanceDecisionResponse(
            req.task_id,
            verdict,
            chosen,
            conf,
            reason,
            _audit_ref(req.task_id, verdict, chosen, reason),
        )

    if req.contract_version.split(".")[0] != SEAM_CONTRACT_VERSION.split(".")[0]:
        return resp(DENY, None, 0.0, f"incompatible contract version {req.contract_version}")

    tier = _RISK_ORDER.get(req.risk_tier, 5)
    high_stakes = tier >= approval_tier

    for vc in req.verified_candidates:
        if not vc.verified:
            continue  # never act on an unverified candidate
        if high_stakes:  # high-stakes never auto-allowed
            if not req.approved:
                return resp(ESCALATE, None, vc.confidence, "high-stakes action requires approval")
            if vc.confidence < confidence_floor:
                return resp(ESCALATE, None, vc.confidence, "high-stakes confidence below floor")
            return resp(
                ALLOW, vc.action, vc.confidence, "high-stakes: verified, confident, approved"
            )
        if vc.confidence < confidence_floor:
            return resp(VERIFY_MORE, None, vc.confidence, "confidence below floor")
        return resp(ALLOW, vc.action, vc.confidence, "low-stakes: verified and confident")

    return resp(ESCALATE, None, 0.0, "no verified-effective candidate")  # never silently act


def handle_raw(body: str) -> str:
    """Pure request-handler: request JSON -> response JSON. Malformed input -> DENY (never crash, never
    silently allow). Testable without a socket."""
    try:
        req = request_from_json(body)
    except (ValueError, TypeError, KeyError):
        return response_to_json(
            GovernanceDecisionResponse(
                "",
                DENY,
                None,
                0.0,
                "malformed request",
                _audit_ref("", DENY, None, "malformed request"),
            )
        )
    return response_to_json(govern(req))


def _make_handler() -> type[BaseHTTPRequestHandler]:
    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 (http.server API)
            if self.path != "/decide":
                self.send_error(404, "only POST /decide")
                return
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8") if length else ""
            try:
                out = handle_raw(body).encode("utf-8")
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


def serve(host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    """Build (but do not start) a threaded HTTP server. port=0 -> an OS-assigned free port
    (read ``server.server_address``)."""
    return ThreadingHTTPServer((host, port), _make_handler())


def main(argv: Any = None) -> int:
    parser = argparse.ArgumentParser(prog="reference_seam_service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args(argv)
    server = serve(args.host, args.port)
    host, port = server.server_address
    print(f"READY http://{host}:{port}/decide", flush=True)  # the integration test reads this line
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
