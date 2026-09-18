"""Workspace writes must not destroy unverified content silently.

Three things a governed write to a developer workspace used to do without
saying so, all three reachable from the interactive chat loop, which passes the
model's tool arguments to the adapter unchanged:

* ``workspace.apply_patch`` without ``expected_sha256`` replaced an existing
  file whatever was on disk. ``expected_sha256`` is optional in the tool schema,
  so a stale proposal -- formed from a read taken before someone else edited the
  file -- wiped that edit out and still sealed ``SUCCEEDED``.
* A file whose mode denies writing was replaced anyway, because ``os.replace``
  needs the *directory* writable, not the file; and the replacement silently
  reset the mode to the staging file's ``0600``.
* An ``OSError`` from a write named the real path it touched. The broker copies
  that text into the durable outcome and the model-visible tool result, so a
  host absolute path outside the workspace reached the model and the TUI.

The tests below pin the replacement rules: a write to an existing file either
says which guard its content passed (``overwrite_guard``), or is refused with a
message the caller can act on. Each one fails on the previous behaviour --
``overwrite_guard`` did not exist, the read-only file lost its content and its
mode, and the refusal that replaced the ``PermissionError`` did not exist.
"""

from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from agent_os_contracts import (
    ActionContract,
    CorrectionEpochVector,
    ResourceBudget,
)
from agent_os_core import CapabilityDenied

from domain_packs.developer_agent import DeveloperWorkspaceAdapter

TENANT = "tenant:workspace-write-safety"
WORKSPACE = "workspace:workspace-write-safety"
PRINCIPAL = "user:local"
RUN = "run:workspace-write-safety"

# A superuser writes through permission bits, so the refusals and the write
# failures below do not happen for it. Skip rather than assert a privilege the
# suite does not run with.
_NEEDS_UNPRIVILEGED_USER = pytest.mark.skipif(
    os.geteuid() == 0,
    reason="permission bits do not deny the root user",
)


def _action(
    capability_id: str,
    arguments: dict[str, Any],
    *,
    idempotency_key: str,
    run_id: str = RUN,
    task_id: str = "task:workspace-write-safety",
    tenant_id: str = TENANT,
    workspace_id: str = WORKSPACE,
    created_at: datetime | None = None,
) -> ActionContract:
    return ActionContract(
        action_id=f"action:{idempotency_key}",
        task_id=task_id,
        run_id=run_id,
        node_id=f"node:{idempotency_key}",
        principal_id=PRINCIPAL,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        capability_id=capability_id,
        capability_version="1",
        arguments_json=json.dumps(arguments),
        risk_tier=1,
        idempotency_key=idempotency_key,
        estimated_budget=ResourceBudget(
            max_cost_usd=Decimal("0"),
            max_duration_seconds=10,
            max_provider_tokens=0,
            max_tool_calls=1,
        ),
        policy_version="policy-1",
        observed_correction_epochs=CorrectionEpochVector(
            task_epoch=0, run_epoch=0, capability_epoch=0
        ),
        expected_outcome_id="expected:workspace-write-safety",
        candidate_envelope_id="envelope:workspace-write-safety",
        created_at=created_at or datetime.now(timezone.utc),
    )


def _execute(
    adapter: DeveloperWorkspaceAdapter,
    capability_id: str,
    arguments: dict[str, Any],
    *,
    idempotency_key: str = "run:write",
) -> dict[str, Any]:
    effect = adapter.execute(
        _action(capability_id, arguments, idempotency_key=idempotency_key)
    )
    return dict(effect.output)


def test_apply_patch_without_digest_reports_the_unchecked_overwrite(
    tmp_path: Path,
) -> None:
    """A stale full-file proposal is reported, not sealed as an ordinary write."""

    target = tmp_path / "fixture.txt"
    target.write_text("v1\n", encoding="utf-8")
    # Out-of-band change: the editor, a git checkout, another agent.
    target.write_text("v2 external\n", encoding="utf-8")
    adapter = DeveloperWorkspaceAdapter(tmp_path)

    output = _execute(
        adapter,
        "workspace.apply_patch",
        {"path": "fixture.txt", "content": "v3 stale\n"},
    )

    assert target.read_text(encoding="utf-8") == "v3 stale\n"
    assert output["overwrite_guard"] == "unchecked_existing_overwrite"
    assert output["before_sha256"] != output["applied_sha256"]
    assert "expected_sha256" in output["overwrite_guard_detail"]


