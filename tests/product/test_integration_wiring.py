"""Integration tests: SQLite persistence + TaskService registry wiring."""

from __future__ import annotations

import json
from datetime import datetime, timezone


from agent_os_contracts import (
    CheckType,
    ExpectedOutcome,
    EvidenceBinding,
    EvidenceSourceType,
    PredicateConfirmation,
    PredicateKind,
    SuccessPredicate,
)

from agent_os_core.contract_inferencer_service import ContractInferencerService
from agent_os_core.event_store import InMemoryTaskEventStore
from agent_os_core.predicate_evaluator import (
    PREDICATE_CONJUNCTION_TYPE,
)
from agent_os_core.predicate_set_store import SQLitePredicateSetStore
from agent_os_core.provider import DeterministicProvider
from agent_os_core.task_service import TaskService


EMAIL_TOOL_SCHEMA = {
    "tool_name": "email_send",
    "description": "Send an email",
    "parameters": {
        "type": "object",
        "properties": {
            "to": {"type": "string", "minLength": 1},
            "subject": {"type": "string"},
        },
        "required": ["to", "subject"],
    },
    "response": {
        "type": "object",
        "properties": {
            "status_code": {"type": "integer"},
            "body": {
                "type": "object",
                "properties": {"message_id": {"type": "string"}},
            },
        },
    },
    "errors": [
        {"status": 400, "action": "abort"},
        {"status": 500, "action": "retry", "max_retries": 2},
    ],
}

MANDATE = 'Send a welcome email to new-user@example.com with subject "Welcome".'


def _llm_response() -> str:
    return json.dumps([
        {
            "predicate_id": "pred:sem:001",
            "kind": "SEMANTIC",
            "description": "The email API returned 200",
            "check_type": "TOOL_RESPONSE",
            "check_params": {
                "tool_name": "email_send",
                "condition": {"$.status_code": {"$gte": 200, "$lt": 300}},
            },
            "evidence_bindings": [{
                "binding_id": "bind:sem1",
                "source_type": "TOOL_RESPONSE",
                "source_selector": "email_send",
                "extract_path": "$.status_code",
                "relation": "confirms success",
            }],
            "confidence": 0.95,
            "falsifiable": False,
            "blocking": False,
            "source": "llm:test-model",
            "meta_template": "evidence_anchor",
            "scope_tags": [],
        },
    ])


