from __future__ import annotations

import json
import threading
import urllib.request
from datetime import timedelta
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from agent_os_contracts import (
    MandateCommitmentContext,
    RelevanceDisposition,
    content_digest,
)
from apps.api_server import _data_agent_situated_startup as startup
from apps.api_server._data_agent_situated_startup import (
    DataAgentSituatedStartupConfigError,
)
from apps.api_server.server import Handler
from tests.product.test_data_agent_external_report_adapter import (
    _adapter as _test_adapter,
    _config as _test_source_config,
    _report_bytes,
)
from tests.product.test_data_agent_situated_cli import (
    NOW,
    _policy,
)
from tests.product.test_data_agent_situated_startup import (
    provider_credential,
    relevance_context,
    source_credential,
    valid_config_data,
    write_canonical,
    write_config,
)
from tests.product.test_provider_relevance_assessor import _draft
from tests.product.mandate_observation_support import (
    authorize_workspace_observation,
    create_workspace_record,
)


class _ProviderResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> _ProviderResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


def _start_http(handler: type[BaseHTTPRequestHandler]):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, f"http://127.0.0.1:{server.server_port}"


def _post(
    base_url: str,
    trace_id: str,
    *,
    opener: Any = urllib.request.urlopen,
) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        f"{base_url}/api/situated/data-agent-reports/{trace_id}/proposal",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with opener(request) as response:
        payload = json.loads(response.read())
        assert isinstance(payload, dict)
        return response.status, payload


def test_canonical_integer_temperature_stays_integer() -> None:
    invocation = _policy(provider_credential()).provider_invocation.model_copy(
        update={"temperature": Decimal("0")}
    )

    converted = startup._canonical_provider_temperature(invocation)

    assert type(converted) is int
    assert converted == 0


def test_exact_float_temperature_preserves_invocation_digest() -> None:
    invocation = _policy(provider_credential()).provider_invocation.model_copy(
        update={"temperature": Decimal("0.25")}
    )

    converted = startup._canonical_provider_temperature(invocation)
    reconstructed = invocation.model_copy(
        update={"temperature": Decimal(str(converted))}
    )

    assert type(converted) is float
    assert content_digest(reconstructed) == content_digest(invocation)


def test_temperature_that_loses_canonical_scale_fails_closed() -> None:
    invocation = _policy(provider_credential()).provider_invocation.model_copy(
        update={"temperature": Decimal("0.10")}
    )

    with pytest.raises(DataAgentSituatedStartupConfigError, match="binding mismatch"):
        startup._canonical_provider_temperature(invocation)


def test_canonical_startup_runs_real_http_proposal_without_invocation_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    trace_id = "trace-123"
    source_calls = [0]
    source_body = _report_bytes(trace_id=trace_id)

    class SourceHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            source_calls[0] += 1
            assert self.path == f"/runs/{trace_id}/report?audience=external"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Encoding", "identity")
            self.send_header("Content-Length", str(len(source_body)))
            self.end_headers()
            self.wfile.write(source_body)

        def log_message(self, format: str, *args: object) -> None:
            return

    source_server, source_thread, source_origin = _start_http(SourceHandler)
    source = source_credential().model_copy(
        update={
            "scopes": tuple(
                sorted(
                    (
                        "reports:read",
                        f"data-agent-origin:{source_origin}",
                        "data-agent-tenant:upstream-tenant-9",
                    )
                )
            )
        }
    )
    provider_ref = provider_credential()
    policy = _policy(provider_ref)
    authority_database = tmp_path / "authority.sqlite3"
    authority_adapter, _, _ = _test_adapter(
        config=_test_source_config(
            source_id="data-agent-source-main",
            base_url=source_origin,
            source_tenant_id="upstream-tenant-9",
            credential=source,
            principal_id="principal-77",
            target_tenant_id="tenant-golden-1",
            target_workspace_id="workspace-golden-1",
            mandate_id="mandate-situated-42",
            environment_binding_id="binding-situated-42",
            scope_ref="scope:data-agent-reports",
            allow_loopback_http=True,
            timeout_seconds=10,
            max_response_bytes=1_048_576,
            freshness_seconds=300,
        )
    )
    workspace_record = create_workspace_record(
        authority_database, tmp_path, adapter=authority_adapter, now=NOW
    )
    context = relevance_context().model_copy(
        update={
            "mandate_version": 1,
            "mandate_digest": content_digest(workspace_record.mandate),
            "open_commitments": (
                MandateCommitmentContext(
                    commitment_id="commitment:quality",
                    statement="Protect the verified product quality boundary.",
                    due_at=NOW + timedelta(hours=2),
                ),
            )
        }
    )

    write_canonical(tmp_path / "source-credential.json", source)
    write_canonical(tmp_path / "provider-credential.json", provider_ref)
    write_canonical(tmp_path / "provider-policy.json", policy)
    write_canonical(tmp_path / "relevance-context.json", context)
    config = valid_config_data()
    config["authority_database"] = str(authority_database)
    config["expected_mandate_version"] = 1
    config["expected_mandate_digest"] = content_digest(workspace_record.mandate)
    config["expected_correction_epoch"] = 0
    config["expected_binding_digest"] = (
        authority_adapter.admission_policy_descriptor.policy_digest
    )
    config["source"].update(
        {
            "base_url": source_origin,
            "allow_loopback_http": True,
            "expected_credential_digest": content_digest(source),
        }
    )
    config["provider"].update(
        {
            "expected_credential_digest": content_digest(provider_ref),
            "expected_policy_digest": content_digest(policy),
            "expected_context_digest": content_digest(context),
        }
    )
    config_path = write_config(tmp_path, config)
    authorize_workspace_observation(
        authority_database,
        tmp_path,
        adapter=authority_adapter,
        assessor=policy.assessor_ref(),
        context=context.ref(),
        now=NOW,
    )

    provider_calls = [0]
    real_urlopen = urllib.request.urlopen

    def provider_opener(*args: object, **kwargs: object) -> _ProviderResponse:
        provider_calls[0] += 1
        return _ProviderResponse(
            {
                "id": "provider-response-1",
                "choices": [
                    {
                        "message": {
                            "content": _draft(RelevanceDisposition.CREATE_TASK)
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 10,
                    "total_tokens": 20,
                },
            }
        )

    monkeypatch.setattr(
        "agent_os_core.provider.urllib.request.urlopen", provider_opener
    )
    monkeypatch.setenv(source.resolver_key, "source-secret")
    monkeypatch.setenv(provider_ref.resolver_key, "provider-secret")

    application = startup._build_data_agent_situated_application(
        config_path=config_path,
        database=tmp_path / "runtime.sqlite3",
        workspace=tmp_path,
        clock=lambda: NOW,
    )
    runtime = application._data_agent_situated_runtime
    assert runtime is not None
    constructed_provider = runtime._steward._proposal_service._assessor._provider
    assert content_digest(constructed_provider.invocation_binding) == content_digest(
        policy.provider_invocation
    )

    api_handler = type("FullStackHandler", (Handler,), {"application": application})
    api_server, api_thread, api_origin = _start_http(api_handler)
    try:
        status, result = _post(api_origin, trace_id, opener=real_urlopen)
    finally:
        api_server.shutdown()
        api_server.server_close()
        api_thread.join(timeout=2)
        source_server.shutdown()
        source_server.server_close()
        source_thread.join(timeout=2)
        application.store.close()

    assert status == 200
    assert result["outcome_kind"] == "TASK_DRAFT"
    assert result["task_draft"]["activation_authorized"] is False
    assert source_calls == [1]
    assert provider_calls == [1]