def test_apply_patch_with_digest_reports_a_checked_write(tmp_path: Path) -> None:
    target = tmp_path / "fixture.txt"
    target.write_text("v1\n", encoding="utf-8")
    adapter = DeveloperWorkspaceAdapter(tmp_path)
    digest = _execute(adapter, "workspace.read", {"path": "fixture.txt"})["sha256"]

    output = _execute(
        adapter,
        "workspace.apply_patch",
        {"path": "fixture.txt", "content": "v2\n", "expected_sha256": digest},
    )

    assert output["overwrite_guard"] == "digest_checked"
    assert "overwrite_guard_detail" not in output
    assert output["before_sha256"] == digest


def test_apply_patch_creation_reports_a_new_file(tmp_path: Path) -> None:
    adapter = DeveloperWorkspaceAdapter(tmp_path)

    output = _execute(
        adapter,
        "workspace.apply_patch",
        {"path": "new.txt", "content": "created\n"},
    )

    assert output["overwrite_guard"] == "created_new_file"


def test_apply_patch_replay_reports_a_replay_not_a_silent_write(
    tmp_path: Path,
) -> None:
    target = tmp_path / "fixture.txt"
    target.write_text("before\n", encoding="utf-8")
    adapter = DeveloperWorkspaceAdapter(tmp_path)
    arguments: dict[str, Any] = {"path": "fixture.txt", "content": "after\n"}

    first = _execute(adapter, "workspace.apply_patch", arguments)
    replayed = _execute(adapter, "workspace.apply_patch", arguments)

    assert first["overwrite_guard"] == "unchecked_existing_overwrite"
    assert replayed["replayed"] is True
    assert replayed["overwrite_guard"] == "replayed"


def test_apply_patch_with_a_stale_digest_names_the_file_and_the_fix(
    tmp_path: Path,
) -> None:
    """A refusal says which file moved and what to do, not just "changed"."""

    target = tmp_path / "fixture.txt"
    target.write_text("v1\n", encoding="utf-8")
    adapter = DeveloperWorkspaceAdapter(tmp_path)
    stale = _execute(adapter, "workspace.read", {"path": "fixture.txt"})["sha256"]
    target.write_text("v2\n", encoding="utf-8")

    with pytest.raises(CapabilityDenied) as denial:
        _execute(
            adapter,
            "workspace.apply_patch",
            {"path": "fixture.txt", "content": "v3\n", "expected_sha256": stale},
        )

    message = str(denial.value)
    assert "fixture.txt changed after that digest was taken" in message
    assert "workspace.read" in message
    assert target.read_text(encoding="utf-8") == "v2\n"


def test_apply_patch_rejects_a_malformed_digest_instead_of_blaming_the_file(
    tmp_path: Path,
) -> None:
    target = tmp_path / "fixture.txt"
    target.write_text("v1\n", encoding="utf-8")
    adapter = DeveloperWorkspaceAdapter(tmp_path)

    with pytest.raises(CapabilityDenied) as denial:
        _execute(
            adapter,
            "workspace.apply_patch",
            {"path": "fixture.txt", "content": "v2\n", "expected_sha256": "abc"},
        )

    assert "expected_sha256 must be the 64-character hex digest" in str(denial.value)
    assert target.read_text(encoding="utf-8") == "v1\n"


@_NEEDS_UNPRIVILEGED_USER
def test_edit_refuses_a_read_only_file_and_keeps_its_content(
    tmp_path: Path,
) -> None:
    """A file whose mode denies writing is not replaced behind that mode."""

    target = tmp_path / "guarded.txt"
    target.write_text("guarded content\n", encoding="utf-8")
    os.chmod(target, 0o444)
    adapter = DeveloperWorkspaceAdapter(tmp_path)

    with pytest.raises(CapabilityDenied) as denial:
        _execute(
            adapter,
            "workspace.edit",
            {"path": "guarded.txt", "old_string": "guarded", "new_string": "hacked"},
        )

    assert "guarded.txt is read-only (mode 0444)" in str(denial.value)
    assert target.read_text(encoding="utf-8") == "guarded content\n"
    assert stat.S_IMODE(target.stat().st_mode) == 0o444


