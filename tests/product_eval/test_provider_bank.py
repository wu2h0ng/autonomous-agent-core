from __future__ import annotations

import hashlib
import http.client
import json
import multiprocessing
import os
import stat
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from agent_os_contracts import (
    CredentialRef,
    CredentialStatus,
    EdgeSpec,
    IdempotencyMode,
    NodeKind,
    NodeSpec,
    ProviderMessage,
    ProviderMessageRole,
    ProviderRequest,
    ProviderResponse,
    RunStatus,
    WorkflowGraph,
)
from apps.api_server.app import AgentOSApplication
from agent_os_core import EnvCredentialBroker, OpenAICompatibleProvider

from product_evals.common import provider_bank
from product_evals.common.provider_bank import FrozenProviderServer, request_body_digest


ROOT = Path(__file__).resolve().parents[2]
CASES_PATH = ROOT / "product_evals/spine_e2e_1/frozen_cases.json"
BANK_PATH = ROOT / "product_evals/spine_e2e_1/provider_responses.json"
DUMMY_BEARER = "spine-e2e-1-local-dummy"
CONTEXT = hashlib.sha256(b"spine-e2e-1-provider-ledger-test").hexdigest()
LEDGER_FIELDS = {
    "schema_version",
    "ordinal",
    "request_digest",
    "accepted",
    "reason",
    "chain_context_sha256",
    "previous_record_sha256",
    "record_sha256",
}


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _load(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _entries() -> list[dict[str, object]]:
    value = _load(BANK_PATH)
    assert isinstance(value, dict)
    return value["entries"]  # type: ignore[return-value]


def _runtime_request(case: dict[str, object]) -> dict[str, object]:
    initial_content = str(case["initial_content"])
    prompt = (
        f"Repository task: {case['goal']}\n"
        f"Target path: {case['target_path']}\n"
        f"Current SHA-256: {hashlib.sha256(initial_content.encode('utf-8')).hexdigest()}\n"
        "Current file content follows:\n"
        f"---BEGIN FILE---\n{initial_content}\n---END FILE---\n"
        "Propose the complete replacement content by calling only the "
        "workspace.apply_patch tool. Include path and content. Do not call any "
        "other capability and do not claim that the patch was applied."
    )
    return {
        "model": "spine-e2e-1-frozen",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "workspace__apply_patch",
                    "description": "Invoke typed capability workspace.apply_patch",
                    "parameters": {"type": "object", "additionalProperties": True},
                },
            }
        ],
        "tool_choice": "auto",
    }


