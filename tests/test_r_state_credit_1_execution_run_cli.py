from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
import pytest

from experiments.r_state_credit_1 import execution_run_cli as cli
from experiments.r_state_credit_1.action_grammar import ALL_ACTIONS
from experiments.r_state_credit_1.actor_interface import ActorRequest
from experiments.r_state_credit_1.execution_bridge import (
    ExecutionBridgeViolation,
    ExecutionReceipt,
    ReceiptKind,
    canonical_json,
)
from experiments.r_state_credit_1.execution_run_cli import (
    ArkSixActionTransport,
    GitWorkspaceProbe,
    ResponsesHttpResponse,
    _parse_args,
    validate_and_publish_result,
)
from experiments.r_state_credit_1.recast_provider_actor import ProviderNotReady
from tests.test_r_state_credit_1_unix_authority_client import _admission


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _row(index: int, run_id: str) -> dict[str, object]:
    return {
        "run_id": run_id,
        "call_index": index,
        "episode_id": f"episode-{index}",
        "family": "CONTRADICTION",
        "seed": 1009,
        "checkpoint_id": "BEFORE_PERTURBATION",
        "arm_id": "A0_FULL_LOG",
        "actor_request_sha256": f"{index:064x}",
        "provider_request_sha256": f"{index + 1000:064x}",
        "provider_receipt_id": f"provider-receipt-{index}",
        "provider_receipt_sha256": f"{index + 3000:064x}",
        "provider_response_sha256": f"{index + 6000:064x}",
        "raw_output_sha256": f"{index + 9000:064x}",
        "model_revision": "glm-5-2-260617",
        "input_tokens": 2,
        "output_tokens": 1,
        "total_tokens": 3,
        "cost_status": "UNAVAILABLE_NOT_GUESSED",
        "cost_amount_microunits": None,
        "cost_currency": None,
        "latency_ms": 1,
        "timeout_seconds": 120,
        "action": "CONTINUE",
        "loss_code": "CORRECT",
        "loss_weight": 0,
    }


def _artifacts(
    tmp_path: Path,
    *,
    row_count: int = 2240,
) -> tuple[object, ExecutionReceipt, Path, Path]:
    admission = _admission("6" * 64)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    rows = [_row(index, admission.run_id) for index in range(1, row_count + 1)]
    usage = {
        "provider_calls": row_count,
        "input_tokens": row_count * 2,
        "output_tokens": row_count,
        "total_tokens": row_count * 3,
        "cost_status": "UNAVAILABLE_NOT_GUESSED",
        "cost_amount_microunits": None,
        "cost_currency": None,
    }
    raw = {
        "schema_version": "r-state-credit-1-execution-raw-v1",
        "artifact_class": "RAW_EXECUTION",
        "state": "SEALED_RAW",
        "run_id": admission.run_id,
        "envelope_sha256": admission.envelope_sha256,
        "run_authorization_receipt_sha256": admission.six_receipt_digests[
            ReceiptKind.RUN_AUTHORIZATION
        ],
        "usage": usage,
        "ordered_provider_receipt_sha256": [
            row["provider_receipt_sha256"] for row in rows
        ],
        "raw_metrics": {"row_count": row_count},
        "rows": rows,
    }
    raw_path = run_dir / "rfinal.raw.json"
    raw_path.write_bytes((canonical_json(raw) + "\n").encode())
    raw_sha256 = _sha(raw_path.read_bytes())
    terminal = {
        "schema_version": "r-state-credit-1-terminal-intent-v1",
        "state": "SEALED_RAW",
        "claim_id": "claim-1",
        "reservation_token_sha256": (
            admission.workflow_reservation.reservation_token_sha256
        ),
        "attempt_epoch": admission.workflow_reservation.attempt_epoch,
        "cas_epoch": admission.workflow_reservation.cas_epoch,
        "artifact_sha256": raw_sha256,
        "run_id": admission.run_id,
        "envelope_sha256": admission.envelope_sha256,
        "row_count": row_count,
        "raw_sha256": raw_sha256,
    }
    terminal_path = run_dir / "execution.terminal-intent.json"
    terminal_path.write_bytes((canonical_json(terminal) + "\n").encode())
    ack = {
        "schema_version": "r-state-credit-1-terminal-ack-v1",
        "state": "SEALED_RAW",
        "claim_id": "claim-1",
        "terminal_intent_sha256": _sha(terminal_path.read_bytes()),
        "registry_verified": True,
    }
    ack_path = run_dir / "execution.terminal-ack.json"
    ack_path.write_bytes((canonical_json(ack) + "\n").encode())
    return (
        admission,
        ExecutionReceipt(
            raw_path=raw_path,
            raw_sha256=raw_sha256,
            row_count=row_count,
        ),
        terminal_path,
        ack_path,
    )


