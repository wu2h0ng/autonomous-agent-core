from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class SmokeTestScriptTest(unittest.TestCase):
    def test_smoke_test_script_exists_and_is_executable(self) -> None:
        script = ROOT / "scripts" / "smoke-test.sh"
        self.assertTrue(script.exists(), "smoke-test.sh must exist")
        self.assertTrue(script.stat().st_mode & 0o111, "smoke-test.sh must be executable")

    def test_smoke_test_script_parses(self) -> None:
        script = ROOT / "scripts" / "smoke-test.sh"
        result = subprocess.run(
            ["bash", "-n", str(script)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")

    def test_smoke_test_script_checks_staged_out_default_off(self) -> None:
        script = (ROOT / "scripts" / "smoke-test.sh").read_text(encoding="utf-8")
        self.assertIn("staged-out management plane", script)
        self.assertIn("/workflows correctly disabled", script)
        self.assertIn("workflow.started", script)
        self.assertIn("docker-compose.staging.yml", script)
        self.assertIn("operator_api_call", script)
        self.assertIn("Building api_server image", script)

    def test_staging_compose_overlay_exists(self) -> None:
        overlay = ROOT / "docker-compose.staging.yml"
        self.assertTrue(overlay.is_file())
        text = overlay.read_text(encoding="utf-8")
        self.assertIn("AGENT_OS_FULL_BPM_WORKFLOW", text)
        self.assertIn("AGENT_OS_MCP_GATEWAY", text)
        self.assertIn("AGENT_OS_R4_R5_AUTO_EXECUTION", text)

    def test_semantic_graph_adr_exists(self) -> None:
        adr = ROOT / "docs" / "decisions" / "ADR-20260707-semantic-graph-slice.md"
        self.assertTrue(adr.is_file())
        self.assertIn("SemanticGraph", adr.read_text(encoding="utf-8"))

    def test_compose_e2e_script_parses(self) -> None:
        script = ROOT / "scripts" / "compose-e2e.sh"
        result = subprocess.run(
            ["bash", "-n", str(script)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(result.returncode, 0)
        text = script.read_text(encoding="utf-8")
        self.assertIn("COMPOSE_E2E=1", text)
        self.assertIn("workspace.compose-api.spec.ts", text)

    def test_pilot_walkthrough_script_parses(self) -> None:
        script = ROOT / "scripts" / "pilot-walkthrough.sh"
        result = subprocess.run(
            ["bash", "-n", str(script)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(result.returncode, 0)
        text = script.read_text(encoding="utf-8")
        self.assertIn("--staging", text)
        self.assertIn("M8 Internal Pilot Walkthrough", text)


if __name__ == "__main__":
    unittest.main()
