"""Opt-in live arm for TERMINAL-CODING-EVAL-1.

Skipped unless a real provider is configured in the environment. When it runs,
it produces the only capability number this corpus can produce: the completion
rate of a real model over the same six frozen tasks, with no threshold
asserted — the result is whatever it is, including NOT_MET.

The two guards below run in every environment, including CI without a key:
the live arm must fail closed when no provider is configured, and the CLI must
refuse to run it without an explicitly given workspace.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from product_evals.terminal_agent_eval.coding_harness import main, score_arm
from product_evals.terminal_agent_eval.coding_live import (
    CodingEvalError,
    live_provider_available,
    run_live_coding_arm,
)
from product_evals.terminal_agent_eval.coding_tasks import MANIFEST_PATH
from product_evals.terminal_agent_eval.manifest import load_manifest


def test_live_arm_refuses_to_run_without_a_configured_provider(tmp_path: Path) -> None:
    if live_provider_available():
        pytest.skip("a live provider is configured in this environment")
    with pytest.raises(CodingEvalError):
        run_live_coding_arm(tmp_path / "ws")


def test_live_cli_requires_an_explicit_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["coding-harness"])
    assert main(["--live", "--out-dir", "unused"]) == 2


@pytest.mark.skipif(
    not live_provider_available(),
    reason="opt-in live arm requires AGENT_OS_PROVIDER_PROFILE plus <PROFILE>_BASE_URL/_MODEL/_API_KEY",
)
def test_live_arm_produces_a_real_provider_report(tmp_path: Path) -> None:
    report_path = tmp_path / "eval-report.live.json"
    report = run_live_coding_arm(tmp_path / "ws", report_json_path=report_path)

    assert report.evidence_level.value == "E3_REAL_PROVIDER"
    assert report.arm == "live"
    assert len(report.tasks) == 6
    assert report.metrics.unsafe_action_count == 0
    assert report.metrics.cost_status.value == "UNKNOWN"
    assert report_path.exists()
    # Deliberately no completion threshold here: the observed rate is reported
    # as-is, and a run that fails tasks is a recorded result, not a broken test.
    assert 0.0 <= report.metrics.completion_rate <= 1.0


def test_live_arm_plumbing_reports_failure_instead_of_fabricating_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The live arm must run the corpus and report honestly when the model is unreachable.

    Plumbing, not a capability measurement: the configured endpoint is a closed
    port, so any completed task would mean the arm fabricated success or graded
    the wrong workspace. Retries are disabled so the failure is immediate and no
    wall clock is spent waiting on a dead socket.
    """
    if live_provider_available():
        pytest.skip("a live provider is configured in this environment")
    monkeypatch.setenv("AGENT_OS_PROVIDER_PROFILE", "openai")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("OPENAI_MODEL", "unreachable-model")
    monkeypatch.setenv("OPENAI_API_KEY", "not-a-real-key")
    monkeypatch.setenv("AGENT_OS_PROVIDER_MAX_RETRIES", "0")

    report = run_live_coding_arm(tmp_path / "ws")

    assert report.evidence_level.value == "E3_REAL_PROVIDER"
    assert report.arm == "live"
    assert len(report.tasks) == 6
    assert report.metrics.unsafe_action_count == 0
    assert report.metrics.cost_status.value == "UNKNOWN"
    assert report.provenance, "a live report must carry provider provenance"
    # No WORK task can complete without a model, and every turn reports zero
    # provider steps. The two REFUSAL tasks do complete: taking no unauthorized
    # effect is exactly what an inert agent does, which is why the inert floor
    # of this corpus is 2/6 and why the WORK split is the attributable number.
    assert report.metrics.provider_step_count == 0
    assert report.metrics.completion_rate == pytest.approx(2 / 6)
    score = score_arm("live", report, load_manifest(MANIFEST_PATH))
    assert (score.work_completed, score.work_total) == (0, 4)
    assert (score.refusal_completed, score.refusal_total) == (2, 2)
