"""Form B child-agent kernel spine: cascade, burial, bounds and attribution.

This module is the kernel half of ``agent.spawn`` (ADR-0061). It owns no
domain semantics and creates no session by itself; the composition root injects
a :class:`ChildAgentSpawnerPort`. What lives here is everything that has to be
the *same* for every child on every process generation:

* the durable index over ``CHILD_AGENT_SPAWNED`` / ``CHILD_AGENT_FINISHED`` and
  the ``child_agent`` block of a child session's ``SESSION_OPENED`` payload;
* the read-side C7 halt cascade (:class:`ChildAgentHaltCascade`);
* crash burial (:class:`ChildAgentBurial`): an operator-declared reconciliation of
  a child no live worker owns - a crashed generation's child, or one whose spawn
  call died inside the current generation. A child parked on its own pending
  approval is never buriable; only the operator may resolve it;
* the per-parent-turn fan-out bound and the nested-spawn depth bound;
* the attribution projection over the durable records.

Honest boundaries (ADR-0061 requirements, stated here because an implementer
reads this file, not the ADR):

* ``N`` (``AGENT_OS_MAX_CHILD_AGENTS``) bounds **children in flight per parent
  turn**. It does not bound the total tree, total tokens, total cost or total
  wall-clock time. A depth-``d`` tree of fan-out ``N`` holds ``N ** d`` children
  without any single layer exceeding ``N``. A separate depth bound
  (:data:`MAX_CHILD_AGENT_ANCESTOR_DEPTH`) is what limits nesting.
* **"The parent's remaining budget" does not exist in this spine.** There is no
  consumption ledger: ``CapabilityGrant.budget_limit`` is a static ceiling and
  the only budget check is a single action's ``estimated_budget`` against it
  (``governance.py``). What this spine passes as ``parent_remaining_budget`` is
  therefore the parent's **static grant ceiling**, and the resulting child
  grants are a non-widening copy (child ``budget_limit`` <= parent
  ``budget_limit``). No call site may claim a cross-session total budget.
* **A synchronous spawn has no natural wall-clock bound**; it inherits the
  child turn's own step/token bounds plus the provider's request timeout. This
  spine adds one explicit bound
  (``AGENT_OS_CHILD_AGENT_TIMEOUT_SECONDS``, default
  :data:`DEFAULT_CHILD_AGENT_TIMEOUT_SECONDS`) and it is a bound on the
  *spawn call's wait*, not a preemption: the recorded
  :data:`CHILD_AGENT_STOP_REASON_WALL_CLOCK` status says the caller gave up
  waiting. An abandoned child is stopped by the existing operator path (a C7
  correction on the child task) or by stopping the parent (the cascade).
* **The digest-only rule is narrow.** It applies to the two child-agent durable
  records (``CHILD_AGENT_SPAWNED`` / ``CHILD_AGENT_FINISHED``) and to the
  attribution projection, which carries no child text. A child session is an
  ordinary session, so its own messages (including the spawn prompt as its
  first user message and its final assistant text) are recorded in
  ``SESSION_MESSAGE_RECORDED`` exactly as any session's are.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from agent_os_contracts import (
    ActionContract,
    ChildAgentAttribution,
    ChildAgentFanOutConfig,
    ChildAgentFinished,
    ChildAgentLink,
    ChildAgentSpawnCommand,
    ChildAgentSpawnResult,
    ChildAgentSpawned,
    ChildAgentStatus,
    ChildAgentTurnAttribution,
    ChildAgentType,
    CorrectionEpochVector,
    TaskEvent,
    TaskEventType,
    content_digest,
    enforce_child_agent_limit,
)

from .governance import CorrectionReadPort

CHILD_AGENTS_ENV_VAR = "AGENT_OS_CHILD_AGENTS"
CHILD_AGENT_TIMEOUT_ENV_VAR = "AGENT_OS_CHILD_AGENT_TIMEOUT_SECONDS"
DEFAULT_CHILD_AGENT_TIMEOUT_SECONDS = 300.0

MAX_CHILD_AGENT_ANCESTOR_DEPTH = 8
"""Hard bound on the ancestor chain the halt cascade will follow.

