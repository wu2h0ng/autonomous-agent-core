#!/usr/bin/env python3
"""Executable acceptance harness for the ADR-0061 Form B probes that need children.

What this is
------------
``docs/reviews/ADR-0061-C6-C7-PRESERVATION-REVIEW-2026-09-19.md`` (PR #95) is an
adversarial review of the frozen ``agent.spawn`` design. It ended with P1-P14, a
list of falsifiable probes, and the honest note that **not one of them was ever
executed**. P1, P2 and P8 can be run against the base commit and are pinned as
real tests in ``tests/product/test_agent_spawn_baseline_pins.py``. The seven
probes here -- P3, P4, P5, P6, P7, P12, P13 -- need child sessions to exist, so
they cannot be tests yet: a test that can never run is worse than no test, and
this repository bounds its skip count for exactly that reason.

So they live here, deliberately invoked, and they **fail loudly**: a probe whose
prerequisite is absent reports ``BLOCKED`` with a named reason and the process
exits non-zero. Nothing here passes silently.

How a kernel author runs it
---------------------------
From the repository root, after landing the kernel::

    uv run --extra product-test python scripts/agent_spawn_probe_harness.py --selftest
    uv run --extra product-test python scripts/agent_spawn_probe_harness.py --list
    uv run --extra product-test python scripts/agent_spawn_probe_harness.py
    uv run --extra product-test python scripts/agent_spawn_probe_harness.py --probe P3 --keep

Exit codes: ``0`` every selected probe PASSED; ``1`` at least one FAILED (the
kernel is present and a probe found the thing it attacks); ``2`` at least one
BLOCKED (the prerequisite is absent -- read the named reason).

Run ``--selftest`` FIRST. It drives this harness's own plumbing against the base
commit -- the contract round-trip, the planning provider, the durable-record
readers, the daemon start/crash/restart path -- and it needs no Form B. Without
it, "everything BLOCKED" is indistinguishable from a harness that would crash the
moment the kernel lands.

What to expect on the frozen contract commit (PR #96)
----------------------------------------------------
Every probe reports BLOCKED, and the reason names a real prerequisite rather than
an absence of effort. Verified on ``af797932``: ``agent.spawn`` is in none of the
three tables the review's A6 requires (``permission_gate.ACTION_RISK_TIERS``,
``agent_loop.CHAT_CAPABILITY_IDS``, ``agent_loop.CHAT_GRANT_MAX_RISK_TIERS``), the
capability registry has no spec for it, **and** neither child-agent event can be
appended: ``TaskAggregate._apply`` (``task_aggregate.py:447-467``) ends in
``raise EventStreamError("unsupported task event")`` and its no-state-transition
allowlist does not contain ``CHILD_AGENT_SPAWNED``/``CHILD_AGENT_FINISHED``, so
the contract PR declared both event types without wiring the aggregate that
rehydrates them. The kernel must fix that before any probe here can return
anything but BLOCKED.

The probes drive the kernel only through
----------------------------------------
* the frozen contract module ``agent_os_contracts.agent_spawn`` -- the spawn
  command, the typed statuses, the digest-only durable payloads and the
  ``ChildAgentLink`` fields are all validated through it, never re-typed here;
* an ordinary provider tool proposal whose ``capability_id`` is
  :data:`AGENT_SPAWN_CAPABILITY_ID` and whose arguments are exactly
  ``ChildAgentSpawnCommand.model_dump()``;
* the ordinary loop/surface entry points and the durable event store.

Nothing here reaches into kernel internals, so the harness does not have to be
rewritten when the kernel is. If the kernel chose a different argument shape or a
spawn path that is not a capability proposal, every probe FAILS with the reason
-- which is the correct outcome, because Form B is specified as a capability on
the single dispatch path (review C3/D1).

Hard rules honoured here
------------------------
* every probe uses a fresh temp directory for its database, workspace and (for
  P6) the runtime descriptor;
* P6's stub provider binds port 0 (an ephemeral port);
* ``~/.agent-os/`` is never read or written -- P6 always passes ``--descriptor``,
  and every other probe passes an explicit ``--database``/``--workspace``;
* every daemon this harness starts is killed in a ``finally`` block, and
  ``--keep`` only stops the temp tree from being deleted (never the process).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

from agent_os_contracts import (  # noqa: E402
    SURFACE_PROTOCOL_VERSION,
    ProviderMessageRole,
    ProviderToolProposal,
    SurfaceBeginTurnCommand,
    SurfaceClientRef,
    SurfaceStreamBinding,
    TaskEventDraft,
    TaskEventType,
)
from agent_os_contracts.agent_spawn import (  # noqa: E402
    AGENT_SPAWN_CAPABILITY_ID,
    DEFAULT_MAX_CHILDREN_IN_FLIGHT,
    EXPLORE_ALLOWED_CAPABILITY_IDS,
    ChildAgentFinished,
    ChildAgentLink,
    ChildAgentSpawnCommand,
    ChildAgentSpawned,
    ChildAgentStatus,
    ChildAgentType,
)
from agent_os_core import (  # noqa: E402
    DeferredApprovalGateway,
    DeterministicProvider,
    SQLiteTaskEventStore,
)
from apps.api_server.app import AgentOSApplication  # noqa: E402

# --- outcomes -----------------------------------------------------------------

PASS = "PASS"
FAIL = "FAIL"
BLOCKED = "BLOCKED"

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_BLOCKED = 2


class ProbeBlocked(Exception):
    """A probe whose prerequisite is absent. Never a silent pass."""


@dataclass(frozen=True)
class ProbeResult:
    probe_id: str
    outcome: str
    detail: str
    observations: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.outcome == PASS


@dataclass(frozen=True)
class ProbeSpec:
    probe_id: str
    title: str
    attacks: str
    command: str
    expected_if_safe: str
    falsifier: str
    requires: str
    run: Callable[[Path, argparse.Namespace], ProbeResult]


# --- shared plumbing ----------------------------------------------------------


def _harden_process_env() -> Path:
    """Point every provider-side path at a fresh temp tree before any app exists.

    Same discipline the governed suite's ``conftest.py`` applies: the harness must
    never read or write the operator's ``~/.agent-os/`` config, pricing file or OS
    keychain. Set once, at process start, and inherited by every daemon subprocess
    the harness starts.
    """

    root = Path(tempfile.mkdtemp(prefix="agent-spawn-harness-env-"))
    os.environ["AGENT_OS_DISABLE_KEYCHAIN"] = "1"
    os.environ["AGENT_OS_PROVIDER_CONFIG"] = str(root / "provider.json")
    os.environ["AGENT_OS_PRICING_FILE"] = str(root / "pricing.json")
    return root


def _app(root: Path) -> AgentOSApplication:
    root.mkdir(parents=True, exist_ok=True)
    (root / "workspace").mkdir(parents=True, exist_ok=True)
    app = AgentOSApplication(
        database=root / "agent-os.sqlite3",
        workspace=root / "workspace",
    )
    app.provider_configured = True
    return app


_CHILD_RECORD_BLOCKER: list[str] = []


def _child_record_write_blocker() -> str | None:
    """Whether the two child-agent records can be appended durably at all.

    Behavioural, on a throwaway app with its own temp database, so it neither
    needs Form B nor pollutes the probe's store. On the frozen contract commit
    (PR #96) both event types are declared in ``TaskEventType`` but
    ``TaskAggregate._apply`` has no arm for them, so ``task_service.append_event``
    rehydrates, hits the final `raise EventStreamError("unsupported task event")`
    and the write never lands. That is a hard prerequisite for every probe here,
    so it is named rather than discovered later.
    """

    if _CHILD_RECORD_BLOCKER:
        return _CHILD_RECORD_BLOCKER[0] or None
    root = Path(tempfile.mkdtemp(prefix="agent-spawn-harness-aggregate-"))
    try:
        app = _app(root)
        try:
            session, _loop = app.open_chat_session(
                "harness: aggregate probe", DeferredApprovalGateway()
            )
        except Exception as exc:
            message = (
                "the composition root cannot open a chat session at all, so the "
                f"child-agent records cannot be probed: {type(exc).__name__}: {exc}"
            )
            _CHILD_RECORD_BLOCKER.append(message)
            return message
        record = ChildAgentSpawned(
            spawn_id="spawn-aggregate-probe",
            parent_session_id=session.session_id,
            parent_turn_id="turn-aggregate-probe",
            child_session_id="session-probe-child",
            child_task_id="task-probe-child",
            agent_type=ChildAgentType.GENERAL,
            description="aggregate probe",
            prompt_digest="0" * 64,
        )
        try:
            app.tasks.append_event(
                session.task_id,
                TaskEventType.CHILD_AGENT_SPAWNED,
                record.model_dump(mode="json"),
                correlation_id=session.run_id,
            )
        except Exception as exc:
            message = (
                "the task service cannot durably append "
                f"CHILD_AGENT_SPAWNED: {type(exc).__name__}: {exc}. The two "
                "child-agent event types are declared in TaskEventType but "
                "TaskAggregate._apply has no arm for them, so a child spawn or "
                "completion cannot be recorded at all. Add them to the "
                "no-state-transition audit-marker set (task_aggregate.py:447-463) or "
                "give them a real state transition, and re-run this harness."
            )
            _CHILD_RECORD_BLOCKER.append(message)
            return message
        _CHILD_RECORD_BLOCKER.append("")
        return None
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _kernel_blocker(app: AgentOSApplication) -> str | None:
    """Why Form B cannot be driven yet, or None when it can.

    Every blocker is collected and reported together rather than one at a time:
    the kernel author needs the whole list, and a partial list invites the belief
    that the next fix will be the last one.
    """

    from agent_os_core import agent_loop, permission_gate

    blockers: list[str] = []

    registration: list[str] = []
    if AGENT_SPAWN_CAPABILITY_ID not in permission_gate.ACTION_RISK_TIERS:
        registration.append("permission_gate.ACTION_RISK_TIERS (the frozen E2 table)")
    if AGENT_SPAWN_CAPABILITY_ID not in agent_loop.CHAT_CAPABILITY_IDS:
        registration.append("agent_loop.CHAT_CAPABILITY_IDS")
    if AGENT_SPAWN_CAPABILITY_ID not in agent_loop.CHAT_GRANT_MAX_RISK_TIERS:
        registration.append("agent_loop.CHAT_GRANT_MAX_RISK_TIERS")
    if registration:
        blockers.append(
            f"{AGENT_SPAWN_CAPABILITY_ID} is not registered in: "
            + "; ".join(registration)
        )
    else:
        specs = app.sandbox.specs(include_internal=True)
        if AGENT_SPAWN_CAPABILITY_ID not in specs:
            blockers.append(
                "the capability registry exposes no "
                f"{AGENT_SPAWN_CAPABILITY_ID} CapabilitySpec, so the broker would "
                "refuse the dispatch (capability.py:_lookup_spec)"
            )
        else:
            try:
                session, _loop = app.open_chat_session(
                    "harness: probe", DeferredApprovalGateway()
                )
                _ = session
            except Exception as exc:
                blockers.append(
                    "the composition root cannot open a chat session with "
                    f"{AGENT_SPAWN_CAPABILITY_ID} granted: {type(exc).__name__}: {exc}"
                )

    aggregate = _child_record_write_blocker()
    if aggregate is not None:
        blockers.append(aggregate)

    if not blockers:
        return None
    return (
        "Form B cannot be driven through the capability path yet. "
        + " | ".join(f"({index}) {text}" for index, text in enumerate(blockers, 1))
    )


def _require_kernel(app: AgentOSApplication) -> None:
    blocker = _kernel_blocker(app)
    if blocker is not None:
        raise ProbeBlocked(blocker)


def _spawn_proposal(
    call_id: str,
    *,
    prompt: str,
    description: str,
    agent_type: ChildAgentType = ChildAgentType.GENERAL,
    max_steps: int | None = None,
) -> ProviderToolProposal:
    """One ``agent.spawn`` capability proposal carrying the frozen command."""

    command = ChildAgentSpawnCommand(
        prompt=prompt,
        description=description,
        agent_type=agent_type,
        max_steps=max_steps,
    )
    return ProviderToolProposal(
        proposal_id=call_id,
        capability_id=AGENT_SPAWN_CAPABILITY_ID,
        arguments_json=json.dumps(
            command.model_dump(mode="json", exclude_none=True),
            sort_keys=True,
        ),
    )


def _proposal(
    call_id: str, capability_id: str, arguments: dict[str, Any]
) -> ProviderToolProposal:
    return ProviderToolProposal(
        proposal_id=call_id,
        capability_id=capability_id,
        arguments_json=json.dumps(arguments, sort_keys=True),
    )


class _PlannedProvider(DeterministicProvider):
    """Scripted provider keyed by task, with a fallback rule for children.

    A synchronous spawn turns one parent turn into several provider calls with an
    interleaving between the parent and its children that the harness cannot know
    in advance. Keying the plan on ``request.task_id`` removes that guesswork for
    the parent, and the spawn contract makes the child's FIRST user message the
    spawn prompt -- which the harness chose -- so a content rule covers every
    child and grandchild.
    """

    def __init__(
        self,
        *,
        invocation_binding: Any,
        task_plans: dict[str, list[tuple[str, tuple[ProviderToolProposal, ...]]]],
        prompt_rules: Sequence[
            tuple[str, Callable[[str], list[tuple[str, tuple[ProviderToolProposal, ...]]]]]
        ] = (),
        default_text: str = "harness: nothing further to do",
    ) -> None:
        super().__init__(invocation_binding=invocation_binding)
        self._plans = {key: list(value) for key, value in task_plans.items()}
        self._prompt_rules = list(prompt_rules)
        self._built: dict[str, list[Any]] = {}
        self._default_text = default_text
        self._first_user: dict[str, str] = {}

    def set_task_plan(
        self,
        task_id: str,
        plan: Sequence[tuple[str, tuple[ProviderToolProposal, ...]]],
    ) -> None:
        self._plans[task_id] = list(plan)

    def _response(self, request: Any) -> Any:
        plan = self._plans.get(request.task_id)
        if plan is None:
            plan = self._built.get(request.task_id)
            if plan is None:
                first_user = next(
                    (
                        message.content
                        for message in request.messages
                        if message.role is ProviderMessageRole.USER
                    ),
                    "",
                )
                self._first_user[request.task_id] = first_user
                plan = []
                for marker, builder in self._prompt_rules:
                    if marker in first_user:
                        plan = list(builder(first_user))
                        break
                self._built[request.task_id] = plan
        if plan:
            text, proposals = plan.pop(0)
        else:
            text, proposals = self._default_text, ()
        self.text = text
        self.tool_proposals = tuple(proposals)
        return super()._response(request)


class _SlowChildProvider(_PlannedProvider):
    """A provider that stalls any call whose messages carry the child's marker.

    P13 needs a child turn that outlives the parent run's execution-lease TTL. The
    stall is keyed on the spawn prompt the harness chose, so it lands on the child
    and never on the parent's own calls.
    """

    def __init__(
        self,
        *,
        invocation_binding: Any,
        slow_marker: str,
        sleep_seconds: float,
    ) -> None:
        super().__init__(
            invocation_binding=invocation_binding,
            task_plans={},
            default_text="harness: slow child done",
        )
        self._slow_marker = slow_marker
        self._sleep_seconds = sleep_seconds

    def _response(self, request: Any) -> Any:
        if self._slow_marker in json.dumps(
            [message.content for message in request.messages]
        ):
            time.sleep(self._sleep_seconds)
        return super()._response(request)


def _events(app: AgentOSApplication, task_id: str) -> list[Any]:
    return list(app.store.read(task_id))


def _events_of(app: AgentOSApplication, task_id: str, event_type: TaskEventType) -> list[Any]:
    return [event for event in _events(app, task_id) if event.event_type is event_type]


def _payloads_of(
    app: AgentOSApplication, task_id: str, event_type: TaskEventType
) -> list[dict[str, Any]]:
    return [json.loads(event.payload_json) for event in _events_of(app, task_id, event_type)]


def _all_payloads(app: AgentOSApplication, event_type: TaskEventType) -> list[dict[str, Any]]:
    """Every payload of one event type, across every task stream in the store."""

    found: list[dict[str, Any]] = []
    for task_id in app.store.list_task_ids():
        found.extend(_payloads_of(app, task_id, event_type))
    return found


def _spawned_children(app: AgentOSApplication) -> list[ChildAgentSpawned]:
    """Parse every durable ``CHILD_AGENT_SPAWNED`` payload with the frozen model.

    The harness deliberately does not prescribe which stream carries the record;
    it requires only that the record exists and validates as
    :class:`ChildAgentSpawned`, which is the frozen durable contract.
    """

    children: list[ChildAgentSpawned] = []
    for payload in _all_payloads(app, TaskEventType.CHILD_AGENT_SPAWNED):
        children.append(ChildAgentSpawned.model_validate(payload))
    return children


def _finished_children(app: AgentOSApplication) -> list[dict[str, Any]]:
    return _all_payloads(app, TaskEventType.CHILD_AGENT_FINISHED)


def _receipts(app: AgentOSApplication, task_id: str) -> list[dict[str, Any]]:
    return _payloads_of(app, task_id, TaskEventType.ACTION_RECEIPT_RECORDED)


def _decisions(app: AgentOSApplication, task_id: str) -> list[dict[str, Any]]:
    return [
        payload["decision"]
        for payload in _payloads_of(app, task_id, TaskEventType.POLICY_DECIDED)
        if isinstance(payload.get("decision"), dict)
    ]


def _one_child(app: AgentOSApplication, *, description: str) -> ChildAgentSpawned:
    children = _spawned_children(app)
    matches = [child for child in children if child.description == description]
    if len(matches) != 1:
        raise AssertionError(
            f"expected exactly one CHILD_AGENT_SPAWNED with description "
            f"{description!r}, found {len(matches)} of {len(children)} total. "
            "The frozen durable model requires CHILD_AGENT_SPAWNED to carry the "
            "ChildAgentSpawned payload (agent_spawn.py:182-196)."
        )
    return matches[0]


def _spawn_parent(
    app: AgentOSApplication,
    *,
    prompt: str,
    description: str,
    agent_type: ChildAgentType = ChildAgentType.GENERAL,
    call_id: str = "call-harness-spawn",
) -> Any:
    """Drive one parent turn that proposes exactly one ``agent.spawn``."""

    session, loop = app.open_chat_session("harness: parent", DeferredApprovalGateway())
    provider = app.provider
    assert isinstance(provider, _PlannedProvider)
    provider.set_task_plan(
        session.task_id,
        [
            ("", (_spawn_proposal(
                call_id,
                prompt=prompt,
                description=description,
                agent_type=agent_type,
            ),)),
            ("harness: parent turn done", ()),
        ],
    )
    result = loop.run_turn(session, "harness: spawn one child")
    return session, result


# --- P3 -----------------------------------------------------------------------


def _probe_p3(workdir: Path, options: argparse.Namespace) -> ProbeResult:
    """An ``explore`` child must not reach the write tier by asking directly."""

    prompt = "harness:p3:explore-child read the workspace"
    target = "harness-p3-target.txt"
    if "workspace.apply_patch" in EXPLORE_ALLOWED_CAPABILITY_IDS:
        raise ProbeBlocked(
            "the frozen contract's own read-only subset lists workspace.apply_patch, "
            "so P3's premise does not hold and the probe must not be read as a pass"
        )
    app = _app(workdir)
    _require_kernel(app)
    (workdir / "workspace" / target).write_text("original\n", encoding="utf-8")

    app.provider = _PlannedProvider(
        invocation_binding=app.provider.invocation_binding,
        task_plans={},
        prompt_rules=[(prompt, lambda _first: [("harness: child read only", ())])],
    )

    parent_session, parent_result = _spawn_parent(
        app,
        prompt=prompt,
        description="p3 explore child",
        agent_type=ChildAgentType.EXPLORE,
    )
    child = _one_child(app, description="p3 explore child")
    observations = [
        f"parent turn stop_reason={parent_result.stop_reason!r}",
        f"child agent_type={child.agent_type.value!r} child_session_id={child.child_session_id!r}",
    ]
    if child.agent_type is not ChildAgentType.EXPLORE:
        return ProbeResult(
            "P3",
            FAIL,
            "the durable CHILD_AGENT_SPAWNED record does not carry "
            f"agent_type=explore but {child.agent_type.value!r}",
            tuple(observations),
        )

    # Inject the write tier straight into a provider proposal, bypassing tool
    # advertising entirely: permission_gate consults the global E2 table only, so
    # a type-confused child would be adapted by the kernel's own gate.
    inject = _PlannedProvider(
        invocation_binding=app.provider.invocation_binding,
        task_plans={
            child.child_task_id: [
                (
                    "",
                    (
                        _proposal(
                            "call-p3-write",
                            "workspace.apply_patch",
                            {"path": target, "content": "overwritten\n"},
                        ),
                    ),
                ),
                ("harness: child write attempt done", ()),
            ]
        },
    )
    app.provider = inject
    child_session, child_loop = app.restore_chat_session(
        child.child_session_id, DeferredApprovalGateway()
    )
    try:
        child_result = child_loop.run_turn(child_session, "harness: write the file")
    except Exception as exc:  # a typed refusal raised out of the loop is accepted
        child_result = exc
    observations.append(f"child write turn outcome={type(child_result).__name__}")

    receipts = [
        receipt
        for receipt in _receipts(app, child.child_task_id)
        if _receipt_capability(receipt) == "workspace.apply_patch"
    ]
    # Two independent denial records exist in this spine and both are accepted as
    # proof of refusal: the E2 permission-gate record (POLICY_VERDICT_RECORDED,
    # which carries capability_id and basis=out_of_allowlist) and the authority
    # kernel's own decision (POLICY_DECIDED, whose payload carries reason_codes).
    gate_denials = [
        payload
        for payload in _payloads_of(
            app, child.child_task_id, TaskEventType.POLICY_VERDICT_RECORDED
        )
        if payload.get("capability_id") == "workspace.apply_patch"
        and payload.get("verdict") != "ALLOW"
    ]
    kernel_denials = [
        decision
        for decision in _decisions(app, child.child_task_id)
        if decision.get("verdict") != "ALLOW" and decision.get("reason_codes")
    ]
    content = (workdir / "workspace" / target).read_text(encoding="utf-8")
    observations.append(
        f"workspace.apply_patch receipts={len(receipts)} "
        f"gate denials={len(gate_denials)} kernel denials={len(kernel_denials)}"
    )
    observations.append(f"target file after the attempt={content!r}")

    if receipts:
        return ProbeResult(
            "P3",
            FAIL,
            "an explore child executed workspace.apply_patch: the child's agent type "
            "is not enforced at an execution point, only at the model's tool "
            "advertising. A denial must exist as a typed durable record and there "
            "must be no receipt.",
            tuple(observations),
        )
    if content != "original\n":
        return ProbeResult(
            "P3",
            FAIL,
            "the target file changed even though no receipt was recorded for the write",
            tuple(observations),
        )
    if not gate_denials and not kernel_denials:
        return ProbeResult(
            "P3",
            FAIL,
            "no receipt and no effect, but also no typed denial for "
            "workspace.apply_patch on the child's stream: the refusal (if any) is "
            "not recorded where the operator can see it",
            tuple(observations),
        )
    if gate_denials:
        observations.append(
            f"gate denial basis={gate_denials[0].get('basis')!r} "
            f"reason={gate_denials[0].get('reason')!r}"
        )
    if kernel_denials:
        observations.append(
            f"kernel denial reason_codes={kernel_denials[0].get('reason_codes')!r}"
        )
    return ProbeResult(
        "P3",
        PASS,
        "the explore child's workspace.apply_patch was refused at an execution "
        "point and recorded as a typed denial, with no receipt and no effect",
        tuple(observations),
    )


def _receipt_capability(receipt: dict[str, Any]) -> str | None:
    decision = receipt.get("decision")
    if isinstance(decision, dict):
        capability_id = decision.get("capability_id")
        if isinstance(capability_id, str):
            return capability_id
    inner = receipt.get("receipt")
    if isinstance(inner, dict) and isinstance(inner.get("connector_id"), str):
        return inner["connector_id"]
    return None


# --- P4 -----------------------------------------------------------------------


def _probe_p4(workdir: Path, options: argparse.Namespace) -> ProbeResult:
    """N bounds each parent turn's in-flight children, not the size of the tree."""

    raw_bound = os.environ.get("AGENT_OS_MAX_CHILD_AGENTS", "").strip()
    try:
        fan_out = int(raw_bound) if raw_bound else DEFAULT_MAX_CHILDREN_IN_FLIGHT
    except ValueError:
        raise ProbeBlocked(
            f"AGENT_OS_MAX_CHILD_AGENTS={raw_bound!r} is not an integer, and the "
            "frozen contract raises rather than guessing "
            "(agent_spawn.py:ChildAgentFanOutConfig.from_env)"
        ) from None
    if fan_out < 1:
        raise ProbeBlocked(
            f"AGENT_OS_MAX_CHILD_AGENTS={fan_out} is below the frozen floor of 1"
        )
    marker_depth1 = "harness:p4:depth1"
    marker_depth2 = "harness:p4:depth2"

    app = _app(workdir)
    _require_kernel(app)
    if not _nested_spawn_enabled(app):
        raise ProbeBlocked(
            "P4 needs nested spawns enabled through an authorized action before a "
            "depth-2 tree can exist. The harness found no way to enable them: "
            f"{AGENT_SPAWN_CAPABILITY_ID} is (correctly) not granted to a general "
            "child by default, and the harness refuses to enable it through an "
            "environment variable -- review E3 requires nested-spawn enablement to "
            "be an authorized, durable, re-tightenable action, not process env. "
            "Give the kernel an operator-facing way to enable nested spawns and "
            "record it in the harness."
        )

    def _depth2_plan() -> list[Any]:
        """A depth-1 child spawns `fan_out` grandchildren, then finishes."""

        return [
            (
                "",
                tuple(
                    _spawn_proposal(
                        f"call-harness-{marker_depth2}-{index}",
                        prompt=f"{marker_depth2} grandchild {index}",
                        description=f"{marker_depth2} grandchild {index}",
                    )
                    for index in range(fan_out)
                ),
            ),
            ("harness: grandchildren spawned", ()),
        ]

    app.provider = _PlannedProvider(
        invocation_binding=app.provider.invocation_binding,
        task_plans={},
        # Only depth-1 children match this marker; a grandchild's first message
        # carries marker_depth2, so it falls through to a plain completion.
        prompt_rules=[(marker_depth1, lambda _first: _depth2_plan())],
    )

    session, loop = app.open_chat_session("harness: p4 parent", DeferredApprovalGateway())
    provider = app.provider
    assert isinstance(provider, _PlannedProvider)
    provider.set_task_plan(
        session.task_id,
        [
            (
                "",
                tuple(
                    _spawn_proposal(
                        f"call-harness-{marker_depth1}-{index}",
                        prompt=f"{marker_depth1} child {index}",
                        description=f"{marker_depth1} child {index}",
                    )
                    for index in range(fan_out)
                ),
            ),
            ("harness: depth-1 children spawned", ()),
        ],
    )
    loop.run_turn(session, "harness: spawn the depth-1 fan-out")

    spawned = _spawned_children(app)
    by_parent_turn: dict[str, int] = {}
    for child in spawned:
        by_parent_turn[child.parent_turn_id] = by_parent_turn.get(child.parent_turn_id, 0) + 1
    heaviest = max(by_parent_turn.values(), default=0)
    depth1 = [child for child in spawned if child.description.startswith(marker_depth1)]
    depth2 = [child for child in spawned if child.description.startswith(marker_depth2)]
    observations = [
        f"fan-out bound N={fan_out} (DEFAULT_MAX_CHILDREN_IN_FLIGHT="
        f"{DEFAULT_MAX_CHILDREN_IN_FLIGHT})",
        f"children spawned in total={len(spawned)} "
        f"(depth-1={len(depth1)}, depth-2={len(depth2)})",
        f"heaviest parent turn holds {heaviest} children in flight",
        f"tree total against N**d (N={fan_out}, d=2) = {fan_out * fan_out}",
    ]
    if not spawned:
        return ProbeResult(
            "P4",
            FAIL,
            "the parent turn produced no CHILD_AGENT_SPAWNED record at all",
            tuple(observations),
        )
    if heaviest > fan_out:
        return ProbeResult(
            "P4",
            FAIL,
            f"a single parent turn spawned {heaviest} children with the bound at "
            f"{fan_out}: the bound is not enforced per parent turn",
            tuple(observations),
        )
    if not depth2:
        return ProbeResult(
            "P4",
            FAIL,
            "no depth-2 children exist, so the probe did not exercise the nested "
            "case it exists to pin: N's quantifier ('per parent turn') can only be "
            "shown to under-bound the tree while a grandchild layer exists",
            tuple(observations),
        )
    return ProbeResult(
        "P4",
        PASS,
        "no parent turn exceeded N in flight, and a depth-2 tree exists. The "
        "observed totals above are the point: N bounds concurrency per parent turn "
        "only, NOT the number of children, tokens, cost or wall clock -- a depth-d "
        "tree with per-layer fan-out N can hold N**d children without violating N "
        "(review E2). The ADR must state that bound explicitly.",
        tuple(observations),
    )


def _nested_spawn_enabled(app: AgentOSApplication) -> bool:
    """Whether a general child may hold ``agent.spawn``.

    Read from the only place the base contract exposes it: the loop's per-type
    capability set is kernel-owned, so the harness looks for a documented,
    authorized switch on the application rather than guessing.
    """

    for attribute in ("nested_spawn_enabled", "child_agent_nested_spawn_enabled"):
        value = getattr(app, attribute, None)
        if isinstance(value, bool):
            return value
    return False


# --- P5 -----------------------------------------------------------------------


def _probe_p5(workdir: Path, options: argparse.Namespace) -> ProbeResult:
    """The parent turn's token accounting must see what its children consumed."""

    control_root = workdir / "control"
    spawn_root = workdir / "spawn"
    child_text = " ".join(f"token{i}" for i in range(400))
    prompt = "harness:p5:heavy-child"

    control = _app(control_root)
    blocker = _kernel_blocker(control)
    if blocker is not None:
        raise ProbeBlocked(blocker)
    control.provider = _PlannedProvider(
        invocation_binding=control.provider.invocation_binding,
        task_plans={},
        default_text="harness: control turn done",
    )
    control_session, control_loop = control.open_chat_session(
        "harness: control", DeferredApprovalGateway()
    )
    control_result = control_loop.run_turn(control_session, "harness: control turn")

    app = _app(spawn_root)
    app.provider = _PlannedProvider(
        invocation_binding=app.provider.invocation_binding,
        task_plans={},
        prompt_rules=[(prompt, lambda _first: [(child_text, ())])],
    )
    _session, parent_result = _spawn_parent(
        app,
        prompt=prompt,
        description="p5 heavy child",
    )

    observations = [
        f"control parent turn total_tokens={control_result.total_tokens}",
        f"spawn parent turn total_tokens={parent_result.total_tokens}",
        f"child completion text words={len(child_text.split())}",
    ]
    if parent_result.total_tokens <= control_result.total_tokens:
        return ProbeResult(
            "P5",
            FAIL,
            "the parent turn that spawned a heavy child reported no more tokens than "
            "the control turn: the child's consumption is invisible to the parent's "
            "accounting. ChildAgentTurnAttribution (agent_spawn.py:260-297) pins "
            "'children_included_in_totals' and validates the totals against the child "
            "rows, so a projection that excludes children cannot even be constructed "
            "-- the kernel must feed it real child usage.",
            tuple(observations),
        )
    return ProbeResult(
        "P5",
        PASS,
        "the parent turn's token total grew with the child's consumption, so the "
        "child's usage reaches the parent's accounting. NOTE: this is accounting, "
        "not necessarily budget ENFORCEMENT -- AgentLoopConfig.max_turn_tokens is "
        "per loop and the child has its own, so review E4's 'parent's remaining "
        "budget' still has no runtime object unless the kernel adds one. Report "
        "which of the two the ADR claims.",
        tuple(observations),
    )


# --- P6 -----------------------------------------------------------------------


class _StubProviderHandler(BaseHTTPRequestHandler):
    """OpenAI-compatible stub: spawn on the parent marker, hang on the child marker."""

    spawn_marker = ""
    hang_marker = ""
    spawn_arguments: dict[str, Any] = {}
    children_started = 0

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        messages = body.get("messages") or []
        joined = json.dumps(messages)
        message: dict[str, Any] = {"role": "assistant", "content": "stub: done"}
        if self.hang_marker and self.hang_marker in joined:
            type(self).children_started += 1
            time.sleep(60.0)
        elif self.spawn_marker and self.spawn_marker in joined:
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-harness-spawn",
                        "type": "function",
                        "function": {
                            "name": AGENT_SPAWN_CAPABILITY_ID.replace(".", "__"),
                            "arguments": json.dumps(self.spawn_arguments),
                        },
                    }
                ],
            }
        payload = {
            "id": "cmpl-harness",
            "choices": [{"message": message, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 4, "total_tokens": 8},
        }
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return


class _StubProvider:
    def __init__(self, *, spawn_marker: str, hang_marker: str, spawn_arguments: dict) -> None:
        _StubProviderHandler.spawn_marker = spawn_marker
        _StubProviderHandler.hang_marker = hang_marker
        _StubProviderHandler.spawn_arguments = spawn_arguments
        _StubProviderHandler.children_started = 0
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _StubProviderHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class _Daemon:
    def __init__(self, process: subprocess.Popen, descriptor_path: Path) -> None:
        self.process = process
        self.descriptor_path = descriptor_path
        self.crashed = False

    def crash(self) -> None:
        """SIGKILL the whole process group: transient state must die with it."""

        self.crashed = True
        if self.process.poll() is None:
            try:
                os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                self.process.kill()
        self.process.wait(timeout=10)

    def stop(self) -> None:
        if self.process.poll() is None:
            try:
                os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                self.process.terminate()
        try:
            self.process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)


