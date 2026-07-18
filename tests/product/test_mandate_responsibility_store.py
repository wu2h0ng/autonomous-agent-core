from __future__ import annotations

import sqlite3
from datetime import timedelta

import pytest

from agent_os_contracts import (
    Goal,
    MandateOperationalStatus,
    MandateTaskLinkCommand,
    MandateTaskLinkRevocationCommand,
    PrincipalIdentity,
    PrincipalRole,
    RatifiedMandateRef,
    canonical_json,
)
from agent_os_core import (
    MandateResponsibilityConflict,
    MandateResponsibilityDenied,
    MandateResponsibilityPersistenceConflict,
    SQLiteMandateResponsibilityStore,
)
from tests.product.test_mandate_observation_authorization import (
    NOW,
    _apps,
    _command,
)


def _setup(tmp_path):
    database, owner, admin = _apps(tmp_path)
    admin.authorize_mandate_observation_binding(
        "mandate:build-agent-os", _command()
    )
    task = owner.create_task(
        Goal(
            goal_id="goal:responsibility",
            tenant_id="tenant:local",
            workspace_id="workspace:local",
            created_by="principal:owner",
            created_at=NOW,
            statement="Ship a responsibility view",
        ).model_dump(mode="json")
    )
    store = SQLiteMandateResponsibilityStore(database, clock=lambda: NOW)
    return database, owner, admin, task, store


def _admin(**updates: object) -> PrincipalIdentity:
    values: dict[str, object] = {
        "principal_id": "principal:security",
        "tenant_id": "tenant:local",
        "workspace_id": "workspace:local",
        "role": PrincipalRole.TENANT_ADMIN,
        "authenticated_at": NOW,
    }
    values.update(updates)
    return PrincipalIdentity.model_validate(values)


def _connection(database) -> sqlite3.Connection:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    return connection


def _non_responsibility_snapshot(database) -> dict[str, tuple[tuple[object, ...], ...]]:
    connection = _connection(database)
    try:
        names = tuple(
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
            if not str(row[0]).startswith("mandate_responsibility_")
        )
        return {
            name: tuple(
                tuple(row)
                for row in connection.execute(
                    f'SELECT * FROM "{name}" ORDER BY rowid'
                ).fetchall()
            )
            for name in names
        }
    finally:
        connection.close()


def test_only_same_scope_tenant_admin_can_link(tmp_path) -> None:
    _, owner, _, task, store = _setup(tmp_path)
    command = MandateTaskLinkCommand(task_id=task.task_id, reason="owned work")

    with pytest.raises(MandateResponsibilityDenied, match="TENANT_ADMIN"):
        store.create_link(command, "mandate:build-agent-os", owner.principal)
    for actor in (
        _admin(tenant_id="tenant:other"),
        _admin(workspace_id="workspace:other"),
    ):
        with pytest.raises(MandateResponsibilityDenied, match="scope"):
            store.create_link(command, "mandate:build-agent-os", actor)


