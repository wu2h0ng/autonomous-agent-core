from __future__ import annotations

import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from agent_os_contracts import (
    CredentialRef,
    CredentialStatus,
    EnvironmentBindingAuthorization,
    ProviderInvocationBinding,
    ProviderProfile,
    ProviderRelevancePolicy,
    RatifiedMandateRef,
    content_digest,
)
from agent_os_core import (
    RELEVANCE_OUTPUT_SCHEMA_DIGEST,
    RELEVANCE_PROMPT_TEMPLATE_DIGEST,
)
from agent_os_core.situated_persistence import SQLiteSituatedAssessmentStore

from apps.api_server import _data_agent_situated_startup as startup
from apps.api_server._data_agent_situated_startup import (
    DataAgentSituatedStartupConfigError,
)
from tests.product.test_data_agent_situated_startup import (
    RESOLVER_ENV_KEY,
    provider_credential,
    relevance_context,
    source_credential,
    valid_config_data,
    write_canonical,
    write_config,
)

NOW = datetime(2026, 7, 17, 0, 0, tzinfo=timezone.utc)


def _build() -> Any:
    build = getattr(startup, "_build_data_agent_situated_application", None)
    assert build is not None, "private situated application builder is missing"
    return build


def _policy(credential: CredentialRef) -> ProviderRelevancePolicy:
    profile = ProviderProfile(
        profile_id="profile:startup-provider",
        provider_id=credential.provider_id,
        model_id="provider-model",
        endpoint_class="openai-compatible",
        credential_ref_id=credential.credential_ref_id,
        capabilities=("chat",),
        max_context_tokens=16_384,
        request_timeout_seconds=20,
        created_at=NOW,
    )
    invocation = ProviderInvocationBinding(
        provider_profile=profile,
        provider_id=profile.provider_id,
        endpoint_class=profile.endpoint_class,
        credential_ref_id=profile.credential_ref_id,
        credential_ref_digest=content_digest(credential),
        max_context_tokens=profile.max_context_tokens,
        adapter_kind="openai-compatible",
        transport="https-json",
        base_url="https://provider.example/v1",
        endpoint_path="/chat/completions",
        model_id=profile.model_id,
        request_timeout_seconds=profile.request_timeout_seconds,
        temperature=Decimal("0"),
    )
    return ProviderRelevancePolicy(
        assessor_id="assessor:startup",
        version=1,
        provider_invocation=invocation,
        prompt_revision="startup-v1",
        prompt_template_digest=RELEVANCE_PROMPT_TEMPLATE_DIGEST,
        output_schema_ref="agent-os://relevance-assessment-draft/v1",
        output_schema_digest=RELEVANCE_OUTPUT_SCHEMA_DIGEST,
        request_timeout_seconds=20,
        max_artifact_bytes=16_384,
        failure_attention_budget_seconds=60,
    )


def _binding(digest: str = "b" * 64) -> EnvironmentBindingAuthorization:
    return EnvironmentBindingAuthorization(
        environment_binding_id="binding-situated-42",
        version=1,
        binding_digest=digest,
    )


def _mandate(
    assessor_id: str = "assessor:startup",
    policy: ProviderRelevancePolicy | None = None,
    **overrides: object,
) -> RatifiedMandateRef:
    pol = policy or _policy(provider_credential())
    ref = pol.assessor_ref()
    if assessor_id != ref.assessor_id:
        ref = ref.model_copy(update={"assessor_id": assessor_id})
    kwargs: dict[str, Any] = {
        "mandate_id": "mandate-situated-42",
        "version": 3,
        "mandate_digest": "a" * 64,
        "ratification_receipt_id": "ratification:situated-42",
        "tenant_id": "tenant-golden-1",
        "workspace_id": "workspace-golden-1",
        "owner_principal_id": "principal-77",
        "ratified_by": "principal-77",
        "ratified_at": NOW - timedelta(hours=2),
        "valid_from": NOW - timedelta(hours=1),
        "expires_at": NOW + timedelta(days=365),
        "correction_epoch": 2,
        "authority_envelope_digest": "e" * 64,
        "allowed_environment_bindings": (_binding(),),
        "relevance_assessor": ref,
        "relevance_context": relevance_context().ref(),
    }
    kwargs.update(overrides)
    return RatifiedMandateRef.model_validate(kwargs)