@_NEEDS_UNPRIVILEGED_USER
def test_preflight_refuses_a_read_only_file_before_any_reservation(
    tmp_path: Path,
) -> None:
    """The refusal is deterministic and runs before the broker reserves work."""

    target = tmp_path / "guarded.txt"
    target.write_text("guarded content\n", encoding="utf-8")
    os.chmod(target, 0o444)
    adapter = DeveloperWorkspaceAdapter(tmp_path)
    args: dict[str, Any] = {
        "path": "guarded.txt",
        "old_string": "guarded",
        "new_string": "hacked",
    }

    with pytest.raises(CapabilityDenied, match="is read-only \\(mode 0444\\)"):
        adapter.preflight("workspace.edit", args, "run:readonly")

    assert target.read_text(encoding="utf-8") == "guarded content\n"


@pytest.mark.parametrize("mode", [0o600, 0o640, 0o664, 0o755])
def test_edit_keeps_the_file_mode(tmp_path: Path, mode: int) -> None:
    """The replacement takes the destination's mode, not the staging file's."""

    target = tmp_path / "kept.txt"
    target.write_text("mode before\n", encoding="utf-8")
    os.chmod(target, mode)
    adapter = DeveloperWorkspaceAdapter(tmp_path)

    output = _execute(
        adapter,
        "workspace.edit",
        {"path": "kept.txt", "old_string": "before", "new_string": "after"},
    )

    assert target.read_text(encoding="utf-8") == "mode after\n"
    assert stat.S_IMODE(target.stat().st_mode) == mode
    # ``workspace.edit`` matched ``old_string`` against the text it decoded, so
    # it can bind the bytes it read and report a checked write rather than an
    # unchecked one.
    assert output["overwrite_guard"] == "digest_checked"


def test_compensation_restores_content_and_keeps_the_file_mode(
    tmp_path: Path,
) -> None:
    target = tmp_path / "compensated.txt"
    target.write_text("before\n", encoding="utf-8")
    os.chmod(target, 0o640)
    adapter = DeveloperWorkspaceAdapter(tmp_path)

    applied = _execute(
        adapter,
        "workspace.apply_patch",
        {"path": "compensated.txt", "content": "after\n"},
    )
    _execute(
        adapter,
        "workspace.compensate_patch",
        {
            "path": "compensated.txt",
            "original_action_key": "run:write",
            "compensation_ref": applied["compensation_ref"],
            "manifest_sha256": applied["manifest_sha256"],
        },
        idempotency_key="run:compensate",
    )

    assert target.read_text(encoding="utf-8") == "before\n"
    assert stat.S_IMODE(target.stat().st_mode) == 0o640


def test_edit_binds_the_bytes_it_matched_against(tmp_path: Path) -> None:
    """An outside write between the edit's read and its write is refused.

    ``workspace.edit`` reads the file, matches ``old_string`` against the
    decoded text and then writes a whole new file, so without a digest the
    bytes it matched are not bound to the bytes it replaces. The helper below
    is the read step ``_edit`` performs; the assertions replay the same
    sequence an edit performs -- read, someone else writes, write -- and pin
    that the second step refuses instead of overwriting the other write.
    """

    target = tmp_path / "raced.txt"
    target.write_text("original line\n", encoding="utf-8")
    adapter = DeveloperWorkspaceAdapter(tmp_path)
    args: dict[str, Any] = {
        "path": "raced.txt",
        "old_string": "original",
        "new_string": "edited",
    }

    patch_args = adapter._edit_patch_args(args)
    assert patch_args["expected_sha256"] is not None
    # ``old_string`` still occurs exactly once, so only the digest can catch
    # that the file moved under the edit.
    target.write_text("original line\nadded by someone else\n", encoding="utf-8")

    with pytest.raises(CapabilityDenied, match="changed after that digest"):
        adapter._apply_patch(patch_args, "run:raced")

    assert (
        target.read_text(encoding="utf-8")
        == "original line\nadded by someone else\n"
    )


