from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from agent_os_contracts import (
    MandateResponsibilityView,
    MandateResponsibilityViewStatus,
    MandateTaskLink,
    MandateTaskLinkCommand,
    MandateOperationalStatus,
    ResponsibilityAttentionReason,
    ResponsibilityItem,
    ResponsibilityItemState,
    ResponsibilityWorkRoute,
    RunStatus,
    TaskStatus,
)


NOW = datetime(2026, 7, 18, 4, 0, tzinfo=timezone.utc)
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64


def _link_payload() -> dict[str, object]:
    return {
        "association_id": "mandate-task-association:one",
        "link_id": "mandate-task-link:one",
        "principal_id": "principal-1",
        "tenant_id": "tenant-1",
        "workspace_id": "workspace-1",
        "mandate_id": "mandate-1",
        "task_id": "task-1",
        "task_created_event_digest": DIGEST_A,
        "workspace_record_digest": DIGEST_B,
        "operational_mandate_ref_digest": DIGEST_C,
        "correction_epoch": 0,
        "linked_by": "admin-1",
        "linked_at": NOW,
        "command_digest": DIGEST_A,
        "record_digest": DIGEST_B,
    }


def _link(**updates: object) -> MandateTaskLink:
    return MandateTaskLink.model_validate({**_link_payload(), **updates})


def _selfdev_spec_payload() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "repository_head": "1" * 40,
        "isolated_branch": "codex/selfdev-task-1",
        "target_path": "packages/os_core/src/agent_os_core/example.py",
        "verifier_command": "pytest",
        "rollback_strategy": "compensate_task",
    }


def test_selfdev_link_command_persists_exact_execution_envelope() -> None:
    command = MandateTaskLinkCommand.model_validate(
        {
            "task_id": "task-1",
            "work_route": ResponsibilityWorkRoute.SELFDEV,
            "selfdev_spec": _selfdev_spec_payload(),
        }
    )

    assert command.model_dump(mode="json")["selfdev_spec"] == _selfdev_spec_payload()


def test_selfdev_precise_mode_persists_one_canonical_ordered_write_set() -> None:
    payload = _selfdev_spec_payload()
    payload.update(
        {
            "edit_mode": "agent_loop_precise",
            "additional_target_paths": [
                "packages/os_core/src/agent_os_core/example_secondary.py",
            ],
        }
    )

    command = MandateTaskLinkCommand.model_validate(
        {
            "task_id": "task-1",
            "work_route": ResponsibilityWorkRoute.SELFDEV,
            "selfdev_spec": payload,
        }
    )

    assert command.selfdev_spec is not None
    assert command.selfdev_spec.allowed_write_paths == (
        "packages/os_core/src/agent_os_core/example.py",
        "packages/os_core/src/agent_os_core/example_secondary.py",
    )
    assert command.model_dump(mode="json")["selfdev_spec"] == payload


@pytest.mark.parametrize(
    "additional_paths,error",
    [
        (
            ["packages/os_core/src/agent_os_core/example.py"],
            "write paths must be unique",
        ),
        (
            ["packages/os_core/src/agent_os_core/agent_cli.py"],
            "outside authority core",
        ),
        (["../escape.py"], "safe Agent OS product path"),
    ],
)
def test_selfdev_precise_mode_rejects_ambiguous_or_unsafe_write_sets(
    additional_paths: list[str],
    error: str,
) -> None:
    payload = _selfdev_spec_payload()
    payload.update(
        {
            "edit_mode": "agent_loop_precise",
            "additional_target_paths": additional_paths,
        }
    )
    with pytest.raises(ValidationError, match=error):
        MandateTaskLinkCommand.model_validate(
            {
                "task_id": "task-1",
                "work_route": ResponsibilityWorkRoute.SELFDEV,
                "selfdev_spec": payload,
            }
        )