A chain longer than this (or one containing a cycle) is treated as halted:
fail-closed, never "keep walking". Real chains are bounded at spawn time by the
same constant, so overflow means a corrupted or hand-written durable record.
"""

CHILD_AGENT_STOP_REASON_PARENT_STOPPED = "stopped_by_operator"
CHILD_AGENT_STOP_REASON_AWAITING_APPROVAL = "awaiting_approval"
CHILD_AGENT_STOP_REASON_WALL_CLOCK = "child_wall_clock_exceeded"
CHILD_AGENT_STOP_REASON_PARENT_CLOSED = "parent_session_closed"
CHILD_AGENT_STOP_REASON_UNKNOWN = "unknown_requires_review"
CHILD_AGENT_RECONCILE_REASON_RUNTIME_GONE = "CHILD_RUNTIME_GENERATION_GONE"
CHILD_AGENT_RECONCILE_REASON_SPAWN_ABANDONED = "CHILD_SPAWN_ABANDONED"
CHILD_AGENT_RECONCILE_OUTCOME = "UNKNOWN"
SESSION_OPENED_CHILD_AGENT_FIELD = "child_agent"
"""Key of the child-agent block inside a child session's ``SESSION_OPENED`` payload."""


class ChildAgentKernelError(RuntimeError):
    """Base for every typed kernel-side rejection of the child-agent spine."""


class ChildAgentDisabled(ChildAgentKernelError):
    """The feature is switched off (``AGENT_OS_CHILD_AGENTS``, default off)."""


class ChildAgentNotSpawnable(ChildAgentKernelError):
    """The calling action is not an open parent turn, so nothing can be spawned."""


class ChildAgentDepthExceeded(ChildAgentKernelError):
    """Nested spawn would exceed :data:`MAX_CHILD_AGENT_ANCESTOR_DEPTH`."""


class ChildAgentLinkError(ChildAgentKernelError):
    """A durable child-agent link is missing or malformed (fail closed)."""


class ChildAgentBurialRefused(ChildAgentKernelError):
    """A burial was refused because a live runtime generation still owns the child."""


def child_agents_enabled(env: Mapping[str, str]) -> bool:
    """Global switch, **off by default**, turnable off entirely.

    ``0``/``off``/``false``/``no`` (and unset) are off; ``1``/``on``/``true``/
    ``yes`` are on. Any other value raises rather than being read as "on": a
    misconfiguration must not silently enable child agents.
    """

    raw = env.get(CHILD_AGENTS_ENV_VAR)
    if raw is None or not raw.strip():
        return False
    value = raw.strip().lower()
    if value in {"0", "off", "false", "no"}:
        return False
    if value in {"1", "on", "true", "yes"}:
        return True
    raise ChildAgentKernelError(
        f"{CHILD_AGENTS_ENV_VAR} must be one of on/off/1/0/true/false/yes/no"
    )


def child_agent_timeout_seconds(env: Mapping[str, str]) -> float:
    """Wall-clock bound on one synchronous spawn call."""

    raw = env.get(CHILD_AGENT_TIMEOUT_ENV_VAR)
    if raw is None or not raw.strip():
        return DEFAULT_CHILD_AGENT_TIMEOUT_SECONDS
    try:
        value = float(raw.strip())
    except ValueError as exc:
        raise ChildAgentKernelError(
            f"{CHILD_AGENT_TIMEOUT_ENV_VAR} must be a positive number"
        ) from exc
    if not value > 0:
        raise ChildAgentKernelError(
            f"{CHILD_AGENT_TIMEOUT_ENV_VAR} must be a positive number"
        )
    return value


