"""Host-path redaction boundaries (second failure-path round, 2026-09-18).

Two leaks in `_redact_host_paths`, both of which produce text that *looks*
redacted while still naming host state:

1. a home path (`~/.agent-os/x`) was left verbatim, because the pattern's
   lookbehind treats the `~` as a boundary it may not start after - so the
   strongest form of the leak (a path under the operator's home directory) was
   the one form that survived;
2. the workspace root was substituted with a bare textual replace, so a
   *sibling* directory whose name merely starts with the root's name was
   rewritten into a fake relative path: root `/tmp/x/ws` turned the host path
   `/tmp/x/ws-backup/secret.txt` into `.-backup/secret.txt`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from domain_packs.developer_agent import workspace_capability
from domain_packs.developer_agent.workspace_capability import _redact_host_paths


@pytest.mark.parametrize(
    ("message", "expected"),
    (
        ("cannot read ~/.agent-os/runtime.json", "cannot read runtime.json"),
        ("cannot read ~/.ssh/id_ed25519", "cannot read id_ed25519"),
        ("denied: /secret", "denied: secret"),
        ("denied: /etc/passwd", "denied: passwd"),
        ("cannot read /usr/local/bin/tool", "cannot read tool"),
    ),
)
def test_a_home_or_single_segment_path_is_still_redacted(
    message: str, expected: str
) -> None:
    assert _redact_host_paths(message, Path("/tmp/x/ws")) == expected


@pytest.mark.parametrize(
    "host_path",
    (
        "/tmp/x/ws-backup/secret.txt",
        "/tmp/x/ws2/secret.txt",
        "/tmp/x/ws.secret/notes.txt",
    ),
)
def test_a_sibling_directory_is_not_rewritten_as_a_relative_path(
    host_path: str,
) -> None:
    """`ws-backup` is not inside `ws`; redaction must not invent a relative path
    that reads as if it were (and must not leave the host path either)."""

    redacted = _redact_host_paths(f"cannot read {host_path}", Path("/tmp/x/ws"))

    assert redacted == f"cannot read {Path(host_path).name}"
    assert "ws-backup" not in redacted
    assert "ws2" not in redacted
    assert "ws.secret" not in redacted


def test_a_real_workspace_path_is_still_relative() -> None:
    """The boundary fix must not disable the in-workspace rewrite."""

    root = Path("/tmp/x/ws")
    assert (
        _redact_host_paths(f"cannot read {root}/sub/fixture.txt", root)
        == "cannot read sub/fixture.txt"
    )
    assert _redact_host_paths(f"denied: {root}", root) == "denied: ."


def test_a_path_fragment_is_not_touched() -> None:
    """Relative paths the caller already uses stay exactly as they are."""

    for message in (
        "workspace.edit old_string must match exactly once in pkg/sub/module.py",
        "keep -var/foo.txt relative",
    ):
        assert _redact_host_paths(message, Path("/tmp/x/ws")) == message


def test_redaction_still_relativises_through_the_adapter_error_path(
    tmp_path: Path,
) -> None:
    """The adapter keeps the exception class and the workspace-relative form."""

    redacted = workspace_capability._redacted_error(
        FileNotFoundError(f"[Errno 2] No such file: '{tmp_path}-backup/notes.txt'"),
        tmp_path,
    )

    assert isinstance(redacted, FileNotFoundError)
    assert str(redacted) == "[Errno 2] No such file: 'notes.txt'"
    assert str(tmp_path) not in str(redacted)