def test_crlf_file_edit_is_reported_unchecked_rather_than_falsely_checked(
    tmp_path: Path,
) -> None:
    """Newline translation means there is no honest digest; do not claim one."""

    target = tmp_path / "crlf.txt"
    target.write_bytes(b"line one\r\nline two\r\n")
    adapter = DeveloperWorkspaceAdapter(tmp_path)

    output = _execute(
        adapter,
        "workspace.edit",
        {"path": "crlf.txt", "old_string": "line one", "new_string": "line 1"},
    )

    assert target.read_bytes() == b"line 1\nline two\n"
    assert output["overwrite_guard"] == "unchecked_existing_overwrite"


@_NEEDS_UNPRIVILEGED_USER
def test_failed_write_reports_a_workspace_relative_path(tmp_path: Path) -> None:
    """An ``OSError`` from the write carries no host path into the tool result.

    The write stages its replacement in the destination directory, so a
    directory that denies writing fails the rename with the real path in the
    message. The adapter reports the workspace-relative path instead, and the
    host root -- which the caller never chose and the model must not learn --
    stays out of the text.
    """

    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "fixture.txt").write_text("original\n", encoding="utf-8")
    adapter = DeveloperWorkspaceAdapter(tmp_path)
    os.chmod(tmp_path / "sub", 0o555)
    try:
        with pytest.raises(PermissionError) as failure:
            _execute(
                adapter,
                "workspace.apply_patch",
                {"path": "sub/fixture.txt", "content": "replacement\n"},
            )
    finally:
        os.chmod(tmp_path / "sub", 0o755)

    message = str(failure.value)
    assert "fixture.txt" in message
    assert str(tmp_path) not in message
    assert "Permission denied" in message
    assert (tmp_path / "sub" / "fixture.txt").read_text(encoding="utf-8") == (
        "original\n"
    )


@_NEEDS_UNPRIVILEGED_USER
def test_write_error_in_a_workspace_root_with_a_space_is_relative(
    tmp_path: Path,
) -> None:
    """A project directory may contain a space; the root still comes out."""

    root = tmp_path / "my project"
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "fixture.txt").write_text("original\n", encoding="utf-8")
    adapter = DeveloperWorkspaceAdapter(root)
    os.chmod(root / "sub", 0o555)
    try:
        with pytest.raises(PermissionError) as failure:
            _execute(
                adapter,
                "workspace.apply_patch",
                {"path": "sub/fixture.txt", "content": "replacement\n"},
            )
    finally:
        os.chmod(root / "sub", 0o755)

    message = str(failure.value)
    assert "sub/.fixture.txt" in message
    assert "my project" not in message
    assert str(tmp_path) not in message


def test_write_error_outside_the_workspace_shows_only_a_filename(
    tmp_path: Path,
) -> None:
    """A host path the workspace cannot relativise collapses to its name."""

    adapter = DeveloperWorkspaceAdapter(tmp_path)
    host_path = "/private/var/folders/zz/secret-dir/notes.txt"

    message = str(
        _execute_error_message(adapter, host_path)
    )
    assert "secret-dir" not in message
    assert "notes.txt" in message


def _execute_error_message(
    adapter: DeveloperWorkspaceAdapter, host_path: str
) -> BaseException:
    """Drive the adapter's write path with a message that names a host path."""

    from domain_packs.developer_agent import workspace_capability

    return workspace_capability._redacted_error(
        PermissionError(f"[Errno 13] Permission denied: '{host_path}'"),
        adapter.root,
    )


def test_redaction_leaves_relative_paths_alone() -> None:
    """A relative path the caller already uses is not a host path to rewrite."""

    from domain_packs.developer_agent import workspace_capability

    message = (
        "workspace.edit old_string must match exactly once (found 0) in "
        "pkg/sub/module.py"
    )
    assert (
        workspace_capability._redact_host_paths(message, Path("/tmp/ws")) == message
    )


