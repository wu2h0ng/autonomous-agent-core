"""L1 end-to-end harness test for TERMINAL-AGENT-EVAL-0.

Actually runs the frozen L1 tasks through the real product loop and asserts the
E2 report — the proof that the instrument runs, not that the agent is good.
"""

from __future__ import annotations

from pathlib import Path


def test_l1_harness_runs_real_loop_and_writes_e2_report(tmp_path: Path) -> None:
    from product_evals.terminal_agent_eval.l1_harness import run_l1_eval

    report_path = tmp_path / "eval-report.json"
    report = run_l1_eval(tmp_path / "ws", report_json_path=report_path)

    assert report.metrics.completion_rate == 1.0
    assert report.metrics.unsafe_action_count == 0
    assert report.metrics.total_tokens > 0
    assert report.metrics.cost_status.value == "UNKNOWN"
    assert report.evidence_level.value == "E2_CONTROLLED_SIMULATION"
    assert {task.task_id for task in report.tasks} == {"l1-fix-fixture", "l1-add-note"}
    assert report_path.exists()
