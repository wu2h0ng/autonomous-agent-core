from __future__ import annotations

import copy
import hashlib
import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest


def _protocol():
    try:
        return importlib.import_module("experiments.continual_retention_f3.protocol")
    except ModuleNotFoundError:
        pytest.fail("F3 protocol is not implemented")


def _evaluator():
    try:
        return importlib.import_module("experiments.continual_retention_f3.evaluator")
    except ModuleNotFoundError:
        pytest.fail("F3 evaluator is not implemented")


def _worker_script(tmp_path: Path, body: str) -> tuple[str, ...]:
    path = tmp_path / "worker.py"
    path.write_text(body)
    return (sys.executable, "-I", str(path))


def _request(kind: str = "act") -> dict[str, object]:
    return {
        "kind": kind,
        "state_version": 0,
        "public_state": {},
        "observation": {
            "features": [["opaque-dimension", "opaque-value"]],
            "authorized_actions": ["a0", "a1"],
        },
        "feedback": None,
    }


def test_exact_cli_runs_evaluator_and_emits_one_summary_line() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "experiments.continual_retention_f3.evaluator",
            "--seed",
            "17",
            "--arm",
            "candidate",
        ],
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    lines = completed.stdout.splitlines()
    assert len(lines) == 1
    summary = json.loads(lines[0])
    assert summary["status"] == "QUALIFICATION_ONLY"
    assert summary["frozen"] is False
    assert summary["result_run"] is False


@pytest.mark.parametrize("forged", ["reward", "cost", "charged_work"])
def test_action_proposal_rejects_arm_reported_evaluator_fields(forged: str) -> None:
    protocol = _protocol()
    payload = {
        "kind": "action_proposal",
        "state_version": 3,
        "action": "a0",
        forged: 999,
    }
    with pytest.raises(protocol.ProtocolError, match="exact fields"):
        protocol.parse_action_proposal(payload, 3, ("a0", "a1"))


def test_protocol_rejects_extra_fields_and_unauthorized_action() -> None:
    protocol = _protocol()
    with pytest.raises(protocol.ProtocolError, match="exact fields"):
        protocol.parse_action_proposal(
            {
                "kind": "action_proposal",
                "state_version": 0,
                "action": "a0",
                "phase": "A1",
            },
            0,
            ("a0", "a1"),
        )
    with pytest.raises(protocol.ProtocolError, match="unauthorized"):
        protocol.parse_action_proposal(
            {"kind": "action_proposal", "state_version": 0, "action": "escape"},
            0,
            ("a0", "a1"),
        )


def test_stale_transition_version_is_rejected() -> None:
    protocol = _protocol()
    with pytest.raises(protocol.ProtocolError, match="stale"):
        protocol.parse_transition_batch(
            {"kind": "transition_batch", "state_version": 4, "operations": []},
            expected_version=5,
            max_operations=4,
        )


def test_budget_is_checked_before_any_transition_is_applied() -> None:
    protocol = _protocol()
    state = {"values": {}, "events": []}
    before = copy.deepcopy(state)
    payload = {
        "kind": "transition_batch",
        "state_version": 0,
        "operations": [
            {"op": "set", "context": "c", "action": f"a{i}", "value": 0.5}
            for i in range(3)
        ],
    }
    with pytest.raises(protocol.ProtocolError, match="budget"):
        protocol.apply_transition_batch(
            state, payload, expected_version=0, max_operations=2
        )
    assert state == before


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("import time; time.sleep(2)\n", "timeout"),
        (
            "import sys; sys.stdin.readline(); sys.stderr.write('leak')\n"
            'print(\'{"kind":"action_proposal","state_version":0,'
            '"action":"a0"}\')\n',
            "stderr",
        ),
        (
            "import sys; sys.stdin.readline(); print('{}'); print('{}')\n",
            "one JSON line",
        ),
    ],
)
def test_worker_transport_fails_closed(tmp_path: Path, body: str, message: str) -> None:
    evaluator = _evaluator()
    command = _worker_script(tmp_path, body)
    with pytest.raises(evaluator.EvaluationError, match=message):
        evaluator.invoke_fresh_worker(command, _request(), timeout_seconds=0.1)


def test_fresh_worker_process_does_not_reuse_module_globals(tmp_path: Path) -> None:
    evaluator = _evaluator()
    command = _worker_script(
        tmp_path,
        "import json, sys\n"
        "counter = 0\n"
        "counter += 1\n"
        "request = json.loads(sys.stdin.readline())\n"
        "action = 'a0' if counter == 1 else 'a1'\n"
        "print(json.dumps({'kind':'action_proposal',"
        "'state_version':request['state_version'],'action':action}))\n",
    )
    first = evaluator.invoke_fresh_worker(command, _request(), timeout_seconds=1)
    second = evaluator.invoke_fresh_worker(command, _request(), timeout_seconds=1)
    assert first == second
    assert first["action"] == "a0"


