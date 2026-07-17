from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

import pytest

from experiments.r_state_credit_1.action_grammar import ALL_ACTIONS
from experiments.r_state_credit_1.actor_interface import ActorRequest
from experiments.r_state_credit_1.execution_bridge import (
    ACTIVE_MANIFEST_FILENAME,
    ARK_BASE_URL_PROFILE,
    ARK_CREDENTIAL_ENV_REF,
    ARK_MODEL_SNAPSHOT,
    EXPECTED_PROVIDER_CALLS,
    ExecutionAdmission,
    ExecutionBridge,
    ExecutionBridgeViolation,
    InternalSealedRawRow,
    ReceiptVerification,
    ReceiptKind,
    ReservationClaimReceipt,
    ReservationTerminalReceipt,
    assert_raw_only,
    canonical_json,
    component_digests,
)
from experiments.r_state_credit_1.recast_provider_actor import (
    ProviderActor,
    ProviderBinding,
)


_TARGET_HEAD = "96eb79e1292d6b8f36ad990d3f97c554a9c33f3b"


class _Transport:
    def __init__(
        self,
        *,
        input_tokens: int = 1,
        output_tokens: int = 1,
        cost_microusd: int = 1,
        fail_on_call: int | None = None,
    ) -> None:
        self.calls = 0
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cost_microusd = cost_microusd
        self.fail_on_call = fail_on_call

    def complete(self, request: ActorRequest) -> dict[str, object]:
        self.calls += 1
        if self.calls == self.fail_on_call:
            raise TimeoutError("ambiguous provider effect")
        return {
            "action": "CONTINUE",
            "notes": None,
            "provider_receipt_id": f"provider-{self.calls}",
            "model_revision": ARK_MODEL_SNAPSHOT,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_microusd": self.cost_microusd,
        }


class _C7:
    owner_id = "c7-owner:security"
    policy_sha256 = "7" * 64
    correction_epoch = "epoch-2026-07-17"

    def __init__(self, abort_at_probe: int | None = None) -> None:
        self.probes = 0
        self.abort_at_probe = abort_at_probe

    def abort_requested(self) -> bool:
        self.probes += 1
        return self.probes == self.abort_at_probe


class _ExternalVerifier:
    def __init__(self, accepted: bool = True) -> None:
        self.accepted = accepted
        self.kinds: list[ReceiptKind] = []
        self.claimed: set[tuple[str, str, int]] = set()
        self.claim_receipts: dict[tuple[str, str, int], ReservationClaimReceipt] = {}
        self.terminal_receipts: dict[str, ReservationTerminalReceipt] = {}
        self.terminal_states: list[str] = []

    def verify(self, kind: ReceiptKind, receipt_bytes: bytes) -> ReceiptVerification:
        assert receipt_bytes
        self.kinds.append(kind)
        receipt = json.loads(receipt_bytes)
        roles = {
            ReceiptKind.PROVIDER_CANARY: ("provider-canary-attestor", "PROVIDER_CANARY_ACCEPTANCE"),
            ReceiptKind.C7: ("c7-owner", "C7_BINDING_ACCEPTANCE"),
            ReceiptKind.EXECUTOR: ("executor-reviewer", "EXECUTOR_ACCEPTANCE"),
            ReceiptKind.INTEGRITY: ("integrity-reviewer", "INTEGRITY_ACCEPTANCE"),
            ReceiptKind.FREEZE: ("freezer", "FREEZE_ACCEPTANCE"),
            ReceiptKind.RUN_AUTHORIZATION: ("run-authorizer", "RUN_AUTHORIZATION"),
        }
        role, purpose = roles[kind]
        return ReceiptVerification(
            registry_verified=self.accepted,
            principal_id=f"registry:{kind.value.lower()}",
            role=role,
            purpose=purpose,
            subject_sha256=receipt["subject_sha256"],
            artifact_sha256=_sha(receipt_bytes),
        )

    def claim(
        self,
        reservation: dict[str, object],
        run_id: str,
        envelope_sha256: str,
    ) -> ReservationClaimReceipt:
        key = (
            run_id,
            str(reservation["reservation_token_sha256"]),
            cast(int, reservation["attempt_epoch"]),
        )
        prior = self.claim_receipts.get(key)
        if prior is not None:
            return prior
        claimed = key not in self.claimed
        self.claimed.add(key)
        receipt = ReservationClaimReceipt(
            registry_verified=self.accepted,
            claimed=claimed,
            claim_id=f"claim:{run_id}:1",
            reservation_id=str(reservation["reservation_id"]),
            reservation_token_sha256=str(reservation["reservation_token_sha256"]),
            attempt_epoch=cast(int, reservation["attempt_epoch"]),
            cas_epoch=cast(int, reservation["cas_epoch"]),
            run_id=run_id,
            envelope_sha256=envelope_sha256,
        )
        self.claim_receipts[key] = receipt
        return receipt

    def query_claim(
        self,
        reservation: dict[str, object],
        run_id: str,
        envelope_sha256: str,
    ) -> ReservationClaimReceipt | None:
        _ = envelope_sha256
        return self.claim_receipts.get(
            (
                run_id,
                str(reservation["reservation_token_sha256"]),
                cast(int, reservation["attempt_epoch"]),
            )
        )

    def terminalize(
        self,
        claim: ReservationClaimReceipt,
        state: str,
        terminal_sha256: str,
    ) -> ReservationTerminalReceipt:
        self.terminal_states.append(state)
        prior = self.terminal_receipts.get(claim.claim_id)
        if prior is not None:
            assert prior.state == state and prior.terminal_sha256 == terminal_sha256
            return prior
        receipt = ReservationTerminalReceipt(
            registry_verified=self.accepted,
            claim_id=claim.claim_id,
            state=state,
            terminal_sha256=terminal_sha256,
            terminalized=True,
        )
        self.terminal_receipts[claim.claim_id] = receipt
        return receipt

    def query_terminal(
        self, claim_id: str
    ) -> ReservationTerminalReceipt | None:
        return self.terminal_receipts.get(claim_id)