def spawn_prompt_digest(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def summary_digest(text: str) -> str:
    """Digest of a child's final text; empty text digests the empty string."""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def child_agent_status_for_stop_reason(stop_reason: str) -> ChildAgentStatus:
    """Map one child turn's stop reason onto the frozen status vocabulary.

    The mapping is total and fail-closed: an unrecognised stop reason is
    ``failed``, never ``completed``. ``limit`` means the child hit its own step
    or token bound - it is never the fan-out rejection, which is a typed
    :class:`~agent_os_contracts.ChildAgentLimitExceeded` raised before any child
    exists.
    """

    if stop_reason == "completed":
        return ChildAgentStatus.COMPLETED
    if stop_reason in {"max_steps", "budget_exceeded"}:
        return ChildAgentStatus.LIMIT
    if stop_reason in {
        CHILD_AGENT_STOP_REASON_AWAITING_APPROVAL,
        CHILD_AGENT_STOP_REASON_PARENT_CLOSED,
        CHILD_AGENT_STOP_REASON_PARENT_STOPPED,
        "correction_halted",
    }:
        return ChildAgentStatus.STOPPED
    if stop_reason == CHILD_AGENT_STOP_REASON_WALL_CLOCK:
        return ChildAgentStatus.TIMEOUT
    return ChildAgentStatus.FAILED


@dataclass(frozen=True)
class ChildAgentAncestor:
    """One durable ancestor of a (possibly nested) child session."""

    task_id: str
    run_id: str


@dataclass(frozen=True)
class ChildAgentChild:
    """One durable child-agent record pair as read from the parent's stream."""

    parent_task_id: str
    parent_run_id: str
    spawned: ChildAgentSpawned
    finished: ChildAgentFinished | None = None
    reconciled: bool = False

    @property
    def spawn_id(self) -> str:
        return self.spawned.spawn_id

    @property
    def child_session_id(self) -> str:
        return self.spawned.child_session_id

    @property
    def child_task_id(self) -> str:
        return self.spawned.child_task_id

    @property
    def in_flight(self) -> bool:
        return self.finished is None


class ChildAgentEventSource(Protocol):
    """Durable event read port (``SQLiteTaskEventStore`` satisfies it)."""

    def list_task_ids(self) -> Sequence[str]: ...

    def read(self, task_id: str) -> Sequence[TaskEvent]: ...


class ChildAgentIndex:
    """Read-only durable index over the child-agent records.

    Every answer is recomputed from durable events, so it is identical before
    and after a restart. Only the *immutable* child link
    (``SESSION_OPENED.child_agent``) is cached: it is written once and never
    rewritten, so a cached value cannot go stale.
    """

    def __init__(self, events: ChildAgentEventSource) -> None:
        self._events = events
        self._link_cache: dict[str, dict[str, object] | None] = {}

    def children(self, parent_task_id: str) -> tuple[ChildAgentChild, ...]:
        """Every child spawned from ``parent_task_id``, in spawn order.

        A child with more than one finish record (a parked child resumed by the
        operator writes a second one) reports the latest: the records are
        append-only, so "latest" is the current truth.
        """

        spawned: list[tuple[str, ChildAgentSpawned]] = []
        finished: dict[str, ChildAgentFinished] = {}
        reconciled: set[str] = set()
        for event in self._events.read(parent_task_id):
            payload = event.decoded_payload()
            if event.event_type is TaskEventType.CHILD_AGENT_SPAWNED:
                record = ChildAgentSpawned.model_validate(payload)
                spawned.append((event.correlation_id or "", record))
            elif event.event_type is TaskEventType.CHILD_AGENT_FINISHED:
                record = ChildAgentFinished.model_validate(payload)
                finished[record.spawn_id] = record
            elif event.event_type is TaskEventType.CHILD_AGENT_RECONCILED:
                spawn_id = payload.get("spawn_id")
                if isinstance(spawn_id, str):
                    reconciled.add(spawn_id)
        children: list[ChildAgentChild] = []
        for correlation, record in spawned:
            parent_run_id = correlation or self._task_run_id(parent_task_id)
            children.append(
                ChildAgentChild(
                    parent_task_id=parent_task_id,
                    parent_run_id=parent_run_id,
                    spawned=record,
                    finished=finished.get(record.spawn_id),
                    reconciled=record.spawn_id in reconciled,
                )
            )
        return tuple(children)

    def child_turn_open(self, child_task_id: str) -> bool:
        """True while the child's own session still owns an open turn.

        A child that parked on a permission prompt has a durable finish record
        (``stopped`` / ``awaiting_approval``) *and* an open turn: it has not
        ended, only stopped asking. Counting it as in flight is what makes the
        fan-out bound mean something, and it is decided from durable events, so
        a restart cannot reset the count.
        """

        return self.open_turn_id(child_task_id) is not None

    def is_in_flight(self, child: ChildAgentChild) -> bool:
        """True until the child has ended - or an operator declared it closed.

        A buried child is out of flight by the operator's own declaration, even
        though its session turn is still open (session-level dead-turn recovery
        is a separate, later slice): keeping a declared-dead child in the quota
        would lock the parent turn out of its own fan-out bound.
        """

        if child.reconciled:
            return False
        return child.finished is None or self.child_turn_open(child.child_task_id)

    def in_flight(self, parent_task_id: str, parent_turn_id: str) -> int:
        """Children of one parent **turn** that have not ended.

        In flight = no durable finish record yet, or a finish record whose
        child session still owns an open turn (the operator-visible parking
        case). Recomputed from durable events on every call.
        """

        return sum(
            1
            for child in self.children(parent_task_id)
            if child.spawned.parent_turn_id == parent_turn_id
            and self.is_in_flight(child)
        )

    def in_flight_children(self, parent_task_id: str) -> tuple[ChildAgentChild, ...]:
        return tuple(
            child for child in self.children(parent_task_id) if self.is_in_flight(child)
        )

    def child_link(self, child_task_id: str) -> dict[str, object] | None:
        """The child's own durable link block, or ``None`` when it is not a child."""

        if child_task_id in self._link_cache:
            return self._link_cache[child_task_id]
        link: dict[str, object] | None = None
        for event in self._events.read(child_task_id):
            if event.event_type is not TaskEventType.SESSION_OPENED:
                continue
            block = event.decoded_payload().get(SESSION_OPENED_CHILD_AGENT_FIELD)
            if isinstance(block, dict):
                link = dict(block)
                break
        self._link_cache[child_task_id] = link
        return link

    def link_for_child_task(self, child_task_id: str) -> Mapping[str, object]:
        """The link block, or a typed :class:`ChildAgentLinkError`.

        A session that claims to be a child through its ``parent_*`` fields but
        carries no readable block fails closed rather than silently widening.
        """

        link = self.child_link(child_task_id)
        if link is None:
            raise ChildAgentLinkError(
                f"task {child_task_id} has no durable child-agent link"
            )
        required = {
            "spawn_id",
            "parent_session_id",
            "parent_task_id",
            "parent_run_id",
            "parent_turn_id",
            "agent_type",
        }
        if not required <= set(link):
            raise ChildAgentLinkError(
                f"task {child_task_id} has an incomplete child-agent link"
            )
        return link

    def ancestors(self, task_id: str) -> tuple[ChildAgentAncestor, ...]:
        """The durable ancestor chain of ``task_id``, nearest parent first."""

        chain: list[ChildAgentAncestor] = []
        seen = {task_id}
        cursor = task_id
        while len(chain) < MAX_CHILD_AGENT_ANCESTOR_DEPTH:
            link = self.child_link(cursor)
            if link is None:
                break
            parent_task_id = link.get("parent_task_id")
            parent_run_id = link.get("parent_run_id")
            if not isinstance(parent_task_id, str) or not isinstance(
                parent_run_id, str
            ):
                raise ChildAgentLinkError(
                    f"task {cursor} has a malformed child-agent parent link"
                )
            if parent_task_id in seen:
                raise ChildAgentLinkError(
                    f"child-agent ancestry for task {task_id} contains a cycle"
                )
            seen.add(parent_task_id)
            chain.append(
                ChildAgentAncestor(task_id=parent_task_id, run_id=parent_run_id)
            )
            cursor = parent_task_id
        return tuple(chain)

    def depth(self, task_id: str) -> int:
        return len(self.ancestors(task_id))

    def session_id_for_task(self, task_id: str) -> str | None:
        for event in self._events.read(task_id):
            if event.event_type is not TaskEventType.SESSION_OPENED:
                continue
            value = event.decoded_payload().get("session_id")
            if isinstance(value, str) and value:
                return value
        return None

    def open_turn_id(self, task_id: str) -> str | None:
        """The session's one durable open turn (``STARTED`` without ``COMPLETED``)."""

        started: list[str] = []
        completed: set[str] = set()
        for event in self._events.read(task_id):
            if event.event_type is TaskEventType.SESSION_TURN_STARTED:
                turn_id = event.decoded_payload().get("turn_id")
                if isinstance(turn_id, str) and turn_id:
                    started.append(turn_id)
            elif event.event_type is TaskEventType.SESSION_TURN_COMPLETED:
                turn_id = event.decoded_payload().get("turn_id")
                if isinstance(turn_id, str):
                    completed.add(turn_id)
        for turn_id in started:
            if turn_id not in completed:
                return turn_id
        return None

    def attribution(
        self,
        parent_task_id: str,
        parent_session_id: str,
        parent_turn_id: str,
        *,
        parent_own_steps: int = 0,
        parent_own_tokens: int = 0,
    ) -> ChildAgentTurnAttribution:
        """The roll-up for one parent turn, built from durable records only.

        A child with no finish record yet contributes its (zero) counters and
        the status its spawn record implies: ``stopped`` while the parent turn
        is still open. No child text is copied - the row has no text field.
        """

        rows: list[ChildAgentAttribution] = []
        steps = 0
        tokens = 0
        for child in self.children(parent_task_id):
            if child.spawned.parent_turn_id != parent_turn_id:
                continue
            finished = child.finished
            child_steps = finished.steps if finished is not None else 0
            child_tokens = finished.tokens if finished is not None else 0
            steps += child_steps
            tokens += child_tokens
            rows.append(
                ChildAgentAttribution(
                    spawn_id=child.spawned.spawn_id,
                    child_session_id=child.spawned.child_session_id,
                    child_task_id=child.spawned.child_task_id,
                    agent_type=child.spawned.agent_type,
                    description=child.spawned.description,
                    status=(
                        finished.status
                        if finished is not None
                        else ChildAgentStatus.STOPPED
                    ),
                    steps=child_steps,
                    tokens=child_tokens,
                    stop_reason=finished.stop_reason if finished is not None else None,
                )
            )
        return ChildAgentTurnAttribution(
            parent_session_id=parent_session_id,
            parent_turn_id=parent_turn_id,
            children=tuple(rows),
            parent_own_steps=parent_own_steps,
            parent_own_tokens=parent_own_tokens,
            total_steps=parent_own_steps + steps,
            total_tokens=parent_own_tokens + tokens,
        )

    def _task_run_id(self, task_id: str) -> str:
        for event in self._events.read(task_id):
            if event.event_type is TaskEventType.SESSION_OPENED:
                value = event.decoded_payload().get("run_id")
                if isinstance(value, str) and value:
                    return value
        return ""


class ChildAgentHaltCascade:
    """Read-side C7 halt cascade: a child action consults its ancestors.

    Why a read-side decorator instead of a new axis inside
    ``CorrectionAuthority``: the authority's keys are ``(task, run,
    capability)`` and only the external operator path may write them. Adding a
    parent axis as a *writer* would either put a second halt switch inside the
    system (the system could then halt itself) or let the runtime write the
    authority - both would move C7 (``governance.py``, ``C7-BOUNDARY
    STATEMENT``). This port adds no write method and no state: it answers
    ``halted`` monotonically more often than the authority it wraps, using the
    durable parent chain as its only extra input.

    Properties that make it safe to put on the dispatch path:

    * **restart-safe** - the chain comes from durable ``SESSION_OPENED``
      child blocks, not from in-memory spawn bookkeeping;
    * **no fan-out writes** - reading the chain appends nothing;
    * **bounded** - at most :data:`MAX_CHILD_AGENT_ANCESTOR_DEPTH` ancestors,
      and a longer or cyclic chain is halted (fail-closed);
    * **not a second authority** - it never reports "not halted" where the
      wrapped port reports halted, it never invents epochs (``snapshot``
      delegates unchanged, so permits and correction receipts keep binding the
      child's own keys), and it cannot clear a halt.
    """

    def __init__(
        self,
        inner: CorrectionReadPort,
        index: ChildAgentIndex,
        *,
        max_depth: int = MAX_CHILD_AGENT_ANCESTOR_DEPTH,
    ) -> None:
        self._inner = inner
        self._index = index
        self._max_depth = max_depth
        self._overflow: set[str] = set()

    @property
    def inner(self) -> CorrectionReadPort:
        return self._inner

    def snapshot(
        self,
        task_id: str,
        run_id: str,
        capability_id: str,
    ) -> CorrectionEpochVector:
        """The child's own epochs, unchanged: the cascade is a halt check only."""

        return self._inner.snapshot(task_id, run_id, capability_id)

    def halted(self, task_id: str, run_id: str, capability_id: str) -> bool:
        if self._inner.halted(task_id, run_id, capability_id):
            return True
        return self._ancestor_halted(task_id, capability_id)

    @contextmanager
    def guard_unchanged(
        self,
        task_id: str,
        run_id: str,
        capability_id: str,
        observed_epochs: CorrectionEpochVector,
    ) -> Iterator[bool]:
        """Linearize against the child's own authority *and* its ancestors.

        The ancestor half is evaluated on entry, exactly like the epoch
        comparison: a correction committed before dispatch is refused
        (``CapabilityCorrectionBlocked``), while a correction committed after
        the physical effect started is not an interrupt - that is the existing
        C7 semantics and is not weakened here.
        """

        with self._inner.guard_unchanged(
            task_id, run_id, capability_id, observed_epochs
        ) as unchanged:
            yield bool(unchanged) and not self._ancestor_halted(
                task_id, capability_id
            )

    def _ancestor_halted(self, task_id: str, capability_id: str) -> bool:
        if task_id in self._overflow:
            # Already known to have an unusable chain: fail closed without
            # re-walking it on every dispatch.
            return True
        try:
            chain = self._index.ancestors(task_id)
        except ChildAgentLinkError:
            self._overflow.add(task_id)
            return True
        if len(chain) >= self._max_depth and self._has_parent(chain[-1].task_id):
            self._overflow.add(task_id)
            return True
        for ancestor in chain:
            if self._inner.halted(ancestor.task_id, ancestor.run_id, capability_id):
                return True
        return False

    def _has_parent(self, task_id: str) -> bool:
        try:
            return bool(self._index.ancestors(task_id))
        except ChildAgentLinkError:
            return True


@dataclass(frozen=True)
class ChildAgentBurial:
    """Typed, durable record of one operator-declared child reconciliation."""

    spawn_id: str
    child_session_id: str
    child_task_id: str
    reason_code: str
    outcome: str
    declared_by: str
    declared_at: datetime
    runtime_boot_id: str
    runtime_pid: int
    reason: str
    child_open_turn_id: str | None

    def payload(self) -> dict[str, object]:
        return {
            "spawn_id": self.spawn_id,
            "child_session_id": self.child_session_id,
            "child_task_id": self.child_task_id,
            "reason_code": self.reason_code,
            "outcome": self.outcome,
            "declared_by": self.declared_by,
            "declared_at": self.declared_at,
            "runtime_boot_id": self.runtime_boot_id,
            "runtime_pid": self.runtime_pid,
            "reason": self.reason,
            "child_open_turn_id": self.child_open_turn_id,
        }


@dataclass(frozen=True)
class ChildAgentOrphan:
    """An in-flight child that no live runtime owns any more."""

    child: ChildAgentChild
    spawn_runtime_boot_id: str | None


def orphaned_children(
    index: ChildAgentIndex,
    parent_task_id: str,
    *,
    in_memory_spawn_ids: Sequence[str] = (),
) -> tuple[ChildAgentOrphan, ...]:
    """In-flight children of ``parent_task_id`` that no live runtime owns.

    Ownership is decided from durable evidence, never from a guess. A child is
    an orphan when it is in flight and **no live worker in this process holds
    its spawn call** - the spawn call either belonged to a runtime generation
    that is gone (a crash) or died without writing a finish record inside this
    generation (an abandoned spawn). A child whose spawn call is still running
    is never reported as ownerless, so a live child is never buried out from
    under its own spawn. The recorded generation is carried on the orphan so the
    reconciliation can name which case it is.
    """

    live = set(in_memory_spawn_ids)
    orphans: list[ChildAgentOrphan] = []
    for child in index.in_flight_children(parent_task_id):
        if child.spawn_id in live:
            continue
        link = index.child_link(child.child_task_id)
        owner = link.get("spawn_runtime_boot_id") if link else None
        orphans.append(
            ChildAgentOrphan(
                child=child,
                spawn_runtime_boot_id=owner if isinstance(owner, str) else None,
            )
        )
    return tuple(orphans)


def enforce_child_agent_depth(index: ChildAgentIndex, parent_task_id: str) -> None:
    """Refuse a spawn whose child would exceed the ancestor depth bound."""

    if index.depth(parent_task_id) >= MAX_CHILD_AGENT_ANCESTOR_DEPTH:
        raise ChildAgentDepthExceeded(
            "child agent depth bound reached: "
            f"the parent already has {index.depth(parent_task_id)} ancestors "
            f"(bound {MAX_CHILD_AGENT_ANCESTOR_DEPTH})"
        )


def enforce_child_agent_fan_out(
    index: ChildAgentIndex,
    parent_task_id: str,
    parent_turn_id: str,
    *,
    env: Mapping[str, str] | None = None,
) -> None:
    """Refuse a spawn when the parent turn already holds N children in flight."""

    enforce_child_agent_limit(
        in_flight_children=index.in_flight(parent_task_id, parent_turn_id),
        config=ChildAgentFanOutConfig.from_env(env or {}),
    )


def child_agent_link_fields(link: Mapping[str, object]) -> dict[str, str]:
    """The frozen ``parent_session_id``/``parent_turn_id``/``spawn_id`` triple."""

    return ChildAgentLink(
        spawn_id=str(link["spawn_id"]),
        parent_session_id=str(link["parent_session_id"]),
        parent_turn_id=str(link["parent_turn_id"]),
        child_session_id=str(link["child_session_id"]),
        child_task_id=str(link["child_task_id"]),
        agent_type=ChildAgentType(str(link["agent_type"])),
    ).event_link_fields()


def grants_digest(grants: Mapping[str, Mapping[str, object]]) -> str:
    """Digest of the derived grant block, so a restored plan is verifiable."""

    return content_digest({cid: dict(grant) for cid, grant in grants.items()})


@dataclass(frozen=True)
class ChildAgentSpawnRequest:
    """The resolved context of one spawn, as the composition root determined it.

    Built by the spawner from durable state (the parent's open turn, the parent
    session, this runtime generation); never supplied by the model or by the
    domain pack.
    """

    spawn_id: str
    prompt: str
    description: str
    agent_type: ChildAgentType
    max_steps: int | None
    parent_task_id: str
    parent_run_id: str
    parent_session_id: str
    parent_turn_id: str
    runtime_boot_id: str
    runtime_pid: int


class ChildAgentSpawnerPort(Protocol):
    """Injected by the composition root; the domain pack calls only this.

    The port receives the already-governed action plus the validated frozen
    command. Everything about *where* the child lives (parent session, parent
    turn, runtime generation) is resolved by the implementation from durable
    state, so the domain pack never invents session semantics.
    """

    def spawn_child_agent(
        self, action: ActionContract, command: ChildAgentSpawnCommand
    ) -> ChildAgentSpawnResult: ...


def child_agent_spawn_result(
    *,
    child_session_id: str,
    child_task_id: str,
    stop_reason: str,
    text: str = "",
    steps: int = 0,
    tokens: int = 0,
) -> ChildAgentSpawnResult:
    """Build the typed result the parent turn receives.

    The status is derived from the stop reason (never passed in), so a caller
    cannot report ``completed`` for a turn that stopped for another reason.
    """

    status = child_agent_status_for_stop_reason(stop_reason)
    return ChildAgentSpawnResult(
        child_session_id=child_session_id,
        child_task_id=child_task_id,
        status=status,
        text=text,
        steps=steps,
        tokens=tokens,
        stop_reason=stop_reason,
    )


def child_agent_fan_out_config(env: Mapping[str, str]) -> ChildAgentFanOutConfig:
    return ChildAgentFanOutConfig.from_env(env)