def test_result_validation_publishes_exact_workflow_usage_contract(
    tmp_path: Path,
) -> None:
    admission, receipt, terminal_path, ack_path = _artifacts(tmp_path)
    usage_path = tmp_path / "usage.jsonl"

    result = validate_and_publish_result(
        admission=admission,
        execution_receipt=receipt,
        terminal_intent_path=terminal_path,
        terminal_ack_path=ack_path,
        usage_ledger_path=usage_path,
    )

    assert set(result) == {
        "schema_version",
        "run_id",
        "status",
        "raw_result_sha256",
        "row_count",
        "provider_calls",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cost_status",
        "cost_amount_microunits",
        "cost_currency",
        "usage_ledger_sha256",
        "reservation_id",
        "reservation_token_sha256",
        "attempt_epoch",
        "cas_epoch",
    }
    lines = usage_path.read_bytes().splitlines(keepends=True)
    assert len(lines) == 2240
    first = json.loads(lines[0])
    last = json.loads(lines[-1])
    assert first["call_index"] == 0
    assert last["call_index"] == 2239
    assert first["provider_receipt_sha256"] == f"{3001:064x}"
    assert set(first) == {
        "call_index",
        "run_id",
        "reservation_id",
        "reservation_token_sha256",
        "attempt_epoch",
        "cas_epoch",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cost_status",
        "cost_amount_microunits",
        "cost_currency",
        "provider_receipt_sha256",
    }
    assert lines[0] == (canonical_json(first) + "\n").encode()
    assert result["usage_ledger_sha256"] == _sha(usage_path.read_bytes())


@pytest.mark.parametrize("row_count", [2239, 2241])
def test_result_validation_rejects_non_exact_coverage(
    tmp_path: Path, row_count: int
) -> None:
    admission, receipt, terminal_path, ack_path = _artifacts(
        tmp_path, row_count=row_count
    )
    with pytest.raises(ExecutionBridgeViolation, match="2240"):
        validate_and_publish_result(
            admission=admission,
            execution_receipt=receipt,
            terminal_intent_path=terminal_path,
            terminal_ack_path=ack_path,
            usage_ledger_path=tmp_path / "usage.jsonl",
        )


def test_result_validation_rejects_duplicate_provider_receipt(tmp_path: Path) -> None:
    admission, receipt, terminal_path, ack_path = _artifacts(tmp_path)
    raw = json.loads(receipt.raw_path.read_bytes())
    raw["rows"][1]["provider_receipt_id"] = raw["rows"][0]["provider_receipt_id"]
    receipt.raw_path.write_bytes((canonical_json(raw) + "\n").encode())
    changed = ExecutionReceipt(
        receipt.raw_path, _sha(receipt.raw_path.read_bytes()), 2240
    )
    terminal = json.loads(terminal_path.read_bytes())
    terminal["raw_sha256"] = changed.raw_sha256
    terminal["artifact_sha256"] = changed.raw_sha256
    terminal_path.write_bytes((canonical_json(terminal) + "\n").encode())
    ack = json.loads(ack_path.read_bytes())
    ack["terminal_intent_sha256"] = _sha(terminal_path.read_bytes())
    ack_path.write_bytes((canonical_json(ack) + "\n").encode())
    with pytest.raises(ExecutionBridgeViolation, match="globally unique"):
        validate_and_publish_result(
            admission=admission,
            execution_receipt=changed,
            terminal_intent_path=terminal_path,
            terminal_ack_path=ack_path,
            usage_ledger_path=tmp_path / "usage.jsonl",
        )