class _WorkspaceProbe:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.revalidations = 0
        self.expected_components: dict[str, str] | None = None

    def admit(self, target_head: str, expected_components: dict[str, str]) -> str:
        assert target_head == _TARGET_HEAD
        assert expected_components == component_digests(self.root)
        self.expected_components = dict(expected_components)
        return "implementation-head-test"

    def revalidate(
        self, anchor_head: str, expected_components: dict[str, str]
    ) -> None:
        assert anchor_head == "implementation-head-test"
        assert expected_components == self.expected_components
        self.revalidations += 1


class _CrashHook:
    def __init__(self, stage: str) -> None:
        self.stage = stage
        self.triggered = False

    def __call__(self, stage: str) -> None:
        if stage == self.stage and not self.triggered:
            self.triggered = True
            raise RuntimeError(f"simulated crash at {stage}")

def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _actor(transport: _Transport) -> ProviderActor:
    return ProviderActor(
        ProviderBinding(
            provider_id="volcengine-ark-agent-plan",
            model_id=ARK_MODEL_SNAPSHOT,
            model_revision=ARK_MODEL_SNAPSHOT,
            revision_confirmed=True,
            transport="API_ONLY",
            action_grammar_sha256=_sha(
                json.dumps(
                    [action.value for action in ALL_ACTIONS], separators=(",", ":")
                ).encode()
            ),
        ),
        transport,
    )


