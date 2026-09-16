"""SPINE-1 batch 7/8: runtime/authority domain modules (corrigibility, approval_lite, connectors).

Ported from the donor os_core; imports rewritten to pack-native contracts.
"""

from __future__ import annotations

import pytest

from domain_packs.data_agent.action_connectors import ActionConnector, ActionConnectorRegistry
from domain_packs.data_agent.approval_lite import ApprovalLiteRuntime, ChoiceSetViolationError
from domain_packs.data_agent.corrigibility import AuditLog, CorrigibilityShell


# --- corrigibility: tamper-evident audit chain + pause shell -------------------------


def test_audit_log_appends_and_verifies_hash_chain() -> None:
    log = AuditLog()

    first = log.append({"event": "pause", "actor": "operator"})
    second = log.append({"event": "resume", "actor": "operator"})

    assert log.verify() is True
    assert len(log.entries()) == 2
    assert second.prev_hash == first.entry_hash
    assert second.seq == first.seq + 1


def test_corrigibility_shell_pause_and_resume() -> None:
    shell = CorrigibilityShell()

    assert shell.paused is False
    shell.op_pause()
    assert shell.paused is True
    shell.op_resume()
    assert shell.paused is False


# --- approval_lite: choice-set invariant present -------------------------------------


def test_approval_choice_set_violation_type_and_runtime_construct() -> None:
    runtime = ApprovalLiteRuntime()

    assert runtime is not None
    assert issubclass(ChoiceSetViolationError, Exception)


# --- action connector registry -------------------------------------------------------


def test_connector_registry_starts_empty_and_connector_is_abstract() -> None:
    registry = ActionConnectorRegistry()

    assert registry.list_connectors() == ()
    with pytest.raises(TypeError):
        ActionConnector()  # abstract
