from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from collections import namedtuple
from dataclasses import asdict
from pathlib import Path
from typing import Any

from experiments.continual_retention_f1.contracts import stable_digest
from experiments.continual_retention_f1.fixture import EpisodePlan, EvaluatorFixture

from .protocol import (
    ProtocolError,
    apply_transition_batch,
    parse_action_proposal,
    parse_transition_batch,
)


class EvaluationError(RuntimeError):
    pass


QualificationSummary = namedtuple(
    "QualificationSummary",
    "status frozen result_run arm_id plan_digest turns total_reward operation_cost "
    "feedback_count valid_feedback_count correction_count active_events "
    "invalidated_events",
)
CompletedEvaluation = namedtuple(
    "CompletedEvaluation", "summary ledger transcript_digest"
)


_RECORD_FIELDS = frozenset(
    "sequence kind turn arm_id state_version observation proposal transition "
    "action reward cost corrupted event_digest".split()
)


def build_hidden_plan(seed: int) -> EpisodePlan:
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise EvaluationError("qualification seed must be a non-negative integer")
    return EvaluatorFixture.build(seed)


def _plan_digest(plan: EpisodePlan) -> str:
    return stable_digest("cls-f3-hidden-plan", asdict(plan))


def invoke_fresh_worker(
    command: tuple[str, ...], request: dict[str, object], *, timeout_seconds: float
) -> dict[str, object]:
    if not command or timeout_seconds <= 0:
        raise EvaluationError("worker command and positive timeout are required")
    try:
        completed = subprocess.run(
            command,
            input=json.dumps(request, sort_keys=True, separators=(",", ":")) + "\n",
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise EvaluationError("worker timeout") from exc
    if completed.stderr:
        raise EvaluationError("worker stderr is forbidden")
    if completed.returncode != 0:
        raise EvaluationError(f"worker failed closed with exit {completed.returncode}")
    lines = completed.stdout.splitlines()
    if len(lines) != 1:
        raise EvaluationError("worker must emit exactly one JSON line")
    try:
        response = json.loads(lines[0])
    except json.JSONDecodeError as exc:
        raise EvaluationError("worker output is not JSON") from exc
    if not isinstance(response, dict):
        raise EvaluationError("worker response must be an object")
    return response


def _worker_command(arm_id: str) -> tuple[str, ...]:
    if arm_id not in {"candidate", "baseline"}:
        raise EvaluationError("closed arm id required")
    raw_worker = Path(__file__).with_name("arm_worker.py")
    if any(path.is_symlink() for path in (raw_worker, *raw_worker.parents)):
        raise EvaluationError("arm worker symlink is forbidden")
    worker = raw_worker.resolve(strict=True)
    return (sys.executable, "-I", str(worker), "--arm", arm_id)


def _request(kind, state, observation, feedback) -> dict[str, object]:
    return {
        "kind": kind,
        "state_version": state["version"],
        "public_state": state,
        "observation": observation,
        "feedback": feedback,
    }


def _new_record(sequence, kind, turn, arm_id, version, **changes) -> dict[str, object]:
    record = dict(
        dict.fromkeys(_RECORD_FIELDS),
        sequence=sequence,
        kind=kind,
        turn=turn,
        arm_id=arm_id,
        state_version=version,
        cost=1,
        corrupted=False,
    )
    record.update(changes)
    return record


def _correction_record(
    *,
    sequence: int,
    turn: int,
    arm_id: str,
    state: dict[str, Any],
    digest: str,
    command: tuple[str, ...],
) -> dict[str, object]:
    version = state["version"]
    correction = {"event_digest": digest}
    response = invoke_fresh_worker(
        command,
        _request(
            "correction", state, {"features": [], "authorized_actions": []}, correction
        ),
        timeout_seconds=2,
    )
    transition = parse_transition_batch(
        response, expected_version=version, max_operations=1
    )
    apply_transition_batch(
        state,
        transition,
        expected_version=version,
        max_operations=1,
        authorized_correction=digest,
    )
    return _new_record(
        sequence,
        "correction",
        turn,
        arm_id,
        version,
        transition=transition,
        event_digest=digest,
    )


def _feedback_record(
    *,
    sequence: int,
    turn: int,
    arm_id: str,
    plan: EpisodePlan,
    state: dict[str, Any],
    command: tuple[str, ...],
) -> dict[str, object]:
    version = state["version"]
    observation = plan.public_steps[turn].observation.to_dict()
    response = invoke_fresh_worker(
        command, _request("act", state, observation, None), timeout_seconds=2
    )
    proposal = parse_action_proposal(
        response,
        version,
        plan.public_steps[turn].observation.authorized_actions,
    )
    action = proposal["action"]
    latent = plan.latent_steps[turn]
    reward = 1.0 if action == latent.optimal_action else 0.0
    corrupted = turn == plan.corrupted_turn
    if corrupted:
        reward = 1.0 - reward
    digest = stable_digest(
        "cls-f3-feedback", [turn, observation, action, reward, corrupted]
    )
    feedback = {
        "event_digest": digest,
        "observation": observation,
        "action": action,
        "reward": reward,
        "corrupted": corrupted,
    }
    response = invoke_fresh_worker(
        command,
        _request("feedback", state, observation, feedback),
        timeout_seconds=2,
    )
    transition = parse_transition_batch(
        response, expected_version=version, max_operations=1
    )
    apply_transition_batch(
        state,
        transition,
        expected_version=version,
        max_operations=1,
        authoritative_feedback=feedback,
    )
    return _new_record(
        sequence,
        "feedback",
        turn,
        arm_id,
        version,
        observation=observation,
        proposal=proposal,
        transition=transition,
        action=action,
        reward=reward,
        corrupted=corrupted,
        event_digest=digest,
    )


def run_hidden_plan(plan: EpisodePlan, arm_id: str) -> CompletedEvaluation:
    command = _worker_command(arm_id)
    state: dict[str, Any] = {"version": 0, "events": [], "invalidated": []}
    corrupted_digest: str | None = None
    with tempfile.TemporaryDirectory(prefix="cls-f3-private-") as directory:
        ledger_path = Path(directory) / "ledger.jsonl"
        ledger_path.touch(mode=0o600)
        records: list[dict[str, object]] = []
        sequence = 0
        for turn in range(len(plan.public_steps)):
            if turn == plan.correction_delivery_turn:
                if corrupted_digest is None:
                    raise EvaluationError("correction has no prior corrupted feedback")
                record = _correction_record(
                    sequence=sequence,
                    turn=turn,
                    arm_id=arm_id,
                    state=state,
                    digest=corrupted_digest,
                    command=command,
                )
                records.append(record)
                sequence += 1
            record = _feedback_record(
                sequence=sequence,
                turn=turn,
                arm_id=arm_id,
                plan=plan,
                state=state,
                command=command,
            )
            if record["corrupted"]:
                corrupted_digest = str(record["event_digest"])
            records.append(record)
            sequence += 1
        ledger_path.write_text(
            "".join(
                json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
                for record in records
            )
        )
        ledger = tuple(
            json.loads(line) for line in ledger_path.read_text().splitlines()
        )
    transcript_digest = stable_digest("cls-f3-ledger-corruption-check", ledger)
    summary = replay_and_score(plan, ledger, transcript_digest)
    return CompletedEvaluation(summary, ledger, transcript_digest)


def replay_and_score(
    plan: EpisodePlan,
    ledger: tuple[dict[str, object], ...],
    transcript_digest: str,
) -> QualificationSummary:
    if stable_digest("cls-f3-ledger-corruption-check", ledger) != transcript_digest:
        raise EvaluationError("ledger corruption checksum mismatch")
    if not ledger:
        raise EvaluationError("ledger is empty")
    arm_id = ledger[0].get("arm_id")
    if arm_id not in {"candidate", "baseline"}:
        raise EvaluationError("ledger arm id invalid")
    state: dict[str, Any] = {"version": 0, "events": [], "invalidated": []}
    position = 0
    for turn in range(len(plan.public_steps)):
        if turn == plan.correction_delivery_turn:
            record = _checked_record(ledger, position, "correction", turn, arm_id)
            corrupted = next(
                event for event in state["events"] if event["corrupted"] is True
            )
            digest = corrupted["event_digest"]
            if (
                record["state_version"] != state["version"]
                or record["event_digest"] != digest
                or any(
                    record[field] is not None
                    for field in ("observation", "proposal", "action", "reward")
                )
                or record["corrupted"] is not False
            ):
                raise EvaluationError("ledger correction content invalid")
            _replay_transition(state, record["transition"], correction=str(digest))
            position += 1
        record = _checked_record(ledger, position, "feedback", turn, arm_id)
        observation = plan.public_steps[turn].observation.to_dict()
        actions = plan.public_steps[turn].observation.authorized_actions
        try:
            proposal = parse_action_proposal(
                record["proposal"], state["version"], actions
            )
        except ProtocolError as exc:
            raise EvaluationError("ledger action proposal invalid") from exc
        action = proposal["action"]
        reward = 1.0 if action == plan.latent_steps[turn].optimal_action else 0.0
        is_corrupted = turn == plan.corrupted_turn
        reward = 1.0 - reward if is_corrupted else reward
        digest = stable_digest(
            "cls-f3-feedback", [turn, observation, action, reward, is_corrupted]
        )
        if (
            record["state_version"] != state["version"]
            or record["observation"] != observation
            or record["action"] != action
            or record["reward"] != reward
            or record["corrupted"] is not is_corrupted
            or record["event_digest"] != digest
        ):
            raise EvaluationError("ledger feedback content invalid")
        feedback = dict(
            event_digest=digest,
            observation=observation,
            action=action,
            reward=reward,
            corrupted=is_corrupted,
        )
        _replay_transition(state, record["transition"], feedback=feedback)
        position += 1
    if position != len(ledger):
        raise EvaluationError("ledger has unexpected trailing records")
    invalidated = tuple(state["invalidated"])
    active = tuple(
        event["event_digest"]
        for event in state["events"]
        if event["event_digest"] not in invalidated
    )
    total_reward = sum(
        float(event["reward"])
        for event in state["events"]
        if event["event_digest"] in active
    )
    return QualificationSummary(
        "QUALIFICATION_ONLY",
        False,
        False,
        str(arm_id),
        _plan_digest(plan),
        len(plan.public_steps),
        total_reward,
        len(ledger),
        len(plan.public_steps),
        len(active),
        1,
        active,
        invalidated,
    )


def _checked_record(ledger, position, kind, turn, arm_id) -> dict[str, object]:
    if position >= len(ledger):
        raise EvaluationError("ledger record deleted")
    record = ledger[position]
    if set(record) != _RECORD_FIELDS:
        raise EvaluationError("ledger record fields invalid")
    if (
        record["sequence"] != position
        or record["kind"] != kind
        or record["arm_id"] != arm_id
    ):
        raise EvaluationError("ledger order or kind invalid")
    if record["turn"] != turn or record["cost"] != 1:
        raise EvaluationError("ledger turn or cost invalid")
    return record


def _replay_transition(
    state: dict[str, Any],
    transition: object,
    *,
    feedback: dict[str, object] | None = None,
    correction: str | None = None,
) -> None:
    try:
        apply_transition_batch(
            state,
            transition,
            expected_version=state["version"],
            max_operations=1,
            authoritative_feedback=feedback,
            authorized_correction=correction,
        )
    except ProtocolError as exc:
        raise EvaluationError("ledger transition invalid") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--arm", choices=("candidate", "baseline"), required=True)
    args = parser.parse_args(argv)
    completed = run_hidden_plan(build_hidden_plan(args.seed), args.arm)
    sys.stdout.write(json.dumps(completed.summary._asdict(), sort_keys=True))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