def test_complete_replacement_mode_rejects_multiple_targets() -> None:
    payload = _selfdev_spec_payload()
    payload["additional_target_paths"] = [
        "packages/os_core/src/agent_os_core/example_secondary.py",
    ]
    with pytest.raises(ValidationError, match="agent_loop_precise"):
        MandateTaskLinkCommand.model_validate(
            {
                "task_id": "task-1",
                "work_route": ResponsibilityWorkRoute.SELFDEV,
                "selfdev_spec": payload,
            }
        )


def test_selfdev_route_requires_envelope_and_ordinary_route_forbids_it() -> None:
    with pytest.raises(ValidationError, match="SELFDEV route requires selfdev_spec"):
        MandateTaskLinkCommand(
            task_id="task-1",
            work_route=ResponsibilityWorkRoute.SELFDEV,
        )


def test_legacy_persisted_selfdev_link_without_envelope_remains_decodable() -> None:
    link = _link(work_route=ResponsibilityWorkRoute.SELFDEV)

    assert link.work_route is ResponsibilityWorkRoute.SELFDEV
    assert link.selfdev_spec is None

    with pytest.raises(ValidationError, match="only valid for SELFDEV route"):
        MandateTaskLinkCommand.model_validate(
            {
                "task_id": "task-1",
                "selfdev_spec": _selfdev_spec_payload(),
            }
        )


@pytest.mark.parametrize(
    "field,bad_value,expected_error",
    [
        ("repository_head", "1" * 39, "40-character lowercase Git object id"),
        ("isolated_branch", "main", "cannot target main/master/release"),
        ("isolated_branch", "release/2026-08", "cannot target main/master/release"),
        ("target_path", "../packages/os_core/pwn.py", "safe Agent OS product path"),
        ("target_path", ".git/config", "safe Agent OS product path"),
            (
                "target_path",
                "tests/product/test_acceptance.py",
                "safe Agent OS product path",
            ),
            (
                "target_path",
                "packages/os_core/src/agent_os_core/responsibility_surface.py",
                "outside authority core",
            ),
            (
                "target_path",
                "packages/os_core/src/agent_os_core/agent_loop.py",
                "outside authority core",
            ),
            (
                "target_path",
                "packages/os_core/src/agent_os_core/event_store.py",
                "outside authority core",
            ),
            (
                "target_path",
                "packages/contracts/src/agent_os_contracts/capability.py",
                "outside authority core",
            ),
            (
                "target_path",
                "apps/api_server/data_agent_report_policy.py",
                "outside authority core",
            ),
            (
                "target_path",
                "packages/os_core/src/agent_os_core/agent_cli.py",
                "outside authority core",
            ),
        ("verifier_command", "pytest -q; git push", "allowlisted verifier"),
        ("verifier_command", "git push origin main", "allowlisted verifier"),
    ],
)
def test_selfdev_execution_envelope_rejects_authority_and_escape_paths(
    field: str,
    bad_value: str,
    expected_error: str,
) -> None:
    spec = _selfdev_spec_payload()
    spec[field] = bad_value
    with pytest.raises(ValidationError, match=expected_error):
        MandateTaskLinkCommand.model_validate(
            {
                "task_id": "task-1",
                "work_route": ResponsibilityWorkRoute.SELFDEV,
                "selfdev_spec": spec,
            }
        )


@pytest.mark.parametrize(
    "server_owned_field,value",
    [
        ("principal_id", "principal-1"),
        ("tenant_id", "tenant-1"),
        ("workspace_id", "workspace-1"),
        ("mandate_id", "mandate-1"),
        ("workspace_record_digest", DIGEST_A),
        ("correction_epoch", 0),
        ("task_created_event_digest", DIGEST_A),
        ("task_activation_authorized", False),
        ("capability_grant_authorized", False),
        ("external_effects_authorized", False),
        ("outcome_status", "VERIFIED"),
        ("linked_at", NOW),
    ],
)
def test_link_command_rejects_server_owned_fields(
    server_owned_field: str, value: object
) -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        MandateTaskLinkCommand.model_validate(
            {"task_id": "task-1", server_owned_field: value}
        )