def _daemon_env(provider_url: str) -> dict[str, str]:
    env = dict(os.environ)
    env["AGENT_OS_PROVIDER_BASE_URL"] = provider_url
    env["AGENT_OS_PROVIDER_MODEL"] = "harness-stub-model"
    env["OPENAI_API_KEY"] = "harness-stub-key"
    # Never let the daemon fall back to the operator's real store or keychain.
    env["AGENT_OS_DISABLE_KEYCHAIN"] = "1"
    env["PYTHONPATH"] = os.pathsep.join(
        [
            str(REPO_ROOT),
            str(REPO_ROOT / "src"),
            str(REPO_ROOT / "packages" / "contracts" / "src"),
            str(REPO_ROOT / "packages" / "os_core" / "src"),
        ]
    )
    return env


def _start_daemon(
    root: Path, provider_url: str, *, index: int
) -> _Daemon:
    (root / "workspace").mkdir(parents=True, exist_ok=True)
    descriptor = root / f"runtime-{index}.json"
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "apps.runtime_daemon",
            "--database",
            str(root / "agent-os.sqlite3"),
            "--workspace",
            str(root / "workspace"),
            "--descriptor",
            str(descriptor),
            "--host",
            "127.0.0.1",
            "--port",
            "0",
        ],
        start_new_session=True,
        env=_daemon_env(provider_url),
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    daemon = _Daemon(process, descriptor)
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise ProbeBlocked(
                "the runtime daemon exited before publishing a descriptor, so the "
                "crash probe cannot run"
            )
        if descriptor.exists():
            return daemon
        time.sleep(0.05)
    daemon.stop()
    raise ProbeBlocked("the runtime daemon did not publish a descriptor within 30s")


