"""Recorded/replay (cassette) offline arm for TERMINAL-CODING-EVAL-1.

This is the *gating* deterministic arm for the eval (founder ruling 6, 2026-09-19):
it drives the REAL product loop (AgentOSApplication -> AgentLoop -> CapabilityBroker)
through the real typed tool path, exactly like the Python `OfflineArm` plans, but the
provider responses come from a recorded JSON cassette on disk instead of from Python
plan objects. Nothing is fetched over the network and no provider key is read.

Why a separate arm when reference/null/mutant are already keyless? Those arms embed
the expected responses in code. A cassette arm makes the recorded responses a data
artifact: they are versioned as a fixture, can be regenerated from a real model run
without touching the harness, and the gate runs purely off that recorded series. The
live arm (E3_REAL_PROVIDER) stays opt-in and never enters the CI gate; this cassette
arm is the offline, deterministic, key-free substitute that does.

Cassette format (``.json``)::

    {
      "version": 1,
      "recorded_from": "reference",
      "tasks": {
        "<task_id>": [
          {"text": "...", "tool_calls": [["<capability_id>", {<args>}]]},
          {"kind": "derive_open_total", "text": "answer.txt holds the open total."}
        ]
      }
    }

A step with ``tool_calls`` replays those exact typed proposals. A step with
``kind: derive_open_total`` reads the most recent ``workspace.read`` result from the
tool history (the frozen ``inventory.csv``), sums the ``quantity`` column for rows
whose ``status`` is ``open``, and writes ``answer.txt`` -- the same derivation the
reference plan performs, recorded as a strategy rather than a magic number.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_os_contracts import ProviderRequest, ProviderResponse, ProviderToolProposal
from agent_os_core import DeterministicProvider

from .coding_solver import (
    PlanExhausted,
    _last_read_content,
    _quantity_total,
    _tool_results,
)
from .models import EvalTask


@dataclass(frozen=True)
class RecordedStep:
    """One recorded provider response for one loop turn."""

    text: str
    tool_calls: tuple[tuple[str, dict[str, object]], ...]
    derive_open_total: bool = False


@dataclass(frozen=True)
class Cassette:
    """A recorded, keyless provider response series keyed by task id."""

    version: int
    recorded_from: str
    tasks: Mapping[str, tuple[RecordedStep, ...]]

    @staticmethod
    def load(path: str | Path) -> "Cassette":
        raw = json.loads(Path(path).read_text("utf-8"))
        if raw.get("version") != 1:
            raise ValueError(f"unsupported cassette version: {raw.get('version')!r}")
        tasks: dict[str, tuple[RecordedStep, ...]] = {}
        for task_id, steps in raw["tasks"].items():
            parsed: list[RecordedStep] = []
            for step in steps:
                derive = step.get("kind") == "derive_open_total"
                tool_calls = tuple(
                    (str(cap), dict(args)) for cap, args in step.get("tool_calls", [])
                )
                parsed.append(
                    RecordedStep(
                        text=str(step.get("text", "")),
                        tool_calls=tool_calls,
                        derive_open_total=derive,
                    )
                )
            tasks[str(task_id)] = tuple(parsed)
        return Cassette(
            version=int(raw["version"]),
            recorded_from=str(raw.get("recorded_from", "unknown")),
            tasks=tasks,
        )

    def steps_for(self, task: EvalTask) -> tuple[RecordedStep, ...]:
        try:
            return self.tasks[task.task_id]
        except KeyError as exc:  # pragma: no cover - guarded by the test
            raise KeyError(
                f"cassette has no recorded steps for task {task.task_id!r}"
            ) from exc


class CassetteProvider(DeterministicProvider):
    """Replay a recorded JSON cassette through the real agent loop.

    Response bookkeeping (usage accounting and invocation-binding digest) is inherited
    from ``DeterministicProvider`` so the cassette arm produces the same event shapes
    the instrument already consumes; only the text and the proposed tool calls come
    from the recorded steps. If the loop asks for more steps than were recorded it
    raises ``PlanExhausted`` rather than fabricating a completion -- a stale cassette is
    an instrument defect and must be loud.
    """

    def __init__(
        self,
        steps: Sequence[RecordedStep],
        *,
        invocation_binding: Any,
        task_id: str,
    ) -> None:
        super().__init__(invocation_binding=invocation_binding)
        self._steps = tuple(steps)
        self._step_index = 0
        self._task_id = task_id

    @property
    def steps_used(self) -> int:
        return self._step_index

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        self.requests.append(request)
        if self._step_index >= len(self._steps):
            raise PlanExhausted(
                f"cassette exhausted after {self._step_index} steps "
                f"for task {request.task_id}"
            )
        step = self._steps[self._step_index]
        self._step_index += 1
        tool_results = _tool_results(request)
        if step.derive_open_total:
            csv_text = _last_read_content(tool_results)
            if not csv_text:
                raise PlanExhausted(
                    f"{request.task_id}: no workspace.read result to derive the open total"
                )
            total = _quantity_total(csv_text, only_status="open")
            proposals = (
                ProviderToolProposal(
                    proposal_id=f"{self._task_id}-s{self._step_index - 1}-c0",
                    capability_id="workspace.apply_patch",
                    arguments_json=json.dumps(
                        {"path": "answer.txt", "content": f"{total}\n"}, sort_keys=True
                    ),
                ),
            )
        else:
            proposals = tuple(
                ProviderToolProposal(
                    proposal_id=f"{self._task_id}-s{self._step_index - 1}-c{index}",
                    capability_id=cap,
                    arguments_json=json.dumps(args, sort_keys=True),
                )
                for index, (cap, args) in enumerate(step.tool_calls)
            )
        response = self._response(request)
        return response.model_copy(update={"text": step.text, "tool_proposals": proposals})