def test_redaction_keeps_the_denied_exception_class() -> None:
    """Callers discriminating on the failure type keep working after redaction."""

    from domain_packs.developer_agent import workspace_capability

    redacted = workspace_capability._redacted_error(
        CapabilityDenied("cannot read /private/tmp/host-only/notes.txt"),
        Path("/tmp/ws"),
    )

    assert isinstance(redacted, CapabilityDenied)
    assert str(redacted) == "cannot read notes.txt"


def test_expired_write_is_still_denied_without_a_side_effect(
    tmp_path: Path,
) -> None:
    """Redaction and the new guard must not weaken the existing refusals."""

    adapter = DeveloperWorkspaceAdapter(tmp_path)

    with pytest.raises(CapabilityDenied, match="path must be a relative"):
        adapter.preflight(
            "workspace.apply_patch",
            {"path": "/etc/hosts", "content": "x\n"},
            "run:escape",
        )

    with pytest.raises(FileNotFoundError):
        adapter.preflight(
            "workspace.read", {"path": "missing.txt"}, "run:missing"
        )

    assert not (tmp_path / ".agent-os-artifacts" / "compensation").exists()


@_NEEDS_UNPRIVILEGED_USER
def test_unreadable_file_error_reports_a_workspace_relative_path(
    tmp_path: Path,
) -> None:
    """Reads leak host paths through the same broker text as writes."""

    target = tmp_path / "locked.txt"
    target.write_text("locked content\n", encoding="utf-8")
    os.chmod(target, 0o000)
    adapter = DeveloperWorkspaceAdapter(tmp_path)
    try:
        with pytest.raises(PermissionError) as failure:
            _execute(adapter, "workspace.read", {"path": "locked.txt"})
    finally:
        os.chmod(target, 0o600)

    message = str(failure.value)
    assert "locked.txt" in message
    assert str(tmp_path) not in message


def test_guard_is_visible_after_tool_result_truncation(tmp_path: Path) -> None:
    """The guard survives the chat loop's tool-result summary.

    The loop replaces a serialized result longer than its budget with a scalar
    ``summary``; the guard is a short string, so it must land in that summary
    rather than be cut off behind the ``path`` key. A patch result is small
    enough to arrive whole, so the summary path is what is pinned here.
    """

    from agent_os_core.agent_loop import _scalar_summary

    target = tmp_path / "fixture.txt"
    target.write_text("v1\n", encoding="utf-8")
    adapter = DeveloperWorkspaceAdapter(tmp_path)
    output = _execute(
        adapter,
        "workspace.apply_patch",
        {"path": "fixture.txt", "content": "v2\n"},
    )

    summary = _scalar_summary(output)

    assert summary["overwrite_guard"] == "unchecked_existing_overwrite"
    assert len(json.dumps(output, default=str)) < 8000


def test_guard_report_is_not_an_effect_binding(tmp_path: Path) -> None:
    """The durable receipt still binds exactly the four effect keys it expects.

    ``TaskService._record_action_receipt`` projects the effect down to ``path``,
    ``compensation_ref``, ``manifest_sha256`` and ``applied_sha256`` and refuses
    any other key set, so the report must not enter that projection.
    """

    target = tmp_path / "fixture.txt"
    target.write_text("v1\n", encoding="utf-8")
    adapter = DeveloperWorkspaceAdapter(tmp_path)
    output = _execute(
        adapter,
        "workspace.apply_patch",
        {"path": "fixture.txt", "content": "v2\n"},
    )

    projection = {
        key: str(output[key])
        for key in ("path", "compensation_ref", "manifest_sha256", "applied_sha256")
    }
    assert all(projection.values())
    assert "overwrite_guard" not in projection


def test_action_arguments_are_not_rewritten_by_the_guard(tmp_path: Path) -> None:
    """The guard is effect-layer reporting; the durable action keeps the args
    the caller proposed, so policy and approval decisions still bind them."""

    target = tmp_path / "fixture.txt"
    target.write_text("v1\n", encoding="utf-8")
    adapter = DeveloperWorkspaceAdapter(tmp_path)
    arguments: dict[str, Any] = {"path": "fixture.txt", "content": "v2\n"}
    action = _action(
        "workspace.apply_patch", arguments, idempotency_key="run:args"
    )

    adapter.execute(action)

    assert json.loads(action.arguments_json) == arguments


