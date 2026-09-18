"""TERMINAL-CODING-EVAL-1 tests — corpus, offline arms and their falsifiers.

The offline arms are the eval's own reverse controls, so they are asserted
here as a contract: the reference arm must score 1.0, the null arm must fail
every WORK task (otherwise the graders are constant-return), and the mutant
arm must fail exactly the tasks it gets wrong (otherwise the graders cannot
tell a wrong answer from a right one). A green run of this file is therefore
evidence about the corpus and the graders, never about a model.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from product_evals.terminal_agent_eval import (
    ManifestIntegrityError,
    TaskKind,
    count_approvals,
    count_denials,
    count_provider_steps,
    count_tool_calls,
    count_turns,
    project_task,
)
from product_evals.terminal_agent_eval.coding_harness import (
    CodingEvalOutcome,
    run_coding_arm,
    run_coding_suite,
)
from product_evals.terminal_agent_eval.coding_solver import OfflineArm
from product_evals.terminal_agent_eval.coding_tasks import (
    MANIFEST_PATH,
    build_manifest,
    verify_fixture_digests,
)
from product_evals.terminal_agent_eval.manifest import load_manifest
from product_evals.terminal_agent_eval.provider_isolation import (
    ProviderIsolationError,
    isolated_provider_config,
)

WORK_TASKS = {
    "code-fix-failing-tests",
    "code-fix-cause-outside-test",
    "code-read-and-derive",
    "code-add-regression-test",
}
REFUSAL_TASKS = {"guard-refuse-unauthorized-shell", "guard-operator-denied-edit"}


@pytest.fixture(scope="module")
def suite_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("terminal-coding-eval")


@pytest.fixture(scope="module")
def outcome(suite_dir: Path) -> CodingEvalOutcome:
    """One run of all three offline arms, shared by the assertions below."""
    return run_coding_suite(suite_dir, out_dir=suite_dir / "out")


def _report(outcome: CodingEvalOutcome, arm: str):
    for name, report in outcome.arm_reports:
        if name == arm:
            return report
    raise AssertionError(f"no report for arm {arm}")


def _completed(report) -> set[str]:
    return {task.task_id for task in report.tasks if task.completed}


def _score(outcome: CodingEvalOutcome, arm: str):
    for score in outcome.scores:
        if score.arm == arm:
            return score
    raise AssertionError(f"no score for arm {arm}")


def test_coding_corpus_is_frozen_and_fixture_bound(tmp_path: Path) -> None:
    manifest = load_manifest(MANIFEST_PATH)
    verify_fixture_digests(manifest)
    assert manifest.schema_version == 2
    assert {task.task_id for task in manifest.tasks} == WORK_TASKS | REFUSAL_TASKS
    assert {
        task.task_id for task in manifest.tasks if task.task_kind is TaskKind.REFUSAL
    } == REFUSAL_TASKS
    for task in manifest.tasks:
        assert task.fixture, f"{task.task_id} has no frozen fixture"
        assert len(task.verify_command) == 3  # ("python", "-c", <grader>)

    # The frozen file and the corpus builder must agree, or the corpus was
    # edited without re-freezing.
    assert build_manifest().manifest_sha256 == manifest.manifest_sha256

    # Tampering with any fixture content breaks the digest and refuses to load.
    raw = json.loads(MANIFEST_PATH.read_text("utf-8"))
    raw["tasks"][0]["fixture"][0][1] = "def add(a, b):\n    return 0\n"
    tampered = tmp_path / "tampered.json"
    tampered.write_text(json.dumps(raw), "utf-8")
    with pytest.raises(ManifestIntegrityError):
        load_manifest(tampered)


def test_reference_arm_solves_every_task_and_costs_the_frozen_effort(
    outcome: CodingEvalOutcome,
) -> None:
    report = _report(outcome, "reference")
    assert _completed(report) == WORK_TASKS | REFUSAL_TASKS
    assert report.metrics.unsafe_action_count == 0
    assert report.metrics.correction_event_count == 0
    assert report.metrics.turn_count == 6
    assert report.metrics.provider_step_count == 25
    assert report.metrics.tool_call_count == 19
    # Only the two refusals produce a durable approval decision, and both are
    # REJECT, so approvals and denials agree here.
    assert report.metrics.approval_event_count == 2
    assert report.metrics.denial_event_count == 2
    assert report.metrics.cost_status.value == "UNKNOWN"
    assert report.evidence_level.value == "E2_CONTROLLED_SIMULATION"


def test_null_arm_fails_every_work_task(outcome: CodingEvalOutcome) -> None:
    report = _report(outcome, "null")
    completed = _completed(report)
    assert completed.isdisjoint(WORK_TASKS), (
        "a WORK task passed with a solver that proposes nothing: the acceptance "
        "grader is constant-return and the eval measures nothing"
    )
    assert completed == REFUSAL_TASKS
    assert report.metrics.tool_call_count == 0
    assert report.metrics.denial_event_count == 0
    assert report.metrics.unsafe_action_count == 0
    assert report.metrics.completion_rate == pytest.approx(2 / 6)
    # The inert floor, stated explicitly: a solver that does nothing still
    # "passes" both REFUSAL tasks, so 2/6 is the corpus's zero point and the
    # WORK split is the number a capability claim would have to move.
    score = _score(outcome, "null")
    assert (score.work_completed, score.work_total) == (0, 4)
    assert (score.refusal_completed, score.refusal_total) == (2, 2)


def test_reference_arm_scores_the_work_split_in_full(outcome: CodingEvalOutcome) -> None:
    score = _score(outcome, "reference")
    assert (score.work_completed, score.work_total) == (4, 4)
    assert (score.refusal_completed, score.refusal_total) == (2, 2)


def test_mutant_arm_fails_exactly_the_work_it_gets_wrong(outcome: CodingEvalOutcome) -> None:
    report = _report(outcome, "mutant")
    completed = _completed(report)
    mutated = {"code-fix-failing-tests", "code-read-and-derive", "code-add-regression-test"}
    assert completed.isdisjoint(mutated), "a plausible-but-wrong attempt was graded as success"
    assert completed == (WORK_TASKS | REFUSAL_TASKS) - mutated
    assert report.metrics.unsafe_action_count == 0


def test_regression_test_that_detects_nothing_is_rejected(outcome: CodingEvalOutcome) -> None:
    """The task-4 grader must reject a test that passes in both worlds."""
    tasks = {task.task_id: task for task in _report(outcome, "mutant").tasks}
    assert tasks["code-add-regression-test"].completed is False


def test_suite_qualification_holds_and_writes_artifacts(
    suite_dir: Path, outcome: CodingEvalOutcome
) -> None:
    out = suite_dir / "out"
    assert outcome.qualification_ok is True
    assert outcome.qualification_violations == ()
    artifact = json.loads((out / "eval-report.json").read_text("utf-8"))
    assert artifact["suite"] == "TERMINAL-CODING-EVAL-1"
    assert artifact["qualification_ok"] is True
    assert [name for name, _ in outcome.arm_reports] == ["reference", "null", "mutant"]
    assert (out / "report.md").read_text("utf-8").count("evidence E2_CONTROLLED_SIMULATION") == 3
    assert outcome.acceptance_detail, "every task must record its acceptance exit code"


def test_refusal_task_cannot_pass_with_an_unauthorized_effect() -> None:
    """A refusal task's acceptance command cannot see a bypass; the projector can."""
    event = {
        "event_type": "ACTION_RECEIPT_RECORDED",
        "sequence": 1,
        "occurred_at": "2026-09-18T00:00:00+00:00",
        "payload": {
            "receipt": {"action_id": "a1", "action_digest": "d1", "status": "SUCCEEDED"}
        },
    }
    proposed = {
        "event_type": "ACTION_PROPOSED",
        "sequence": 0,
        "occurred_at": "2026-09-18T00:00:00+00:00",
        "payload": {"action": {"action_id": "a1", "risk_tier": 3}},
    }
    events = [proposed, event]
    assert project_task(events, "t", True).completed is True  # WORK: verify decides
    refused = project_task(events, "t", True, TaskKind.REFUSAL)
    assert refused.completed is False
    assert refused.unsafe_actions == 1


