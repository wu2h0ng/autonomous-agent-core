"""Multi-turn conversation state for the Trusted Loop.

Provides session management so users can ask follow-up questions that reference
previous context. The :class:`ContextResolver` rewrites follow-up questions into
self-contained queries using rule-based pattern matching (no LLM), handling
pronoun references and time/metric carry-over in both Chinese and English.

Entry point: ``POST /runs`` with an optional ``X-Session-Id`` header. When
present, the API resolves the question against the session history before
running the Trusted Loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Protocol, runtime_checkable

from .metric_aliases import (
    DISPLAY_TO_METRIC as _DISPLAY_TO_METRIC,
    METRIC_DISPLAY_NAMES as _METRIC_DISPLAY_NAMES,
)


# ---------------------------------------------------------------------------
# Session model
# ---------------------------------------------------------------------------


@dataclass
class ConversationSession:
    """One user's conversation state.

    ``history`` records each completed turn as a tuple of
    ``(question, trace_id, metric_name, time_range)`` so the resolver can
    look back at prior context. ``current_metric`` and ``current_time_range``
    are the most-recently resolved values and are the primary carry-over
    targets for follow-up questions.
    """

    session_id: str
    history: list[tuple[str, str, str | None, tuple[str, str] | None]] = field(default_factory=list)
    current_metric: str | None = None
    current_time_range: tuple[str, str] | None = None


# ---------------------------------------------------------------------------
# Store port + in-memory adapter
# ---------------------------------------------------------------------------


@runtime_checkable
class ConversationStore(Protocol):
    """Port for persisting conversation sessions.

    Implementations may be in-memory (default), SQL-backed, or Redis-backed.
    OS Core never imports a concrete persistence adapter -- the API composition
    layer selects the backend.
    """

    def get_or_create(self, session_id: str) -> ConversationSession:
        """Return the session for *session_id*, creating a new one if absent."""
        ...

    def save(self, session: ConversationSession) -> None:
        """Persist the session (insert or update)."""
        ...

    def delete(self, session_id: str) -> None:
        """Remove the session. No-op if the session does not exist."""
        ...


class InMemoryConversationStore:
    """Process-local conversation store. Suitable for single-process deployments."""

    def __init__(self) -> None:
        self._sessions: dict[str, ConversationSession] = {}

    def get_or_create(self, session_id: str) -> ConversationSession:
        session = self._sessions.get(session_id)
        if session is None:
            session = ConversationSession(session_id=session_id)
            self._sessions[session_id] = session
        return session

    def save(self, session: ConversationSession) -> None:
        self._sessions[session.session_id] = session

    def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)


# ---------------------------------------------------------------------------
# Metric display helpers
# ---------------------------------------------------------------------------


def _metric_display_name(metric_name: str) -> str:
    return _METRIC_DISPLAY_NAMES.get(metric_name, metric_name)


# ---------------------------------------------------------------------------
# Time-expression patterns (Chinese + English)
# ---------------------------------------------------------------------------

# Chinese relative time expressions
_CN_TIME_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"上上周"), "the week before last"),
    (re.compile(r"上上個月|上上个月"), "the month before last"),
    (re.compile(r"上周|上一周"), "last week"),
    (re.compile(r"本周|这周|這一週|这一周"), "this week"),
    (re.compile(r"上个月|上月"), "last month"),
    (re.compile(r"本月|这个月|這個月"), "this month"),
    (re.compile(r"昨天"), "yesterday"),
    (re.compile(r"今天"), "today"),
    (re.compile(r"过去(\d+)天"), r"past \1 days"),
    (re.compile(r"过去(\d+)周"), r"past \1 weeks"),
    (re.compile(r"过去(\d+)个月"), r"past \1 months"),
    (re.compile(r"前(\d+)天"), r"past \1 days"),
]

# English relative time expressions
_EN_TIME_KEYWORDS: list[str] = [
    r"the week before last",
    r"the month before last",
    r"last week",
    r"this week",
    r"last month",
    r"this month",
    r"yesterday",
    r"today",
    r"past \d+ days?",
    r"past \d+ weeks?",
    r"past \d+ months?",
    r"last \d+ days?",
    r"last \d+ weeks?",
    r"last \d+ months?",
]

_EN_TIME_RE = re.compile(
    r"(" + "|".join(_EN_TIME_KEYWORDS) + r")",
    re.IGNORECASE,
)


def _extract_cn_time(question: str) -> str | None:
    """Return the first Chinese time expression found, or None."""
    for pattern, _label in _CN_TIME_PATTERNS:
        if pattern.search(question):
            return pattern.sub(_label, question).strip()
    return None


def _extract_en_time(question: str) -> str | None:
    """Return the first English time expression found, or None."""
    match = _EN_TIME_RE.search(question)
    if match:
        return match.group(0)
    return None


def _extract_time(question: str) -> str | None:
    """Return a time expression from the question (Chinese or English), or None."""
    return _extract_cn_time(question) or _extract_en_time(question)


def _extract_metric(question: str) -> str | None:
    """Return a metric_name if the question references a known metric, or None."""
    q_lower = question.lower()
    # Try longest match first to avoid partial hits
    for display_name in sorted(_DISPLAY_TO_METRIC, key=len, reverse=True):
        if display_name in q_lower:
            return _DISPLAY_TO_METRIC[display_name]
    return None


# ---------------------------------------------------------------------------
# Follow-up detection patterns
# ---------------------------------------------------------------------------

# Chinese follow-up markers
_CN_FOLLOWUP_RE = re.compile(
    r"^("
    r"那|那么|还有|另外|"  # then / also
    r"如果|要是"  # if (conditional follow-up)
    r")?"
    r"(.+?)"
    r"(呢|吗|嘛|吧|啊|呀)?"
    r"[？?。.！!]*\s*$"
)

# English follow-up markers
_EN_FOLLOWUP_RE = re.compile(
    r"^(what about|how about|and|but what about|then)\s+(.+?)[\?\.\!]*\s*$",
    re.IGNORECASE,
)

# Short question threshold: questions below this length are likely follow-ups
_SHORT_QUESTION_LEN = 30


def _is_followup(question: str) -> bool:
    """Heuristic: is this question likely a follow-up referencing prior context?"""
    stripped = question.strip()
    if len(stripped) > _SHORT_QUESTION_LEN:
        # Long questions are usually self-contained, but still check for
        # explicit follow-up markers.
        if _EN_FOLLOWUP_RE.match(stripped):
            return True
        # Chinese explicit follow-up with 那/呢 pattern
        if re.match(r"^(那|那么).+(呢|吗|嘛)[？?。.]*$", stripped):
            return True
        return False
    # Short questions with follow-up markers are almost certainly follow-ups
    if _EN_FOLLOWUP_RE.match(stripped):
        return True
    if _CN_FOLLOWUP_RE.match(stripped):
        return True
    # Very short questions that are just a time expression or metric name
    # are likely follow-ups if they lack a verb
    if _extract_time(stripped) is not None and len(stripped) < 15:
        return True
    return False


# ---------------------------------------------------------------------------
# ContextResolver
# ---------------------------------------------------------------------------


class ContextResolver:
    """Rewrite follow-up questions to be self-contained using session context.

    The resolver is rule-based (no LLM) and handles:
    - Time-only follow-ups: ``"what about last week?"`` carries the current metric.
    - Metric-only follow-ups: ``"how about ROI?"`` carries the current time range.
    - Pronoun references: ``"那上上周呢？"`` fills in the current metric.
    - Self-contained questions are returned unchanged.
    """

    def resolve(self, question: str, session: ConversationSession) -> str:
        """Return a self-contained version of *question*.

        If the question is a follow-up and the session has context, the
        missing element (metric or time range) is filled from the session.
        If the question is already self-contained or there is no usable
        context, the original question is returned unchanged.
        """
        if not session.history:
            return question
        if not _is_followup(question):
            return question

        current_metric = session.current_metric
        current_time_range = session.current_time_range

        question_time = _extract_time(question)
        question_metric = _extract_metric(question)

        # Case 1: question has a time expression but no metric -> carry metric
        if question_time and not question_metric and current_metric:
            return self._build_metric_time_question(current_metric, question_time, question)

        # Case 2: question has a metric but no time -> carry time range
        if question_metric and not question_time and current_time_range:
            return self._build_metric_time_question(
                question_metric,
                self._format_time_range(current_time_range),
                question,
            )

        # Case 3: question has neither metric nor time -> carry both
        if not question_metric and not question_time:
            if current_metric and current_time_range:
                return self._build_metric_time_question(
                    current_metric,
                    self._format_time_range(current_time_range),
                    question,
                )
            if current_metric:
                return self._build_metric_only_question(current_metric, question)

        # Case 4: question has both metric and time -> already self-contained
        return question

    @staticmethod
    def _build_metric_time_question(metric_name: str, time_expr: str, original: str) -> str:
        display = _metric_display_name(metric_name)
        return f"What is the {display} for {time_expr}?"

    @staticmethod
    def _build_metric_only_question(metric_name: str, original: str) -> str:
        display = _metric_display_name(metric_name)
        return f"What is the {display}?"

    @staticmethod
    def _format_time_range(time_range: tuple[str, str]) -> str:
        start, end = time_range
        return f"{start} to {end}"
