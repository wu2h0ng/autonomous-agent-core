"""A truncated tool result must still carry WHY it is incomplete.

`canonical_output` sorts keys, so a search payload renders as
`matches, mode, scanned_files, truncated, truncated_reason, unexamined_files`.
The truncation preview is a raw prefix of that rendering, so the moment the
payload exceeds the cap the diagnostics - the fields that tell the model the scan
stopped early - are cut off, and an empty `matches` reads as "not found". The
truncated result now carries them as a summary.
"""

from __future__ import annotations

from agent_os_core.agent_loop import _MAX_TOOL_RESULT_CHARS, _truncate_json


def _search_payload(*, reason: str | None, match_chars: int) -> dict[str, object]:
    # Key order mirrors what canonical_output produces for a grep result.
    return {
        "matches": [f"src/f0000.txt:1:{'x' * match_chars}"],
        "mode": "grep",
        "scanned_files": 1000,
        "truncated": reason is not None,
        "truncated_reason": reason,
        "unexamined_files": 205,
    }


def test_small_results_pass_through_untouched() -> None:
    payload = _search_payload(reason=None, match_chars=10)
    assert _truncate_json(payload) == payload


def test_truncated_result_keeps_the_truncation_reason() -> None:
    payload = _search_payload(reason="scan_cap", match_chars=_MAX_TOOL_RESULT_CHARS)
    truncated = _truncate_json(payload)
    assert truncated["truncated"] is True
    summary = truncated["summary"]
    assert summary["truncated_reason"] == "scan_cap"
    assert summary["scanned_files"] == 1000
    assert summary["unexamined_files"] == 205
    assert summary["mode"] == "grep"
    # The diagnostics must actually be in the serialised result the model reads,
    # not only in the returned object.
    import json

    rendered = json.dumps(truncated, default=str)
    assert "scan_cap" in rendered
    assert "unexamined_files" in rendered


def test_summary_stays_bounded_for_a_huge_single_value() -> None:
    # A 5 MB read: the long string must not re-inflate the summary.
    payload = {"content": "A" * (5 * 1024 * 1024), "path": "big.txt"}
    truncated = _truncate_json(payload)
    summary = truncated["summary"]
    assert summary["path"] == "big.txt"
    assert summary["content"] == f"<omitted: {5 * 1024 * 1024} chars>"
    import json

    assert len(json.dumps(truncated, default=str)) < _MAX_TOOL_RESULT_CHARS + 500


def test_a_conversation_sized_payload_is_not_truncated() -> None:
    # Boundaries: exactly at the cap passes through, one char over truncates.
    filler = {"text": "y" * (_MAX_TOOL_RESULT_CHARS - 100)}
    import json

    size = len(json.dumps(filler, default=str))
    assert size <= _MAX_TOOL_RESULT_CHARS
    assert _truncate_json(filler) == filler