@pytest.mark.parametrize(
    "field",
    [
        "task_activation_authorized",
        "capability_grant_authorized",
        "external_effects_authorized",
    ],
)
@pytest.mark.parametrize("bad_value", [True, 0, 1, "false", None])
def test_link_authority_flags_accept_literal_false_only(
    field: str, bad_value: object
) -> None:
    payload = _link_payload()
    payload[field] = bad_value
    with pytest.raises(ValidationError, match="cannot grant execution authority"):
        MandateTaskLink.model_validate(payload)


@pytest.mark.parametrize(
    "state",
    [ResponsibilityItemState.UNKNOWN, ResponsibilityItemState.NEEDS_ATTENTION],
)
def test_attention_states_require_typed_reasons(state: ResponsibilityItemState) -> None:
    with pytest.raises(ValidationError, match="requires at least one attention reason"):
        ResponsibilityItem(
            link=_link(),
            task_status=None,
            run_status=None,
            state=state,
        )


@pytest.mark.parametrize(
    "state",
    [ResponsibilityItemState.TRACKED, ResponsibilityItemState.DONE_VERIFIED],
)
def test_non_attention_states_forbid_reasons(state: ResponsibilityItemState) -> None:
    with pytest.raises(ValidationError, match="cannot contain attention reasons"):
        ResponsibilityItem(
            link=_link(),
            task_status=TaskStatus.RUNNING,
            run_status=RunStatus.RUNNING,
            state=state,
            attention_reasons=(ResponsibilityAttentionReason.TASK_SOURCE_MISSING,),
        )


def test_reasons_and_view_rows_are_deterministic_and_unique() -> None:
    item_b = ResponsibilityItem(
        link=_link(link_id="mandate-task-link:b", task_id="task-b"),
        task_status=None,
        run_status=None,
        state=ResponsibilityItemState.UNKNOWN,
        attention_reasons=(
            ResponsibilityAttentionReason.TASK_SOURCE_MISSING,
            ResponsibilityAttentionReason.MANDATE_CORRECTION_DRIFT,
            ResponsibilityAttentionReason.TASK_SOURCE_MISSING,
        ),
    )
    item_a = ResponsibilityItem(
        link=_link(link_id="mandate-task-link:a", task_id="task-a"),
        task_status=TaskStatus.RUNNING,
        run_status=RunStatus.RUNNING,
        state=ResponsibilityItemState.TRACKED,
    )

    view = MandateResponsibilityView(
        principal_id="principal-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        mandate_id="mandate-1",
        mandate_status=MandateOperationalStatus.ACTIVE,
        desired_outcomes=("Outcome B", "Outcome A", "Outcome B"),
        status=MandateResponsibilityViewStatus.PARTIAL_UNKNOWN,
        items=(item_b, item_a, item_b),
        global_gaps=(
            ResponsibilityAttentionReason.SCHEDULE_SOURCE_MALFORMED,
            ResponsibilityAttentionReason.SCHEDULE_SOURCE_MALFORMED,
        ),
        workspace_record_digest=DIGEST_A,
        operational_mandate_ref_digest=DIGEST_B,
        computed_at=NOW,
        view_digest=DIGEST_C,
    )

    assert view.desired_outcomes == ("Outcome A", "Outcome B")
    assert tuple(item.link.link_id for item in view.items) == (
        "mandate-task-link:b",
        "mandate-task-link:a",
    )
    assert item_b.attention_reasons == (
        ResponsibilityAttentionReason.MANDATE_CORRECTION_DRIFT,
        ResponsibilityAttentionReason.TASK_SOURCE_MISSING,
    )
    assert view.global_gaps == (
        ResponsibilityAttentionReason.SCHEDULE_SOURCE_MALFORMED,
    )