def test_result_validation_rejects_raw_mutation_after_execution(tmp_path: Path) -> None:
    admission, receipt, terminal_path, ack_path = _artifacts(tmp_path)
    receipt.raw_path.write_bytes(receipt.raw_path.read_bytes() + b" ")
    with pytest.raises(ExecutionBridgeViolation, match="raw result digest"):
        validate_and_publish_result(
            admission=admission,
            execution_receipt=receipt,
            terminal_intent_path=terminal_path,
            terminal_ack_path=ack_path,
            usage_ledger_path=tmp_path / "usage.jsonl",
        )


@pytest.mark.parametrize("preexisting", ["file", "symlink"])
def test_usage_output_must_be_new_regular_path(
    tmp_path: Path, preexisting: str
) -> None:
    admission, receipt, terminal_path, ack_path = _artifacts(tmp_path)
    usage_path = tmp_path / "usage.jsonl"
    if preexisting == "file":
        usage_path.write_text("attacker", encoding="utf-8")
    else:
        target = tmp_path / "target"
        target.write_text("attacker", encoding="utf-8")
        usage_path.symlink_to(target)
    with pytest.raises(ExecutionBridgeViolation, match="usage ledger"):
        validate_and_publish_result(
            admission=admission,
            execution_receipt=receipt,
            terminal_intent_path=terminal_path,
            terminal_ack_path=ack_path,
            usage_ledger_path=usage_path,
        )


def test_sealed_raw_result_cannot_be_replaced_by_a_symlink(tmp_path: Path) -> None:
    admission, receipt, terminal_path, ack_path = _artifacts(tmp_path)
    target = tmp_path / "attacker-raw.json"
    receipt.raw_path.replace(target)
    receipt.raw_path.symlink_to(target)
    with pytest.raises(ExecutionBridgeViolation, match="non-symlink"):
        validate_and_publish_result(
            admission=admission,
            execution_receipt=receipt,
            terminal_intent_path=terminal_path,
            terminal_ack_path=ack_path,
            usage_ledger_path=tmp_path / "usage.jsonl",
        )


class _Http:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def post(self, **_: object) -> ResponsesHttpResponse:
        return ResponsesHttpResponse(status=200, body=self.body)


def _provider_payload(
    *, include_cost: bool = True, output_text: str | None = None
) -> bytes:
    usage: dict[str, object] = {
        "input_tokens": 4,
        "input_tokens_details": {"cached_tokens": 0},
        "output_tokens": 2,
        "output_tokens_details": {"reasoning_tokens": 0},
        "total_tokens": 6,
    }
    if include_cost:
        usage["cost"] = {
            "status": "PROVIDER_REPORTED",
            "amount_microunits": 7,
            "currency": "USD",
        }
    return canonical_json(
        {
            "caching": None,
            "created_at": 1,
            "id": "provider-receipt-1",
            "max_output_tokens": 256,
            "model": "glm-5-2-260617",
            "object": "response",
            "status": "completed",
            "output": [
                {
                    "id": "reasoning-1",
                    "status": "completed",
                    "summary": [],
                    "type": "reasoning",
                },
                {
                    "id": "message-1",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {
                            "type": "output_text",
                            "text": output_text
                            if output_text is not None
                            else canonical_json({"action": "CONTINUE", "notes": None}),
                        }
                    ],
                },
            ],
            "service_tier": "default",
            "store": False,
            "temperature": 0,
            "top_p": 1,
            "usage": usage,
        }
    ).encode()