def _request(
    server: FrozenProviderServer,
    body: object,
    *,
    method: str = "POST",
    path: str = "/chat/completions",
    authorization: str = f"Bearer {DUMMY_BEARER}",
    content_type: str = "application/json",
) -> tuple[int, object]:
    request = urllib.request.Request(
        server.base_url + path,
        data=_canonical(body),
        headers={"Authorization": authorization, "Content-Type": content_type},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        payload = json.loads(exc.read())
        return exc.code, payload


def _server(tmp_path: Path, *, bank_path: Path = BANK_PATH) -> FrozenProviderServer:
    server = FrozenProviderServer(
        bank_path,
        ledger_path=tmp_path / "provider_calls.jsonl",
        context_sha256=CONTEXT,
    )
    server.start()
    assert server.base_url.endswith("/v1")
    return server


def test_server_accepts_an_explicit_successor_bearer(tmp_path: Path) -> None:
    successor_bearer = "spine-e2e-3-local-dummy"
    server = FrozenProviderServer(
        BANK_PATH,
        ledger_path=tmp_path / "provider_calls.jsonl",
        context_sha256=CONTEXT,
        expected_bearer=successor_bearer,
    )
    server.start()
    try:
        body = _entries()[0]["request"]
        status, payload = _request(
            server,
            body,
            authorization=f"Bearer {successor_bearer}",
        )
        assert status == 200
        assert payload == _entries()[0]["response"]
        status, payload = _request(server, body)
        assert status == 401
        assert payload == {"error": "UNAUTHORIZED"}
    finally:
        server.close(validate_counts=False)


def _ledger(path: Path) -> list[dict[str, object]]:
    raw = path.read_bytes()
    assert raw.endswith(b"\n")
    return [json.loads(line) for line in raw.splitlines()]


def _child_call(bank: str, ledger: str, context: str, body: dict[str, object]) -> None:
    server = FrozenProviderServer(
        Path(bank), ledger_path=Path(ledger), context_sha256=context
    )
    server.start()
    try:
        _request(server, body)
    finally:
        server.close(validate_counts=False)


def _raw_request(
    server: FrozenProviderServer, raw: bytes, *, method: str = "POST"
) -> tuple[int, object | None]:
    location = urlsplit(server.base_url)
    connection = http.client.HTTPConnection(location.hostname, location.port, timeout=5)
    connection.request(
        method,
        "/v1/chat/completions",
        body=raw,
        headers={
            "Authorization": f"Bearer {DUMMY_BEARER}",
            "Content-Type": "application/json",
        },
    )
    response = connection.getresponse()
    payload = response.read()
    connection.close()
    return response.status, json.loads(payload) if payload else None


def test_frozen_corpus_has_twelve_distinct_real_cases_and_exact_provider_wire() -> None:
    cases = _load(CASES_PATH)["cases"]
    entries = _entries()
    assert len(cases) == len(entries) == 12
    assert {case["family"] for case in cases} == {
        "string_transform",
        "numeric_reducer",
        "validator",
        "formatter",
    }
    assert {
        family: sum(case["family"] == family for case in cases)
        for family in {case["family"] for case in cases}
    } == {
        "string_transform": 3,
        "numeric_reducer": 3,
        "validator": 3,
        "formatter": 3,
    }
    by_id = {case["case_id"]: case for case in cases}
    assert len(by_id) == 12
    for entry in entries:
        case = by_id[entry["case_id"]]
        assert set(case) == {
            "case_id",
            "family",
            "goal",
            "target_path",
            "test_path",
            "initial_content",
            "patched_content",
            "pytest_source",
        }
        assert case["target_path"] == "subject.py"
        assert case["test_path"] == "test_subject.py"
        assert not Path(case["target_path"]).is_absolute()
        assert ".." not in Path(case["target_path"]).parts
        assert entry["expected_calls"] == 2
        request = entry["request"]
        assert request == _runtime_request(case)
        assert entry["digest"] == request_body_digest(request)
        response = entry["response"]
        assert response["choices"][0]["finish_reason"] == "tool_calls"
        usage = response["usage"]
        assert all(
            type(usage[name]) is int
            for name in ("prompt_tokens", "completion_tokens", "total_tokens")
        )
        calls = response["choices"][0]["message"]["tool_calls"]
        assert len(calls) == 1
        arguments = json.loads(calls[0]["function"]["arguments"])
        assert arguments == {
            "path": case["target_path"],
            "content": case["patched_content"],
        }
        assert set(arguments) == {"path", "content"}


def test_real_application_provider_wire_matches_frozen_single_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _load(CASES_PATH)["cases"][0]
    entry = next(item for item in _entries() if item["case_id"] == case["case_id"])
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / case["target_path"]).write_text(
        case["initial_content"], encoding="utf-8"
    )
    (workspace / case["test_path"]).write_text(case["pytest_source"], encoding="utf-8")
    ledger_path = tmp_path / "provider_calls.jsonl"
    server = FrozenProviderServer(
        BANK_PATH, ledger_path=ledger_path, context_sha256=CONTEXT
    )
    server.start()
    now = datetime.now(timezone.utc)
    monkeypatch.setenv("AGENT_OS_PROVIDER_BASE_URL", server.base_url)
    monkeypatch.setenv("AGENT_OS_PROVIDER_MODEL", "spine-e2e-1-frozen")
    monkeypatch.setenv("AGENT_OS_PROVIDER_TEMPERATURE", "0")
    monkeypatch.setenv("AGENT_OS_PROVIDER_API_KEY_ENV", "SPINE_E2E_1_TEST_BEARER")
    monkeypatch.setenv("SPINE_E2E_1_TEST_BEARER", DUMMY_BEARER)
    app = AgentOSApplication(
        database=tmp_path / "agent-os.sqlite3", workspace=workspace
    )
    task = app.create_task(
        {
            "goal_id": "goal:provider-wire",
            "tenant_id": "tenant:local",
            "workspace_id": "workspace:local",
            "created_by": "user:local",
            "created_at": now,
            "statement": case["goal"],
        }
    )
    nodes = (
        NodeSpec(
            node_id="read",
            kind=NodeKind.TOOL,
            capability="workspace.read",
            idempotency=IdempotencyMode.IDEMPOTENT,
        ),
        NodeSpec(
            node_id="provider", kind=NodeKind.PROVIDER, capability="provider.chat"
        ),
        NodeSpec(node_id="approve", kind=NodeKind.APPROVAL),
        NodeSpec(
            node_id="apply",
            kind=NodeKind.TOOL,
            capability="workspace.apply_patch",
            idempotency=IdempotencyMode.COMPENSATABLE,
            risk_tier=1,
        ),
        NodeSpec(
            node_id="tests",
            kind=NodeKind.TOOL,
            capability="workspace.run_tests",
            idempotency=IdempotencyMode.IDEMPOTENT,
        ),
        NodeSpec(node_id="evaluate", kind=NodeKind.EVALUATION),
        NodeSpec(node_id="done", kind=NodeKind.TERMINAL),
    )
    workflow = WorkflowGraph(
        workflow_id="workflow:provider-wire",
        version=1,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        created_by="user:local",
        created_at=now,
        policy_version="policy-1",
        evaluator_refs=("evaluator:pytest:1",),
        nodes=nodes,
        edges=tuple(
            EdgeSpec(source=source, target=target)
            for source, target in (
                ("read", "provider"),
                ("provider", "approve"),
                ("approve", "apply"),
                ("apply", "tests"),
                ("tests", "evaluate"),
                ("evaluate", "done"),
            )
        ),
    )
    commitment = {
        "commitment_id": "commitment:provider-wire",
        "task_id": task.task_id,
        "goal_id": "goal:provider-wire",
        "tenant_id": "tenant:local",
        "workspace_id": "workspace:local",
        "accepted_by": "user:local",
        "accepted_at": now,
        "deliverables": ["subject.py patch"],
        "acceptance_criteria": ["python -m pytest exits 0"],
        "authority_scopes": ["workspace:read", "workspace:write"],
        "budget": {
            "max_cost_usd": "1",
            "max_duration_seconds": 300,
            "max_provider_tokens": 1000,
            "max_tool_calls": 10,
        },
        "risk_tier": 1,
        "exit_conditions": ["verified"],
        "expires_at": now + timedelta(hours=1),
    }
    expected = {
        "expected_outcome_id": "expected:provider-wire",
        "task_id": task.task_id,
        "tenant_id": "tenant:local",
        "workspace_id": "workspace:local",
        "evaluator_type": "pytest",
        "evaluator_version": "1",
        "evidence_requirements": ["pytest-report"],
        "failure_semantics": ["non-zero exit"],
        "threshold": 1,
        "observation_window_seconds": 60,
        "frozen_at": now,
    }
    app.commit_task(
        task.task_id,
        {
            "commitment": commitment,
            "workflow": workflow.model_dump(mode="json"),
            "expected_outcome": expected,
        },
    )
    try:
        waiting = app.run_task(
            task.task_id,
            {"target_path": case["target_path"], "test_command": "python -m pytest"},
        )
    finally:
        server.close(validate_counts=False)
    assert waiting.run is not None
    assert waiting.run.status is RunStatus.WAITING_APPROVAL
    records = _ledger(ledger_path)
    assert len(records) == 1
    assert records[0]["accepted"] is True
    assert records[0]["request_digest"] == entry["digest"]