def _read_task_events(database: Path, task_id: str) -> list[Any]:
    store = SQLiteTaskEventStore(database)
    try:
        return list(store.read(task_id))
    finally:
        close = getattr(store, "close", None)
        if callable(close):
            close()


def _db_payloads(database: Path, event_type: TaskEventType) -> list[dict[str, Any]]:
    """Every payload of one event type in the database, from every task stream.

    P6 reads the store directly (the daemon is down at each read), and it does not
    prescribe which stream carries the child-agent records -- only that they exist
    and validate against the frozen contract.
    """

    found: list[dict[str, Any]] = []
    store = SQLiteTaskEventStore(database)
    try:
        for task_id in store.list_task_ids():
            for event in store.read(task_id):
                if event.event_type is event_type:
                    found.append(json.loads(event.payload_json))
    finally:
        close = getattr(store, "close", None)
        if callable(close):
            close()
    return found


def _db_child_task_id(database: Path) -> str:
    payloads = _db_payloads(database, TaskEventType.CHILD_AGENT_SPAWNED)
    if not payloads:
        return ""
    child = ChildAgentSpawned.model_validate(payloads[0])
    return child.child_task_id


def _probe_p6(workdir: Path, options: argparse.Namespace) -> ProbeResult:
    """A crash mid-child-turn must be reaped, not left in flight forever."""

    database = workdir / "agent-os.sqlite3"
    spawn_marker = "harness:p6:spawn"
    hang_marker = "harness:p6:child-hangs"
    spawn_arguments = ChildAgentSpawnCommand(
        prompt=hang_marker,
        description="p6 child",
    ).model_dump(mode="json", exclude_none=True)

    blocker_app = _app(workdir)
    blocker = _kernel_blocker(blocker_app)
    if blocker is not None:
        raise ProbeBlocked(blocker)

    from apps.cli.surface_client import SurfaceClient
    from apps.runtime_daemon.descriptor import load_runtime_descriptor

    provider = _StubProvider(
        spawn_marker=spawn_marker,
        hang_marker=hang_marker,
        spawn_arguments=spawn_arguments,
    )
    first: _Daemon | None = None
    second: _Daemon | None = None
    try:
        first = _start_daemon(workdir, provider.url, index=1)
        client = SurfaceClient(load_runtime_descriptor(first.descriptor_path))
        opened = client.open_session(
            statement=f"harness {spawn_marker}", idempotency_key="harness:p6:open:1"
        )
        session_id = opened.session.session_id
        subscription = client.subscribe_stream(session_id)
        client.begin_turn(
            SurfaceBeginTurnCommand(
                protocol_version=SURFACE_PROTOCOL_VERSION,
                client=SurfaceClientRef(
                    client_id="harness",
                    client_type="CLI",
                    principal_id="user:local",
                    tenant_id="tenant:local",
                    workspace_id="workspace:local",
                    device_id="device:harness",
                ),
                session_id=session_id,
                text=f"harness {spawn_marker} a child that hangs",
                stream=SurfaceStreamBinding(
                    runtime_boot_id=subscription.runtime_boot_id,
                    stream_id=subscription.stream_id,
                ),
                expected_event_sequence=opened.event_sequence,
                idempotency_key="harness:p6:turn:1",
                requested_at=datetime.now(timezone.utc),
            )
        )

        # Wait until the child exists AND is inside its hanging provider call.
        deadline = time.monotonic() + 60.0
        child_task_id = ""
        while time.monotonic() < deadline:
            if _StubProviderHandler.children_started:
                try:
                    child_task_id = _db_child_task_id(database)
                except Exception:
                    child_task_id = ""
                if child_task_id:
                    break
            time.sleep(0.1)
        if not child_task_id:
            raise ProbeBlocked(
                "the parent turn never produced a durable CHILD_AGENT_SPAWNED "
                "record within 60s, so there was no child turn to crash mid-flight"
            )

        first.crash()
        first = None
        before = _read_task_events(database, child_task_id)
        started_before = {
            json.loads(event.payload_json).get("turn_id")
            for event in before
            if event.event_type is TaskEventType.SESSION_TURN_STARTED
        }
        completed_before = {
            json.loads(event.payload_json).get("turn_id")
            for event in before
            if event.event_type is TaskEventType.SESSION_TURN_COMPLETED
        }
        observations = [
            f"child task={child_task_id}",
            f"child turns started={(started_before or set())}",
            f"child turns completed={(completed_before or set())}",
        ]
        if not started_before:
            raise ProbeBlocked(
                "the child session recorded no SESSION_TURN_STARTED before the crash, "
                "so the crash did not land inside a child turn; re-run the probe"
            )

        second = _start_daemon(workdir, provider.url, index=2)
        time.sleep(5.0)
        after = _read_task_events(database, child_task_id)
    finally:
        for daemon in (first, second):
            if daemon is not None:
                daemon.stop()
        provider.close()

    spawned_payloads = _db_payloads(database, TaskEventType.CHILD_AGENT_SPAWNED)
    finished_payloads = _db_payloads(database, TaskEventType.CHILD_AGENT_FINISHED)
    spawn_ids = {payload.get("spawn_id") for payload in spawned_payloads}
    finished_ids = {payload.get("spawn_id") for payload in finished_payloads}
    unreaped = spawn_ids - finished_ids
    observations.append(f"child spawn_ids={sorted(str(value) for value in spawn_ids)}")
    observations.append(f"reaped spawn_ids={sorted(str(value) for value in finished_ids)}")
    observations.append(f"child events after restart={len(after)}")

    if not finished_payloads:
        return ProbeResult(
            "P6",
            FAIL,
            "after a SIGKILL mid-child-turn and a restart there is no "
            "CHILD_AGENT_FINISHED record for the child. The child session is left "
            "with a turn that started and never completed, no component re-drives "
            "it, and nothing reaps it: the parent roll-up shows an in-flight child "
            "for ever (review G4). Nothing in the durable model is commit-time, so "
            "an operator has no way to tell 'still running' from 'was killed'.",
            tuple(observations),
        )
    if unreaped:
        return ProbeResult(
            "P6",
            FAIL,
            f"children {sorted(unreaped)} were spawned and never reaped after the "
            "crash",
            tuple(observations),
        )
    status = finished_payloads[0].get("status")
    stop_reason = finished_payloads[0].get("stop_reason")
    observations.append(f"terminal status={status!r} stop_reason={stop_reason!r}")
    if status == ChildAgentStatus.COMPLETED.value:
        return ProbeResult(
            "P6",
            FAIL,
            "the crashed child was recorded as 'completed'; it provably did not "
            "complete, so the terminal status is not authoritative",
            tuple(observations),
        )
    if not stop_reason:
        return ProbeResult(
            "P6",
            FAIL,
            "the crashed child has a terminal record with no stop_reason, so the "
            "operator cannot tell a runtime death from an operator stop",
            tuple(observations),
        )
    return ProbeResult(
        "P6",
        PASS,
        "every spawned child has a terminal record after a mid-turn SIGKILL and the "
        "restart, the record is not 'completed', and it names a stop reason",
        tuple(observations),
    )


