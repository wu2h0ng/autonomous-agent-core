"""Rule-based NL→Query engine — parse natural language into structured metric queries.

Pure rule-based engine (no LLM) that extracts:
- Metric keyword (Chinese + English, via shared metric aliases)
- Time range (relative date expressions → concrete datetime.date tuples)
- Group-by dimensions (channel, region, category, date)

Pipeline: ``parse → match → build parameters → QueryEngineResult``

Entry point: ``NLQueryEngine(metric_registry).query(question)``
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass

from agent_os_contracts import MetricContract

from .._metric_aliases import DISPLAY_TO_METRIC
from ..semantic_runtime import SemanticRegistry


# ---------------------------------------------------------------------------
# ParsedIntent — structured output of NLIntentParser
# ---------------------------------------------------------------------------


@dataclass
class ParsedIntent:
    """Structured representation of a natural-language business question.

    Fields:
        metric_keyword:  normalized metric name (e.g. ``"gmv"``) or ``"unknown"``.
        raw_question:    the original input text unchanged.
        time_range:      parsed (start, end) as ``datetime.date``, or ``None``.
        dimensions:      group-by dimension names, possibly empty.
        chart_type:      suggested visualization type (line/bar/number/table).
    """

    metric_keyword: str
    raw_question: str
    time_range: tuple[datetime.date, datetime.date] | None = None
    dimensions: tuple[str, ...] = ()
    chart_type: str = "table"


# ---------------------------------------------------------------------------
# QueryEngineResult — structured output of NLQueryEngine
# ---------------------------------------------------------------------------


@dataclass
class QueryEngineResult:
    """The fully resolved query plan from a natural-language question.

    Fields:
        matched_metric:  the ``MetricContract`` found, or ``None``.
        parameters:      ``{"start_date": ISO, "end_date": ISO}`` ready for SQL.
        confidence:      a score in ``[0.0, 1.0]``.
        dimensions:      group-by dimension names, possibly empty.
        chart_type:      suggested visualization type (line/bar/number/table).
    """

    matched_metric: MetricContract | None
    parameters: dict[str, str]
    confidence: float
    dimensions: tuple[str, ...] = ()
    chart_type: str = "table"


# ---------------------------------------------------------------------------
# Dimension extraction patterns
# ---------------------------------------------------------------------------

_DIMENSION_PATTERNS: dict[str, re.Pattern[str]] = {
    "channel": re.compile(r"按渠道|by\s+channel"),
    "region": re.compile(r"按地区|by\s+region"),
    "category": re.compile(r"按品类|按类目|by\s+category"),
    "date": re.compile(r"按日|按日期|by\s+date"),
}

_DIMENSION_ORDER = ("channel", "region", "category", "date")


def _extract_dimensions(question: str) -> tuple[str, ...]:
    dims: list[str] = []
    for name in _DIMENSION_ORDER:
        if _DIMENSION_PATTERNS[name].search(question):
            dims.append(name)
    return tuple(dims)


def _detect_chart_type(
    dimensions: tuple[str, ...],
    time_range: tuple[datetime.date, datetime.date] | None,
    has_matched_metric: bool,
) -> str:
    """Rule-based chart-type suggestion for a parsed natural-language question.

    - ``line``: the result is likely a time series (date dimension or explicit time
      range present).
    - ``bar``: a categorical breakdown is requested.
    - ``number``: a single scalar metric with no breakdown.
    - ``table``: fallback for ambiguous or multi-metric cases.
    """
    if "date" in dimensions or time_range is not None:
        return "line"
    if dimensions:
        return "bar"
    if has_matched_metric:
        return "number"
    return "table"


# ---------------------------------------------------------------------------
# Metric extraction
# ---------------------------------------------------------------------------


def _extract_metric_keyword(question: str) -> str:
    q_lower = question.lower()
    best_keyword = "unknown"
    best_index: int | None = None
    best_len = 0
    for display_name in sorted(DISPLAY_TO_METRIC, key=len, reverse=True):
        index = q_lower.find(display_name)
        if index == -1:
            continue
        # Prefer the earliest mention; break ties by longer match.
        if (
            best_index is None
            or index < best_index
            or (index == best_index and len(display_name) > best_len)
        ):
            best_index = index
            best_len = len(display_name)
            best_keyword = DISPLAY_TO_METRIC[display_name]
    if best_keyword != "unknown":
        return best_keyword
    for canonical in (
        "gmv",
        "roi",
        "revenue",
        "conversion_rate",
        "spend",
        "cac",
        "orders",
        "customer_count",
    ):
        index = q_lower.find(canonical)
        if index != -1:
            if best_index is None or index < best_index:
                best_index = index
                best_keyword = canonical
    return best_keyword


# ---------------------------------------------------------------------------
# Time range extraction
# ---------------------------------------------------------------------------

_CN_TIME_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"上上周"), "the week before last"),
    (re.compile(r"上上個月|上上个月"), "the month before last"),
    (re.compile(r"上周|上一周"), "last week"),
    (re.compile(r"本周|这周|這一週|这一周"), "this week"),
    (re.compile(r"上个月|上月"), "last month"),
    (re.compile(r"本月|这个月|這個月"), "this month"),
    (re.compile(r"昨天"), "yesterday"),
    (re.compile(r"今天"), "today"),
    (re.compile(r"最近(\d+)天"), "last N days"),
    (re.compile(r"过去(\d+)天"), "last N days"),
    (re.compile(r"前(\d+)天"), "last N days"),
    (re.compile(r"最近(\d+)周"), "last N weeks"),
    (re.compile(r"过去(\d+)周"), "last N weeks"),
    (re.compile(r"最近(\d+)个?月"), "last N months"),
    (re.compile(r"过去(\d+)个?月"), "last N months"),
]

_EN_TIME_RE = re.compile(
    r"(the week before last|the month before last|last\s+week|this\s+week|"
    r"last\s+month|this\s+month|yesterday|today|"
    r"last\s+(\d+)\s+days?|past\s+(\d+)\s+days?|"
    r"last\s+(\d+)\s+weeks?|past\s+(\d+)\s+weeks?|"
    r"last\s+(\d+)\s+months?|past\s+(\d+)\s+months?)",
    re.IGNORECASE,
)


def _resolve_time_range(
    label: str, match: re.Match | None = None
) -> tuple[datetime.date, datetime.date] | None:
    today = datetime.date.today()
    label_lower = label.lower().strip()

    if label_lower == "the week before last":
        days_since_monday = today.weekday()
        last_monday = today - datetime.timedelta(days=days_since_monday + 7)
        return (last_monday, last_monday + datetime.timedelta(days=7))
    if label_lower == "the month before last":
        first_this = today.replace(day=1)
        first_last = (first_this - datetime.timedelta(days=1)).replace(day=1)
        first_prev = (first_last - datetime.timedelta(days=1)).replace(day=1)
        return (first_prev, first_last)
    if label_lower == "last week":
        days_since_monday = today.weekday()
        last_monday = today - datetime.timedelta(days=days_since_monday + 7)
        return (last_monday, last_monday + datetime.timedelta(days=7))
    if label_lower == "this week":
        this_monday = today - datetime.timedelta(days=today.weekday())
        return (this_monday, today + datetime.timedelta(days=1))
    if label_lower == "last month":
        first_this = today.replace(day=1)
        first_last = (first_this - datetime.timedelta(days=1)).replace(day=1)
        return (first_last, first_this)
    if label_lower == "this month":
        return (today.replace(day=1), today + datetime.timedelta(days=1))
    if label_lower == "yesterday":
        yest = today - datetime.timedelta(days=1)
        return (yest, today)
    if label_lower == "today":
        return (today, today + datetime.timedelta(days=1))
    if label_lower in ("last n days", "past n days"):
        if match:
            n = int(match.group(1) or match.group(2) or match.group(3) or 7)
            return (today - datetime.timedelta(days=n - 1), today + datetime.timedelta(days=1))
    if label_lower in ("last n weeks", "past n weeks"):
        if match:
            n = int(match.group(1) or match.group(2) or 1)
            return (today - datetime.timedelta(weeks=n), today + datetime.timedelta(days=1))
    if label_lower in ("last n months", "past n months"):
        if match:
            n = int(match.group(1) or match.group(2) or 1)
            month = today.month - n
            year = today.year
            while month <= 0:
                month += 12
                year -= 1
            first = today.replace(year=year, month=month, day=1)
            return (
                first,
                today.replace(day=1)
                if n == 1
                else first.replace(
                    year=first.year + (first.month // 12), month=(first.month % 12) + 1 or 12
                ),
            )
    return None


def _extract_cn_time(question: str) -> tuple[datetime.date, datetime.date] | None:
    for pattern, label in _CN_TIME_PATTERNS:
        m = pattern.search(question)
        if m:
            return _resolve_time_range(label, m)
    return None


def _extract_en_time(question: str) -> tuple[datetime.date, datetime.date] | None:
    m = _EN_TIME_RE.search(question)
    if m:
        return _resolve_time_range(m.group(0).strip(), m)
    return None


def _extract_time(question: str) -> tuple[datetime.date, datetime.date] | None:
    return _extract_cn_time(question) or _extract_en_time(question)


# ---------------------------------------------------------------------------
# NLIntentParser
# ---------------------------------------------------------------------------


class NLIntentParser:
    """Parse a natural-language question into a structured ``ParsedIntent``.

    Extraction order: dimensions → metric → time range.
    This ensures that dimension keywords like ``"by date"`` are captured as
    dimensions, not confused with time expressions.
    """

    def parse(self, question: str) -> ParsedIntent:
        if not question or not question.strip():
            return ParsedIntent(
                metric_keyword="unknown",
                raw_question=question,
            )
        dims = _extract_dimensions(question)
        metric_kw = _extract_metric_keyword(question)
        time_range = _extract_time(question)
        chart_type = _detect_chart_type(dims, time_range, has_matched_metric=metric_kw != "unknown")
        return ParsedIntent(
            metric_keyword=metric_kw,
            raw_question=question,
            time_range=time_range,
            dimensions=dims,
            chart_type=chart_type,
        )


# ---------------------------------------------------------------------------
# MetricContractMatcher
# ---------------------------------------------------------------------------


class MetricContractMatcher:
    """Match a ``ParsedIntent`` against a ``SemanticRegistry``.

    Returns the ``MetricContract`` whose ``metric_name`` equals the intent's
    ``metric_keyword``, or ``None`` if no match is found.
    """

    def match(
        self,
        intent: ParsedIntent,
        registry: SemanticRegistry,
    ) -> MetricContract | None:
        if not intent.metric_keyword or intent.metric_keyword == "unknown":
            return None
        return registry.try_resolve_metric(intent.metric_keyword)


# ---------------------------------------------------------------------------
# NLQueryEngine
# ---------------------------------------------------------------------------


class NLQueryEngine:
    """End-to-end natural-language query pipeline.

    Parses a question, resolves it against the metric registry, builds SQL-
    ready date parameters, and returns a ``QueryEngineResult`` with a
    confidence score.

    Args:
        metric_registry: ``SemanticRegistry`` holding the product's metrics.
    """

    def __init__(self, metric_registry: SemanticRegistry) -> None:
        self._parser = NLIntentParser()
        self._matcher = MetricContractMatcher()
        self._registry = metric_registry

    def query(self, question: str) -> QueryEngineResult:
        intent = self._parser.parse(question)
        matched = self._matcher.match(intent, self._registry)

        today = datetime.date.today()
        if intent.time_range is not None:
            start, end = intent.time_range
        else:
            start = today - datetime.timedelta(days=29)
            end = today + datetime.timedelta(days=1)

        parameters = {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        }

        if matched is None:
            confidence = 0.0
        elif intent.metric_keyword == question.strip().lower():
            confidence = 0.95
        elif intent.raw_question.strip().lower() == intent.metric_keyword:
            confidence = 0.95
        else:
            metric_in_question = any(
                intent.metric_keyword in w
                for w in intent.raw_question.lower().replace("?", " ").replace("？", " ").split()
            )
            confidence = 0.85 if metric_in_question else 0.5

        chart_type = _detect_chart_type(
            intent.dimensions, intent.time_range, has_matched_metric=matched is not None
        )

        return QueryEngineResult(
            matched_metric=matched,
            parameters=parameters,
            confidence=confidence,
            dimensions=intent.dimensions,
            chart_type=chart_type,
        )