def test_bound_provider_fixture_parses_observed_topology_with_explicit_cost() -> None:
    transport = ArkSixActionTransport(
        http_transport=_Http(_provider_payload()),
        environ={"ARK_API_KEY": "test-only-secret"},
    )
    result = transport.complete(ActorRequest("state", ALL_ACTIONS, "neutral-session"))
    assert result == {
        "action": "CONTINUE",
        "notes": None,
        "provider_receipt_id": "provider-receipt-1",
        "model_revision": "glm-5-2-260617",
        "input_tokens": 4,
        "output_tokens": 2,
        "total_tokens": 6,
        "cost_status": "PROVIDER_REPORTED",
        "cost_amount_microunits": 7,
        "cost_currency": "USD",
        "actor_request_sha256": result["actor_request_sha256"],
        "provider_request_sha256": result["provider_request_sha256"],
        "provider_response_sha256": result["provider_response_sha256"],
        "raw_output_sha256": result["raw_output_sha256"],
        "latency_ms": result["latency_ms"],
        "timeout_seconds": 120,
    }


def test_provider_request_contains_fixed_canonical_json_instruction() -> None:
    transport = ArkSixActionTransport(environ={"ARK_API_KEY": "test-only-secret"})
    body = json.loads(
        transport._request_body(ActorRequest("state", ALL_ACTIONS, "neutral-session"))
    )
    actor_input = json.loads(body["input"])
    assert actor_input["instruction"] == cli.ARK_ACTION_INSTRUCTION
    assert "only one canonical JSON object" in actor_input["instruction"]


@pytest.mark.parametrize(
    "output_text",
    (
        'Explanation: {"action":"CONTINUE","notes":null}',
        '{"notes":null, "action":"CONTINUE"}',
    ),
)
def test_provider_rejects_explanation_or_noncanonical_action_output(
    output_text: str,
) -> None:
    transport = ArkSixActionTransport(
        http_transport=_Http(_provider_payload(output_text=output_text)),
        environ={"ARK_API_KEY": "test-only-secret"},
    )
    with pytest.raises(ProviderNotReady):
        transport.complete(ActorRequest("state", ALL_ACTIONS, "neutral-session"))


def test_observed_live_topology_preserves_unknown_cost_without_guessing() -> None:
    transport = ArkSixActionTransport(
        http_transport=_Http(_provider_payload(include_cost=False)),
        environ={"ARK_API_KEY": "test-only-secret"},
    )
    result = transport.complete(ActorRequest("state", ALL_ACTIONS, "neutral-session"))
    assert result["cost_status"] == "UNAVAILABLE_NOT_GUESSED"
    assert result["cost_amount_microunits"] is None
    assert result["cost_currency"] is None


def test_cli_argv_is_fixed_and_has_no_fake_switch(tmp_path: Path) -> None:
    arguments = [
        "--admission",
        str(tmp_path / "admission.json"),
        "--receipt-dir",
        str(tmp_path / "receipts"),
        "--active-manifest",
        str(tmp_path / "active.json"),
        "--run-dir",
        str(tmp_path / "run"),
        "--authority-socket",
        str(tmp_path / "authority.sock"),
        "--authority-public-key",
        str(tmp_path / "authority.pem"),
        "--reservation-token-fd",
        "9",
        "--usage-ledger",
        str(tmp_path / "usage.jsonl"),
    ]
    parsed = _parse_args(arguments)
    assert parsed.reservation_token_fd == 9
    with pytest.raises(SystemExit):
        _parse_args([*arguments, "--fake-provider"])