def test_edit_after_an_external_change_still_lands(tmp_path: Path) -> None:
    """The guard must not turn ordinary editing into a denial."""

    target = tmp_path / "notes.txt"
    target.write_text("alpha\n", encoding="utf-8")
    adapter = DeveloperWorkspaceAdapter(tmp_path)
    # The model formed this proposal from an older read of the file.
    target.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

    output = _execute(
        adapter,
        "workspace.edit",
        {"path": "notes.txt", "old_string": "alpha", "new_string": "ALPHA"},
    )

    assert target.read_text(encoding="utf-8") == "ALPHA\nbeta\ngamma\n"
    assert output["overwrite_guard"] == "digest_checked"


def test_guard_constants_are_the_only_reported_values(tmp_path: Path) -> None:
    """The four guard states are closed: no write reports an unknown value."""

    from domain_packs.developer_agent import workspace_capability

    known = {
        workspace_capability._OVERWRITE_GUARD_DIGEST_CHECKED,
        workspace_capability._OVERWRITE_GUARD_UNCHECKED,
        workspace_capability._OVERWRITE_GUARD_CREATED,
        workspace_capability._OVERWRITE_GUARD_REPLAYED,
    }
    target = tmp_path / "fixture.txt"
    target.write_text("v1\n", encoding="utf-8")
    adapter = DeveloperWorkspaceAdapter(tmp_path)
    digest = _execute(adapter, "workspace.read", {"path": "fixture.txt"})["sha256"]

    observed = {
        _execute(
            adapter,
            "workspace.apply_patch",
            {"path": "fixture.txt", "content": "a\n", "expected_sha256": digest},
            idempotency_key="run:guard:checked",
        )["overwrite_guard"],
        _execute(
            adapter,
            "workspace.apply_patch",
            {"path": "fixture.txt", "content": "b\n"},
            idempotency_key="run:guard:unchecked",
        )["overwrite_guard"],
        _execute(
            adapter,
            "workspace.apply_patch",
            {"path": "fresh.txt", "content": "c\n"},
            idempotency_key="run:guard:created",
        )["overwrite_guard"],
    }

    assert observed <= known


@_NEEDS_UNPRIVILEGED_USER
def test_read_only_file_cannot_be_reached_through_the_broker(
    tmp_path: Path,
) -> None:
    """The refusal runs on the real dispatch path, before any reservation.

    A refusal raised from the effect would seal a ``UNKNOWN`` receipt, which
    says the effect may or may not have landed. The check lives in the
    preflight, so the broker denies before reserving anything and the receipt
    never claims an uncertain write.
    """

    from agent_os_core import (
        CapabilityBroker,
        CorrectionAuthority,
        SQLiteTaskEventStore,
    )
    from tests.product.test_long_horizon_compensation import (
        _permissive_preflight,
        _permit,
        _test_claim,
    )

    target = tmp_path / "guarded.txt"
    target.write_text("guarded content\n", encoding="utf-8")
    os.chmod(target, 0o444)
    adapter = DeveloperWorkspaceAdapter(
        tmp_path,
        idempotency_store=SQLiteTaskEventStore(tmp_path / "state.sqlite3"),
    )
    correction = CorrectionAuthority()
    now = datetime.now(timezone.utc)
    # The collaboration fence helper holds its lease for ``task:long`` /
    # ``run:long`` in ``tenant:local`` / ``workspace:local``.
    action = _action(
        "workspace.edit",
        {"path": "guarded.txt", "old_string": "guarded", "new_string": "hacked"},
        idempotency_key="run:broker-readonly",
        run_id="run:long",
        task_id="task:long",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
    )
    permit = _permit(
        action,
        issued_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(minutes=5),
    )

    with pytest.raises(CapabilityDenied, match="is read-only"):
        CapabilityBroker(
            adapter,
            correction,
            collaboration_preflight=_permissive_preflight(),
        ).invoke(action, permit, execution_claim=_test_claim())

    assert target.read_text(encoding="utf-8") == "guarded content\n"
    assert not any(adapter.artifacts.iterdir())
