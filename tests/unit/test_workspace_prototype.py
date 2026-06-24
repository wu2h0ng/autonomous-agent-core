from pathlib import Path
import re
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_HTML = REPO_ROOT / "apps" / "workspace" / "prototype" / "index.html"


class WorkspacePrototypeContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.html = WORKSPACE_HTML.read_text(encoding="utf-8")

    def test_f1_shows_dataproduct_and_knowledgeasset_candidates(self) -> None:
        """F1 must show the product loop beyond trusted Q&A."""
        required_markers = (
            'id="dataProductCandidate"',
            'id="dataProductStatus"',
            'id="dataProductId"',
            'id="dataProductContract"',
            'id="dataProductFreshness"',
            'id="dataProductReuse"',
            'id="dataProductSource"',
            'id="knowledgeAssetCandidate"',
            'id="knowledgeAssetState"',
            'id="knowledgeAssetReview"',
            "DataProduct candidate",
            "KnowledgeAsset candidate",
        )
        for marker in required_markers:
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)

    def test_f1_states_override_candidate_fields(self) -> None:
        for marker in (
            'dataProductId: "blocked-before-candidate"',
            'dataProductContract: "SQL Safety blocked"',
            'dataProductFreshness: "not applicable"',
            'dataProductReuse: "no reusable artifact"',
            'dataProductId: "draft-pending-evidence"',
            'dataProductContract: "contract pending owner evidence"',
            'dataProductFreshness: "pending required dimension"',
            'dataProductReuse: "review-only draft"',
            "candidateOverrideKeys",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)

    def test_f1_keeps_contract_shaped_mock_states_visible(self) -> None:
        for marker in (
            'data-state="loaded"',
            'data-state="blocked"',
            'data-state="insufficient"',
            "const states =",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)

    def test_workspace_prototype_does_not_import_os_core(self) -> None:
        forbidden_markers = (
            "agent_os_core",
            "from agent_os_core",
            "import agent_os_core",
            "packages/os_core",
            "../packages/os_core",
        )
        workspace_root = REPO_ROOT / "apps" / "workspace"
        for path in workspace_root.rglob("*"):
            if path.suffix not in {".html", ".md", ".js", ".css", ".ts", ".tsx"}:
                continue
            content = path.read_text(encoding="utf-8")
            for marker in forbidden_markers:
                with self.subTest(path=path.relative_to(REPO_ROOT), marker=marker):
                    self.assertNotIn(marker, content)

    def test_mobile_candidate_header_can_wrap(self) -> None:
        self.assertIsNotNone(
            re.search(r"\.action-title\s*\{[^}]*flex-wrap: wrap;", self.html, re.S)
        )
        self.assertIsNotNone(
            re.search(r"\.action-title\s*>\s*\*\s*\{[^}]*min-width: 0;", self.html, re.S)
        )

    def test_f2_reads_report_projection_through_public_api_contract(self) -> None:
        """F2 may read existing report projections, not invent backend fields."""
        required_markers = (
            'id="apiBaseUrl"',
            'id="apiTraceId"',
            'id="apiKey"',
            'id="apiAudience"',
            'id="loadReportButton"',
            'id="apiReportStatus"',
            "GET /runs/{trace_id}/report",
            "function buildReportReadUrl",
            "function loadReportProjection",
            "function renderUserResultArtifact",
            "fetch(reportUrl",
            '"X-API-Key"',
            "encodeURIComponent(traceId)",
            "payload.user_result",
            "artifact.report.evidence_cards",
            "artifact.dashboard.widgets",
            "artifact.business_action",
            "artifact.decision",
            "artifact.redaction",
        )
        for marker in required_markers:
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)

    def test_f2_report_projection_is_read_only(self) -> None:
        """The workspace read projection must not execute approvals or outcomes."""
        forbidden_markers = (
            'fetch("/approvals/',
            "fetch('/approvals/",
            'fetch("/outcomes',
            "fetch('/outcomes",
            'method: "POST"',
            "method: 'POST'",
            "X-Operator-Key",
        )
        for marker in forbidden_markers:
            with self.subTest(marker=marker):
                self.assertNotIn(marker, self.html)


if __name__ == "__main__":
    unittest.main()