def test_runtime_isolation_binds_interpreter_and_exact_child_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parsed = _parse_args(
        [
            "--admission",
            str(tmp_path / "admission.json"),
            "--receipt-dir",
            str(tmp_path / "receipts"),
            "--active-manifest",
            str(tmp_path / "active.json"),
            "--run-dir",
            str(tmp_path / "run"),
            "--authority-socket",
            str(tmp_path / "authority.sock"),
            "--authority-public-key",
            str(tmp_path / "authority.pem"),
            "--reservation-token-fd",
            "9",
            "--usage-ledger",
            str(tmp_path / "usage.jsonl"),
        ]
    )
    interpreter = Path(sys.executable).resolve()
    monkeypatch.setattr(
        sys,
        "orig_argv",
        [
            str(interpreter),
            "-m",
            "experiments.r_state_credit_1.execution_run_cli",
            *[
                item
                for pair in (
                    ("--admission", str(parsed.admission)),
                    ("--receipt-dir", str(parsed.receipt_dir)),
                    ("--active-manifest", str(parsed.active_manifest)),
                    ("--run-dir", str(parsed.run_dir)),
                    ("--authority-socket", str(parsed.authority_socket)),
                    ("--authority-public-key", str(parsed.authority_public_key)),
                    ("--reservation-token-fd", str(parsed.reservation_token_fd)),
                    ("--usage-ledger", str(parsed.usage_ledger)),
                )
                for item in pair
            ],
        ],
    )
    admission = _admission("6" * 64)
    child_sha256 = _sha(canonical_json(list(cli.canonical_child_command())).encode())
    bound = replace(
        admission,
        isolation_binding=replace(
            admission.isolation_binding,
            interpreter_path=str(interpreter),
            interpreter_sha256=_sha(interpreter.read_bytes()),
            child_command_sha256=child_sha256,
        ),
    )

    cli._verify_runtime_isolation(bound)
    with pytest.raises(ExecutionBridgeViolation, match="child command digest"):
        cli._verify_runtime_isolation(
            replace(
                bound,
                isolation_binding=replace(
                    bound.isolation_binding, child_command_sha256="0" * 64
                ),
            ),
        )


@pytest.mark.parametrize(
    "tail",
    (
        (
            "-m",
            "experiments.r_state_credit_1.execution_run_cli",
            "--admission",
            "/tmp/admission.json",
        ),
        (
            "-I",
            "/sealed/tests/support/r_state_fake_execution_launcher.py",
            "--admission",
            "/tmp/admission.json",
        ),
    ),
)
def test_canonical_child_command_preserves_module_script_and_python_flags(
    monkeypatch: pytest.MonkeyPatch,
    tail: tuple[str, ...],
) -> None:
    interpreter = str(Path(sys.executable).resolve())
    monkeypatch.setattr(sys, "orig_argv", [interpreter, *tail])

    assert cli.canonical_child_command() == (interpreter, *tail)


def test_canonical_child_command_rejects_interpreter_path_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    alien_interpreter = tmp_path / "python"
    monkeypatch.setattr(
        sys,
        "orig_argv",
        [
            str(alien_interpreter),
            "-m",
            "experiments.r_state_credit_1.execution_run_cli",
        ],
    )

    with pytest.raises(ExecutionBridgeViolation, match="command interpreter drift"):
        cli.canonical_child_command()


def test_python_flag_mutation_changes_child_command_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    interpreter = str(Path(sys.executable).resolve())
    tail = ("/sealed/tests/support/r_state_fake_execution_launcher.py",)
    monkeypatch.setattr(sys, "orig_argv", [interpreter, *tail])
    plain = _sha(canonical_json(list(cli.canonical_child_command())).encode())
    monkeypatch.setattr(sys, "orig_argv", [interpreter, "-I", *tail])
    isolated = _sha(canonical_json(list(cli.canonical_child_command())).encode())

    assert plain != isolated


def test_git_workspace_probe_binds_clean_head_and_component_bytes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "sealed"
    component_root = root / "experiments" / "r_state_credit_1"
    component_root.mkdir(parents=True)
    for name in ("execution_bridge.py", "recast_scorer.py", "statistical_integrity.py"):
        (component_root / name).write_text(f"# {name}\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "sealed"], cwd=root, check=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    components = {
        "executor_sha256": _sha((component_root / "execution_bridge.py").read_bytes()),
        "scorer_sha256": _sha((component_root / "recast_scorer.py").read_bytes()),
        "integrity_sha256": _sha(
            (component_root / "statistical_integrity.py").read_bytes()
        ),
    }
    probe = GitWorkspaceProbe(root)
    assert probe.admit("0" * 40, head, components) == head
    (component_root / "execution_bridge.py").write_text("# drift\n", encoding="utf-8")
    with pytest.raises(ExecutionBridgeViolation, match="changed"):
        probe.revalidate(head, components)