# --- P7 -----------------------------------------------------------------------


def _probe_p7(workdir: Path, options: argparse.Namespace) -> ProbeResult:
    """'No prompt or completion TEXT in a durable record' is an event-level claim."""

    sentinel = "HARNESS-P7-PLAINTEXT-SENTINEL-9f3a1c"
    prompt = f"harness:p7 {sentinel} read the workspace"
    app = _app(workdir)
    _require_kernel(app)
    app.provider = _PlannedProvider(
        invocation_binding=app.provider.invocation_binding,
        task_plans={},
        prompt_rules=[(sentinel, lambda _first: [("harness: child said something", ())])],
    )
    _spawn_parent(app, prompt=prompt, description="p7 child")

    session_payloads = _all_payloads(app, TaskEventType.SESSION_MESSAGE_RECORDED)
    session_hits = [
        payload
        for payload in session_payloads
        if sentinel in json.dumps(payload)
    ]
    child_payloads = _all_payloads(
        app, TaskEventType.CHILD_AGENT_SPAWNED
    ) + _all_payloads(app, TaskEventType.CHILD_AGENT_FINISHED)
    child_hits = [payload for payload in child_payloads if sentinel in json.dumps(payload)]

    database = workdir / "agent-os.sqlite3"
    raw_hit = sentinel.encode() in database.read_bytes() if database.exists() else False

    observations = [
        f"SESSION_MESSAGE_RECORDED payloads carrying the spawn prompt={len(session_hits)} "
        f"of {len(session_payloads)}",
        f"CHILD_AGENT_* payloads carrying the spawn prompt={len(child_hits)} "
        f"of {len(child_payloads)}",
        f"spawn prompt present in the raw database bytes={raw_hit}",
    ]
    if child_hits:
        return ProbeResult(
            "P7",
            FAIL,
            "a CHILD_AGENT_SPAWNED/CHILD_AGENT_FINISHED payload carries the spawn "
            "prompt TEXT. The frozen module docstring says the events carry "
            "prompt_digest/summary_digest only (agent_spawn.py:38-48), and a durable "
            "event that carries the text is worse than the review's F3 finding.",
            tuple(observations),
        )
    if not session_hits:
        return ProbeResult(
            "P7",
            FAIL,
            "the spawn prompt is nowhere in the durable session stream, so the "
            "digest-only events are the only record. Re-run after checking the "
            "child really received its prompt: a child spawned without a durable "
            "prompt message contradicts F1/H4 (a child's actions must be "
            "attributable and its input reconstructable).",
            tuple(observations),
        )
    return ProbeResult(
        "P7",
        PASS,
        "the two child-agent events are digest-only, AND the spawn prompt is stored "
        "verbatim in SESSION_MESSAGE_RECORDED. Read that second fact against "
        "agent_spawn.py:38-48 -- 'No prompt or completion TEXT is ever carried by a "
        "durable record' is written as a system-level claim and is FALSE as written; "
        "it holds only for the two child-agent events (review F3). Either narrow the "
        "sentence or stop claiming it.",
        tuple(observations),
    )


