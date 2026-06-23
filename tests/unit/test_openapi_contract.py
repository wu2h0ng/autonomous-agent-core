from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (
    ROOT / "packages" / "contracts" / "src",
    ROOT / "packages" / "os_core" / "src",
    ROOT / "packages" / "persistence" / "src",
    ROOT / "action_connectors",
    ROOT / "apps" / "api_server" / "src",
):
    sys.path.insert(0, str(_p))

_FASTAPI = importlib.util.find_spec("fastapi") is not None

SNAPSHOT = ROOT / "apps" / "api_server" / "openapi.json"


@unittest.skipUnless(_FASTAPI, "fastapi not installed (install .[http])")
class OpenApiContractTest(unittest.TestCase):
    """The committed OpenAPI snapshot is the API contract (AR-20260611).

    Any route/model/parameter/status-code change must regenerate the snapshot
    (`python -m agent_os_api.openapi_contract`), turning API changes into
    reviewable contract diffs. This test is the drift gate.
    """

    def test_snapshot_matches_live_schema(self) -> None:
        from agent_os_api.openapi_contract import generate_openapi_spec, render

        self.assertTrue(SNAPSHOT.exists(), f"missing API contract snapshot: {SNAPSHOT}")
        self.assertEqual(
            SNAPSHOT.read_text(encoding="utf-8"),
            render(generate_openapi_spec()),
            "OpenAPI contract drift: run `python -m agent_os_api.openapi_contract` "
            "and commit the regenerated apps/api_server/openapi.json",
        )

    def test_contract_covers_all_trigger_surfaces(self) -> None:
        spec = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        self.assertEqual(
            sorted(spec["paths"]),
            [
                "/adoptions",
                "/approvals/{approval_id}/execute",
                "/knowledge/search",
                "/outcomes",
                "/runs",
                "/traces/{trace_id}",
            ],
        )

    def test_approval_execution_contract_is_declared(self) -> None:
        spec = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        approval_execute = spec["paths"]["/approvals/{approval_id}/execute"]["post"]
        rendered_route = json.dumps(approval_execute)
        self.assertIn("X-Operator-Key", rendered_route)
        self.assertNotIn("X-API-Key", rendered_route)
        operator_key = next(
            parameter
            for parameter in approval_execute["parameters"]
            if parameter["in"] == "header" and parameter["name"] == "X-Operator-Key"
        )
        self.assertIs(operator_key["required"], True)
        self.assertEqual(operator_key["schema"]["type"], "string")
        self.assertIn("404", approval_execute["responses"])
        self.assertIn("409", approval_execute["responses"])
        request_schema = spec["components"]["schemas"]["ApprovalExecuteRequest"]
        self.assertEqual(set(request_schema["required"]), {"reason", "approved_by"})
        response_schema = spec["components"]["schemas"]["ApprovalExecuteResponse"]
        self.assertEqual(
            set(response_schema["required"]),
            {
                "approval_id",
                "approval_status",
                "proposal_id",
                "operation_trace_id",
                "state",
                "evidence_chain_id",
            },
        )
        error_schema = spec["components"]["schemas"]["ApprovalExecuteErrorResponse"]
        self.assertEqual(set(error_schema["required"]), {"detail"})

    def test_adoption_contract_declares_causal_attribution_request_field(self) -> None:
        spec = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        adoption = spec["components"]["schemas"]["AdoptionRequest"]
        self.assertIn("causal_attribution", adoption["properties"])
        causal = spec["components"]["schemas"]["CausalAttributionRequest"]
        self.assertEqual(
            set(causal["required"]),
            {
                "metric_name",
                "observed_value",
                "counterfactual_value",
                "delta_absolute",
                "method",
                "comparison_ref",
                "window_start",
                "window_end",
                "confidence",
            },
        )

    def test_unified_block_contract_is_declared_on_runs(self) -> None:
        # AR-20260606-unified-block-outcome: the 422 business-block shape must be
        # part of the published schema, not folklore.
        spec = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        responses = spec["paths"]["/runs"]["post"]["responses"]
        self.assertIn("422", responses)
        block = spec["components"]["schemas"]["BlockDetail"]
        self.assertEqual(
            set(block["required"]) | set(block["properties"]),
            # trace_id: refusals reference their persisted RunTrace (AR-20260611).
            {"code", "message", "stage", "details", "trace_id"},
        )

    def test_check_mode_detects_drift(self) -> None:
        # Negative path: --check must exit 1 when the snapshot disagrees.
        import io
        from unittest import mock

        from agent_os_api import openapi_contract

        out = io.StringIO()
        self.assertEqual(openapi_contract.main(["--check"], stdout=out), 0)
        with mock.patch.object(
            openapi_contract, "generate_openapi_spec", return_value={"drifted": True}
        ):
            self.assertEqual(openapi_contract.main(["--check"], stdout=out), 1)
        self.assertIn("drift", out.getvalue())


if __name__ == "__main__":
    unittest.main()