def test_main_emits_only_one_strict_subprocess_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    arguments = [
        "--admission",
        str(tmp_path / "a"),
        "--receipt-dir",
        str(tmp_path / "r"),
        "--active-manifest",
        str(tmp_path / "m"),
        "--run-dir",
        str(tmp_path / "run"),
        "--authority-socket",
        str(tmp_path / "s"),
        "--authority-public-key",
        str(tmp_path / "p"),
        "--reservation-token-fd",
        "9",
        "--usage-ledger",
        str(tmp_path / "u"),
    ]
    result = {
        "schema_version": "r-state-credit-1-subprocess-result-v1",
        "run_id": "run-1",
        "status": "SEALED_RAW_RESULT",
        "raw_result_sha256": "1" * 64,
        "row_count": 2240,
        "provider_calls": 2240,
        "input_tokens": 1,
        "output_tokens": 1,
        "total_tokens": 2,
        "cost_status": "UNAVAILABLE_NOT_GUESSED",
        "cost_amount_microunits": None,
        "cost_currency": None,
        "usage_ledger_sha256": "2" * 64,
        "reservation_id": "reservation-1",
        "reservation_token_sha256": "3" * 64,
        "attempt_epoch": 1,
        "cas_epoch": 1,
    }
    monkeypatch.setattr(cli, "_execute", lambda *_args, **_kwargs: result)
    assert cli.main(arguments) == 0
    output = capfd.readouterr()
    assert output.out.encode() == (canonical_json(result) + "\n").encode()
    assert output.err == ""


def test_main_rejects_dependency_forged_stdout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    arguments = [
        "--admission",
        str(tmp_path / "a"),
        "--receipt-dir",
        str(tmp_path / "r"),
        "--active-manifest",
        str(tmp_path / "m"),
        "--run-dir",
        str(tmp_path / "run"),
        "--authority-socket",
        str(tmp_path / "s"),
        "--authority-public-key",
        str(tmp_path / "p"),
        "--reservation-token-fd",
        "9",
        "--usage-ledger",
        str(tmp_path / "u"),
    ]

    def forged(*_args: object, **_kwargs: object) -> dict[str, object]:
        print('{"status":"FAKE_SUCCESS"}')
        return {}

    monkeypatch.setattr(cli, "_execute", forged)
    assert cli.main(arguments) == 1
    output = capfd.readouterr()
    assert output.out == ""
    diagnostic = json.loads(output.err)
    assert diagnostic["message"] == "execution dependency wrote forged stdout"


def test_execute_closes_authority_client_when_actor_factory_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    arguments = _parse_args(
        [
            "--admission",
            str(tmp_path / "admission.json"),
            "--receipt-dir",
            str(tmp_path / "receipts"),
            "--active-manifest",
            str(tmp_path / "active.json"),
            "--run-dir",
            str(run_dir),
            "--authority-socket",
            str(tmp_path / "authority.sock"),
            "--authority-public-key",
            str(tmp_path / "authority.pem"),
            "--reservation-token-fd",
            "9",
            "--usage-ledger",
            str(tmp_path / "usage.jsonl"),
        ]
    )
    admission = _admission("6" * 64)

    class FakeAuthority:
        closed = False

        def close(self) -> None:
            self.closed = True

    authority = FakeAuthority()
    monkeypatch.setattr(cli, "_regular_bytes", lambda *_args, **_kwargs: b"{}")
    monkeypatch.setattr(cli, "_load_receipts", lambda *_args: {})
    monkeypatch.setattr(cli, "_verify_runtime_isolation", lambda *_args: None)
    monkeypatch.setattr(
        cli.ExecutionAdmission,
        "from_canonical_json",
        lambda _encoded: admission,
    )
    monkeypatch.setattr(cli, "UnixAuthorityClient", lambda **_kwargs: authority)

    with pytest.raises(ExecutionBridgeViolation, match="actor factory"):
        cli._execute(arguments, actor_factory=lambda _admission: object())

    assert authority.closed is True