# --- P12 ----------------------------------------------------------------------


def _probe_p12(workdir: Path, options: argparse.Namespace) -> ProbeResult:
    """'stopped' means no further effects, not that an UNKNOWN becomes clean."""

    prompt = "harness:p12:child"
    app = _app(workdir)
    _require_kernel(app)
    target = "harness-p12-target.txt"
    (workdir / "workspace").mkdir(parents=True, exist_ok=True)
    (workdir / "workspace" / target).write_text("original\n", encoding="utf-8")

    app.provider = _PlannedProvider(
        invocation_binding=app.provider.invocation_binding,
        task_plans={},
        prompt_rules=[(prompt, lambda _first: [("harness: child idle", ())])],
    )
    _spawn_parent(app, prompt=prompt, description="p12 child")
    child = _one_child(app, description="p12 child")

    connector = app.sandbox
    original_execute = getattr(connector, "execute", None)
    if original_execute is None or not callable(original_execute):
        raise ProbeBlocked(
            "the composition root's connector exposes no execute() to fault-inject, "
            "so an UNKNOWN receipt cannot be produced from the harness"
        )
    faults: list[str] = []

    def _faulty_execute(action: Any) -> Any:
        faults.append(str(getattr(action, "capability_id", "?")))
        raise RuntimeError("harness: injected post-dispatch fault")

    try:
        connector.execute = _faulty_execute  # type: ignore[method-assign]
    except Exception as exc:  # pragma: no cover - defensive
        raise ProbeBlocked(
            f"the connector cannot be fault-injected ({type(exc).__name__}: {exc})"
        ) from exc

    app.provider = _PlannedProvider(
        invocation_binding=app.provider.invocation_binding,
        task_plans={
            child.child_task_id: [
                (
                    "",
                    (_proposal("call-p12-read", "workspace.read", {"path": target}),),
                ),
                ("harness: child read attempted", ()),
            ]
        },
    )
    child_session, child_loop = app.restore_chat_session(
        child.child_session_id, DeferredApprovalGateway()
    )
    try:
        child_loop.run_turn(child_session, "harness: read the file")
    except Exception:
        pass

    receipts_before = _receipts(app, child.child_task_id)
    unknown = [
        receipt
        for receipt in receipts_before
        if _receipt_status(receipt) == "UNKNOWN"
    ]
    observations = [
        f"injected faults={faults}",
        f"child receipts={[(_receipt_capability(r), _receipt_status(r)) for r in receipts_before]}",
    ]
    if not faults:
        raise ProbeBlocked(
            "the child never executed a capability, so no UNKNOWN receipt could be "
            "produced; the probe cannot test the stop semantics"
        )
    if not unknown:
        return ProbeResult(
            "P12",
            FAIL,
            "the faulted dispatch produced no UNKNOWN receipt. A post-dispatch "
            "failure must be a typed UNKNOWN (ADR-0059, _action_outcome.py), because "
            "'we do not know whether the effect happened' is a different state from "
            "'it failed'.",
            tuple(observations),
        )

    # Operator stops the child, then nothing may rewrite the unknown.
    app.correct_task(child.child_task_id, "harness: stop the child")
    time.sleep(0.2)
    receipts_after = _receipts(app, child.child_task_id)
    unknown_after = [
        receipt for receipt in receipts_after if _receipt_status(receipt) == "UNKNOWN"
    ]
    compensations = [
        receipt
        for receipt in receipts_after
        if _receipt_capability(receipt) == "workspace.compensate_patch"
    ]
    observations.append(
        f"after the operator stop: receipts={len(receipts_after)} unknown={len(unknown_after)} "
        f"compensations={len(compensations)} faults={len(faults)}"
    )
    if len(unknown_after) != len(unknown):
        return ProbeResult(
            "P12",
            FAIL,
            "the operator stop changed an UNKNOWN receipt's status; an unknown must "
            "stay unknown (ReceiptStatus.UNKNOWN, authority.py:51-58)",
            tuple(observations),
        )
    if compensations:
        return ProbeResult(
            "P12",
            FAIL,
            "stopping the child triggered an automatic compensation; compensation is "
            "a decided action, never automatic (ADR-0059)",
            tuple(observations),
        )
    if len(faults) != len(unknown):
        return ProbeResult(
            "P12",
            FAIL,
            "the child's action was re-dispatched after the fault (faults != unknown "
            "receipts): stopping a child must not resend an unknown effect",
            tuple(observations),
        )
    return ProbeResult(
        "P12",
        PASS,
        "the UNKNOWN receipt survived the operator stop unchanged, the effect was not "
        "re-dispatched and no compensation was auto-triggered. Invariant only: "
        "'stopped' does not mean 'no side effect happened' -- an effect dispatched "
        "before the stop still lands (C7-BOUNDARY-STATEMENT.md:19-23, review G3), and "
        "the operator-facing text must say so.",
        tuple(observations),
    )


