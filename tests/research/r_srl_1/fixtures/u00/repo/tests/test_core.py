"""Tests for canonical_lib.core.

These tests exercise the real library surface. One test is intentionally
xfailed so that the NEW_FAILING_TEST event has a concrete target in the
starting snapshot.
"""

from __future__ import annotations

import pytest

from canonical_lib.core import calculate, greet, parse_config  # type: ignore[reportMissingImports]


def test_greet_defaults() -> None:
    assert greet("world") == "Hello, world!"


def test_greet_custom_greeting() -> None:
    assert greet("Ada", "Hi") == "Hi, Ada!"


def test_calculate_add() -> None:
    assert calculate(2, 3) == 5


def test_calculate_divide_by_zero_raises() -> None:
    with pytest.raises(ValueError, match="division by zero"):
        calculate(1, 0, op="divide")


def test_parse_config_round_trip() -> None:
    raw = '{"debug": true, "retries": 3}'
    assert parse_config(raw) == {"debug": True, "retries": 3}


@pytest.mark.xfail(reason="intentionally failing fixture target for event-01")
def test_new_feature_not_yet_implemented() -> None:
    """Placeholder for the NEW_FAILING_TEST event.

    Arms are expected to notice this failing test and resolve it within
    the unit's authority ceiling.
    """
    assert False