def _seed(
    database: str | Path, mandates: list[RatifiedMandateRef]
) -> SQLiteSituatedAssessmentStore:
    path = Path(str(database))
    if path.exists():
        path.unlink()
    return SQLiteSituatedAssessmentStore(database, mandates=mandates)


def _setup(
    tmp_path: Path,
    *,
    prov_cred: CredentialRef | None = None,
    policy: ProviderRelevancePolicy | None = None,
) -> Path:
    src = source_credential()
    prv = prov_cred or provider_credential()
    pol = policy or _policy(prv)
    ctx = relevance_context()
    write_canonical(tmp_path / "source-credential.json", src)
    write_canonical(tmp_path / "provider-credential.json", prv)
    write_canonical(tmp_path / "provider-policy.json", pol)
    write_canonical(tmp_path / "relevance-context.json", ctx)
    config = valid_config_data()
    config["authority_database"] = str(tmp_path / "authority.sqlite3")
    config["source"]["expected_credential_digest"] = content_digest(src)
    config["provider"]["expected_credential_digest"] = content_digest(prv)
    config["provider"]["expected_policy_digest"] = content_digest(pol)
    config["provider"]["expected_context_digest"] = content_digest(ctx)
    return write_config(tmp_path, config)


def _assert_safe(excinfo: pytest.ExceptionInfo[BaseException], tmp_path: Path) -> None:
    msg = str(excinfo.value)
    assert msg.startswith("data agent situated startup ")
    assert str(tmp_path) not in msg
    assert RESOLVER_ENV_KEY not in msg
    assert "AGENT_OS_PROVIDER_API_KEY" not in msg
    assert excinfo.value.__cause__ is None


class TestCliLegacy:
    def test_legacy_no_flag_creates_plain_app_and_never_touches_builder(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        application = object()
        calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

        def construct(**kwargs: Any) -> object:
            calls.append(("app", (), kwargs))
            return application

        def serve(value: object, host: str, port: int) -> None:
            calls.append(("serve", (value, host, port), {}))

        monkeypatch.setattr("apps.api_server.__main__.AgentOSApplication", construct)
        monkeypatch.setattr("apps.api_server.__main__.serve", serve)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "agent-os",
                "--database",
                str(tmp_path / "legacy.sqlite3"),
                "--workspace",
                str(tmp_path),
            ],
        )

        from apps.api_server.__main__ import main

        main()

        assert calls == [
            (
                "app",
                (),
                {
                    "database": str(tmp_path / "legacy.sqlite3"),
                    "workspace": str(tmp_path),
                },
            ),
            ("serve", (application, "127.0.0.1", 8787), {}),
        ]

    def test_legacy_does_not_touch_builder(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(
            "apps.api_server.__main__.AgentOSApplication", lambda **_: object()
        )
        monkeypatch.setattr("apps.api_server.__main__.serve", lambda *args: None)
        monkeypatch.setattr(
            sys, "argv", ["agent-os", "--database", str(tmp_path / "db.sqlite3")]
        )
        monkeypatch.setattr(startup, "_build_data_agent_situated_application", None)
        from apps.api_server.__main__ import main

        main()


class TestCliFlag:
    def test_flag_routes_to_private_builder(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        sentinel = object()
        calls: list[dict[str, Any]] = []
        monkeypatch.setattr(
            startup,
            "_build_data_agent_situated_application",
            lambda **kw: calls.append(kw) or sentinel,
        )
        monkeypatch.setattr("apps.api_server.__main__.serve", lambda *args: None)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "agent-os",
                "--database",
                str(tmp_path / "db.sqlite3"),
                "--workspace",
                str(tmp_path),
                "--data-agent-situated-config",
                str(tmp_path / "cfg.json"),
            ],
        )
        from apps.api_server.__main__ import main

        main()
        assert calls == [
            {
                "config_path": str(tmp_path / "cfg.json"),
                "database": str(tmp_path / "db.sqlite3"),
                "workspace": str(tmp_path),
            }
        ]

    def test_flag_rejects_memory_before_serve(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr("apps.api_server.__main__.serve", lambda *_: None)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "agent-os",
                "--database",
                ":memory:",
                "--workspace",
                str(tmp_path),
                "--data-agent-situated-config",
                str(tmp_path / "cfg.json"),
            ],
        )
        from apps.api_server.__main__ import main

        with pytest.raises(DataAgentSituatedStartupConfigError) as excinfo:
            main()
        assert "in-memory" in str(excinfo.value).lower()


