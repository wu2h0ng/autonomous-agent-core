from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
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


_MECHANISM_HEAD = "96eb79e1292d6b8f36ad990d3f97c554a9c33f3b"
_EXECUTION_CODE_HEAD = "38f850e73da5a4fd41f0418e15d156939731e046"


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
        self.claim_receipts: dict[
            tuple[str, str, int, int, str, str], ReservationClaimReceipt
        ] = {}
        self.terminal_receipts: dict[str, ReservationTerminalReceipt] = {}
        self.terminal_states: list[str] = []

    def verify(self, kind: ReceiptKind, receipt_bytes: bytes) -> ReceiptVerification:
        assert receipt_bytes
        self.kinds.append(kind)
        receipt = json.loads(receipt_bytes)
        roles = {
            ReceiptKind.PROVIDER_CANARY: (
                "provider-canary-attestor",
                "PROVIDER_CANARY_ACCEPTANCE",
            ),
            ReceiptKind.C7: ("c7-owner", "C7_BINDING_ACCEPTANCE"),
            ReceiptKind.EXECUTOR: ("executor-reviewer", "EXECUTOR_ACCEPTANCE"),
            ReceiptKind.INTEGRITY: ("integrity-reviewer", "INTEGRITY_ACCEPTANCE"),
            ReceiptKind.FREEZE: ("freezer", "FREEZE_ACCEPTANCE"),
            ReceiptKind.RUN_AUTHORIZATION: ("run-authorizer", "RUN_AUTHORIZATION"),
        }
        role, purpose = roles[kind]
        return ReceiptVerification(
            registry_verified=self.accepted,
            principal_id=receipt["signer_id"],
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
        claimant_nonce_sha256: str,
    ) -> ReservationClaimReceipt:
        key = (
            str(reservation["reservation_id"]),
            str(reservation["reservation_token_sha256"]),
            cast(int, reservation["attempt_epoch"]),
            cast(int, reservation["cas_epoch"]),
            run_id,
            envelope_sha256,
        )
        prior = self.claim_receipts.get(key)
        if prior is not None:
            if prior.claimant_nonce_sha256 == claimant_nonce_sha256:
                return prior
            return ReservationClaimReceipt(
                registry_verified=self.accepted,
                claimed=False,
                claim_id=prior.claim_id,
                reservation_id=prior.reservation_id,
                reservation_token_sha256=prior.reservation_token_sha256,
                attempt_epoch=prior.attempt_epoch,
                cas_epoch=prior.cas_epoch,
                run_id=prior.run_id,
                envelope_sha256=prior.envelope_sha256,
                claimant_nonce_sha256=claimant_nonce_sha256,
            )
        receipt = ReservationClaimReceipt(
            registry_verified=self.accepted,
            claimed=True,
            claim_id=f"claim:{run_id}:1",
            reservation_id=str(reservation["reservation_id"]),
            reservation_token_sha256=str(reservation["reservation_token_sha256"]),
            attempt_epoch=cast(int, reservation["attempt_epoch"]),
            cas_epoch=cast(int, reservation["cas_epoch"]),
            run_id=run_id,
            envelope_sha256=envelope_sha256,
            claimant_nonce_sha256=claimant_nonce_sha256,
        )
        self.claim_receipts[key] = receipt
        return receipt

    def query_claim(
        self,
        reservation: dict[str, object],
        run_id: str,
        envelope_sha256: str,
        claimant_nonce_sha256: str,
    ) -> ReservationClaimReceipt | None:
        key = (
            str(reservation["reservation_id"]),
            str(reservation["reservation_token_sha256"]),
            cast(int, reservation["attempt_epoch"]),
            cast(int, reservation["cas_epoch"]),
            run_id,
            envelope_sha256,
        )
        prior = self.claim_receipts.get(key)
        if prior is None or prior.claimant_nonce_sha256 == claimant_nonce_sha256:
            return prior
        return ReservationClaimReceipt(
            registry_verified=self.accepted,
            claimed=False,
            claim_id=prior.claim_id,
            reservation_id=prior.reservation_id,
            reservation_token_sha256=prior.reservation_token_sha256,
            attempt_epoch=prior.attempt_epoch,
            cas_epoch=prior.cas_epoch,
            run_id=prior.run_id,
            envelope_sha256=prior.envelope_sha256,
            claimant_nonce_sha256=claimant_nonce_sha256,
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

    def query_terminal(self, claim_id: str) -> ReservationTerminalReceipt | None:
        return self.terminal_receipts.get(claim_id)


class _StealingVerifier(_ExternalVerifier):
    def __init__(self) -> None:
        super().__init__()
        self.stolen = False

    def query_claim(
        self,
        reservation: dict[str, object],
        run_id: str,
        envelope_sha256: str,
        claimant_nonce_sha256: str,
    ) -> ReservationClaimReceipt | None:
        prior = super().query_claim(
            reservation, run_id, envelope_sha256, claimant_nonce_sha256
        )
        if prior is None and not self.stolen:
            self.stolen = True
            super().claim(
                reservation,
                run_id,
                envelope_sha256,
                "f" * 64,
            )
            return None
        return prior


class _WorkspaceProbe:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.revalidations = 0
        self.expected_components: dict[str, str] | None = None

    def admit(
        self,
        mechanism_head: str,
        execution_code_head: str,
        expected_components: dict[str, str],
    ) -> str:
        assert mechanism_head == _MECHANISM_HEAD
        assert execution_code_head == _EXECUTION_CODE_HEAD
        assert expected_components == component_digests(self.root)
        self.expected_components = dict(expected_components)
        return "implementation-head-test"

    def revalidate(self, anchor_head: str, expected_components: dict[str, str]) -> None:
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
                "signature_b64": base64.b64encode(
                    f"signature:{kind.value}".encode()
                ).decode(),
                "signer_id": f"registry:{kind.value.lower()}",
                "subject_sha256": subjects[kind],
            }
        ).encode()
    documents[ReceiptKind.RUN_AUTHORIZATION] = canonical_json(
        {
            "authorization_context_sha256": "0" * 64,
            "kind": ReceiptKind.RUN_AUTHORIZATION.value,
            "receipt_id": "run-authorization-receipt-1",
            "signature_b64": base64.b64encode(b"signature:RUN_AUTHORIZATION").decode(),
            "signer_id": "registry:run_authorization",
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
        "schema_version": "r-state-credit-1-execution-admission-v2",
        "route_id": "R-STATE-CREDIT-1",
        "run_id": "run-bridge-test-1",
        "freeze_subject_digest": "a" * 64,
        "freeze_receipt_id": "freeze-receipt-1",
        "run_authorization_receipt_id": "run-authorization-receipt-1",
        "mechanism_head": _MECHANISM_HEAD,
        "execution_code_head": _EXECUTION_CODE_HEAD,
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
        "authority_binding": {
            "broker_id": "workflow-authority-broker-1",
            "protocol_version": "r-state-authority-v1",
            "response_public_key_sha256": "6" * 64,
            "server_nonce_sha256": "5" * 64,
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
    core_receipts = dict(cast(dict[str, str], core_payload["six_receipt_digests"]))
    core_receipts.pop(ReceiptKind.RUN_AUTHORIZATION.value)
    core_payload["six_receipt_digests"] = core_receipts
    core_sha256 = _sha(canonical_json(core_payload).encode())
    payload["envelope_core_sha256"] = core_sha256
    receipts[ReceiptKind.RUN_AUTHORIZATION] = canonical_json(
        {
            "authorization_context_sha256": core_sha256,
            "kind": ReceiptKind.RUN_AUTHORIZATION.value,
            "receipt_id": "run-authorization-receipt-1",
            "signature_b64": base64.b64encode(b"signature:RUN_AUTHORIZATION").decode(),
            "signer_id": "registry:run_authorization",
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
def admission_inputs(
    tmp_path: Path,
) -> tuple[Path, Path, dict[ReceiptKind, bytes], bytes]:
    root = Path(__file__).resolve().parents[1]
    active_manifest = tmp_path / ACTIVE_MANIFEST_FILENAME
    active_manifest.write_bytes(b'{"status":"ACTIVE_TEST_AUTHORITY"}\n')
    receipts = _receipt_documents(root)
    return (
        root,
        active_manifest,
        receipts,
        _envelope_bytes(root, active_manifest, receipts),
    )


def test_execution_admission_is_closed_canonical_and_pinned(
    admission_inputs: tuple[Path, Path, dict[ReceiptKind, bytes], bytes],
) -> None:
    root, active_manifest, receipts, encoded = admission_inputs
    envelope = ExecutionAdmission.from_canonical_json(encoded)
    assert envelope.mechanism_head == _MECHANISM_HEAD
    assert envelope.execution_code_head == _EXECUTION_CODE_HEAD
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


def test_authority_binding_mutation_invalidates_run_authorization_context(
    admission_inputs: tuple[Path, Path, dict[ReceiptKind, bytes], bytes],
) -> None:
    _root, _active_manifest, receipts, encoded = admission_inputs
    original = ExecutionAdmission.from_canonical_json(encoded)
    mutated = json.loads(encoded)
    mutated["authority_binding"]["broker_id"] = "attacker-broker"

    with pytest.raises(ExecutionBridgeViolation, match="core digest drift"):
        ExecutionAdmission.from_mapping(mutated)

    assert (
        json.loads(receipts[ReceiptKind.RUN_AUTHORIZATION])[
            "authorization_context_sha256"
        ]
        == original.envelope_core_sha256
    )


def test_execution_admission_cli_emits_parse_only_machine_receipt(
    admission_inputs: tuple[Path, Path, dict[ReceiptKind, bytes], bytes],
) -> None:
    root, _active_manifest, _receipts, encoded = admission_inputs

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "experiments.r_state_credit_1.execution_bridge_cli",
            "validate-admission",
        ],
        cwd=root,
        input=encoded,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0
    assert completed.stderr == b""
    receipt = json.loads(completed.stdout)
    assert completed.stdout == (canonical_json(receipt) + "\n").encode()
    assert set(receipt) == {
        "authority_verified",
        "envelope_core_sha256",
        "envelope_sha256",
        "execution_code_head",
        "mechanism_head",
        "route_id",
        "run_id",
        "schema_version",
        "status",
    }
    assert receipt["schema_version"] == "r-state-credit-1-admission-parse-receipt-v1"
    assert receipt["status"] == "PARSED_ONLY"
    assert receipt["authority_verified"] is False
    assert receipt["mechanism_head"] == _MECHANISM_HEAD
    assert receipt["execution_code_head"] == _EXECUTION_CODE_HEAD
    assert (
        receipt["envelope_sha256"]
        == ExecutionAdmission.from_canonical_json(encoded).envelope_sha256
    )


def test_execution_admission_cli_fails_closed_without_stdout(
    admission_inputs: tuple[Path, Path, dict[ReceiptKind, bytes], bytes],
) -> None:
    root, _active_manifest, _receipts, encoded = admission_inputs
    noncanonical = json.dumps(json.loads(encoded), indent=2).encode()

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "experiments.r_state_credit_1.execution_bridge_cli",
            "validate-admission",
        ],
        cwd=root,
        input=noncanonical,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 2
    assert completed.stdout == b""
    diagnostic = json.loads(completed.stderr)
    assert completed.stderr == (canonical_json(diagnostic) + "\n").encode()
    assert diagnostic == {
        "error_code": "EXECUTION_ADMISSION_REJECTED",
        "message": "execution admission must be strict canonical JSON",
        "schema_version": "r-state-credit-1-execution-cli-error-v1",
    }


@pytest.mark.parametrize("arguments", [[], ["run"], ["validate-admission", "extra"]])
def test_execution_admission_cli_rejects_every_other_command(
    arguments: list[str],
) -> None:
    root = Path(__file__).resolve().parents[1]

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "experiments.r_state_credit_1.execution_bridge_cli",
            *arguments,
        ],
        cwd=root,
        input=b"{}",
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 2
    assert completed.stdout == b""
    diagnostic = json.loads(completed.stderr)
    assert diagnostic == {
        "error_code": "CLI_USAGE_REJECTED",
        "message": "expected exactly: validate-admission",
        "schema_version": "r-state-credit-1-execution-cli-error-v1",
    }


def test_execution_admission_cli_rejects_oversized_stdin() -> None:
    root = Path(__file__).resolve().parents[1]

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "experiments.r_state_credit_1.execution_bridge_cli",
            "validate-admission",
        ],
        cwd=root,
        input=b"x" * (1024 * 1024 + 1),
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 2
    assert completed.stdout == b""
    diagnostic = json.loads(completed.stderr)
    assert diagnostic == {
        "error_code": "EXECUTION_ADMISSION_REJECTED",
        "message": "execution admission exceeds 1048576 bytes",
        "schema_version": "r-state-credit-1-execution-cli-error-v1",
    }


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


@pytest.mark.parametrize("field", ["signer_id", "signature_b64"])
def test_signed_receipt_field_tampering_breaks_envelope_digest(
    admission_inputs: tuple[Path, Path, dict[ReceiptKind, bytes], bytes],
    tmp_path: Path,
    field: str,
) -> None:
    root, active_manifest, receipts, encoded = admission_inputs
    tampered = dict(receipts)
    payload = json.loads(tampered[ReceiptKind.C7])
    payload[field] = "dGFtcGVyZWQ=" if field == "signature_b64" else "attacker"
    tampered[ReceiptKind.C7] = canonical_json(payload).encode()

    with pytest.raises(ExecutionBridgeViolation, match="receipt digest drift"):
        ExecutionBridge(
            root=root,
            active_manifest=active_manifest,
            run_dir=tmp_path / field,
            receipt_documents=tampered,
            receipt_verifier=_ExternalVerifier(),
            workspace_probe=_WorkspaceProbe(root),
            c7=_C7(),
            actor=_actor(_Transport()),
        ).admit(ExecutionAdmission.from_canonical_json(encoded))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("signer_id", "", "signer_id"),
        ("signature_b64", "", "signature_b64"),
        ("signature_b64", "***", "strict base64"),
    ],
)
def test_signed_receipt_wire_rejects_empty_identity_or_signature(
    admission_inputs: tuple[Path, Path, dict[ReceiptKind, bytes], bytes],
    tmp_path: Path,
    field: str,
    value: str,
    message: str,
) -> None:
    root, active_manifest, receipts, _encoded = admission_inputs
    changed = dict(receipts)
    payload = json.loads(changed[ReceiptKind.C7])
    payload[field] = value
    changed[ReceiptKind.C7] = canonical_json(payload).encode()
    encoded = _envelope_bytes(root, active_manifest, changed)

    with pytest.raises(ExecutionBridgeViolation, match=message):
        ExecutionBridge(
            root=root,
            active_manifest=active_manifest,
            run_dir=tmp_path / field,
            receipt_documents=changed,
            receipt_verifier=_ExternalVerifier(),
            workspace_probe=_WorkspaceProbe(root),
            c7=_C7(),
            actor=_actor(_Transport()),
        ).admit(ExecutionAdmission.from_canonical_json(encoded))