def _receipt_documents(root: Path) -> dict[ReceiptKind, bytes]:
    components = component_digests(root)
    provider_subject = _sha(
        canonical_json(
            {
                "base_url_profile": ARK_BASE_URL_PROFILE,
                "credential_env_ref": ARK_CREDENTIAL_ENV_REF,
                "model_id": ARK_MODEL_SNAPSHOT,
                "model_revision": ARK_MODEL_SNAPSHOT,
                "provider_id": "volcengine-ark-agent-plan",
            }
        ).encode()
    )
    c7_subject = _sha(
        canonical_json(
            {
                "correction_epoch": _C7.correction_epoch,
                "owner_id": _C7.owner_id,
                "policy_sha256": _C7.policy_sha256,
            }
        ).encode()
    )
    subjects = {
        ReceiptKind.PROVIDER_CANARY: provider_subject,
        ReceiptKind.C7: c7_subject,
        ReceiptKind.EXECUTOR: components["executor_sha256"],
        ReceiptKind.INTEGRITY: components["integrity_sha256"],
        ReceiptKind.FREEZE: "a" * 64,
    }
    documents: dict[ReceiptKind, bytes] = {}
    for kind in ReceiptKind:
        if kind is ReceiptKind.RUN_AUTHORIZATION:
            continue
        documents[kind] = canonical_json(
            {
                "kind": kind.value,
                "receipt_id": (
                    "freeze-receipt-1"
                    if kind is ReceiptKind.FREEZE
                    else f"receipt-{kind.value.lower()}"
                ),
                "subject_sha256": subjects[kind],
            }
        ).encode()
    documents[ReceiptKind.RUN_AUTHORIZATION] = canonical_json(
        {
            "authorization_context_sha256": "0" * 64,
            "kind": ReceiptKind.RUN_AUTHORIZATION.value,
            "receipt_id": "run-authorization-receipt-1",
            "subject_sha256": _sha(documents[ReceiptKind.FREEZE]),
        }
    ).encode()
    return documents


def _envelope_bytes(
    root: Path,
    active_manifest: Path,
    receipts: dict[ReceiptKind, bytes],
    **budget_changes: int,
) -> bytes:
    components = component_digests(root)
    budget: dict[str, int] = {
        "max_provider_calls": EXPECTED_PROVIDER_CALLS,
        "max_total_input_tokens": EXPECTED_PROVIDER_CALLS + 10,
        "max_total_output_tokens": EXPECTED_PROVIDER_CALLS + 10,
        "max_total_cost_microusd": EXPECTED_PROVIDER_CALLS + 10,
        "max_input_tokens_per_call": 1,
        "max_output_tokens_per_call": 1,
        "max_cost_microusd_per_call": 1,
    }
    budget.update(budget_changes)
    payload: dict[str, object] = {
        "schema_version": "r-state-credit-1-execution-admission-v1",
        "route_id": "R-STATE-CREDIT-1",
        "run_id": "run-bridge-test-1",
        "freeze_subject_digest": "a" * 64,
        "freeze_receipt_id": "freeze-receipt-1",
        "run_authorization_receipt_id": "run-authorization-receipt-1",
        "target_head": _TARGET_HEAD,
        "active_manifest_sha256": _sha(active_manifest.read_bytes()),
        "provider_binding": {
            "provider_id": "volcengine-ark-agent-plan",
            "base_url_profile": ARK_BASE_URL_PROFILE,
            "model_id": ARK_MODEL_SNAPSHOT,
            "model_revision": ARK_MODEL_SNAPSHOT,
            "credential_env_ref": ARK_CREDENTIAL_ENV_REF,
            "canary_receipt_sha256": _sha(receipts[ReceiptKind.PROVIDER_CANARY]),
        },
        "c7_binding": {
            "owner_id": _C7.owner_id,
            "policy_sha256": _C7.policy_sha256,
            "correction_epoch": _C7.correction_epoch,
        },
        "workflow_reservation": {
            "reservation_id": "workflow-reservation-1",
            "reservation_token_sha256": "8" * 64,
            "attempt_epoch": 1,
            "cas_epoch": 1,
        },
        "components": components,
        "budget": budget,
        "six_receipt_digests": {
            kind.value: _sha(receipts[kind]) for kind in ReceiptKind
        },
    }
    payload["envelope_core_sha256"] = "0" * 64
    payload["envelope_sha256"] = "0" * 64
    core_payload = dict(payload)
    core_payload.pop("envelope_core_sha256")
    core_payload.pop("envelope_sha256")
    core_receipts = dict(
        cast(dict[str, str], core_payload["six_receipt_digests"])
    )
    core_receipts.pop(ReceiptKind.RUN_AUTHORIZATION.value)
    core_payload["six_receipt_digests"] = core_receipts
    core_sha256 = _sha(canonical_json(core_payload).encode())
    payload["envelope_core_sha256"] = core_sha256
    receipts[ReceiptKind.RUN_AUTHORIZATION] = canonical_json(
        {
            "authorization_context_sha256": core_sha256,
            "kind": ReceiptKind.RUN_AUTHORIZATION.value,
            "receipt_id": "run-authorization-receipt-1",
            "subject_sha256": _sha(receipts[ReceiptKind.FREEZE]),
        }
    ).encode()
    receipt_digests = dict(cast(dict[str, str], payload["six_receipt_digests"]))
    receipt_digests[ReceiptKind.RUN_AUTHORIZATION.value] = _sha(
        receipts[ReceiptKind.RUN_AUTHORIZATION]
    )
    payload["six_receipt_digests"] = receipt_digests
    payload.pop("envelope_sha256")
    payload["envelope_sha256"] = _sha(canonical_json(payload).encode())
    return canonical_json(payload).encode()


