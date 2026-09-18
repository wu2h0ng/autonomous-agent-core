from __future__ import annotations

from .evidence import EvidenceCompleteness


class GroundingInvariantViolation(Exception):
    """A formal Data Agent answer or action would be emitted WITHOUT passing SQL Safety and a
    complete evidence chain (P5.1b / AR-20260614).

    This is distinct from a governed business denial (e.g. ``DataAgentDenied``): a denial is an
    expected, user-facing outcome; this is a HARD invariant breach.

    Scope note (honest): ``assert_grounded`` is a reusable domain guard. It is currently covered by
    its own test and is NOT yet wired into ``DataAgentRuntime`` as the runtime's single checkpoint;
    wiring it in (with a computed completeness) is a follow-up. Until then "non-bypassable at
    runtime" is not established by this module alone.
    """


def assert_grounded(*, sql_allowed: bool, evidence: EvidenceCompleteness) -> None:
    """The single explicit grounding checkpoint for a formal answer/action.

    Requires both the SQL Safety gate to have passed and the evidence chain to be typed-complete.
    Raises :class:`GroundingInvariantViolation` otherwise — never silently proceeds.
    """
    if not sql_allowed:
        raise GroundingInvariantViolation(
            "refused to ground a formal answer/action: SQL Safety did not pass"
        )
    if not evidence.complete:
        raise GroundingInvariantViolation(
            "refused to ground a formal answer/action: evidence chain is incomplete "
            f"(missing: {', '.join(evidence.missing)})"
        )