def test_signed_receipt_signer_must_match_external_verified_principal(
    admission_inputs: tuple[Path, Path, dict[ReceiptKind, bytes], bytes],
    tmp_path: Path,
) -> None:
    root, active_manifest, receipts, encoded = admission_inputs

    class _SignerMismatch(_ExternalVerifier):
        def verify(
            self, kind: ReceiptKind, receipt_bytes: bytes
        ) -> ReceiptVerification:
            result = super().verify(kind, receipt_bytes)
            if kind is ReceiptKind.C7:
                return ReceiptVerification(
                    registry_verified=result.registry_verified,
                    principal_id="registry:someone-else",
                    role=result.role,
                    purpose=result.purpose,
                    subject_sha256=result.subject_sha256,
                    artifact_sha256=result.artifact_sha256,
                )
            return result

    with pytest.raises(ExecutionBridgeViolation, match="signature binding drift"):
        ExecutionBridge(
            root=root,
            active_manifest=active_manifest,
            run_dir=tmp_path / "signer-mismatch",
            receipt_documents=receipts,
            receipt_verifier=_SignerMismatch(),
            workspace_probe=_WorkspaceProbe(root),
            c7=_C7(),
            actor=_actor(_Transport()),
        ).admit(ExecutionAdmission.from_canonical_json(encoded))


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
    assert envelope.six_receipt_digests[ReceiptKind.RUN_AUTHORIZATION] == _sha(
        receipts[ReceiptKind.RUN_AUTHORIZATION]
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
    second_transport = _Transport()
    second = ExecutionBridge(
        root=root,
        active_manifest=active_manifest,
        run_dir=tmp_path / "claim-b",
        receipt_documents=receipts,
        receipt_verifier=authority,
        workspace_probe=_WorkspaceProbe(root),
        c7=_C7(),
        actor=_actor(second_transport),
    )
    with pytest.raises(ExecutionBridgeViolation, match="already claimed"):
        second.execute(envelope)
    assert second_transport.calls == 0


def test_claim_cas_rejects_toctou_steal_before_provider_effect(
    admission_inputs: tuple[Path, Path, dict[ReceiptKind, bytes], bytes],
    tmp_path: Path,
) -> None:
    root, active_manifest, receipts, encoded = admission_inputs
    transport = _Transport()
    bridge = ExecutionBridge(
        root=root,
        active_manifest=active_manifest,
        run_dir=tmp_path / "claim-toctou",
        receipt_documents=receipts,
        receipt_verifier=_StealingVerifier(),
        workspace_probe=_WorkspaceProbe(root),
        c7=_C7(),
        actor=_actor(transport),
    )

    with pytest.raises(ExecutionBridgeViolation, match="already claimed"):
        bridge.execute(ExecutionAdmission.from_canonical_json(encoded))

    assert transport.calls == 0
    claim_intent = json.loads(bridge.claim_intent_path.read_bytes())
    assert len(claim_intent["claimant_nonce_sha256"]) == 64
    assert claim_intent["claimant_nonce_sha256"] != "f" * 64


def test_reconcile_without_claim_intent_fails_closed_before_provider(
    admission_inputs: tuple[Path, Path, dict[ReceiptKind, bytes], bytes],
    tmp_path: Path,
) -> None:
    root, active_manifest, receipts, encoded = admission_inputs
    transport = _Transport()
    run_dir = tmp_path / "missing-claim-intent"
    run_dir.mkdir()
    (run_dir / "execution.lock.json").write_text("{}", encoding="utf-8")
    bridge = ExecutionBridge(
        root=root,
        active_manifest=active_manifest,
        run_dir=run_dir,
        receipt_documents=receipts,
        receipt_verifier=_ExternalVerifier(),
        workspace_probe=_WorkspaceProbe(root),
        c7=_C7(),
        actor=_actor(transport),
    )

    with pytest.raises(ExecutionBridgeViolation, match="claim intent"):
        bridge.execute(ExecutionAdmission.from_canonical_json(encoded))

    assert transport.calls == 0


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
    claim_intent = json.loads(crashing.claim_intent_path.read_bytes())
    nonce = claim_intent["claimant_nonce_sha256"]
    assert len(nonce) == 64
    assert next(iter(authority.claim_receipts.values())).claimant_nonce_sha256 == nonce

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
