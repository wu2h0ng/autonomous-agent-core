from __future__ import annotations

import argparse
import json
import sys
from typing import Any


def _exact(value: object, fields: set[str], label: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{label} exact fields required")
    return value


def _act(request: dict[str, object], arm_id: str) -> dict[str, object]:
    observation = _exact(
        request["observation"], {"features", "authorized_actions"}, "observation"
    )
    actions = observation["authorized_actions"]
    if (
        not isinstance(actions, list)
        or not actions
        or not all(isinstance(action, str) for action in actions)
    ):
        raise ValueError("authorized actions required")
    state = request["public_state"]
    if not isinstance(state, dict):
        raise ValueError("public state must be an object")
    events = state.get("events", [])
    invalidated = set(state.get("invalidated", []))
    if not isinstance(events, list):
        raise ValueError("public state events must be a list")
    relevant = [
        event
        for event in events
        if isinstance(event, dict)
        and event.get("event_digest") not in invalidated
        and isinstance(event.get("observation"), dict)
        and event["observation"].get("features") == observation["features"]
    ]
    if arm_id == "baseline":
        relevant = relevant[-4:]
    totals = {action: [0.0, 0] for action in actions}
    for event in relevant:
        action = event.get("action")
        reward = event.get("reward")
        if action in totals and isinstance(reward, (int, float)):
            totals[action][0] += float(reward)
            totals[action][1] += 1
    chosen = max(
        actions,
        key=lambda action: (
            totals[action][0] / totals[action][1] if totals[action][1] else 0.0,
            -actions.index(action),
        ),
    )
    return {
        "kind": "action_proposal",
        "state_version": request["state_version"],
        "action": chosen,
    }


def _transition(request: dict[str, object]) -> dict[str, object]:
    feedback = request["feedback"]
    if not isinstance(feedback, dict):
        raise ValueError("feedback/correction object required")
    if request["kind"] == "feedback":
        _exact(
            feedback,
            {"event_digest", "observation", "action", "reward", "corrupted"},
            "feedback",
        )
        operation = "record_feedback"
    elif request["kind"] == "correction":
        _exact(feedback, {"event_digest"}, "correction")
        operation = "invalidate_feedback"
    else:
        raise ValueError("unsupported transition request")
    return {
        "kind": "transition_batch",
        "state_version": request["state_version"],
        "operations": [{"op": operation, "event_digest": feedback["event_digest"]}],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--arm", choices=("candidate", "baseline"), required=True)
    args = parser.parse_args(argv)
    lines = sys.stdin.read().splitlines()
    if len(lines) != 1:
        raise ValueError("exactly one request line required")
    request: dict[str, Any] = _exact(
        json.loads(lines[0]),
        {"kind", "state_version", "public_state", "observation", "feedback"},
        "request",
    )
    response = (
        _act(request, args.arm) if request["kind"] == "act" else _transition(request)
    )
    sys.stdout.write(json.dumps(response, sort_keys=True, separators=(",", ":")))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
