"""Tests for multi-turn conversation context resolution.

Test-first discipline: these tests prove the ContextResolver rewrites follow-up
questions using prior metric/time context, and that the in-memory store
persists sessions.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))

from agent_os_core.conversation import (  # noqa: E402
    ContextResolver,
    ConversationSession,
    InMemoryConversationStore,
)


class InMemoryConversationStoreTest(unittest.TestCase):
    def test_get_or_create_creates_new_session(self) -> None:
        store = InMemoryConversationStore()
        session = store.get_or_create("session-1")
        self.assertEqual(session.session_id, "session-1")
        self.assertEqual(session.history, [])
        self.assertIsNone(session.current_metric)

    def test_get_or_create_returns_existing_session(self) -> None:
        store = InMemoryConversationStore()
        first = store.get_or_create("session-1")
        first.current_metric = "gmv"
        store.save(first)
        second = store.get_or_create("session-1")
        self.assertIs(second, first)
        self.assertEqual(second.current_metric, "gmv")

    def test_save_overwrites_session(self) -> None:
        store = InMemoryConversationStore()
        session = store.get_or_create("session-1")
        session.history.append(("q", "t", "gmv", ("2026-05-01", "2026-06-01")))
        store.save(session)
        fetched = store.get_or_create("session-1")
        self.assertEqual(len(fetched.history), 1)

    def test_delete_removes_session(self) -> None:
        store = InMemoryConversationStore()
        session = store.get_or_create("session-1")
        store.save(session)
        store.delete("session-1")
        self.assertEqual(store.get_or_create("session-1").history, [])


class ContextResolverMetricCarryOverTest(unittest.TestCase):
    def setUp(self) -> None:
        self.resolver = ContextResolver()

    def _session(
        self, metric: str | None = None, time_range: tuple[str, str] | None = None
    ) -> ConversationSession:
        session = ConversationSession(session_id="s1")
        if metric is not None:
            session.current_metric = metric
            session.history.append(("initial", "t0", metric, time_range))
        if time_range is not None:
            session.current_time_range = time_range
        return session

    def test_time_only_follow_up_carries_metric(self) -> None:
        session = self._session(metric="gmv", time_range=("2026-05-01", "2026-06-01"))
        resolved = self.resolver.resolve("what about last week?", session)
        self.assertIn("GMV", resolved)
        self.assertIn("last week", resolved)

    def test_metric_only_follow_up_carries_time(self) -> None:
        session = self._session(metric="gmv", time_range=("2026-05-01", "2026-06-01"))
        resolved = self.resolver.resolve("how about ROI?", session)
        self.assertIn("ROI", resolved)
        self.assertIn("2026-05-01", resolved)
        self.assertIn("2026-06-01", resolved)

    def test_neither_metric_nor_time_carries_both(self) -> None:
        session = self._session(metric="gmv", time_range=("2026-05-01", "2026-06-01"))
        resolved = self.resolver.resolve("and by region?", session)
        self.assertIn("GMV", resolved)
        self.assertIn("2026-05-01", resolved)

    def test_short_time_expression_carries_metric(self) -> None:
        session = self._session(metric="roi", time_range=("2026-05-01", "2026-06-01"))
        resolved = self.resolver.resolve("last week", session)
        self.assertIn("ROI", resolved)
        self.assertIn("last week", resolved)

    def test_self_contained_question_unchanged(self) -> None:
        session = self._session(metric="gmv", time_range=("2026-05-01", "2026-06-01"))
        question = "What was the ROI last week?"
        resolved = self.resolver.resolve(question, session)
        self.assertEqual(resolved, question)

    def test_empty_history_returns_original(self) -> None:
        session = ConversationSession(session_id="s1")
        question = "what about last week?"
        resolved = self.resolver.resolve(question, session)
        self.assertEqual(resolved, question)


class ContextResolverPronounHandlingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.resolver = ContextResolver()

    def test_chinese_follow_up_with_marker_carries_metric(self) -> None:
        session = ConversationSession(session_id="s1")
        session.current_metric = "gmv"
        session.current_time_range = ("2026-05-01", "2026-06-01")
        session.history.append(("GMV", "t0", "gmv", ("2026-05-01", "2026-06-01")))
        resolved = self.resolver.resolve("那上周呢？", session)
        self.assertIn("GMV", resolved)

    def test_english_follow_up_marker_carries_metric(self) -> None:
        session = ConversationSession(session_id="s1")
        session.current_metric = "conversion_rate"
        session.current_time_range = ("2026-05-01", "2026-06-01")
        session.history.append(
            ("conversion rate", "t0", "conversion_rate", ("2026-05-01", "2026-06-01"))
        )
        resolved = self.resolver.resolve("what about last month?", session)
        self.assertIn("conversion rate", resolved)
        self.assertIn("last month", resolved)


class MultiTurnConversationTest(unittest.TestCase):
    """Three-turn conversation preserves metric and time-window context."""

    def setUp(self) -> None:
        self.resolver = ContextResolver()
        self.store = InMemoryConversationStore()

    def _update_session(
        self,
        session_id: str,
        metric_name: str,
        time_range: tuple[str, str],
    ) -> ConversationSession:
        session = self.store.get_or_create(session_id)
        session.current_metric = metric_name
        session.current_time_range = time_range
        session.history.append(("question", "trace-1", metric_name, time_range))
        self.store.save(session)
        return session

    def test_three_turn_context_carries_metric_and_time(self) -> None:
        session_id = "multi-turn-1"

        # Turn 1: GMV this week.
        session = self._update_session(session_id, "gmv", ("2026-06-01", "2026-06-08"))
        resolved = self.resolver.resolve("and last week?", session)
        self.assertIn("GMV", resolved)
        self.assertIn("last week", resolved)

        # Turn 2: user only mentions a new time window; metric should still be GMV.
        session = self._update_session(session_id, "gmv", ("2026-05-25", "2026-06-01"))
        resolved = self.resolver.resolve("what about yesterday?", session)
        self.assertIn("GMV", resolved)
        self.assertIn("yesterday", resolved)

        # Turn 3: user only mentions a new metric; time should carry from turn 2.
        session = self.store.get_or_create(session_id)
        session.current_metric = "roi"
        session.history.append(("ROI?", "trace-3", "roi", ("2026-05-25", "2026-06-01")))
        self.store.save(session)
        resolved = self.resolver.resolve("how about ROI?", session)
        self.assertIn("ROI", resolved)
        self.assertIn("2026-05-25", resolved)
        self.assertIn("2026-06-01", resolved)


if __name__ == "__main__":
    unittest.main()
