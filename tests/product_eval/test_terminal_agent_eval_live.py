"""Opt-in live E3 arm test for TERMINAL-AGENT-EVAL-0.

Skipped unless a real provider is configured in the environment (profile
deepseek). When run, it exercises a real provider call and asserts the report
shape — never a completion threshold (the result is whatever it is).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from product_evals.terminal_agent_eval.live_harness import live_provider_available, run_live_eval


@pytest.mark.skipif(
    not live_provider_available(),
    reason="opt-in live E3 arm requires AGENT_OS_PROVIDER_PROFILE=deepseek + DEEPSEEK_{BASE_URL,MODEL,API_KEY}",
)
def test_live_e3_arm_produces_real_provider_report(tmp_path: Path) -> None:
    report_path = tmp_path / "eval-report.json"
    report = run_live_eval(tmp_path / "ws", report_json_path=report_path)
    assert report.evidence_level.value == "E3_REAL_PROVIDER"
    assert report_path.exists()
    assert report.metrics.unsafe_action_count == 0
    assert report.metrics.cost_status.value == "UNKNOWN"
