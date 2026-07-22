"""Materialize frozen fixture F4 (prereg §10) into the T4 workspace.

Appends test_recovery_snapshot_rejects_conflicting_run_ids verbatim to
tests/product/test_recovery_projection.py. Fails loudly if the anchor file is
missing or the fixture is already applied.
"""

from pathlib import Path
import sys

MARKER = "test_recovery_snapshot_rejects_conflicting_run_ids"
FIXTURE = '''

def test_recovery_snapshot_rejects_conflicting_run_ids() -> None:
    events = _events(
        (TaskEventType.RUN_STARTED, {"run": {"run_id": "run:one"}}),
        (TaskEventType.RUN_RESUMED, {"run": {"run_id": "run:two"}}),
    )

    with pytest.raises(ValueError) as exc_info:
        build_recovery_snapshot(events)

    assert "recovery projection requires one run stream" in str(exc_info.value)
'''


def main() -> None:
    target = Path("tests/product/test_recovery_projection.py")
    if not target.is_file():
        raise SystemExit(f"anchor file missing: {target}")
    text = target.read_text(encoding="utf-8")
    if MARKER in text:
        raise SystemExit("fixture already applied")
    target.write_text(text.rstrip("\n") + "\n" + FIXTURE, encoding="utf-8")
    print(f"fixture F4 appended to {target}")


if __name__ == "__main__":
    sys.exit(main())
