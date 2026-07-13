"""RED/GREEN contract for the fresh SPINE-E2E-2 receipt instrument."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_os_core import WorkerInterrupted
from product_evals.spine_e2e_2.protocol import interrupt_batch, resume_spine
from product_evals.spine_e2e_2.public_surface import public_evidence


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
def test_malformed_apply_receipt_identity_fails_closed(
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
def test_interrupt_rejects_second_replaced_or_non_apply_increase(
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


def test_normal_resume_allows_tests_receipt_but_preserves_apply_keys() -> None:
    class App:
        calls = 0

        def run_task(
            self, task_id: str, inputs: dict[str, str], **kwargs: object
        ) -> object:
            self.calls += 1
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


def test_resume_rejects_second_apply_or_replaced_equal_count() -> None:
    class App:
        def run_task(
            self, task_id: str, inputs: dict[str, str], **kwargs: object
        ) -> object:
            return SimpleNamespace(observed_outcome=object())

    for keys in (["apply-1", "apply-2"], ["replacement"]):
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


def test_composition_surface_accepts_normal_tests_receipt(tmp_path: Path) -> None:
    app = EvidenceApp([_event("workspace.apply_patch", "apply-1")])
    snapshots = [
        public_evidence(
            app, "task-1", tmp_path / "workspace", tmp_path / "provider.jsonl"
        )
    ]
    app.events.append(_event("workspace.run_tests", "tests-1"))
    snapshots.extend(
        [
            public_evidence(
                app, "task-1", tmp_path / "workspace", tmp_path / "provider.jsonl"
            ),
            public_evidence(
                app, "task-1", tmp_path / "workspace", tmp_path / "provider.jsonl"
            ),
        ]
    )

    class ResumeApp(EvidenceApp):
        def run_task(
            self, task_id: str, inputs: dict[str, str], **kwargs: object
        ) -> object:
            return SimpleNamespace(observed_outcome=object())

    snapshots[0]["lease_fence"] = 1
    snapshots[1]["lease_fence"] = snapshots[2]["lease_fence"] = 2
    values = iter(snapshots)
    result = resume_spine(
        ResumeApp(app.events), ("task-1",), lambda app, task: dict(next(values))
    )
    assert result[0]["resumed_terminal"]["action_receipt_count"] == 2