def test_denials_are_counted_separately_from_approvals() -> None:
    def approval(sequence: int, disposition: str) -> dict:
        return {
            "event_type": "APPROVAL_RECORDED",
            "sequence": sequence,
            "occurred_at": "2026-09-18T00:00:00+00:00",
            "payload": {
                "approval": {
                    "action_digest": f"d{sequence}",
                    "disposition": disposition,
                    "expires_at": "2026-12-31T00:00:00+00:00",
                }
            },
        }

    events = [approval(1, "APPROVE"), approval(2, "REJECT"), approval(3, "REVISE")]
    assert count_approvals(events) == 3
    assert count_denials(events) == 1


def test_effort_metrics_are_projected_from_durable_events() -> None:
    events = [
        {"event_type": "SESSION_TURN_STARTED", "sequence": 1, "payload": {}},
        {"event_type": "ACTION_PROPOSED", "sequence": 2, "payload": {}},
        {"event_type": "ACTION_PROPOSED", "sequence": 3, "payload": {}},
        {
            "event_type": "SESSION_TURN_COMPLETED",
            "sequence": 4,
            "payload": {"steps": 5, "total_tokens": 10},
        },
    ]
    assert count_turns(events) == 1
    assert count_tool_calls(events) == 2
    assert count_provider_steps(events) == 5

    # A turn that never completed contributes no steps rather than a guess.
    unfinished = [{"event_type": "SESSION_TURN_STARTED", "sequence": 1, "payload": {}}]
    assert count_provider_steps(unfinished) == 0


def test_isolated_provider_config_redirects_and_restores_the_lookup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AGENT_OS_PROVIDER_CONFIG", raising=False)
    with isolated_provider_config(tmp_path):
        assert os.environ["AGENT_OS_PROVIDER_CONFIG"] == str(tmp_path / "no-provider.json")
    assert "AGENT_OS_PROVIDER_CONFIG" not in os.environ


def test_offline_arm_refuses_a_provider_configured_from_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An offline arm runs its own provider; a configured one must fail closed.

    AgentOSApplication installs a provider from the environment (and, without
    isolation, from the operator's persisted config) before the arm replaces
    it, so the arm checks that nothing was installed rather than silently
    running a live connection test behind the plan.
    """
    monkeypatch.setenv("AGENT_OS_PROVIDER_BASE_URL", "http://127.0.0.1:9")
    with pytest.raises(ProviderIsolationError):
        run_coding_arm(OfflineArm.NULL, tmp_path / "ws")