@pytest.fixture
def admission_inputs(tmp_path: Path) -> tuple[Path, Path, dict[ReceiptKind, bytes], bytes]:
    root = Path(__file__).resolve().parents[1]
    active_manifest = tmp_path / ACTIVE_MANIFEST_FILENAME
    active_manifest.write_bytes(b'{"status":"ACTIVE_TEST_AUTHORITY"}\n')
    receipts = _receipt_documents(root)
    return root, active_manifest, receipts, _envelope_bytes(
        root, active_manifest, receipts
    )


def test_execution_admission_is_closed_canonical_and_pinned(
    admission_inputs: tuple[Path, Path, dict[ReceiptKind, bytes], bytes],
) -> None:
    root, active_manifest, receipts, encoded = admission_inputs
    envelope = ExecutionAdmission.from_canonical_json(encoded)
    assert envelope.target_head == _TARGET_HEAD
    assert envelope.budget.max_provider_calls == 2240
    assert envelope.envelope_core_sha256

    noncanonical = json.dumps(json.loads(encoded), indent=2).encode()
    with pytest.raises(ExecutionBridgeViolation, match="canonical"):
        ExecutionAdmission.from_canonical_json(noncanonical)

    extra = json.loads(encoded)
    extra["unexpected"] = True
    with pytest.raises(ExecutionBridgeViolation, match="closed"):
        ExecutionAdmission.from_mapping(extra)

    floating = json.loads(encoded)
    floating["provider_binding"]["model_id"] = "ark-code-latest"
    floating.pop("envelope_sha256")
    floating["envelope_sha256"] = _sha(canonical_json(floating).encode())
    with pytest.raises(ExecutionBridgeViolation, match="immutable snapshot"):
        ExecutionAdmission.from_canonical_json(canonical_json(floating).encode())

    assert active_manifest.is_file() and len(receipts) == 6 and root.is_dir()


def test_admission_rejects_component_manifest_receipt_and_external_signature_drift(
    admission_inputs: tuple[Path, Path, dict[ReceiptKind, bytes], bytes],
    tmp_path: Path,
) -> None:
    root, active_manifest, receipts, encoded = admission_inputs
    envelope = ExecutionAdmission.from_canonical_json(encoded)
    run_dir = tmp_path / "run"

    drifted_receipts = dict(receipts)
    drifted_receipts[ReceiptKind.C7] += b"\n"
    with pytest.raises(ExecutionBridgeViolation, match="receipt digest drift"):
        ExecutionBridge(
            root=root,
            active_manifest=active_manifest,
            run_dir=run_dir,
            receipt_documents=drifted_receipts,
            receipt_verifier=_ExternalVerifier(),
            workspace_probe=_WorkspaceProbe(root),
            c7=_C7(),
            actor=_actor(_Transport()),
        ).admit(envelope)

    with pytest.raises(ExecutionBridgeViolation, match="external receipt signature"):
        ExecutionBridge(
            root=root,
            active_manifest=active_manifest,
            run_dir=run_dir,
            receipt_documents=receipts,
            receipt_verifier=_ExternalVerifier(accepted=False),
            workspace_probe=_WorkspaceProbe(root),
            c7=_C7(),
            actor=_actor(_Transport()),
        ).admit(envelope)

    active_manifest.write_bytes(b"drift")
    with pytest.raises(ExecutionBridgeViolation, match="active manifest"):
        ExecutionBridge(
            root=root,
            active_manifest=active_manifest,
            run_dir=run_dir,
            receipt_documents=receipts,
            receipt_verifier=_ExternalVerifier(),
            workspace_probe=_WorkspaceProbe(root),
            c7=_C7(),
            actor=_actor(_Transport()),
        ).admit(envelope)