def test_link_requires_exact_dual_mandate_join_and_active_time(tmp_path) -> None:
    database, _, admin, task, store = _setup(tmp_path)
    command = MandateTaskLinkCommand(task_id=task.task_id)
    connection = _connection(database)
    try:
        original = connection.execute(
            "SELECT mandate_json FROM situated_mandates"
        ).fetchone()
        assert original is not None
        mandate = RatifiedMandateRef.model_validate_json(original[0])

        connection.execute("DELETE FROM situated_mandates")
        connection.commit()
        with pytest.raises(MandateResponsibilityDenied, match="operational"):
            store.create_link(command, "mandate:build-agent-os", admin.principal)

        mismatched = mandate.model_copy(update={"workspace_record_digest": "f" * 64})
        connection.execute(
            "INSERT INTO situated_mandates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                mismatched.owner_principal_id,
                mismatched.tenant_id,
                mismatched.workspace_id,
                mismatched.mandate_id,
                mismatched.version,
                mismatched.mandate_digest,
                mismatched.status.value,
                mismatched.correction_epoch,
                canonical_json(mismatched),
            ),
        )
        connection.commit()
        with pytest.raises(MandateResponsibilityPersistenceConflict, match="join"):
            store.create_link(command, "mandate:build-agent-os", admin.principal)

        paused = mandate.model_copy(update={"status": MandateOperationalStatus.PAUSED})
        connection.execute(
            "UPDATE situated_mandates SET status = ?, mandate_json = ?",
            (paused.status.value, canonical_json(paused)),
        )
        connection.commit()
        with pytest.raises(MandateResponsibilityDenied, match="active"):
            store.create_link(command, "mandate:build-agent-os", admin.principal)

        expired = mandate.model_copy(update={"expires_at": NOW + timedelta(seconds=1)})
        connection.execute(
            "UPDATE situated_mandates SET status = ?, mandate_json = ?",
            (expired.status.value, canonical_json(expired)),
        )
        connection.commit()
        late_store = SQLiteMandateResponsibilityStore(
            database, clock=lambda: NOW + timedelta(seconds=2)
        )
        with pytest.raises(MandateResponsibilityDenied, match="active"):
            late_store.create_link(command, "mandate:build-agent-os", admin.principal)
    finally:
        connection.close()