def _receipt_status(receipt: dict[str, Any]) -> str | None:
    inner = receipt.get("receipt")
    if isinstance(inner, dict) and isinstance(inner.get("status"), str):
        return inner["status"]
    return None


# --- P13 ----------------------------------------------------------------------


def _probe_p13(workdir: Path, options: argparse.Namespace) -> ProbeResult:
    """A child turn can outlive the parent run's 5-minute execution lease."""

    if not options.allow_slow:
        raise ProbeBlocked(
            "P13 needs a child turn that outlives the parent run's execution-lease "
            "TTL, whose default is 5 minutes and is not injectable through the app "
            "composition (agent_os_core/_action_outcome.py:92 "
            "'ttl: timedelta = timedelta(minutes=5)'). Re-run with --allow-slow to "
            "spend the real wall clock, or expose a TTL injection point and record it "
            "in this harness. The deterministic half of this question -- whether an "
            "expired lease can be reclaimed and whether a stale lease can reserve -- "
            "is already pinned in tests/product/test_agent_spawn_baseline_pins.py."
        )

    prompt = "harness:p13:slow-child"
    app = _app(workdir)
    _require_kernel(app)
    lease = getattr(app.sandbox, "acquire_execution_lease", None)
    if not callable(lease):
        raise ProbeBlocked(
            "the connector exposes no acquire_execution_lease, so the harness cannot "
            "observe the parent run's lease fence"
        )

    ttl_seconds = 300.0
    sleep_for = ttl_seconds + 30.0
    app.provider = _SlowChildProvider(
        invocation_binding=app.provider.invocation_binding,
        slow_marker=prompt,
        sleep_seconds=sleep_for,
    )
    started = time.monotonic()
    _session, parent_result = _spawn_parent(
        app, prompt=prompt, description="p13 slow child"
    )
    elapsed = time.monotonic() - started

    receipts = _receipts(app, _session.task_id)
    spawn_receipts = [
        receipt
        for receipt in receipts
        if _receipt_capability(receipt) == AGENT_SPAWN_CAPABILITY_ID
    ]
    observations = [
        f"child turn duration={elapsed:.1f}s against a {ttl_seconds:.0f}s lease TTL",
        f"parent turn stop_reason={parent_result.stop_reason!r}",
        f"agent.spawn receipts={[(_receipt_capability(r), _receipt_status(r)) for r in spawn_receipts]}",
    ]
    if elapsed <= ttl_seconds:
        return ProbeResult(
            "P13",
            FAIL,
            "the child turn finished before the lease TTL elapsed, so the probe did "
            "not test anything. Raise the stub child's duration above the TTL.",
            tuple(observations),
        )
    if not spawn_receipts:
        return ProbeResult(
            "P13",
            FAIL,
            "the parent's agent.spawn produced no receipt even though the parent turn "
            "returned; without a receipt the outcome of an over-TTL spawn is unrecorded",
            tuple(observations),
        )
    statuses = {_receipt_status(receipt) for receipt in spawn_receipts}
    if "UNKNOWN" in statuses:
        return ProbeResult(
            "P13",
            PASS,
            "the parent's agent.spawn receipt is UNKNOWN after the lease TTL passed, "
            "which is the fail-closed answer: the effect's fate is not claimed. "
            "Confirm the operator can still see the child session and its turn.",
            tuple(observations),
        )
    return ProbeResult(
        "P13",
        PASS,
        f"the parent's agent.spawn sealed as {sorted(statuses)} after its run's lease "
        "had expired (seal does not recheck fence or expiry, "
        "_action_outcome.py:243-297). That is not a duplicate-effect hole -- the "
        "reservation, not the lease, is the interlock, and a reservation without an "
        "outcome replays as typed UNKNOWN -- but the ADR must say that a spawn "
        "outliving its lease is expected rather than silently impossible.",
        tuple(observations),
    )


# --- self-test -----------------------------------------------------------------
# A harness that reports BLOCKED for everything has proved nothing about itself.
# These checks drive the harness's own plumbing -- the contract round-trip, the
# planning provider, the prompt rule and the whole daemon start/crash/restart/read
# path -- WITHOUT Form B, so a BLOCKED probe is a real blocker rather than a
# broken harness. They need no kernel and no wall clock.


def _client_ref() -> SurfaceClientRef:
    return SurfaceClientRef(
        client_id="harness",
        client_type="CLI",
        principal_id="user:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        device_id="device:harness",
    )


def _selfcheck_contract_roundtrip(workdir: Path) -> str:
    proposal = _spawn_proposal(
        "call-selftest",
        prompt="harness selftest prompt",
        description="selftest child",
        agent_type=ChildAgentType.EXPLORE,
    )
    assert proposal.capability_id == AGENT_SPAWN_CAPABILITY_ID
    parsed = ChildAgentSpawnCommand.model_validate_json(proposal.arguments_json)
    assert parsed.agent_type is ChildAgentType.EXPLORE
    assert parsed.prompt == "harness selftest prompt"
    assert parsed.description == "selftest child"
    spawned = ChildAgentSpawned(
        spawn_id="spawn-selftest",
        parent_session_id="session-parent",
        parent_turn_id="turn-parent",
        child_session_id="session-child",
        child_task_id="task-child",
        agent_type=ChildAgentType.EXPLORE,
        description="selftest child",
        prompt_digest="0" * 64,
    )
    link = ChildAgentLink.from_spawned(spawned)
    assert set(link.event_link_fields()) == {
        "parent_session_id",
        "parent_turn_id",
        "spawn_id",
    }
    return (
        "the spawn proposal's arguments round-trip through ChildAgentSpawnCommand, "
        "and the frozen durable models construct"
    )


def _selfcheck_planned_provider(workdir: Path) -> str:
    app = _app(workdir)
    target = "selftest.txt"
    (workdir / "workspace" / target).write_text("stable\n", encoding="utf-8")
    app.provider = _PlannedProvider(
        invocation_binding=app.provider.invocation_binding,
        task_plans={},
    )
    session, loop = app.open_chat_session("harness selftest", DeferredApprovalGateway())
    provider = app.provider
    assert isinstance(provider, _PlannedProvider)
    provider.set_task_plan(
        session.task_id,
        [
            ("", (_proposal("call-selftest-read", "workspace.read", {"path": target}),)),
            ("selftest read done", ()),
        ],
    )
    result = loop.run_turn(session, "harness selftest read")
    receipts = _receipts(app, session.task_id)
    assert receipts, "the planned provider delivered no capability proposal"
    assert result.stop_reason == "completed", (
        f"the planned turn did not complete: stop_reason={result.stop_reason!r}"
    )
    return (
        f"a task-keyed plan drove one workspace.read to a receipt and the turn "
        f"completed (receipts={len(receipts)})"
    )


def _selfcheck_prompt_rule(workdir: Path) -> str:
    app = _app(workdir)
    target = "selftest-rule.txt"
    (workdir / "workspace" / target).write_text("stable\n", encoding="utf-8")
    marker = "harness-selftest-rule-marker"
    app.provider = _PlannedProvider(
        invocation_binding=app.provider.invocation_binding,
        task_plans={},
        prompt_rules=[
            (
                marker,
                lambda _first: [
                    (
                        "",
                        (
                            _proposal(
                                "call-selftest-rule", "workspace.read", {"path": target}
                            ),
                        ),
                    ),
                    ("selftest rule done", ()),
                ],
            )
        ],
    )
    session, loop = app.open_chat_session("harness selftest rule", DeferredApprovalGateway())
    loop.run_turn(session, f"harness {marker} read the file")
    receipts = _receipts(app, session.task_id)
    assert receipts, (
        "the prompt rule did not fire: a child task the harness does not know by id "
        "would receive no plan, so every child-driven probe would silently do nothing"
    )
    return "a prompt-marker rule drove a proposal for a task the harness never named"


