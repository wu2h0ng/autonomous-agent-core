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
            if "node_modules" in path.parts:
                continue
            if path.suffix not in {".html", ".md", ".js", ".css", ".ts", ".tsx"}:
                continue
            if not path.is_file():
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
            "function parseReportApiBase",
            "function isTrustedReportOrigin",
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
            "API base must be same-origin or localhost.",
            "loopbackHosts",
        )
        for marker in required_markers:
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)
        self.assertIn("firstWidget.type", self.html)
        self.assertIn("decision.reason", self.html)
        self.assertNotIn("firstWidget.widget_type", self.html)
        self.assertNotIn("decision.rationale", self.html)

    def test_f2_report_projection_is_read_only(self) -> None:
        """The workspace read projection must not execute approvals or outcomes."""
        forbidden_markers = (
            'fetch("/approvals/',
            "fetch('/approvals/",
            'fetch("/outcomes',
            "fetch('/outcomes",
            "navigator.sendBeacon",
            "XMLHttpRequest",
            "X-Operator-Key",
        )
        for marker in forbidden_markers:
            with self.subTest(marker=marker):
                self.assertNotIn(marker, self.html)
        self.assertEqual(2, len(re.findall(r"\bfetch\s*\(", self.html)))
        self.assertEqual(1, len(re.findall(r"\bmethod\s*:\s*\"POST\"", self.html)))

    def test_f2_report_projection_does_not_html_inject_trace_fields(self) -> None:
        """API report fields rendered into Trace must stay text, not HTML."""
        self.assertNotIn("traceSteps.innerHTML", self.html)
        self.assertIn("document.createElement", self.html)
        self.assertIn("textContent = String(value)", self.html)

    def test_f2_report_projection_does_not_surface_raw_sql_or_error_body(self) -> None:
        """F2 demo and error path must keep the no-raw-SQL report baseline."""
        forbidden_markers = (
            "await response.text()",
            "sales.orders",
            "ads.daily_performance",
            "daily_ops where",
            ":start_date",
            ":limit",
            ":week",
            ":date",
        )
        for marker in forbidden_markers:
            with self.subTest(marker=marker):
                self.assertNotIn(marker, self.html)
        self.assertIn("parameters=redacted", self.html)
        self.assertIn("Report request failed with HTTP", self.html)

    def test_f2_responsive_layout_switches_before_1280px_overflow(self) -> None:
        """The three-column desktop layout must collapse before 1280px notebooks overflow."""
        self.assertIn("@media (max-width: 1320px)", self.html)
        self.assertNotIn("@media (max-width: 1220px)", self.html)
        self.assertIsNotNone(
            re.search(
                r"@media \(max-width: 760px\)\s*\{.*?\.api-grid,.*?grid-template-columns: 1fr;",
                self.html,
                re.S,
            )
        )

    def test_f3_live_run_submit_uses_public_run_contract(self) -> None:
        """F3a may submit a governed run, then render the returned user_result."""
        required_markers = (
            "F3a boundary",
            'data-contract="POST /runs"',
            "POST /runs",
            "function trustedApiRoot",
            "function buildRunSubmitUrl",
            "function buildRunRequestBody",
            "function submitGovernedRun",
            "fetch(runUrl",
            'method: "POST"',
            '"Content-Type": "application/json"',
            "JSON.stringify(buildRunRequestBody())",
            "question: refs.question.value.trim()",
            "parameters: {}",
            "audience: refs.apiAudience.value",
            "payload.user_result",
            "renderUserResultArtifact(payload)",
            'setApiReportStatus("submitted", "badge ok")',
        )
        for marker in required_markers:
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)
        self.assertIn("const root = trustedApiRoot(apiBase);", self.html)
        self.assertIn('new URL("/runs", root)', self.html)
        self.assertNotIn("apiUrl.href.replace", self.html)

    def test_f3_live_run_submit_keeps_management_surfaces_blocked(self) -> None:
        """F3a is live analysis only; no approval execution or management writes."""
        forbidden_markers = (
            "/approvals/",
            "/outcomes",
            "/adoptions",
            "/knowledge",
            "X-Operator-Key",
            "approval execute",
            "executeApproval",
            "navigator.sendBeacon",
            "XMLHttpRequest",
        )
        for marker in forbidden_markers:
            with self.subTest(marker=marker):
                self.assertNotIn(marker, self.html)
        self.assertIn('refs.apiReportNote.textContent = "Run request failed.";', self.html)
        self.assertEqual(2, len(re.findall(r"\bfetch\s*\(", self.html)))
        self.assertEqual(1, len(re.findall(r"\bmethod\s*:\s*\"POST\"", self.html)))

    def test_f3_live_run_submit_is_not_nested_inside_report_loader(self) -> None:
        """The run button handler must be script-global and browser-callable."""
        load_start = self.html.index("async function loadReportProjection")
        submit_start = self.html.index("async function submitGovernedRun")
        report_error_path = self.html.index('"Report request failed."', load_start)
        self.assertLess(load_start, submit_start)
        self.assertLess(report_error_path, submit_start)