def test_real_2240_call_loop_seals_raw_output_without_route_verdicts(
    admission_inputs: tuple[Path, Path, dict[ReceiptKind, bytes], bytes],
    tmp_path: Path,
) -> None:
    root, active_manifest, receipts, encoded = admission_inputs
    encoded = _envelope_bytes(
        root,
        active_manifest,
        receipts,
        max_total_cost_microusd=EXPECTED_PROVIDER_CALLS * 10,
        max_cost_microusd_per_call=10,
    )
    transport = _Transport()
    verifier = _ExternalVerifier()
    bridge = ExecutionBridge(
        root=root,
        active_manifest=active_manifest,
        run_dir=tmp_path / "complete",
        receipt_documents=receipts,
        receipt_verifier=verifier,
        workspace_probe=_WorkspaceProbe(root),
        c7=_C7(),
        actor=_actor(transport),
    )
    receipt = bridge.execute(ExecutionAdmission.from_canonical_json(encoded))

    assert transport.calls == EXPECTED_PROVIDER_CALLS == 2240
    assert receipt.row_count == EXPECTED_PROVIDER_CALLS
    raw = receipt.raw_path.read_text(encoding="utf-8")
    assert all(
        token not in raw.casefold()
        for token in ('"met"', '"not_met"', '"verdict"', '"promotion"')
    )
    payload = json.loads(raw)
    assert payload["raw_metrics"]["row_count"] == EXPECTED_PROVIDER_CALLS
    assert len(payload["rows"]) == EXPECTED_PROVIDER_CALLS
    assert payload["usage"]["cost_microusd"] == EXPECTED_PROVIDER_CALLS
    assert set(verifier.kinds) == set(ReceiptKind)
    assert verifier.terminal_states == ["SEALED_RAW"]
    assert bridge.terminal_path.is_file()


def test_failure_or_exhausted_budget_atomically_seals_partial_and_consumes_lock(
    admission_inputs: tuple[Path, Path, dict[ReceiptKind, bytes], bytes],
    tmp_path: Path,
) -> None:
    root, active_manifest, receipts, _ = admission_inputs
    encoded = _envelope_bytes(
        root,
        active_manifest,
        receipts,
        max_total_input_tokens=1,
    )
    transport = _Transport(input_tokens=1)
    bridge = ExecutionBridge(
        root=root,
        active_manifest=active_manifest,
        run_dir=tmp_path / "partial",
        receipt_documents=receipts,
        receipt_verifier=_ExternalVerifier(),
        workspace_probe=_WorkspaceProbe(root),
        c7=_C7(),
        actor=_actor(transport),
    )
    envelope = ExecutionAdmission.from_canonical_json(encoded)
    with pytest.raises(ExecutionBridgeViolation, match="remaining input token budget"):
        bridge.execute(envelope)
    assert transport.calls == 1
    partial = json.loads(bridge.partial_path.read_text(encoding="utf-8"))
    assert partial["row_count"] == 1
    assert partial["state"] == "PARTIAL_TERMINAL"
    assert partial["last_call_index"] == 2
    assert bridge.lock_path.is_file()
    with pytest.raises(ExecutionBridgeViolation, match="permanently consumed"):
        bridge.execute(envelope)
    assert transport.calls == 1