def _selfcheck_child_record_parsing(workdir: Path) -> str:
    """The durable-record readers every child-driven probe depends on.

    ``_spawned_children`` and ``_finished_children`` are how P3, P4, P6, P7 and
    P12 find their subject. This writes both frozen records through the real store
    and reads them back through the real parsers, so a payload-shape change breaks
    the harness loudly instead of silently starving a probe.
    """

    app = _app(workdir)
    session, _loop = app.open_chat_session(
        "harness selftest record", DeferredApprovalGateway()
    )
    spawned = ChildAgentSpawned(
        spawn_id="spawn-selftest",
        parent_session_id=session.session_id,
        parent_turn_id="turn-selftest",
        child_session_id="session-child",
        child_task_id="task-child",
        agent_type=ChildAgentType.GENERAL,
        description="selftest child",
        prompt_digest="0" * 64,
    )
    finished = ChildAgentFinished(
        spawn_id="spawn-selftest",
        status=ChildAgentStatus.FAILED,
        steps=1,
        tokens=2,
        stop_reason="harness_selftest",
        summary_digest="1" * 64,
    )
    # Appended straight to the event store: the harness's READ path is what is
    # under test here. The kernel's WRITE path (task_service) is a separate
    # self-check below, because on the frozen contract commit it is not wired yet.
    existing = _events(app, session.task_id)
    sequence = existing[-1].sequence if existing else 0
    app.store.append(
        session.task_id,
        expected_sequence=sequence,
        drafts=(
            TaskEventDraft(
                event_id="harness-selftest-spawned",
                task_id=session.task_id,
                event_type=TaskEventType.CHILD_AGENT_SPAWNED,
                payload_json=spawned.model_dump_json(),
                occurred_at=datetime.now(timezone.utc),
                correlation_id=session.run_id,
            ),
            TaskEventDraft(
                event_id="harness-selftest-finished",
                task_id=session.task_id,
                event_type=TaskEventType.CHILD_AGENT_FINISHED,
                payload_json=finished.model_dump_json(),
                occurred_at=datetime.now(timezone.utc),
                correlation_id=session.run_id,
            ),
        ),
    )

    children = _spawned_children(app)
    assert len(children) == 1, f"expected one spawn record, read {len(children)}"
    assert children[0].child_task_id == "task-child"
    assert children[0].agent_type is ChildAgentType.GENERAL
    finals = _finished_children(app)
    assert len(finals) == 1 and finals[0]["status"] == ChildAgentStatus.FAILED.value
    assert _one_child(app, description="selftest child").spawn_id == "spawn-selftest"

    # The receipt readers P3 and P12 judge on.
    sample = {
        "receipt": {"connector_id": "workspace.read", "status": "UNKNOWN"},
        "decision": {"action_id": "action-selftest"},
    }
    assert _receipt_capability(sample) == "workspace.read"
    assert _receipt_status(sample) == "UNKNOWN"
    return (
        "CHILD_AGENT_SPAWNED/CHILD_AGENT_FINISHED round-trip through a real SQLite "
        "store into the frozen models, and the receipt readers resolve connector id "
        "and status"
    )


def _selfcheck_child_record_write_path(workdir: Path) -> str:
    """Whether the task service can append the two child-agent records at all.

    This is the write half of the durable model. The harness's readers are checked
    above through the store; this checks the path the KERNEL must use
    (``task_service.append_event``), and reports what it finds either way.
    """

    blocker = _child_record_write_blocker()
    if blocker is not None:
        return f"REPOSITORY GAP (not a harness failure): {blocker}"
    return "task_service.append_event accepts CHILD_AGENT_SPAWNED"


def _selfcheck_daemon_plumbing(workdir: Path) -> str:
    root = workdir / "daemon"
    root.mkdir(parents=True, exist_ok=True)
    database = root / "agent-os.sqlite3"
    hang_marker = "harness-selftest-hang"
    provider = _StubProvider(
        spawn_marker="",
        hang_marker=hang_marker,
        spawn_arguments={},
    )
    from apps.cli.surface_client import SurfaceClient
    from apps.runtime_daemon.descriptor import load_runtime_descriptor

    first: _Daemon | None = None
    second: _Daemon | None = None
    try:
        first = _start_daemon(root, provider.url, index=1)
        client = SurfaceClient(load_runtime_descriptor(first.descriptor_path))
        opened = client.open_session(
            statement="harness selftest", idempotency_key="harness:selftest:open"
        )
        session_id = opened.session.session_id
        task_id = opened.session.task_id
        subscription = client.subscribe_stream(session_id)
        client.begin_turn(
            SurfaceBeginTurnCommand(
                protocol_version=SURFACE_PROTOCOL_VERSION,
                client=_client_ref(),
                session_id=session_id,
                text=f"harness {hang_marker} stall",
                stream=SurfaceStreamBinding(
                    runtime_boot_id=subscription.runtime_boot_id,
                    stream_id=subscription.stream_id,
                ),
                expected_event_sequence=opened.event_sequence,
                idempotency_key="harness:selftest:turn",
                requested_at=datetime.now(timezone.utc),
            )
        )
        deadline = time.monotonic() + 60.0
        started = False
        while time.monotonic() < deadline:
            events = _read_task_events(database, task_id)
            started = any(
                event.event_type is TaskEventType.SESSION_TURN_STARTED
                for event in events
            )
            if started:
                break
            time.sleep(0.1)
        assert started, "the daemon never recorded SESSION_TURN_STARTED"

        first.crash()
        first = None
        events = _read_task_events(database, task_id)
        started_ids = {
            json.loads(event.payload_json).get("turn_id")
            for event in events
            if event.event_type is TaskEventType.SESSION_TURN_STARTED
        }
        completed_ids = {
            json.loads(event.payload_json).get("turn_id")
            for event in events
            if event.event_type is TaskEventType.SESSION_TURN_COMPLETED
        }
        assert started_ids and started_ids.isdisjoint(completed_ids), (
            "the crashed turn is not in the expected started-without-completed state"
        )

        second = _start_daemon(root, provider.url, index=2)
        time.sleep(3.0)
        restarted = _read_task_events(database, task_id)
        assert restarted, "no durable events were readable after the restart"
    finally:
        for daemon in (first, second):
            if daemon is not None:
                daemon.stop()
        provider.close()
    return (
        "the daemon started on an ephemeral port with a temp descriptor/database/"
        "workspace, a turn was killed mid-flight with SIGKILL, and the durable store "
        "was readable before and after the restart"
    )


SELFCHECKS: tuple[tuple[str, Callable[[Path], str]], ...] = (
    ("contract round-trip", _selfcheck_contract_roundtrip),
    ("planned provider", _selfcheck_planned_provider),
    ("prompt-marker rule", _selfcheck_prompt_rule),
    ("child-record readers", _selfcheck_child_record_parsing),
    ("child-record write path", _selfcheck_child_record_write_path),
    ("daemon crash/restart plumbing", _selfcheck_daemon_plumbing),
)


def _run_selftest(options: argparse.Namespace) -> int:
    failures: list[str] = []
    for name, check in SELFCHECKS:
        workdir = Path(tempfile.mkdtemp(prefix="agent-spawn-harness-selftest-"))
        try:
            try:
                detail = check(workdir)
            except Exception as exc:
                failures.append(name)
                print(
                    f"FAIL  {name}: {type(exc).__name__}: {exc}\n"
                    + "".join(traceback.format_exc())
                )
            else:
                print(f"PASS  {name}: {detail}")
        finally:
            if options.keep:
                print(f"      kept: {workdir}")
            else:
                shutil.rmtree(workdir, ignore_errors=True)
    if failures:
        print(
            f"\nSUMMARY: {len(SELFCHECKS) - len(failures)}/{len(SELFCHECKS)} self-checks "
            f"passed. The harness itself is broken ({failures}); a BLOCKED probe "
            "result cannot be trusted until these pass."
        )
        return EXIT_FAILED
    print(
        f"\nSUMMARY: all {len(SELFCHECKS)} self-checks passed. A probe that reports "
        "BLOCKED is reporting a real absent prerequisite, not a broken harness."
    )
    return EXIT_OK


# --- registry -----------------------------------------------------------------