class WorkspaceFrontendLiveApiTest(unittest.TestCase):
    """F3+ live API integration: API client, pages, and components."""

    def setUp(self) -> None:
        self.repo_root = REPO_ROOT
        self.frontend_root = self.repo_root / "apps" / "workspace" / "frontend" / "src"
        self.api_client = self.frontend_root / "lib" / "api.ts"
        self.run_detail_client = (
            self.frontend_root / "app" / "runs" / "[traceId]" / "RunDetailClient.tsx"
        )
        self.approval_detail = self.frontend_root / "components" / "ApprovalDetail.tsx"

    def test_api_client_exports_required_functions(self) -> None:
        source = self.api_client.read_text(encoding="utf-8")
        required_functions = (
            "export async function runQuestion",
            "export async function getReport",
            "export async function recordOutcome",
            "export async function listApprovals",
            "export async function getApproval",
            "export async function executeApproval",
            "export async function recordAdoption",
            "export async function searchKnowledge",
            "export async function getTrace",
        )
        for marker in required_functions:
            with self.subTest(marker=marker):
                self.assertIn(marker, source)

    def test_api_client_uses_correct_endpoints(self) -> None:
        source = self.api_client.read_text(encoding="utf-8")
        required_endpoints = (
            "/runs",
            "/runs/${encodeURIComponent(traceId)}/report",
            "/outcomes",
            "/approvals",
            "/approvals/${encodeURIComponent(approvalId)}/execute",
            "/adoptions",
            "/knowledge/search",
            "/traces/${traceId}",
        )
        for marker in required_endpoints:
            with self.subTest(marker=marker):
                self.assertIn(marker, source)

    def test_api_client_uses_env_and_operator_key_header(self) -> None:
        source = self.api_client.read_text(encoding="utf-8")
        self.assertIn("process.env.NEXT_PUBLIC_API_URL", source)
        self.assertIn("'X-API-Key': apiKey", source)
        self.assertIn("X-Operator-Key", source)
        self.assertIn("operatorKeyOverride", source)

    def test_f3_pages_exist(self) -> None:
        required_pages = (
            self.frontend_root / "app" / "runs" / "page.tsx",
            self.frontend_root / "app" / "runs" / "[traceId]" / "page.tsx",
            self.frontend_root / "app" / "approvals" / "page.tsx",
            self.frontend_root / "app" / "approvals" / "[approvalId]" / "page.tsx",
        )
        for page in required_pages:
            with self.subTest(page=str(page)):
                self.assertTrue(page.exists(), f"{page} must exist")

    def test_f3_components_exist(self) -> None:
        required_components = (
            "EvidenceChainViewer.tsx",
            "ActionProposalPanel.tsx",
            "DataProductCard.tsx",
            "ApprovalList.tsx",
            "OutcomeForm.tsx",
        )
        for name in required_components:
            with self.subTest(component=name):
                self.assertTrue(
                    (self.frontend_root / "components" / name).exists(),
                    f"{name} must exist",
                )

    def test_run_detail_renders_evidence_action_dataproduct(self) -> None:
        source = self.run_detail_client.read_text(encoding="utf-8")
        self.assertIn("EvidenceChainViewer", source)
        self.assertIn("ActionProposalPanel", source)
        self.assertIn("DataProductCard", source)
        self.assertIn("Business Context", source)
        self.assertIn("artifact.report", source)
        self.assertIn("artifact.business_action", source)

    def test_approval_execute_uses_operator_key_header(self) -> None:
        source = self.approval_detail.read_text(encoding="utf-8")
        self.assertIn("executeApproval", source)
        self.assertIn("operatorKey", source)
        # The API client is responsible for the X-Operator-Key header.
        api_source = self.api_client.read_text(encoding="utf-8")
        self.assertIn("X-Operator-Key", api_source)


if __name__ == "__main__":
    unittest.main()