def test_ambiguous_effect_and_c7_interrupt_are_zero_retry_terminal(
    admission_inputs: tuple[Path, Path, dict[ReceiptKind, bytes], bytes],
    tmp_path: Path,
) -> None:
    root, active_manifest, receipts, encoded = admission_inputs
    envelope = ExecutionAdmission.from_canonical_json(encoded)
    transport = _Transport(fail_on_call=2)
    bridge = ExecutionBridge(
        root=root,
        active_manifest=active_manifest,
        run_dir=tmp_path / "ambiguous",
        receipt_documents=receipts,
        receipt_verifier=_ExternalVerifier(),
        workspace_probe=_WorkspaceProbe(root),
        c7=_C7(),
        actor=_actor(transport),
    )
    with pytest.raises(TimeoutError, match="ambiguous provider effect"):
        bridge.execute(envelope)
    assert transport.calls == 2
    ambiguous = json.loads(bridge.partial_path.read_text())
    assert ambiguous["row_count"] == 1
    assert ambiguous["state"] == "AMBIGUOUS_EFFECT_TERMINAL"
    assert ambiguous["last_call_index"] == 2

    interrupted_transport = _Transport()
    interrupted = ExecutionBridge(
        root=root,
        active_manifest=active_manifest,
        run_dir=tmp_path / "interrupted",
        receipt_documents=receipts,
        receipt_verifier=_ExternalVerifier(),
        workspace_probe=_WorkspaceProbe(root),
        c7=_C7(abort_at_probe=2),
        actor=_actor(interrupted_transport),
    )
    with pytest.raises(ExecutionBridgeViolation, match="C7 interrupted"):
        interrupted.execute(envelope)
    assert interrupted_transport.calls == 1
    assert interrupted.partial_path.is_file()


def test_run_authority_subject_binds_core_without_a_hash_cycle(
    admission_inputs: tuple[Path, Path, dict[ReceiptKind, bytes], bytes],
) -> None:
    _, _, receipts, encoded = admission_inputs
    envelope = ExecutionAdmission.from_canonical_json(encoded)
    authorization = json.loads(receipts[ReceiptKind.RUN_AUTHORIZATION])
    assert authorization["subject_sha256"] == _sha(receipts[ReceiptKind.FREEZE])
    assert authorization["authorization_context_sha256"] == (
        envelope.envelope_core_sha256
    )
    assert (
        envelope.six_receipt_digests[ReceiptKind.RUN_AUTHORIZATION]
        == _sha(receipts[ReceiptKind.RUN_AUTHORIZATION])
    )
    assert envelope.recompute_core_sha256() == envelope.envelope_core_sha256
    assert envelope.recompute_envelope_sha256() == envelope.envelope_sha256


def test_atomic_reservation_claim_rejects_same_envelope_in_a_new_run_dir(
    admission_inputs: tuple[Path, Path, dict[ReceiptKind, bytes], bytes],
    tmp_path: Path,
) -> None:
    root, active_manifest, receipts, encoded = admission_inputs
    authority = _ExternalVerifier()
    envelope = ExecutionAdmission.from_canonical_json(encoded)
    first = ExecutionBridge(
        root=root,
        active_manifest=active_manifest,
        run_dir=tmp_path / "claim-a",
        receipt_documents=receipts,
        receipt_verifier=authority,
        workspace_probe=_WorkspaceProbe(root),
        c7=_C7(abort_at_probe=1),
        actor=_actor(_Transport()),
    )
    first.admit(envelope)
    assert authority.claim_receipts == {}
    with pytest.raises(ExecutionBridgeViolation, match="C7 interrupted"):
        first.execute(envelope)
    second = ExecutionBridge(
        root=root,
        active_manifest=active_manifest,
        run_dir=tmp_path / "claim-b",
        receipt_documents=receipts,
        receipt_verifier=authority,
        workspace_probe=_WorkspaceProbe(root),
        c7=_C7(),
        actor=_actor(_Transport()),
    )
    with pytest.raises(ExecutionBridgeViolation, match="already claimed"):
        second.execute(envelope)


