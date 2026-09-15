from __future__ import annotations

from .evidence import EvidenceCompleteness


class GroundingInvariantViolation(Exception):
    """A formal Data Agent answer or action would be emitted WITHOUT passing SQL Safety and a
    complete evidence chain — a bypass of the non-bypassable grounding mediation (P5.1b / AR-20260614).

    This is distinct from a governed business denial (e.g. ``DataAgentDenied``): a denial is an
    expected, user-facing outcome; this is a HARD invariant breach. Reaching here means the
    data/evidence path was bypassed by a wiring or refactor bug. Fail loudly; never emit an
    ungrounded answer or action.
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