def test_link_rejects_malformed_or_replaced_task_creation_identity(tmp_path) -> None:
    database, _, admin, task, store = _setup(tmp_path)
    connection = _connection(database)
    try:
        connection.execute(
            "UPDATE task_events SET event_type = 'RUN_STARTED' "
            "WHERE task_id = ? AND sequence = 1",
            (task.task_id,),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(MandateResponsibilityPersistenceConflict, match="TASK_CREATED"):
        store.create_link(
            MandateTaskLinkCommand(task_id=task.task_id),
            "mandate:build-agent-os",
            admin.principal,
        )


def test_exact_replay_conflict_and_no_mutation_of_product_truth(tmp_path) -> None:
    database, owner, admin, task, store = _setup(tmp_path)
    before = _non_responsibility_snapshot(database)
    command = MandateTaskLinkCommand(task_id=task.task_id, reason="mainline")

    first = store.create_link(command, "mandate:build-agent-os", admin.principal)
    replay = store.create_link(command, "mandate:build-agent-os", admin.principal)
    assert replay == first
    with pytest.raises(MandateResponsibilityConflict, match="different command"):
        store.create_link(
            MandateTaskLinkCommand(task_id=task.task_id, reason="replacement"),
            "mandate:build-agent-os",
            admin.principal,
        )

    assert store.list_links(
        "mandate:build-agent-os", owner.principal
    ) == (first,)
    assert _non_responsibility_snapshot(database) == before
    assert owner.tasks.get_task(task.task_id) == task


def test_revocation_is_append_only_replayable_and_allows_same_epoch_relink(
    tmp_path,
) -> None:
    database, owner, admin, task, store = _setup(tmp_path)
    before = _non_responsibility_snapshot(database)
    command = MandateTaskLinkCommand(task_id=task.task_id, reason="mainline")
    first = store.create_link(command, "mandate:build-agent-os", admin.principal)
    revoke = MandateTaskLinkRevocationCommand(
        expected_link_digest=first.record_digest,
        reason="superseded",
    )

    first_revocation = store.revoke_link(
        revoke,
        "mandate:build-agent-os",
        first.link_id,
        admin.principal,
    )
    replay = store.revoke_link(
        revoke,
        "mandate:build-agent-os",
        first.link_id,
        admin.principal,
    )
    assert replay == first_revocation
    with pytest.raises(MandateResponsibilityConflict, match="revocation"):
        store.revoke_link(
            revoke.model_copy(update={"reason": "different"}),
            "mandate:build-agent-os",
            first.link_id,
            admin.principal,
        )
    assert store.list_links(
        "mandate:build-agent-os", owner.principal, include_revoked=False
    ) == ()
    assert store.list_links(
        "mandate:build-agent-os", owner.principal, include_revoked=True
    ) == (first,)

    second = store.create_link(command, "mandate:build-agent-os", admin.principal)
    assert second.association_id == first.association_id
    assert second.link_id != first.link_id
    assert second.prior_record_digest == first_revocation.record_digest
    assert store.list_links(
        "mandate:build-agent-os", owner.principal, include_revoked=False
    ) == (second,)
    assert _non_responsibility_snapshot(database) == before


def test_stale_digest_and_correction_epoch_drift_fail_closed(tmp_path) -> None:
    database, _, admin, task, store = _setup(tmp_path)
    first = store.create_link(
        MandateTaskLinkCommand(task_id=task.task_id),
        "mandate:build-agent-os",
        admin.principal,
    )
    with pytest.raises(MandateResponsibilityConflict, match="stale link digest"):
        store.revoke_link(
            MandateTaskLinkRevocationCommand(
                expected_link_digest="f" * 64,
                reason="stale",
            ),
            "mandate:build-agent-os",
            first.link_id,
            admin.principal,
        )

    connection = _connection(database)
    try:
        row = connection.execute(
            "SELECT mandate_json FROM situated_mandates"
        ).fetchone()
        assert row is not None
        mandate = RatifiedMandateRef.model_validate_json(row[0])
        drifted = mandate.model_copy(update={"correction_epoch": 1, "version": 2})
        connection.execute(
            "UPDATE situated_mandates SET mandate_version = 2, correction_epoch = 1, "
            "mandate_json = ?",
            (canonical_json(drifted),),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(MandateResponsibilityDenied, match="correction epoch"):
        store.revoke_link(
            MandateTaskLinkRevocationCommand(
                expected_link_digest=first.record_digest,
                reason="late",
            ),
            "mandate:build-agent-os",
            first.link_id,
            admin.principal,
        )
    with pytest.raises(MandateResponsibilityDenied, match="relink"):
        store.create_link(
            MandateTaskLinkCommand(task_id=task.task_id),
            "mandate:build-agent-os",
            admin.principal,
        )


def test_active_only_list_validates_revocation_before_hiding_link(tmp_path) -> None:
    database, owner, admin, task, store = _setup(tmp_path)
    link = store.create_link(
        MandateTaskLinkCommand(task_id=task.task_id),
        "mandate:build-agent-os",
        admin.principal,
    )
    store.revoke_link(
        MandateTaskLinkRevocationCommand(
            expected_link_digest=link.record_digest,
            reason="superseded",
        ),
        "mandate:build-agent-os",
        link.link_id,
        admin.principal,
    )
    connection = _connection(database)
    try:
        connection.execute(
            "UPDATE mandate_responsibility_revocations SET record_json = 'not-json' "
            "WHERE link_id = ?",
            (link.link_id,),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(MandateResponsibilityPersistenceConflict, match="revocation"):
        store.list_links(
            "mandate:build-agent-os",
            owner.principal,
            include_revoked=False,
        )


@pytest.mark.parametrize("operation", ["replay", "revoke"])
def test_same_epoch_operational_ref_digest_drift_blocks_link_writes(
    tmp_path, operation
) -> None:
    database, _, admin, task, store = _setup(tmp_path)
    command = MandateTaskLinkCommand(task_id=task.task_id)
    link = store.create_link(
        command,
        "mandate:build-agent-os",
        admin.principal,
    )
    connection = _connection(database)
    try:
        row = connection.execute(
            "SELECT mandate_json FROM situated_mandates"
        ).fetchone()
        assert row is not None
        operational = RatifiedMandateRef.model_validate_json(row[0])
        drifted = operational.model_copy(update={"ratified_by": "principal:replacement"})
        connection.execute(
            "UPDATE situated_mandates SET mandate_json = ?",
            (canonical_json(drifted),),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(MandateResponsibilityDenied, match="authority digest"):
        if operation == "replay":
            store.create_link(
                command,
                "mandate:build-agent-os",
                admin.principal,
            )
        else:
            store.revoke_link(
                MandateTaskLinkRevocationCommand(
                    expected_link_digest=link.record_digest,
                    reason="stale authority",
                ),
                "mandate:build-agent-os",
                link.link_id,
                admin.principal,
            )
