from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))

from agent_os_contracts.causal_discovery_seam import (  # noqa: E402
    CausalDiscoveryRequest,
    CausalDiscoveryResponse,
)


class CausalDiscoverySeamContractsTest(unittest.TestCase):
    def test_request_serializes_to_json(self) -> None:
        request = CausalDiscoveryRequest(data=[[1.0, 2.0], [3.0, 4.0]])
        parsed = json.loads(request.to_json())
        self.assertEqual(parsed["contract_version"], "1.0.0")
        self.assertEqual(parsed["data"], [[1.0, 2.0], [3.0, 4.0]])

    def test_response_round_trips_through_json(self) -> None:
        response = CausalDiscoveryResponse(
            dag=[(0, 1)],
            skeleton=[(0, 1)],
            n_nodes=2,
            n_skeleton_edges=1,
            n_dag_edges=1,
            confidence=0.9,
            orientation_confidence=0.8,
        )
        restored = CausalDiscoveryResponse.from_json(response.to_json())
        self.assertEqual(restored.dag, [(0, 1)])
        self.assertEqual(restored.skeleton, [(0, 1)])
        self.assertEqual(restored.confidence, 0.9)
        self.assertEqual(restored.contract_version, "1.0.0")


if __name__ == "__main__":
    unittest.main()
