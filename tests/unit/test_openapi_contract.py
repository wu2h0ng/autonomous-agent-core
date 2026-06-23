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
        self.assertIn("execution_audit", response_schema["properties"])
        self.assertEqual(
            response_schema["properties"]["execution_audit"],
            {"$ref": "#/components/schemas/ApprovalExecutionAudit"},
        )
        execution_audit_schema = spec["components"]["schemas"]["ApprovalExecutionAudit"]
        self.assertEqual(
            set(execution_audit_schema["properties"]),
            {
                "durability_scope",
                "execution_outcome",
                "replay_status",
                "external_ack_status",
                "ledger_status",
                "record_id",
                "external_request_id",
                "execution_certainty",
                "ack_status",
            },
        )
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

    def test_user_result_evidence_cards_are_strongly_typed(self) -> None:
        spec = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        run_request = spec["components"]["schemas"]["RunRequest"]
        self.assertEqual(run_request["properties"]["audience"]["default"], "internal")
        self.assertEqual(
            run_request["properties"]["audience"]["enum"],
            ["internal", "external"],
        )

        artifact = spec["components"]["schemas"]["UserResultArtifact"]
        self.assertIn("audience", artifact["required"])
        self.assertIn("redaction", artifact["required"])
        redaction = spec["components"]["schemas"]["UserResultRedaction"]
        self.assertGreaterEqual(
            set(redaction["required"]),
            {"audience", "applied", "data_classification", "redacted_fields"},
        )

        report = spec["components"]["schemas"]["UserResultReport"]
        self.assertIn("evidence_cards", report["required"])
        evidence_items = report["properties"]["evidence_cards"]["items"]
        self.assertEqual(evidence_items["discriminator"]["propertyName"], "type")
        self.assertEqual(len(evidence_items["oneOf"]), 3)

        schemas = spec["components"]["schemas"]
        metric_card = schemas["MetricContractEvidenceCard"]
        self.assertGreaterEqual(
            set(metric_card["required"]),
            {
                "card_id",
                "type",
                "title",
                "evidence_chain_id",
                "trace_id",
                "derived_from",
                "metric_name",
                "metric_version",
                "display_name",
                "owner",
                "unit",
                "dimensions",
                "data_classification",
            },
        )
        sql_card = schemas["SQLSafetyEvidenceCard"]
        self.assertGreaterEqual(
            set(sql_card["required"]),
            {
                "card_id",
                "type",
                "title",
                "evidence_chain_id",
                "trace_id",
                "derived_from",
                "query_metric_name",
                "sql_safety_allowed",
                "checked_schemas",
                "checked_tables",
                "bound_parameter_names",
                "sql_fingerprint",
            },
        )
        query_card = schemas["QueryResultEvidenceCard"]
        self.assertGreaterEqual(
            set(query_card["required"]),
            {
                "card_id",
                "type",
                "title",
                "evidence_chain_id",
                "trace_id",
                "derived_from",
                "row_count",
                "columns",
                "preview_row_count",
            },
        )
        widget = spec["components"]["schemas"]["UserResultDashboardWidget"]
        self.assertIn("redacted_fields", widget["properties"])

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
