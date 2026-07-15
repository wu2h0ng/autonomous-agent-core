from __future__ import annotations

from research_tools.active_discovery.canonical import canonical_json, content_digest


def test_canonical_digest_is_order_independent_and_domain_separated() -> None:
    left = {"b": [2, 1], "a": {"x": True}}
    right = {"a": {"x": True}, "b": [2, 1]}

    assert canonical_json(left) == canonical_json(right)
    assert content_digest("probe", left) == content_digest("probe", right)
    assert content_digest("probe", left) != content_digest("observation", left)