class TestSQLitePredicateSetStore:
    def test_save_and_load_roundtrip(self, tmp_path):
        store = SQLitePredicateSetStore(tmp_path / "test.sqlite3")
        from agent_os_contracts import PredicateSet

        ps = PredicateSet(
            set_id="set:1",
            contract_id="contract:1",
            task_id="task:1",
            tenant_id="tenant:1",
            workspace_id="ws:1",
            predicates=(
                SuccessPredicate(
                    predicate_id="pred:1",
                    kind=PredicateKind.STRUCTURAL,
                    description="test",
                    check_type=CheckType.FIELD_PRESENCE,
                    check_params={},
                    evidence_bindings=(EvidenceBinding(
                        binding_id="bind:1",
                        source_type=EvidenceSourceType.ARTIFACT,
                        source_selector="output.json",
                        relation="test",
                    ),),
                    confidence=1.0,
                    falsifiable=True,
                    blocking=True,
                    source="mechanical:test",
                ),
            ),
            frozen_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        digest = ps.content_key()
        store.save(ps)
        assert store.exists(digest)

        loaded = store.load(digest)
        assert loaded is not None
        assert loaded.content_key() == digest
        assert loaded.set_id == "set:1"
        assert len(loaded.predicates) == 1
        assert loaded.predicates[0].predicate_id == "pred:1"
        store.close()

    def test_load_nonexistent_returns_none(self, tmp_path):
        store = SQLitePredicateSetStore(tmp_path / "test.sqlite3")
        assert store.load("nonexistent") is None
        assert store.exists("nonexistent") is False
        store.close()

    def test_save_idempotent(self, tmp_path):
        store = SQLitePredicateSetStore(tmp_path / "test.sqlite3")
        from agent_os_contracts import PredicateSet

        ps = PredicateSet(
            set_id="set:1",
            contract_id="contract:1",
            task_id="task:1",
            tenant_id="tenant:1",
            workspace_id="ws:1",
            predicates=(
                SuccessPredicate(
                    predicate_id="pred:1",
                    kind=PredicateKind.STRUCTURAL,
                    description="test",
                    check_type=CheckType.FIELD_PRESENCE,
                    check_params={},
                    evidence_bindings=(EvidenceBinding(
                        binding_id="bind:1",
                        source_type=EvidenceSourceType.ARTIFACT,
                        source_selector="output.json",
                        relation="test",
                    ),),
                    confidence=1.0,
                    falsifiable=True,
                    blocking=True,
                    source="mechanical:test",
                ),
            ),
            frozen_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        store.save(ps)
        store.save(ps)  # should not raise
        assert store.exists(ps.content_key())
        store.close()


class TestContractInferencerService:
    def test_full_lifecycle_with_persistence(self, tmp_path):
        provider = DeterministicProvider(text=_llm_response())
        service = ContractInferencerService(
            provider=provider,
            model_id="test-model",
            store_path=str(tmp_path / "predicate-sets.sqlite3"),
        )

        # Stage 0-3: infer
        contract, report = service.infer(
            mandate_text=MANDATE,
            tool_schemas=[EMAIL_TOOL_SCHEMA],
            task_id="task:int:1",
        )
        assert contract is not None
        assert report.pipeline_state == "CONFIRMATION_PENDING"

        # Stage 4.5: confirm
        sem_preds = [
            p for p in contract.success_predicates
            if p.kind is PredicateKind.SEMANTIC
        ]
        confirmations = [
            PredicateConfirmation(
                predicate_id=p.predicate_id,
                decision="approve",
                confirmed_by="operator:test",
                confirmed_at=datetime.now(timezone.utc),
            )
            for p in sem_preds
        ]
        contract, predicate_set, report = service.apply_confirmation(
            contract, confirmations
        )
        assert report.pipeline_state == "FROZEN"
        assert predicate_set is not None

        # Verify persistence
        digest = predicate_set.content_key()
        assert service.predicate_set_store.exists(digest)
        loaded = service.predicate_set_store.load(digest)
        assert loaded is not None
        assert len(loaded.predicates) == len(predicate_set.predicates)

        # Build ExpectedOutcome
        frozen_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        expected = service.build_expected_outcome(
            predicate_set,
            task_id="task:int:1",
            tenant_id="tenant:1",
            workspace_id="ws:1",
            frozen_at=frozen_at,
        )
        assert expected.evaluator_type == PREDICATE_CONJUNCTION_TYPE
        assert expected.evaluator_version == digest
        service.close()


class TestTaskServiceRegistryDispatch:
    """Verify TaskService dispatches predicate:conjunction to the registered evaluator."""

    def test_registry_dispatches_predicate_evaluator(self, tmp_path):
        # Build a frozen predicate set via the service
        provider = DeterministicProvider(text=_llm_response())
        service = ContractInferencerService(
            provider=provider,
            model_id="test-model",
            store_path=str(tmp_path / "ps.sqlite3"),
        )
        contract, report = service.infer(
            mandate_text=MANDATE,
            tool_schemas=[EMAIL_TOOL_SCHEMA],
            task_id="task:reg:1",
        )
        assert contract is not None
        sem_preds = [
            p for p in contract.success_predicates
            if p.kind is PredicateKind.SEMANTIC
        ]
        confirmations = [
            PredicateConfirmation(
                predicate_id=p.predicate_id,
                decision="approve",
                confirmed_by="operator:test",
                confirmed_at=datetime.now(timezone.utc),
            )
            for p in sem_preds
        ]
        _, predicate_set, _ = service.apply_confirmation(contract, confirmations)
        assert predicate_set is not None

        # Create TaskService with in-memory event store
        event_store = InMemoryTaskEventStore()
        task_service = TaskService(event_store)

        # Register the predicate evaluator using the same SQLite store
        task_service.register_predicate_evaluator(service.predicate_set_store)

        # Verify registry recognizes the predicate evaluator type
        registry = task_service.evaluator_registry
        assert registry.get(PREDICATE_CONJUNCTION_TYPE) is not None

        # Build ExpectedOutcome and verify contract_error is None
        frozen_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        expected = service.build_expected_outcome(
            predicate_set,
            task_id="task:reg:1",
            tenant_id="tenant:1",
            workspace_id="ws:1",
            frozen_at=frozen_at,
        )
        assert registry.contract_error(expected) is None
        service.close()

    def test_registry_fails_closed_for_unknown_type(self):
        event_store = InMemoryTaskEventStore()
        task_service = TaskService(event_store)
        registry = task_service.evaluator_registry

        expected = ExpectedOutcome(
            expected_outcome_id="expected:unknown",
            task_id="task:1",
            tenant_id="tenant:1",
            workspace_id="ws:1",
            evaluator_type="unknown:evaluator",
            evaluator_version="1",
            evidence_requirements=("something",),
            failure_semantics=("failure",),
            threshold=1.0,
            observation_window_seconds=3600,
            frozen_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        assert registry.contract_error(expected) == "unsupported evaluator"