@pytest.mark.parametrize(
    ("stage", "abort_at_probe"),
    (
        ("after_claim_before_lock", None),
        ("after_terminal_intent_before_external_terminalize", 1),
        ("after_external_terminalize_before_ack", 1),
    ),
)
def test_crash_recovery_only_reconciles_and_never_calls_provider(
    admission_inputs: tuple[Path, Path, dict[ReceiptKind, bytes], bytes],
    tmp_path: Path,
    stage: str,
    abort_at_probe: int | None,
) -> None:
    root, active_manifest, receipts, encoded = admission_inputs
    envelope = ExecutionAdmission.from_canonical_json(encoded)
    authority = _ExternalVerifier()
    transport = _Transport()
    run_dir = tmp_path / stage
    crashing = ExecutionBridge(
        root=root,
        active_manifest=active_manifest,
        run_dir=run_dir,
        receipt_documents=receipts,
        receipt_verifier=authority,
        workspace_probe=_WorkspaceProbe(root),
        c7=_C7(abort_at_probe=abort_at_probe),
        actor=_actor(transport),
        fault_hook=_CrashHook(stage),
    )
    with pytest.raises(RuntimeError, match="simulated crash"):
        crashing.execute(envelope)
    assert transport.calls == 0

    recovering = ExecutionBridge(
        root=root,
        active_manifest=active_manifest,
        run_dir=run_dir,
        receipt_documents=receipts,
        receipt_verifier=authority,
        workspace_probe=_WorkspaceProbe(root),
        c7=_C7(),
        actor=_actor(transport),
    )
    with pytest.raises(ExecutionBridgeViolation, match="reconciled"):
        recovering.execute(envelope)
    assert transport.calls == 0
    assert recovering.terminal_intent_path.is_file()
    assert recovering.terminal_ack_path.is_file()


def test_internal_raw_rows_are_closed_and_recursively_reject_route_fields() -> None:
    row = {
        "run_id": "r",
        "call_index": 1,
        "episode_id": "e",
        "family": "CONTRADICTION",
        "seed": 1009,
        "checkpoint_id": "BEFORE_PERTURBATION",
        "arm_id": "A0_FULL_LOG",
        "request_sha256": "1" * 64,
        "provider_receipt_id": "p",
        "provider_receipt_sha256": "2" * 64,
        "response_sha256": "3" * 64,
        "model_revision": ARK_MODEL_SNAPSHOT,
        "input_tokens": 1,
        "output_tokens": 1,
        "cost_microusd": 1,
        "action": "CONTINUE",
        "loss_code": "CORRECT",
        "loss_weight": 0,
    }
    assert InternalSealedRawRow.from_mapping(row).to_mapping() == row
    with pytest.raises(ExecutionBridgeViolation, match="closed"):
        InternalSealedRawRow.from_mapping({**row, "extra": True})
    with pytest.raises(ExecutionBridgeViolation, match="route adjudication"):
        assert_raw_only({"nested": {"verdict": "MET"}})


def test_missing_workflow_reservation_or_role_retagging_fails_before_effect(
    admission_inputs: tuple[Path, Path, dict[ReceiptKind, bytes], bytes],
    tmp_path: Path,
) -> None:
    root, active_manifest, receipts, encoded = admission_inputs
    payload = json.loads(encoded)
    payload["workflow_reservation"]["reservation_token_sha256"] = "0" * 64
    payload.pop("envelope_core_sha256")
    payload.pop("envelope_sha256")
    # A caller cannot repair this without a matching registry reservation and
    # a newly signed run-authorization receipt.
    with pytest.raises(ExecutionBridgeViolation):
        ExecutionAdmission.from_mapping(payload)

    class _Retagged(_ExternalVerifier):
        def verify(
            self, kind: ReceiptKind, receipt_bytes: bytes
        ) -> ReceiptVerification:
            result = super().verify(kind, receipt_bytes)
            if kind is ReceiptKind.RUN_AUTHORIZATION:
                return ReceiptVerification(
                    registry_verified=True,
                    principal_id=result.principal_id,
                    role="executor-reviewer",
                    purpose=result.purpose,
                    subject_sha256=result.subject_sha256,
                    artifact_sha256=result.artifact_sha256,
                )
            return result

    transport = _Transport()
    bridge = ExecutionBridge(
        root=root,
        active_manifest=active_manifest,
        run_dir=tmp_path / "retagged",
        receipt_documents=receipts,
        receipt_verifier=_Retagged(),
        workspace_probe=_WorkspaceProbe(root),
        c7=_C7(),
        actor=_actor(transport),
    )
    with pytest.raises(ExecutionBridgeViolation, match="role/purpose"):
        bridge.admit(ExecutionAdmission.from_canonical_json(encoded))
    assert transport.calls == 0