def test_canonical_request_replays_stored_response_verbatim_after_json_decode(
    tmp_path: Path,
) -> None:
    entry = _entries()[0]
    server = _server(tmp_path)
    try:
        status, response = _request(server, entry["request"])
        assert status == 200
        assert response == entry["response"]
    finally:
        server.close(validate_counts=False)


def test_real_openai_compatible_provider_hits_frozen_wire(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = _entries()[0]
    prompt = entry["request"]["messages"][0]["content"]
    key_name = "SPINE_E2E_1_TEST_BEARER"
    monkeypatch.setenv(key_name, DUMMY_BEARER)
    now = datetime.now(timezone.utc)
    credential = CredentialRef(
        credential_ref_id="credential:spine-e2e-1",
        owner_principal_id="principal:spine-e2e-1",
        tenant_id="tenant:spine-e2e-1",
        workspace_id="workspace:spine-e2e-1",
        provider_id="openai-compatible",
        resolver_key=key_name,
        scopes=("chat",),
        status=CredentialStatus.ACTIVE,
        created_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    server = _server(tmp_path)
    provider = OpenAICompatibleProvider(
        base_url=server.base_url,
        model="spine-e2e-1-frozen",
        credential=credential,
        credentials=EnvCredentialBroker(),
        timeout_seconds=5,
        temperature=0.0,
    )
    try:
        response = provider.complete(
            ProviderRequest(
                request_id="request:spine-e2e-1",
                task_id="task:spine-e2e-1",
                run_id="run:spine-e2e-1",
                provider_profile_id="profile:spine-e2e-1",
                messages=(
                    ProviderMessage(role=ProviderMessageRole.USER, content=prompt),
                ),
                allowed_capability_ids=("workspace.apply_patch",),
                timeout_seconds=5,
                created_at=now,
            )
        )
        assert isinstance(response, ProviderResponse)
        assert len(response.tool_proposals) == 1
        proposal = response.tool_proposals[0]
        assert proposal.capability_id == "workspace.apply_patch"
        assert json.loads(proposal.arguments_json) == json.loads(
            entry["response"]["choices"][0]["message"]["tool_calls"][0]["function"][
                "arguments"
            ]
        )
    finally:
        server.close(validate_counts=False)


@pytest.mark.parametrize("invalid_kind", ["duplicate_key", "nan", "infinity"])
def test_noncanonical_json_is_rejected_before_digest_matching(
    tmp_path: Path, invalid_kind: str
) -> None:
    raw = _canonical(_entries()[0]["request"])
    if invalid_kind == "duplicate_key":
        model = b'"model":"spine-e2e-1-frozen"'
        raw = raw.replace(model, b'"model":"evil",' + model, 1)
    elif invalid_kind == "nan":
        raw = raw.replace(b'"temperature":0.0', b'"temperature":NaN', 1)
    else:
        raw = raw.replace(b'"temperature":0.0', b'"temperature":Infinity', 1)
    server = _server(tmp_path)
    try:
        status, payload = _raw_request(server, raw)
        assert status == 400
        assert payload == {"error": "INVALID_JSON"}
    finally:
        server.close(validate_counts=False)
    records = _ledger(tmp_path / "provider_calls.jsonl")
    assert len(records) == 1
    assert records[0]["accepted"] is False
    assert records[0]["reason"] == "INVALID_JSON"


@pytest.mark.parametrize(
    "field", ["model", "messages", "temperature", "tools", "tool_choice"]
)
def test_any_complete_request_body_drift_fails_closed(
    tmp_path: Path, field: str
) -> None:
    entry = _entries()[0]
    body = deepcopy(entry["request"])
    if field == "messages":
        body[field][0]["content"] += " drift"
    elif field == "tools":
        body[field][0]["function"]["parameters"] = {
            "type": "object",
            "additionalProperties": False,
        }
    elif field == "temperature":
        body[field] = 0.1
    else:
        body[field] = str(body[field]) + "-drift"
    server = _server(tmp_path)
    try:
        status, payload = _request(server, body)
        assert status == 422
        assert payload["error"] == "UNKNOWN_REQUEST_DIGEST"
    finally:
        server.close(validate_counts=False)


@pytest.mark.parametrize(
    ("method", "path", "authorization", "content_type"),
    [
        ("PUT", "/chat/completions", f"Bearer {DUMMY_BEARER}", "application/json"),
        ("POST", "/models", f"Bearer {DUMMY_BEARER}", "application/json"),
        ("POST", "/chat/completions", "Bearer wrong", "application/json"),
        ("POST", "/chat/completions", DUMMY_BEARER, "application/json"),
        ("POST", "/chat/completions", f"Bearer {DUMMY_BEARER}", "text/json"),
    ],
)
def test_method_path_and_required_semantic_headers_fail_closed(
    tmp_path: Path,
    method: str,
    path: str,
    authorization: str,
    content_type: str,
) -> None:
    server = _server(tmp_path)
    try:
        status, payload = _request(
            server,
            _entries()[0]["request"],
            method=method,
            path=path,
            authorization=authorization,
            content_type=content_type,
        )
        assert status in {401, 404, 405, 415}
        assert payload["error"]
    finally:
        server.close(validate_counts=False)


@pytest.mark.parametrize("method", ["HEAD", "OPTIONS", "TRACE", "CONNECT", "PROPFIND"])
def test_all_common_non_post_methods_are_durably_rejected(
    tmp_path: Path, method: str
) -> None:
    server = _server(tmp_path)
    try:
        status, _ = _raw_request(server, b"", method=method)
        assert status == 405
    finally:
        server.close(validate_counts=False)
    records = _ledger(tmp_path / "provider_calls.jsonl")
    assert len(records) == 1
    assert records[0]["accepted"] is False
    assert records[0]["reason"] == "METHOD_NOT_ALLOWED"


def test_content_type_is_semantic_and_transport_headers_are_not_frozen(
    tmp_path: Path,
) -> None:
    server = _server(tmp_path)
    entry = _entries()[0]
    request = urllib.request.Request(
        server.base_url + "/chat/completions",
        data=_canonical(entry["request"]),
        headers={
            "Authorization": f"Bearer {DUMMY_BEARER}",
            "Content-Type": "Application/JSON; charset=utf-8",
            "User-Agent": "arbitrary-platform-agent",
            "Accept-Encoding": "identity",
            "Connection": "close",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            assert json.loads(response.read()) == entry["response"]
    finally:
        server.close(validate_counts=False)


@pytest.mark.parametrize("missing_header", ["Authorization", "Content-Type"])
def test_missing_required_semantic_header_is_rejected(
    tmp_path: Path, missing_header: str
) -> None:
    server = _server(tmp_path)
    headers = {
        "Authorization": f"Bearer {DUMMY_BEARER}",
        "Content-Type": "application/json",
    }
    headers.pop(missing_header)
    request = urllib.request.Request(
        server.base_url + "/chat/completions",
        data=_canonical(_entries()[0]["request"]),
        headers=headers,
        method="POST",
    )
    try:
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=5)
        assert caught.value.code in {401, 415}
        assert json.loads(caught.value.read())["error"]
    finally:
        server.close(validate_counts=False)


def test_duplicate_request_digest_keys_are_rejected_at_bank_load(
    tmp_path: Path,
) -> None:
    bank = deepcopy(_load(BANK_PATH))
    bank["entries"][1]["digest"] = bank["entries"][0]["digest"]
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(json.dumps(bank), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate request digest"):
        FrozenProviderServer(
            duplicate,
            ledger_path=tmp_path / "ledger.jsonl",
            context_sha256=CONTEXT,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "expected_calls",
        "expected_calls_bool",
        "duplicate_case_id",
        "eleven",
        "thirteen",
    ],
)
def test_bank_cardinality_and_call_budget_are_frozen(
    tmp_path: Path, mutation: str
) -> None:
    bank = deepcopy(_load(BANK_PATH))
    if mutation == "expected_calls":
        bank["entries"][0]["expected_calls"] = 3
    elif mutation == "expected_calls_bool":
        bank["entries"][0]["expected_calls"] = True
    elif mutation == "duplicate_case_id":
        bank["entries"][1]["case_id"] = bank["entries"][0]["case_id"]
    elif mutation == "eleven":
        bank["entries"].pop()
    else:
        extra = deepcopy(bank["entries"][0])
        extra["case_id"] = "extra_case"
        extra["request"]["messages"][0]["content"] += " extra"
        extra["digest"] = request_body_digest(extra["request"])
        bank["entries"].append(extra)
    malformed = tmp_path / "malformed-cardinality.json"
    malformed.write_text(json.dumps(bank), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid provider bank"):
        FrozenProviderServer(
            malformed,
            ledger_path=tmp_path / "ledger.jsonl",
            context_sha256=CONTEXT,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "choices_count",
        "tool_calls_count",
        "function_name",
        "arguments_fields",
        "arguments_json",
        "usage_bool",
        "choice_index_bool",
        "finish_reason",
    ],
)
def test_malformed_frozen_response_is_rejected_at_bank_load(
    tmp_path: Path, mutation: str
) -> None:
    bank = deepcopy(_load(BANK_PATH))
    response = bank["entries"][0]["response"]
    choice = response["choices"][0]
    tool_calls = choice["message"]["tool_calls"]
    if mutation == "choices_count":
        response["choices"].append(deepcopy(choice))
    elif mutation == "tool_calls_count":
        tool_calls.append(deepcopy(tool_calls[0]))
    elif mutation == "function_name":
        tool_calls[0]["function"]["name"] = "other"
    elif mutation == "arguments_fields":
        tool_calls[0]["function"]["arguments"] = json.dumps(
            {"path": "subject.py", "content": "x", "extra": True}
        )
    elif mutation == "arguments_json":
        tool_calls[0]["function"]["arguments"] = "{"
    elif mutation == "usage_bool":
        response["usage"]["prompt_tokens"] = True
    elif mutation == "choice_index_bool":
        choice["index"] = False
    else:
        choice["finish_reason"] = "stop"
    malformed = tmp_path / "malformed.json"
    malformed.write_text(json.dumps(bank), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid provider response"):
        FrozenProviderServer(
            malformed,
            ledger_path=tmp_path / "ledger.jsonl",
            context_sha256=CONTEXT,
        )


def test_expected_calls_allows_exactly_two_then_rejects_third(tmp_path: Path) -> None:
    server = _server(tmp_path)
    entry = _entries()[0]
    try:
        assert _request(server, entry["request"])[0] == 200
        assert _request(server, entry["request"])[0] == 200
        status, payload = _request(server, entry["request"])
        assert status == 409
        assert payload["error"] == "EXPECTED_CALLS_EXCEEDED"
    finally:
        server.close(validate_counts=False)
    records = _ledger(tmp_path / "provider_calls.jsonl")
    assert [record["accepted"] for record in records] == [True, True, False]


def test_close_rejects_call_count_mismatch(tmp_path: Path) -> None:
    server = _server(tmp_path)
    assert _request(server, _entries()[0]["request"])[0] == 200
    with pytest.raises(ValueError, match="CALL_COUNT_MISMATCH"):
        server.close(validate_counts=True)


def test_all_twelve_entries_accept_exactly_two_calls_and_validate_counts(
    tmp_path: Path,
) -> None:
    server = _server(tmp_path)
    for entry in _entries():
        assert _request(server, entry["request"])[0] == 200
        assert _request(server, entry["request"])[0] == 200
    server.close(validate_counts=True)
    records = _ledger(tmp_path / "provider_calls.jsonl")
    assert len(records) == 24
    assert all(record["accepted"] is True for record in records)


def test_new_server_replays_existing_ledger_counts(tmp_path: Path) -> None:
    ledger = tmp_path / "provider_calls.jsonl"
    entry = _entries()[0]
    first = _server(tmp_path)
    assert _request(first, entry["request"])[0] == 200
    first.close(validate_counts=False)

    second = FrozenProviderServer(BANK_PATH, ledger_path=ledger, context_sha256=CONTEXT)
    second.start()
    try:
        assert _request(second, entry["request"])[0] == 200
        status, payload = _request(second, entry["request"])
        assert status == 409
        assert payload["error"] == "EXPECTED_CALLS_EXCEEDED"
    finally:
        second.close(validate_counts=False)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_final_newline",
        "blank_line",
        "extra_field",
        "missing_field",
        "chain_tamper",
        "context_tamper",
        "digest_tamper",
    ],
)
def test_existing_ledger_corruption_fails_closed_at_construction_or_start(
    tmp_path: Path, mutation: str
) -> None:
    ledger = tmp_path / "provider_calls.jsonl"
    server = _server(tmp_path)
    assert _request(server, _entries()[0]["request"])[0] == 200
    server.close(validate_counts=False)
    records = _ledger(ledger)
    if mutation == "missing_final_newline":
        ledger.write_bytes(ledger.read_bytes().removesuffix(b"\n"))
    elif mutation == "blank_line":
        ledger.write_bytes(ledger.read_bytes() + b"\n")
    else:
        record = records[0]
        if mutation == "extra_field":
            record["extra"] = "forbidden"
        elif mutation == "missing_field":
            record.pop("reason")
        elif mutation == "chain_tamper":
            record["previous_record_sha256"] = "0" * 64
        elif mutation == "context_tamper":
            record["chain_context_sha256"] = "0" * 64
        else:
            record["record_sha256"] = "0" * 64
        ledger.write_bytes(_canonical(record) + b"\n")

    with pytest.raises(ValueError):
        replay = FrozenProviderServer(
            BANK_PATH, ledger_path=ledger, context_sha256=CONTEXT
        )
        replay.start()


def test_existing_ledger_rejects_unknown_rejected_reason(tmp_path: Path) -> None:
    ledger = tmp_path / "provider_calls.jsonl"
    server = _server(tmp_path)
    unknown = deepcopy(_entries()[0]["request"])
    unknown["model"] = "unknown"
    assert _request(server, unknown)[0] == 422
    server.close(validate_counts=False)
    record = _ledger(ledger)[0]
    record["reason"] = "ARBITRARY_REJECTED_REASON"
    unsigned = {key: value for key, value in record.items() if key != "record_sha256"}
    record["record_sha256"] = hashlib.sha256(_canonical(unsigned)).hexdigest()
    ledger.write_bytes(_canonical(record) + b"\n")
    with pytest.raises(ValueError):
        FrozenProviderServer(BANK_PATH, ledger_path=ledger, context_sha256=CONTEXT)


def test_accepted_and_rejected_attempts_use_exact_context_bound_hash_chain_schema(
    tmp_path: Path,
) -> None:
    server = _server(tmp_path)
    known = _entries()[0]["request"]
    unknown = deepcopy(known)
    unknown["model"] = "unknown"
    try:
        assert _request(server, known)[0] == 200
        assert _request(server, unknown)[0] == 422
    finally:
        server.close(validate_counts=False)
    records = _ledger(tmp_path / "provider_calls.jsonl")
    previous = hashlib.sha256(
        b"agent-os-provider-call-ledger-v1\0" + bytes.fromhex(CONTEXT)
    ).hexdigest()
    for ordinal, record in enumerate(records):
        assert set(record) == LEDGER_FIELDS
        assert record["schema_version"] == "agent-os-provider-call-ledger-v1"
        assert record["ordinal"] == ordinal
        assert record["chain_context_sha256"] == CONTEXT
        assert record["previous_record_sha256"] == previous
        unsigned = {
            key: value for key, value in record.items() if key != "record_sha256"
        }
        assert (
            record["record_sha256"] == hashlib.sha256(_canonical(unsigned)).hexdigest()
        )
        previous = record["record_sha256"]
    assert records[0]["reason"] == "ACCEPTED"
    assert records[1]["reason"] == "UNKNOWN_REQUEST_DIGEST"


def test_shared_ledger_serializes_cross_process_contention(tmp_path: Path) -> None:
    entry = _entries()[0]
    ledger = tmp_path / "shared.jsonl"
    ctx = multiprocessing.get_context("spawn")
    processes = [
        ctx.Process(
            target=_child_call,
            args=(str(BANK_PATH), str(ledger), CONTEXT, entry["request"]),
        )
        for _ in range(3)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(15)
        assert process.exitcode == 0
    records = _ledger(ledger)
    assert len(records) == 3
    assert sum(record["accepted"] is True for record in records) == 2
    assert [record["ordinal"] for record in records] == [0, 1, 2]


@pytest.mark.parametrize("written", [0, 1])
def test_short_or_zero_ledger_write_rolls_back_without_partial_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, written: int
) -> None:
    server = _server(tmp_path)
    real_write = provider_bank.os.write
    calls = 0

    def short_write(fd: int, data: bytes) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            if written:
                real_write(fd, data[:written])
            return written
        return real_write(fd, data)

    monkeypatch.setattr(provider_bank.os, "write", short_write)
    try:
        status, payload = _request(server, _entries()[0]["request"])
        assert status == 500
        assert payload["error"] == "DURABLE_LEDGER_WRITE_FAILED"
    finally:
        server.close(validate_counts=False)
    ledger = tmp_path / "provider_calls.jsonl"
    assert not ledger.exists() or ledger.read_bytes() == b""


def test_durable_append_fsyncs_file_and_parent_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = _server(tmp_path)
    real_fsync = provider_bank.os.fsync
    modes: list[int] = []

    def recording_fsync(fd: int) -> None:
        modes.append(os.fstat(fd).st_mode)
        real_fsync(fd)

    monkeypatch.setattr(provider_bank.os, "fsync", recording_fsync)
    try:
        assert _request(server, _entries()[0]["request"])[0] == 200
    finally:
        server.close(validate_counts=False)
    assert any(stat.S_ISREG(mode) for mode in modes)
    assert any(stat.S_ISDIR(mode) for mode in modes)