PROBES: tuple[ProbeSpec, ...] = (
    ProbeSpec(
        probe_id="P3",
        title="explore child enforcement point (review A5)",
        attacks=(
            "An explore child is restricted by tool ADVERTISING only. A child whose "
            "context was poisoned emits workspace.apply_patch directly; the loop "
            "checks the global CHAT_CAPABILITY_IDS and the gate checks the global "
            "ACTION_RISK_TIERS, and both admit it. Under ACCEPT_IN_WORKSPACE it is "
            "then auto-allowed with no human in the loop."
        ),
        command=(
            "uv run --extra product-test python scripts/agent_spawn_probe_harness.py "
            "--probe P3"
        ),
        expected_if_safe=(
            "The child's workspace.apply_patch is refused at an execution-level "
            "enforcement point (not the tool list), recorded as a typed denial on the "
            "child's own stream, with no ACTION_RECEIPT_RECORDED and no file change."
        ),
        falsifier=(
            "A receipt for workspace.apply_patch on the child's task, or a changed "
            "file, or a silent refusal with no durable denial."
        ),
        requires="Form B kernel (agent.spawn registered and dispatchable)",
        run=_probe_p3,
    ),
    ProbeSpec(
        probe_id="P4",
        title="the fan-out bound's real quantifier (review E2)",
        attacks=(
            "N bounds 'at most N children in flight per parent turn'. A depth-d tree "
            "with per-layer fan-out N holds N**d children while no layer breaks N, so "
            "an operator reading 'at most N children' is misled about total tokens, "
            "cost and wall clock."
        ),
        command=(
            "uv run --extra product-test python scripts/agent_spawn_probe_harness.py "
            "--probe P4"
        ),
        expected_if_safe=(
            "No parent turn ever holds more than N children in flight, AND the "
            "observed total tree size is reported so the ADR can state what N does "
            "NOT bound."
        ),
        falsifier=(
            "Any single parent turn with more than N children in flight."
        ),
        requires="Form B kernel + an authorized way to enable nested spawns",
        run=_probe_p4,
    ),
    ProbeSpec(
        probe_id="P5",
        title="whether a child's tokens reach the parent's budget (review E4)",
        attacks=(
            "'budget_limit(child) <= parent's remaining budget' names a quantity that "
            "does not exist: CapabilityGrant.budget_limit is a static ceiling, "
            "ResourceBudget.fits_within is a static comparison, and srl_budget_ledger "
            "is not a capability cost ledger. A child that burns tokens may be "
            "invisible to the parent turn's accounting."
        ),
        command=(
            "uv run --extra product-test python scripts/agent_spawn_probe_harness.py "
            "--probe P5"
        ),
        expected_if_safe=(
            "The parent turn that spawned a heavy child reports strictly more tokens "
            "than the identical control turn without a child, so child consumption "
            "reaches the parent's accounting."
        ),
        falsifier=(
            "The parent turn's token total is unchanged by the child's consumption."
        ),
        requires="Form B kernel",
        run=_probe_p5,
    ),
    ProbeSpec(
        probe_id="P6",
        title="reaping an in-flight child after a runtime death (review G4/G5/E1)",
        attacks=(
            "SIGKILL the daemon mid-child-turn. The child is an in-process object, so "
            "it stops existing; nobody writes a terminal record, nobody closes its "
            "session, and the parent roll-up can show an in-flight child for ever. "
            "The single-session fix (recover from the durable boundary, never "
            "fabricate) does not compose, because no parent turn is waiting."
        ),
        command=(
            "uv run --extra product-test python scripts/agent_spawn_probe_harness.py "
            "--probe P6"
        ),
        expected_if_safe=(
            "After the restart every spawned child has a CHILD_AGENT_FINISHED record "
            "whose status is not 'completed' and whose stop_reason names the runtime "
            "death, so the roll-up holds no permanently in-flight child."
        ),
        falsifier=(
            "A spawned child with no terminal record after the restart, or a terminal "
            "record claiming 'completed', or a completed-without-stop_reason record."
        ),
        requires="Form B kernel + the runtime daemon (temp descriptor/db/workspace)",
        run=_probe_p6,
    ),
    ProbeSpec(
        probe_id="P7",
        title="the digest-only claim's real scope (review F3)",
        attacks=(
            "The frozen module says 'No prompt or completion TEXT is ever carried by a "
            "durable record'. A child is an ordinary session, so its spawn prompt is "
            "the first user message and lands verbatim in SESSION_MESSAGE_RECORDED. "
            "Read as a system-level privacy claim it is false; read as an event-level "
            "claim about the two child-agent events it holds."
        ),
        command=(
            "uv run --extra product-test python scripts/agent_spawn_probe_harness.py "
            "--probe P7"
        ),
        expected_if_safe=(
            "The CHILD_AGENT_SPAWNED/CHILD_AGENT_FINISHED payloads carry digests only, "
            "AND the spawn prompt is found verbatim in the durable session stream -- "
            "the second fact is what forces the docstring's wording to be narrowed."
        ),
        falsifier=(
            "The spawn prompt appears in a child-agent event payload (a real leak "
            "beyond the review's finding), or the prompt is nowhere durable (the child "
            "received input that cannot be reconstructed for attribution)."
        ),
        requires="Form B kernel",
        run=_probe_p7,
    ),
    ProbeSpec(
        probe_id="P12",
        title="what 'stopped' promises about side effects (review G3)",
        attacks=(
            "A child whose action ended UNKNOWN is stopped by the operator. If the "
            "stop rewrites the receipt, the operator reads 'stopped' as 'nothing "
            "happened' -- but the receipt is a pre-commit linearization token, not an "
            "interrupt, so an already-dispatched effect still lands."
        ),
        command=(
            "uv run --extra product-test python scripts/agent_spawn_probe_harness.py "
            "--probe P12"
        ),
        expected_if_safe=(
            "The UNKNOWN receipt is unchanged by the stop, the effect is not "
            "re-dispatched, and no compensation runs automatically."
        ),
        falsifier=(
            "The stop changes the receipt status, or the faulted action is "
            "re-dispatched, or a compensation is auto-triggered."
        ),
        requires="Form B kernel",
        run=_probe_p12,
    ),
    ProbeSpec(
        probe_id="P13",
        title="a child turn outliving the parent run's execution lease (review E5)",
        attacks=(
            "The parent's agent.spawn action holds the parent run's execution lease, "
            "default TTL 5 minutes. A synchronous child turn can exceed it, and seal "
            "does not recheck fence or expiry. Either the late seal is accepted (an "
            "expected state the ADR must name) or a second owner takes a larger fence "
            "and the effect is ambiguous."
        ),
        command=(
            "uv run --extra product-test python scripts/agent_spawn_probe_harness.py "
            "--probe P13 --allow-slow"
        ),
        expected_if_safe=(
            "The parent's agent.spawn either seals with a named status after its lease "
            "expired, or seals as UNKNOWN; in neither case is the effect dispatched "
            "twice."
        ),
        falsifier=(
            "Two effects for one agent.spawn action, or a parent turn that returns "
            "success while the spawn's outcome is unrecorded."
        ),
        requires=(
            "Form B kernel + ~5.5 minutes of wall clock (--allow-slow); blocked by "
            "name without it"
        ),
        run=_probe_p13,
    ),
)


# --- CLI ----------------------------------------------------------------------


def _format_table(specs: Sequence[ProbeSpec], results: Sequence[ProbeResult]) -> str:
    by_id = {result.probe_id: result for result in results}
    lines: list[str] = []
    for spec in specs:
        result = by_id.get(spec.probe_id)
        if result is None:
            continue
        lines.append(f"{result.outcome:<7} {spec.probe_id}  {spec.title}")
        lines.append(f"        attacks : {spec.attacks}")
        lines.append(f"        run     : {spec.command}")
        lines.append(f"        if safe : {spec.expected_if_safe}")
        lines.append(f"        falsify : {spec.falsifier}")
        lines.append(f"        needs   : {spec.requires}")
        lines.append(f"        result  : {result.detail}")
        for observation in result.observations:
            lines.append(f"        observed: {observation}")
        lines.append("")
    return "\n".join(lines)


def _select(specs: Sequence[ProbeSpec], requested: Sequence[str]) -> list[ProbeSpec]:
    if not requested:
        return list(specs)
    wanted = {value.strip().upper() for value in requested}
    known = {spec.probe_id for spec in specs}
    unknown = wanted - known
    if unknown:
        raise SystemExit(
            f"unknown probe id(s) {sorted(unknown)}; known: {sorted(known)}"
        )
    return [spec for spec in specs if spec.probe_id in wanted]


def _run_selected(
    specs: Sequence[ProbeSpec], options: argparse.Namespace
) -> list[ProbeResult]:
    """Run each probe, narrating progress on stderr so stdout stays parseable."""

    results: list[ProbeResult] = []
    for spec in specs:
        workdir = Path(tempfile.mkdtemp(prefix=f"agent-spawn-probe-{spec.probe_id}-"))
        print(f"=== {spec.probe_id}: {spec.title} ===", file=sys.stderr, flush=True)
        print(f"    workspace: {workdir}", file=sys.stderr, flush=True)
        try:
            try:
                result = spec.run(workdir, options)
            except ProbeBlocked as exc:
                result = ProbeResult(spec.probe_id, BLOCKED, str(exc))
            except Exception as exc:
                result = ProbeResult(
                    spec.probe_id,
                    FAIL,
                    f"the probe raised {type(exc).__name__}: {exc}\n"
                    + "".join(traceback.format_exc()),
                )
            results.append(result)
            print(f"    -> {result.outcome}: {result.detail}", file=sys.stderr, flush=True)
            for observation in result.observations:
                print(f"       observed: {observation}", file=sys.stderr, flush=True)
        finally:
            if options.keep:
                print(f"    kept: {workdir}", file=sys.stderr, flush=True)
            else:
                shutil.rmtree(workdir, ignore_errors=True)
    return results


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="agent_spawn_probe_harness",
        description=(
            "Executable acceptance harness for the ADR-0061 Form B probes that need "
            "child agents (P3, P4, P5, P6, P7, P12, P13)."
        ),
    )
    parser.add_argument(
        "--probe",
        action="append",
        default=[],
        help="run only these probes (repeatable), e.g. --probe P3 --probe P6",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="print every probe's attack, command, expected-if-safe and falsifier",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit machine-readable results on stdout instead of the table",
    )
    parser.add_argument(
        "--allow-slow",
        action="store_true",
        help="permit probes that need real wall clock (P13 spends ~5.5 minutes)",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="keep each probe's temp workspace for inspection",
    )
    parser.add_argument(
        "--selftest",
        action="store_true",
        help=(
            "check the harness's own plumbing (no Form B needed) before trusting a "
            "BLOCKED result"
        ),
    )
    options = parser.parse_args(argv)
    _harden_process_env()
    specs = _select(PROBES, options.probe)

    if options.selftest:
        return _run_selftest(options)

    if options.list:
        for spec in specs:
            print(f"{spec.probe_id}  {spec.title}")
            print(f"  attacks    : {spec.attacks}")
            print(f"  command    : {spec.command}")
            print(f"  if safe    : {spec.expected_if_safe}")
            print(f"  falsifier  : {spec.falsifier}")
            print(f"  requires   : {spec.requires}")
            print()
        return EXIT_OK

    results = _run_selected(specs, options)

    if options.json:
        print(
            json.dumps(
                [
                    {
                        "probe_id": result.probe_id,
                        "outcome": result.outcome,
                        "detail": result.detail,
                        "observations": list(result.observations),
                    }
                    for result in results
                ],
                indent=2,
            )
        )
    else:
        print()
        print(_format_table(specs, results))
        passed = sum(1 for result in results if result.outcome == PASS)
        blocked = [result.probe_id for result in results if result.outcome == BLOCKED]
        failed = [result.probe_id for result in results if result.outcome == FAIL]
        print(
            f"summary: {passed}/{len(results)} PASS"
            + (f" | FAIL {failed}" if failed else "")
            + (f" | BLOCKED {blocked}" if blocked else "")
        )
        if blocked:
            print(
                "A BLOCKED probe is not a pass: its prerequisite is absent. Read the "
                "named reason above."
            )

    if any(result.outcome == FAIL for result in results):
        return EXIT_FAILED
    if any(result.outcome == BLOCKED for result in results):
        return EXIT_BLOCKED
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
