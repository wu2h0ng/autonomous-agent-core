"""Protocol and public-surface contract for the SPINE-E2E-3 successor."""

from __future__ import annotations

import inspect
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_os_core import WorkerInterrupted
from product_evals.spine_e2e_3.identity import IDENTITY
from product_evals.spine_e2e_3.protocol import (
    build_case_contracts,
    interrupt_batch,
    resume_spine,
)
from product_evals.spine_e2e_3.public_surface import (
    configure_provider_environment,
    open_application,
    public_evidence,
)


def _event(connector: object, key: object) -> dict[str, object]:
    return {
        "event_type": "ACTION_RECEIPT_RECORDED",
        "payload": {"receipt": {"connector_id": connector, "idempotency_key": key}},
    }


class EvidenceApp:
    def __init__(self, events: list[dict[str, object]]) -> None:
        self.events = events

    def task_json(self, task_id: str) -> dict[str, object]:
        return {"task_id": task_id, "status": "RUNNING", "sequence": 1}

    def evidence_json(self, task_id: str) -> list[dict[str, object]]:
        return list(self.events)

    def recovery_json(self, task_id: str) -> dict[str, object]:
        return {"lease_fence": 1}


def test_contract_identifiers_and_schema_text_are_derived_from_identity() -> None:
    from datetime import datetime, timezone

    case = {"case_id": "case-1", "goal": "change subject"}
    payload = build_case_contracts(case, datetime(2026, 7, 13, tzinfo=timezone.utc))

    assert payload["goal"]["goal_id"] == f"goal:{IDENTITY.slug}:case-1"
    assert payload["commitment"]["commitment_id"] == (
        f"commitment:{IDENTITY.slug}:case-1"
    )
    assert payload["commitment"]["task_id"] == f"task:{IDENTITY.slug}:case-1"
    assert payload["workflow"]["workflow_id"] == f"workflow:{IDENTITY.slug}:case-1"
    assert payload["expected_outcome"]["expected_outcome_id"] == (
        f"expected:{IDENTITY.slug}:case-1"
    )

    source = inspect.getsource(
        __import__("product_evals.spine_e2e_3.protocol", fromlist=["*"])
    )
    predecessor_slugs = tuple(
        f"spine-e2e-{sequence}" for sequence in range(1, IDENTITY.sequence)
    )
    forbidden = predecessor_slugs + tuple(value.upper() for value in predecessor_slugs)
    assert not any(value in source for value in forbidden)


def test_configure_provider_environment_clears_correlated_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale_keys = {
        "AGENT_OS_PROVIDER_BASE_URL": "old",
        "AGENT_OS_PROVIDER_MODEL": "old",
        "AGENT_OS_PROVIDER_TEMPERATURE": "1",
        "AGENT_OS_PROVIDER_API_KEY_ENV": "STALE_PROVIDER_KEY",
        "AGENT_OS_RUNTIME_PROVIDER_KEY": "old",
        "OPENAI_API_KEY": "old",
        "STALE_PROVIDER_KEY": "old",
        IDENTITY.provider_api_key_env: "old",
    }
    for name, value in stale_keys.items():
        monkeypatch.setenv(name, value)

    base_url = "http://127.0.0.1:43123/v1"
    configure_provider_environment(base_url)

    assert {
        name: os.environ.get(name) for name in IDENTITY.provider_environment(base_url)
    } == IDENTITY.provider_environment(base_url)
    for name in (
        "OPENAI_API_KEY",
        "AGENT_OS_RUNTIME_PROVIDER_KEY",
        "STALE_PROVIDER_KEY",
    ):
        assert name not in os.environ


def test_open_application_requires_identity_provider_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}

    class FakeApplication:
        def __init__(self, *, database: Path, workspace: Path) -> None:
            seen.update(database=database, workspace=workspace)

        def provider_status(self) -> dict[str, object]:
            return IDENTITY.expected_provider_status()

    monkeypatch.setattr(
        "product_evals.spine_e2e_3.public_surface.AgentOSApplication",
        FakeApplication,
    )
    database = tmp_path / "state" / "agent-os.sqlite3"
    workspace = tmp_path / "workspace"

    application = open_application(database, workspace)

    assert isinstance(application, FakeApplication)
    assert seen == {"database": database, "workspace": workspace}


def test_open_application_fails_closed_on_provider_status_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeApplication:
        def __init__(self, **_: object) -> None:
            pass

        def provider_status(self) -> dict[str, object]:
            return {**IDENTITY.expected_provider_status(), "model_id": "stale"}

    monkeypatch.setattr(
        "product_evals.spine_e2e_3.public_surface.AgentOSApplication",
        FakeApplication,
    )
    with pytest.raises(RuntimeError, match="provider status mismatch"):
        open_application(tmp_path / "state.sqlite3", tmp_path / "workspace")