class TestBuilder:
    def test_rejects_legacy_preexisting_authority_with_zero_provider_calls(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv(RESOLVER_ENV_KEY, "raw-source-secret")
        monkeypatch.setenv("AGENT_OS_PROVIDER_API_KEY", "raw-provider-secret")
        config = _setup(tmp_path)
        _seed(tmp_path / "authority.sqlite3", [_mandate()])
        orig = urllib.request.urlopen
        count = [0]
        urllib.request.urlopen = lambda *a, **kw: (
            count.__setitem__(0, count[0] + 1)
            or (_ for _ in ()).throw(AssertionError("no net calls"))
        )  # type: ignore[assignment]
        try:
            with pytest.raises(DataAgentSituatedStartupConfigError):
                _build()(
                    config_path=config,
                    database=str(tmp_path / "runtime.sqlite3"),
                    workspace=str(tmp_path),
                    clock=lambda: NOW,
                )
        finally:
            urllib.request.urlopen = orig  # type: ignore[assignment]
        assert count[0] == 0

    def test_rejects_memory_database(self, tmp_path: Path) -> None:
        config = _setup(tmp_path)
        _seed(tmp_path / "authority.sqlite3", [_mandate()])
        with pytest.raises(DataAgentSituatedStartupConfigError) as excinfo:
            _build()(
                config_path=config,
                database=":memory:",
                workspace=str(tmp_path),
                clock=lambda: NOW,
            )
        _assert_safe(excinfo, tmp_path)
        assert "in-memory" in str(excinfo.value).lower()

    def test_authority_absent_fails(self, tmp_path: Path) -> None:
        config = _setup(tmp_path)
        with pytest.raises(DataAgentSituatedStartupConfigError) as excinfo:
            _build()(
                config_path=config,
                database=str(tmp_path / "runtime.sqlite3"),
                workspace=str(tmp_path),
                clock=lambda: NOW,
            )
        _assert_safe(excinfo, tmp_path)
        assert "authority database" in str(excinfo.value)

    def test_authority_revoked_fails(self, tmp_path: Path) -> None:
        config = _setup(tmp_path)
        s = _seed(tmp_path / "authority.sqlite3", [_mandate()])
        s.revoke(
            "mandate-situated-42",
            expected_epoch=2,
            principal_id="principal-77",
            tenant_id="tenant-golden-1",
            workspace_id="workspace-golden-1",
        )
        with pytest.raises(DataAgentSituatedStartupConfigError) as excinfo:
            _build()(
                config_path=config,
                database=str(tmp_path / "runtime.sqlite3"),
                workspace=str(tmp_path),
                clock=lambda: NOW,
            )
        _assert_safe(excinfo, tmp_path)
        assert "authority resolution" in str(excinfo.value)

    def test_authority_paused_fails(self, tmp_path: Path) -> None:
        config = _setup(tmp_path)
        s = _seed(tmp_path / "authority.sqlite3", [_mandate()])
        s.pause(
            "mandate-situated-42",
            expected_epoch=2,
            principal_id="principal-77",
            tenant_id="tenant-golden-1",
            workspace_id="workspace-golden-1",
        )
        with pytest.raises(DataAgentSituatedStartupConfigError) as excinfo:
            _build()(
                config_path=config,
                database=str(tmp_path / "runtime.sqlite3"),
                workspace=str(tmp_path),
                clock=lambda: NOW,
            )
        _assert_safe(excinfo, tmp_path)
        assert "authority resolution" in str(excinfo.value)

    @pytest.mark.parametrize(
        "mandate,label",
        [
            (_mandate(version=4), "version"),
            (_mandate(mandate_digest="c" * 64), "digest"),
            (_mandate(correction_epoch=5), "epoch"),
        ],
        ids=lambda x: str(x) if isinstance(x, str) else None,
    )
    def test_field_mismatch_fails(
        self, tmp_path: Path, mandate: RatifiedMandateRef, label: str
    ) -> None:
        config = _setup(tmp_path)
        _seed(tmp_path / "authority.sqlite3", [mandate])
        with pytest.raises(DataAgentSituatedStartupConfigError) as excinfo:
            _build()(
                config_path=config,
                database=str(tmp_path / "runtime.sqlite3"),
                workspace=str(tmp_path),
                clock=lambda: NOW,
            )
        _assert_safe(excinfo, tmp_path)
        assert "binding mismatch" in str(excinfo.value)

    def test_binding_id_absent_fails(self, tmp_path: Path) -> None:
        config = _setup(tmp_path)
        mb = _mandate(
            allowed_environment_bindings=(
                _binding().model_copy(update={"environment_binding_id": "wrong"}),
            )
        )
        _seed(tmp_path / "authority.sqlite3", [mb])
        with pytest.raises(DataAgentSituatedStartupConfigError) as excinfo:
            _build()(
                config_path=config,
                database=str(tmp_path / "runtime.sqlite3"),
                workspace=str(tmp_path),
                clock=lambda: NOW,
            )
        _assert_safe(excinfo, tmp_path)
        assert "authority resolution" in str(excinfo.value)

    def test_binding_digest_mismatch_fails(self, tmp_path: Path) -> None:
        config = _setup(tmp_path)
        _seed(
            tmp_path / "authority.sqlite3",
            [_mandate(allowed_environment_bindings=(_binding(digest="c" * 64),))],
        )
        with pytest.raises(DataAgentSituatedStartupConfigError) as excinfo:
            _build()(
                config_path=config,
                database=str(tmp_path / "runtime.sqlite3"),
                workspace=str(tmp_path),
                clock=lambda: NOW,
            )
        _assert_safe(excinfo, tmp_path)
        assert "binding mismatch" in str(excinfo.value)

    def test_assessor_ref_mismatch_fails(self, tmp_path: Path) -> None:
        config = _setup(tmp_path)
        _seed(
            tmp_path / "authority.sqlite3", [_mandate(assessor_id="assessor:foreign")]
        )
        with pytest.raises(DataAgentSituatedStartupConfigError) as excinfo:
            _build()(
                config_path=config,
                database=str(tmp_path / "runtime.sqlite3"),
                workspace=str(tmp_path),
                clock=lambda: NOW,
            )
        _assert_safe(excinfo, tmp_path)
        assert "binding mismatch" in str(excinfo.value)

    def test_context_ref_mismatch_fails(self, tmp_path: Path) -> None:
        config = _setup(tmp_path)
        fc = relevance_context().model_copy(update={"mandate_version": 99})
        _seed(tmp_path / "authority.sqlite3", [_mandate(relevance_context=fc.ref())])
        with pytest.raises(DataAgentSituatedStartupConfigError) as excinfo:
            _build()(
                config_path=config,
                database=str(tmp_path / "runtime.sqlite3"),
                workspace=str(tmp_path),
                clock=lambda: NOW,
            )
        _assert_safe(excinfo, tmp_path)
        assert "binding mismatch" in str(excinfo.value)

    def test_provider_credential_revoked_live_fails(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("AGENT_OS_PROVIDER_API_KEY", "raw-provider-secret")
        rv = provider_credential().model_copy(
            update={"status": CredentialStatus.REVOKED}
        )
        policy = _policy(rv)
        config = _setup(tmp_path, prov_cred=rv, policy=policy)
        _seed(tmp_path / "authority.sqlite3", [_mandate(policy=policy)])
        with pytest.raises(DataAgentSituatedStartupConfigError) as excinfo:
            _build()(
                config_path=config,
                database=str(tmp_path / "runtime.sqlite3"),
                workspace=str(tmp_path),
                clock=lambda: NOW,
            )
        _assert_safe(excinfo, tmp_path)
        assert "raw-provider-secret" not in str(excinfo.value)

    def test_provider_invocation_drift_fails_before_composition(
        self, tmp_path: Path
    ) -> None:
        credential = provider_credential()
        policy = _policy(credential)
        drifted = policy.model_copy(
            update={
                "provider_invocation": policy.provider_invocation.model_copy(
                    update={"adapter_kind": "unratified-adapter"}
                )
            }
        )
        config = _setup(tmp_path, policy=drifted)
        _seed(tmp_path / "authority.sqlite3", [_mandate(policy=drifted)])

        with pytest.raises(DataAgentSituatedStartupConfigError) as excinfo:
            _build()(
                config_path=config,
                database=str(tmp_path / "runtime.sqlite3"),
                workspace=str(tmp_path),
                clock=lambda: NOW,
            )

        _assert_safe(excinfo, tmp_path)
        assert "composition failed" in str(excinfo.value)

    def test_non_https_provider_endpoint_is_rejected_before_composition(
        self, tmp_path: Path
    ) -> None:
        credential = provider_credential()
        policy = _policy(credential)
        insecure = policy.model_copy(
            update={
                "provider_invocation": policy.provider_invocation.model_copy(
                    update={"base_url": "http://provider.example/v1"}
                )
            }
        )
        config = _setup(tmp_path, policy=insecure)
        _seed(tmp_path / "authority.sqlite3", [_mandate(policy=insecure)])

        with pytest.raises(DataAgentSituatedStartupConfigError) as excinfo:
            _build()(
                config_path=config,
                database=str(tmp_path / "runtime.sqlite3"),
                workspace=str(tmp_path),
                clock=lambda: NOW,
            )

        _assert_safe(excinfo, tmp_path)
        assert "binding mismatch" in str(excinfo.value)

    def test_live_provider_broker_uses_injected_clock_for_expiry(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("AGENT_OS_PROVIDER_API_KEY", "raw-provider-secret")
        config = _setup(tmp_path)
        _seed(tmp_path / "authority.sqlite3", [_mandate()])
        provisioned = startup.load_data_agent_situated_startup_provisioning(config)
        broker_type = getattr(startup, "_LiveProviderCredentialFileBroker", None)
        assert broker_type is not None, "live provider credential broker is missing"
        broker = broker_type(
            provisioned.provider_credentials(),
            clock=lambda: provider_credential().expires_at + timedelta(seconds=1),
        )

        with pytest.raises(RuntimeError, match="credential is unavailable"):
            broker.resolve(provider_credential())

    def test_safe_error_no_leak(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv(RESOLVER_ENV_KEY, "secret-must-not-leak")
        monkeypatch.setenv("AGENT_OS_PROVIDER_API_KEY", "provider-must-not-leak")
        config = _setup(tmp_path)
        with pytest.raises(DataAgentSituatedStartupConfigError) as excinfo:
            _build()(
                config_path=config,
                database=str(tmp_path / "runtime.sqlite3"),
                workspace=str(tmp_path),
                clock=lambda: NOW,
            )
        msg = str(excinfo.value)
        assert str(tmp_path) not in msg
        assert "secret-must-not-leak" not in msg
        assert "provider-must-not-leak" not in msg
        assert ".sqlite3" not in msg