def test_exact_worker_path_rejects_a_symlinked_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evaluator = _evaluator()
    real = tmp_path / "real"
    real.mkdir()
    (real / "arm_worker.py").write_text("raise SystemExit(0)\n")
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    monkeypatch.setattr(evaluator, "__file__", str(alias / "evaluator.py"))
    with pytest.raises(evaluator.EvaluationError, match="symlink"):
        evaluator._worker_command("candidate")


def test_evaluator_owns_reward_cost_correction_and_private_ledger() -> None:
    evaluator = _evaluator()
    plan = evaluator.build_hidden_plan(23)
    completed = evaluator.run_hidden_plan(plan, "candidate")
    assert completed.summary.operation_cost == len(completed.ledger)
    assert completed.summary.correction_count == 1
    assert completed.summary.valid_feedback_count < completed.summary.feedback_count
    replayed = evaluator.replay_and_score(
        plan, completed.ledger, completed.transcript_digest
    )
    assert replayed == completed.summary


@pytest.mark.parametrize("attack", ["reorder", "delete", "action", "reward", "cost"])
def test_pure_replay_rejects_ledger_tampering(attack: str) -> None:
    evaluator = _evaluator()
    plan = evaluator.build_hidden_plan(29)
    completed = evaluator.run_hidden_plan(plan, "baseline")
    ledger = [dict(record) for record in completed.ledger]
    if attack == "reorder":
        ledger[0], ledger[1] = ledger[1], ledger[0]
    elif attack == "delete":
        del ledger[1]
    elif attack == "action":
        ledger[0]["action"] = plan.public_steps[0].observation.authorized_actions[-1]
    elif attack == "reward":
        ledger[0]["reward"] = 999.0
    else:
        ledger[0]["cost"] = 999
    with pytest.raises(evaluator.EvaluationError, match="ledger"):
        evaluator.replay_and_score(plan, tuple(ledger), completed.transcript_digest)


def test_correction_cannot_pollute_replayed_state_or_score() -> None:
    evaluator = _evaluator()
    plan = evaluator.build_hidden_plan(31)
    completed = evaluator.run_hidden_plan(plan, "candidate")
    corrupted_turn = plan.corrupted_turn
    corrupt_record = next(
        record
        for record in completed.ledger
        if record["kind"] == "feedback" and record["turn"] == corrupted_turn
    )
    assert corrupt_record["corrupted"] is True
    assert corrupt_record["event_digest"] in completed.summary.invalidated_events
    assert corrupt_record["event_digest"] not in completed.summary.active_events


def test_candidate_and_baseline_consume_the_same_hidden_plan() -> None:
    evaluator = _evaluator()
    plan = evaluator.build_hidden_plan(37)
    candidate = evaluator.run_hidden_plan(plan, "candidate")
    baseline = evaluator.run_hidden_plan(plan, "baseline")
    assert candidate.summary.plan_digest == baseline.summary.plan_digest
    assert candidate.summary.turns == baseline.summary.turns
    assert candidate.summary.arm_id == "candidate"
    assert baseline.summary.arm_id == "baseline"


def test_exact_manifest_covers_every_consumed_source_and_test() -> None:
    root = Path(__file__).parents[1]
    manifest_path = (
        root
        / "docs/pre_spec/CLS-F3-INDEPENDENT-CUSTODY-1.QUALIFICATION-MANIFEST-2026-07-18.json"
    )
    manifest = json.loads(manifest_path.read_text())
    expected = {
        "experiments/continual_retention_f1/contracts.py",
        "experiments/continual_retention_f1/fixture.py",
        "experiments/continual_retention_f3/__init__.py",
        "experiments/continual_retention_f3/protocol.py",
        "experiments/continual_retention_f3/arm_worker.py",
        "experiments/continual_retention_f3/evaluator.py",
        "tests/test_cls_f3_independent_custody.py",
    }
    artifacts = manifest["exact_content"]
    assert set(artifacts) == expected
    for relative, digest in artifacts.items():
        raw_path = root / relative
        assert not any(path.is_symlink() for path in (raw_path, *raw_path.parents))
        path = raw_path.resolve(strict=True)
        assert path.is_relative_to(root.resolve())
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    assert manifest["authority"] == {
        "freeze_authorized": False,
        "result_run_authorized": False,
    }
