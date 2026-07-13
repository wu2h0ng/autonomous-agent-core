"""Protocol and public-surface boundaries for the corrected successor."""

from __future__ import annotations

import importlib
import inspect
import os
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agent_os_core import ConcurrentWriteError, WorkerInterrupted
from product_evals.spine_e2e_4.identity import IDENTITY


def _protocol() -> Any:
    return importlib.import_module("product_evals.spine_e2e_4.protocol")


def _surface() -> Any:
    return importlib.import_module("product_evals.spine_e2e_4.public_surface")


def test_contract_ids_and_protocol_schemas_are_identity_derived() -> None:
    protocol = _protocol()
    case = {"case_id": "case-1", "goal": "change subject"}

    payload = protocol.build_case_contracts(
        case, datetime(2026, 7, 13, tzinfo=timezone.utc)
    )

    assert payload["goal"]["goal_id"] == f"goal:{IDENTITY.slug}:case-1"
    assert payload["commitment"]["commitment_id"] == (
        f"commitment:{IDENTITY.slug}:case-1"
    )
    assert payload["workflow"]["workflow_id"] == (f"workflow:{IDENTITY.slug}:case-1")
    assert payload["expected_outcome"]["expected_outcome_id"] == (
        f"expected:{IDENTITY.slug}:case-1"
    )
    source = inspect.getsource(protocol)
    for sequence in (1, 2, 3):
        assert f"spine-e2e-{sequence}" not in source
        assert f"SPINE-E2E-{sequence}" not in source


def test_provider_environment_clears_every_correlated_stale_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    surface = _surface()
    stale = {
        "AGENT_OS_PROVIDER_BASE_URL": "old",
        "AGENT_OS_PROVIDER_MODEL": "old",
        "AGENT_OS_PROVIDER_TEMPERATURE": "1",
        "AGENT_OS_PROVIDER_API_KEY_ENV": "STALE_PROVIDER_KEY",
        "OPENAI_API_KEY": "old",
        "AGENT_OS_RUNTIME_PROVIDER_KEY": "old",
        "STALE_PROVIDER_KEY": "old",
        "SPINE_E2E_3_PROVIDER_KEY": "old",
        IDENTITY.provider_api_key_env: "old",
    }
    for name, value in stale.items():
        monkeypatch.setenv(name, value)

    base_url = "http://127.0.0.1:43123/v1"
    surface.configure_provider_environment(base_url)

    assert {
        name: os.environ.get(name) for name in IDENTITY.provider_environment(base_url)
    } == IDENTITY.provider_environment(base_url)
    for name in (
        "OPENAI_API_KEY",
        "AGENT_OS_RUNTIME_PROVIDER_KEY",
        "STALE_PROVIDER_KEY",
        "SPINE_E2E_3_PROVIDER_KEY",
    ):
        assert name not in os.environ


def test_open_application_fails_closed_on_provider_identity_mismatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    surface = _surface()

    class Application:
        def __init__(self, **_: object) -> None:
            pass

        def provider_status(self) -> dict[str, object]:
            return {**IDENTITY.expected_provider_status(), "model_id": "stale"}

    monkeypatch.setattr(surface, "AgentOSApplication", Application)
    with pytest.raises(RuntimeError, match="provider status mismatch"):
        surface.open_application(tmp_path / "state.sqlite3", tmp_path / "workspace")


def test_interrupt_requires_one_new_apply_receipt_and_no_provider_call() -> None:
    protocol = _protocol()

    class App:
        def run_task(self, task_id: str, inputs: object, **kwargs: object) -> None:
            assert kwargs == {"stop_after_node": "apply"}
            raise WorkerInterrupted("apply")

    snapshots = iter(
        [
            {
                "apply_receipt_idempotency_keys": [],
                "workspace_tree_sha256": "before",
                "provider_ledger_sha256": "same",
            },
            {
                "apply_receipt_idempotency_keys": ["apply-1"],
                "workspace_tree_sha256": "after",
                "provider_ledger_sha256": "same",
            },
        ]
    )

    result = protocol.interrupt_batch(
        App(), ("task-1",), lambda app, task: next(snapshots)
    )

    assert result[0]["apply_receipt_idempotency_keys"] == ["apply-1"]


def test_active_lease_probe_is_denied_without_public_state_mutation() -> None:
    protocol = _protocol()

    class App:
        def run_task(self, task_id: str, inputs: object, **kwargs: object) -> None:
            assert kwargs == {"recover_stale_lease": False}
            raise ConcurrentWriteError("active")

    snapshot = {"lease_fence": 7, "state": "unchanged"}
    result = protocol.probe_active_lease(
        App(), ("task-1",), lambda app, task: dict(snapshot)
    )

    assert result == [snapshot]


def test_resume_advances_fence_once_preserves_apply_sequence_and_replays_exactly() -> (
    None
):
    protocol = _protocol()

    class App:
        def run_task(self, task_id: str, inputs: object, **kwargs: object) -> object:
            assert kwargs == {"recover_stale_lease": False}
            return SimpleNamespace(observed_outcome=object())

    before = {
        "lease_fence": 7,
        "apply_receipt_idempotency_keys": ["apply-1"],
        "provider_ledger_sha256": "same",
    }
    terminal = {
        "lease_fence": 8,
        "apply_receipt_idempotency_keys": ["apply-1"],
        "provider_ledger_sha256": "same",
    }
    snapshots = iter([before, terminal, terminal])

    result = protocol.resume_spine(
        App(), ("task-1",), lambda app, task: dict(next(snapshots))
    )

    assert result == [{"resumed_terminal": terminal, "terminal_replay": terminal}]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"unexpected": True},
        {
            "schema_version": IDENTITY.schema("adjudication-input"),
            "expected_case_ids": [],
            "bindings": {},
            "phases": {},
            "recovery_configuration": [],
            "cases": {},
            "unknown": "field",
        },
    ],
)
def test_adjudicator_marks_partial_or_unknown_top_level_protocol_invalid(
    payload: dict[str, object],
) -> None:
    result = _protocol().adjudicate_spine(payload)

    assert result["verdict"] == "INVALID"
    assert result["verified_case_count"] == 0
    assert result["reason_codes"]
    assert result["schema_version"] == IDENTITY.schema("adjudication-result")
