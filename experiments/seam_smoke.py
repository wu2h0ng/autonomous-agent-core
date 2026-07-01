"""Local end-to-end smoke for the governed-decision seam service (RR-0032 #1 local run).

Boots the core seam service as a local process (127.0.0.1, OS-assigned port) and POSTs a few v1.1
requests over REAL HTTP — proving the service is up and speaks the versioned contract. No server/infra:
just this process. The enterprise OS connects the IDENTICAL way in production:

    from agent_os_core.governance_decision_seam import RemoteGovernanceDecisionClient, http_transport
    client = RemoteGovernanceDecisionClient(http_transport("http://HOST:PORT/decide"), verifier=<CohortABVerifier>)

Two-terminal manual smoke (what "deploy locally" looks like):
    terminal A:  PYTHONPATH=src python3 -m aac.seam_service --port 8900
    terminal B:  point the OS RemoteGovernanceDecisionClient's http_transport at http://127.0.0.1:8900/decide

Run this self-contained smoke: PYTHONPATH=src python3 experiments/seam_smoke.py
"""

from __future__ import annotations

import json
import threading
import urllib.request

from aac.seam_service import default_producer, serve
from aac.seam_contract import GovernedDecisionRequest, VerifiedCandidate, to_json


def _post(url: str, req: GovernedDecisionRequest) -> dict:
    r = urllib.request.urlopen(
        urllib.request.Request(url, data=to_json(req).encode("utf-8"),
                               headers={"Content-Type": "application/json"}, method="POST"),
        timeout=5)
    return json.loads(r.read().decode("utf-8"))


def main() -> None:
    server = serve(default_producer(), port=0)
    host, port = server.server_address
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://{host}:{port}/decide"
    print(f"core seam service up at {url}  (v1.1: OS verifies -> core governs)\n")
    cases = [
        ("low-risk, OS-verified",
         GovernedDecisionRequest("t1", "R1", ["lever_a"], verified_candidates=(VerifiedCandidate("lever_a", True, 0.9, 3),))),
        ("high-risk, unapproved",
         GovernedDecisionRequest("t2", "R4", ["lever_a"], verified_candidates=(VerifiedCandidate("lever_a", True, 0.9, 3),))),
        ("high-risk, approved",
         GovernedDecisionRequest("t3", "R4", ["lever_a"], approved=True, verified_candidates=(VerifiedCandidate("lever_a", True, 0.9, 3),))),
        ("OS says unverified",
         GovernedDecisionRequest("t4", "R1", ["lever_a"], verified_candidates=(VerifiedCandidate("lever_a", False, 0.0, 0),))),
    ]
    try:
        for label, req in cases:
            out = _post(url, req)
            print(f"  {label:24} -> verdict={out['verdict']:11} chosen={out['chosen_action']}  audit={out['audit_ref'][:12]}")
    finally:
        server.shutdown()
        server.server_close()
    print("\nExpected: verified low-risk ALLOW; high-risk unapproved ESCALATE; high-risk approved ALLOW; "
          "unverified ESCALATE. The OS points its http_transport at this same /decide URL.")


if __name__ == "__main__":
    main()