def test_public_evidence_separates_total_receipts_from_apply_keys(
    tmp_path: Path,
) -> None:
    app = EvidenceApp(
        [
            _event("workspace.apply_patch", "apply-1"),
            _event("workspace.run_tests", "tests-1"),
        ]
    )
    value = public_evidence(
        app, "task-1", tmp_path / "workspace", tmp_path / "provider.jsonl"
    )
    assert value["action_receipt_count"] == 2
    assert value["apply_receipt_idempotency_keys"] == ["apply-1"]


@pytest.mark.parametrize(
    "event",
    [
        _event(None, "apply-1"),
        _event("workspace.apply_patch", None),
        _event("workspace.apply_patch", ""),
        _event("workspace.apply_patch", "   "),
        _event("   ", "apply-1"),
        {"event_type": "ACTION_RECEIPT_RECORDED", "payload": {}},
    ],
)
def test_malformed_action_receipt_identity_fails_closed(
    tmp_path: Path, event: dict[str, object]
) -> None:
    with pytest.raises(ValueError, match="malformed action receipt"):
        public_evidence(
            EvidenceApp([event]),
            "task-1",
            tmp_path / "workspace",
            tmp_path / "provider.jsonl",
        )


def test_interrupt_requires_exactly_one_appended_apply_key() -> None:
    class App:
        def run_task(
            self, task_id: str, inputs: dict[str, str], **kwargs: object
        ) -> None:
            assert kwargs == {"stop_after_node": "apply"}
            raise WorkerInterrupted("apply")

    snapshots = iter(
        [
            {
                "apply_receipt_idempotency_keys": [],
                "workspace_tree_sha256": "a",
                "provider_ledger_sha256": "p",
            },
            {
                "apply_receipt_idempotency_keys": ["apply-1"],
                "workspace_tree_sha256": "b",
                "provider_ledger_sha256": "p",
            },
        ]
    )
    result = interrupt_batch(App(), ("task-1",), lambda app, task: next(snapshots))
    assert result[0]["apply_receipt_idempotency_keys"] == ["apply-1"]


@pytest.mark.parametrize(
    "before,after",
    [
        (["old"], ["old", "new", "second"]),
        (["old"], ["replacement"]),
        ([], []),
    ],
)
def test_interrupt_rejects_non_single_apply_increase(
    before: list[str], after: list[str]
) -> None:
    class App:
        def run_task(
            self, task_id: str, inputs: dict[str, str], **kwargs: object
        ) -> None:
            raise WorkerInterrupted("apply")

    snapshots = iter(
        [
            {
                "apply_receipt_idempotency_keys": before,
                "workspace_tree_sha256": "a",
                "provider_ledger_sha256": "p",
            },
            {
                "apply_receipt_idempotency_keys": after,
                "workspace_tree_sha256": "b",
                "provider_ledger_sha256": "p",
            },
        ]
    )
    with pytest.raises(RuntimeError, match="exactly one new apply receipt"):
        interrupt_batch(App(), ("task-1",), lambda app, task: next(snapshots))


def test_normal_resume_allows_non_apply_receipt_and_preserves_apply_keys() -> None:
    class App:
        def run_task(
            self, task_id: str, inputs: dict[str, str], **kwargs: object
        ) -> object:
            return SimpleNamespace(observed_outcome=object())

    before = {
        "lease_fence": 1,
        "action_receipt_count": 1,
        "apply_receipt_idempotency_keys": ["apply-1"],
        "provider_ledger_sha256": "p",
    }
    terminal = {
        "lease_fence": 2,
        "action_receipt_count": 2,
        "apply_receipt_idempotency_keys": ["apply-1"],
        "provider_ledger_sha256": "p",
    }
    snapshots = iter([before, terminal, terminal])
    result = resume_spine(App(), ("task-1",), lambda app, task: dict(next(snapshots)))
    assert result == [{"resumed_terminal": terminal, "terminal_replay": terminal}]


@pytest.mark.parametrize("keys", [["apply-1", "apply-2"], ["replacement"]])
def test_resume_rejects_changed_apply_sequence(keys: list[str]) -> None:
    class App:
        def run_task(
            self, task_id: str, inputs: dict[str, str], **kwargs: object
        ) -> object:
            return SimpleNamespace(observed_outcome=object())

    snapshots = iter(
        [
            {
                "lease_fence": 1,
                "action_receipt_count": 1,
                "apply_receipt_idempotency_keys": ["apply-1"],
                "provider_ledger_sha256": "p",
            },
            {
                "lease_fence": 2,
                "action_receipt_count": len(keys),
                "apply_receipt_idempotency_keys": keys,
                "provider_ledger_sha256": "p",
            },
        ]
    )
    with pytest.raises(RuntimeError, match="apply receipt sequence"):
        resume_spine(App(), ("task-1",), lambda app, task: dict(next(snapshots)))
