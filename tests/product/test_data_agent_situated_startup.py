from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from agent_os_contracts import (
    CredentialRef,
    CredentialStatus,
    MandateOutcomeContext,
    MandateRelevanceContext,
    ProviderInvocationBinding,
    ProviderProfile,
    ProviderRelevancePolicy,
    canonical_json,
    content_digest,
)

from apps.api_server import _data_agent_situated_startup as startup
from apps.api_server._data_agent_situated_startup import (
    STRUCTURALLY_VALIDATED_CONFIG_ONLY,
    DataAgentSituatedStartupConfig,
    DataAgentSituatedStartupConfigError,
    load_data_agent_situated_startup_config,
)

STRUCTURALLY_VALIDATED_PROVISIONING_ONLY = getattr(
    startup, "STRUCTURALLY_VALIDATED_PROVISIONING_ONLY", "MISSING"
)


def load_data_agent_situated_startup_provisioning(path: Path) -> Any:
    loader = getattr(startup, "load_data_agent_situated_startup_provisioning", None)
    assert loader is not None, "startup provisioning loader is missing"
    return loader(path)


RESOLVER_ENV_KEY = "DATA_AGENT_REPORT_KEY_REF_9Q"

PREFIX = "data agent situated startup configuration "
E_UNAVAILABLE = PREFIX + "is unavailable"
E_SYMLINK = PREFIX + "cannot be a symlink"
E_NOT_REGULAR = PREFIX + "must be a regular file"
E_OVERSIZE = PREFIX + "exceeds the size limit"
E_NOT_JSON = PREFIX + "must be strict UTF-8 JSON"
E_DUPLICATE = PREFIX + "contains duplicate JSON keys"
E_NON_FINITE = PREFIX + "contains a non-finite number"
E_ROOT = PREFIX + "root must be an object"
E_UNKNOWN = PREFIX + "contains an unknown field"
E_MISSING = PREFIX + "is missing a required field"
E_MALFORMED = PREFIX + "field is malformed"
SAFE_ERROR_MESSAGES = frozenset(
    {
        E_UNAVAILABLE,
        E_SYMLINK,
        E_NOT_REGULAR,
        E_OVERSIZE,
        E_NOT_JSON,
        E_DUPLICATE,
        E_NON_FINITE,
        E_ROOT,
        E_UNKNOWN,
        E_MISSING,
        E_MALFORMED,
    }
)


def valid_config_data() -> dict[str, Any]:
    return {
        "config_contract": "agent-os.data-agent-situated-startup-config.v2",
        "principal_id": "principal-77",
        "tenant_id": "tenant-golden-1",
        "workspace_id": "workspace-golden-1",
        "mandate_id": "mandate-situated-42",
        "environment_binding_id": "binding-situated-42",
        "expected_mandate_version": 3,
        "expected_correction_epoch": 2,
        "expected_mandate_digest": "a" * 64,
        "expected_binding_digest": "b" * 64,
        "authority_database": "authority.sqlite3",
        "source": {
            "source_id": "data-agent-source-main",
            "base_url": "https://reports.dataagent.example",
            "source_tenant_id": "upstream-tenant-9",
            "scope_ref": "scope:data-agent-reports",
            "allow_loopback_http": False,
            "timeout_seconds": 10,
            "max_response_bytes": 1_048_576,
            "freshness_seconds": 300,
            "credential_file": "source-credential.json",
            "expected_credential_digest": "c" * 64,
        },
        "provider": {
            "policy_file": "provider-policy.json",
            "expected_policy_digest": "d" * 64,
            "context_file": "relevance-context.json",
            "expected_context_digest": "e" * 64,
            "credential_file": "provider-credential.json",
            "expected_credential_digest": "f" * 64,
        },
    }


REMOVE = object()


def mutated(dotted: str, value: Any) -> dict[str, Any]:
    data = valid_config_data()
    target: dict[str, Any] = data
    *parents, leaf = dotted.split(".")
    for parent in parents:
        target = target[parent]
    if value is REMOVE:
        del target[leaf]
    else:
        target[leaf] = value
    return data


def write_config(tmp_path: Path, payload: dict[str, Any] | str | bytes) -> Path:
    path = tmp_path / "startup-config.json"
    if isinstance(payload, dict):
        payload = json.dumps(payload)
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    path.write_bytes(payload)
    return path


def load(
    tmp_path: Path, payload: dict[str, Any] | str | bytes
) -> DataAgentSituatedStartupConfig:
    return load_data_agent_situated_startup_config(write_config(tmp_path, payload))


def assert_rejected(target: Path, expected: str) -> None:
    with pytest.raises(DataAgentSituatedStartupConfigError) as excinfo:
        load_data_agent_situated_startup_config(target)
    message = str(excinfo.value)
    assert message == expected
    assert message in SAFE_ERROR_MESSAGES
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__suppress_context__ is True
    assert RESOLVER_ENV_KEY not in message


class TestValidConfig:
    def test_loads_declared_locators_and_expectations(self, tmp_path: Path) -> None:
        config = load(tmp_path, valid_config_data())
        assert config.principal_id == "principal-77"
        assert config.mandate_id == "mandate-situated-42"
        assert config.environment_binding_id == "binding-situated-42"
        assert config.expected_mandate_version == 3
        assert config.expected_correction_epoch == 2
        assert config.expected_mandate_digest == "a" * 64
        assert config.expected_binding_digest == "b" * 64
        assert config.source.base_url == "https://reports.dataagent.example"
        assert config.source.timeout_seconds == 10
        assert config.authority_database == "authority.sqlite3"
        assert config.source.credential_file == "source-credential.json"
        assert config.source.expected_credential_digest == "c" * 64
        assert config.provider.policy_file == "provider-policy.json"

    def test_claim_is_structural_only(self, tmp_path: Path) -> None:
        config = load(tmp_path, valid_config_data())
        assert STRUCTURALLY_VALIDATED_CONFIG_ONLY == (
            "STRUCTURALLY_VALIDATED_CONFIG_ONLY"
        )
        assert config.config_state == STRUCTURALLY_VALIDATED_CONFIG_ONLY

    @pytest.mark.parametrize(
        ("dotted", "value"),
        [
            ("principal_id", "principal/user-77"),
            ("principal_id", "urn:agent-os:principal:user-77"),
            ("mandate_id", "mandates/tenant-golden-1/42"),
            ("source.credential_file", "source/credential.json"),
            ("provider.policy_file", "provisioning/policy.json"),
        ],
    )
    def test_accepts_opaque_locators_and_key_names(
        self, tmp_path: Path, dotted: str, value: str
    ) -> None:
        config = load(tmp_path, mutated(dotted, value))
        node: Any = config
        for part in dotted.split("."):
            node = getattr(node, part)
        assert node == value

    @pytest.mark.parametrize(
        "base_url",
        ["http://127.0.0.1:8043", "http://localhost:8043", "http://[::1]:8043"],
    )
    def test_accepts_adapter_loopback_origins_with_explicit_flag(
        self, tmp_path: Path, base_url: str
    ) -> None:
        data = mutated("source.base_url", base_url)
        data["source"]["allow_loopback_http"] = True
        assert load(tmp_path, data).source.base_url == base_url


class TestDirectConstructionIsValidated:
    def test_junk_direct_construction_cannot_forge_a_config(self) -> None:
        junk: dict[str, Any] = {key: object() for key in valid_config_data()}
        with pytest.raises(ValidationError):
            DataAgentSituatedStartupConfig(**junk)

    def test_direct_construction_rejects_extra_fields(self) -> None:
        data = valid_config_data()
        data["factory"] = "apps.api_server.app:AgentOSApplication"
        with pytest.raises(ValidationError):
            DataAgentSituatedStartupConfig.model_validate(data)

    def test_direct_construction_validates_like_the_loader(
        self, tmp_path: Path
    ) -> None:
        direct = DataAgentSituatedStartupConfig.model_validate(valid_config_data())
        assert direct == load(tmp_path, valid_config_data())
        assert direct.config_state == STRUCTURALLY_VALIDATED_CONFIG_ONLY

    def test_instances_are_frozen(self, tmp_path: Path) -> None:
        config = load(tmp_path, valid_config_data())
        with pytest.raises(ValidationError):
            config.principal_id = "attacker"  # type: ignore[misc]
        with pytest.raises(ValidationError):
            config.source.base_url = "http://evil.example"  # type: ignore[misc]


class TestFileBoundary:
    def test_missing_file_is_safe_unavailable(self, tmp_path: Path) -> None:
        assert_rejected(tmp_path / "absent.json", E_UNAVAILABLE)

    def test_symlink_is_rejected(self, tmp_path: Path) -> None:
        target = write_config(tmp_path, valid_config_data())
        link = tmp_path / "link.json"
        link.symlink_to(target)
        assert_rejected(link, E_SYMLINK)

    @pytest.mark.parametrize("kind", ["directory", "fifo"])
    def test_non_regular_files_are_rejected(self, tmp_path: Path, kind: str) -> None:
        if kind == "directory":
            path = tmp_path
        else:
            path = tmp_path / "config.fifo"
            os.mkfifo(path)
        assert_rejected(path, E_NOT_REGULAR)

    def test_oversize_file_is_rejected(self, tmp_path: Path) -> None:
        payload = json.dumps(valid_config_data())
        padded = payload + " " * (65_537 - len(payload))
        assert_rejected(write_config(tmp_path, padded), E_OVERSIZE)

    def test_error_never_contains_path_or_content(self, tmp_path: Path) -> None:
        secret_dir = tmp_path / "customer-secret-dir"
        secret_dir.mkdir()
        path = write_config(secret_dir, '{"config_contract": "wrong"}')
        with pytest.raises(DataAgentSituatedStartupConfigError) as excinfo:
            load_data_agent_situated_startup_config(path)
        assert str(excinfo.value) in SAFE_ERROR_MESSAGES
        assert "customer-secret-dir" not in str(excinfo.value)
        assert "config_contract" not in str(excinfo.value)


class TestStrictJson:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (b'\xff\xfe{"config_contract": "x"}', E_NOT_JSON),
            (b"{not json", E_NOT_JSON),
            (b'{"config_contract": "a", "config_contract": "b"}', E_DUPLICATE),
            (b'{"provider": {"policy_ref": "a", "policy_ref": "b"}}', E_DUPLICATE),
            (b'{"expected_mandate_version": NaN}', E_NON_FINITE),
            (b'{"expected_mandate_version": 1e999}', E_NON_FINITE),
            (b"[]", E_ROOT),
        ],
    )
    def test_broken_documents_are_rejected(
        self, tmp_path: Path, raw: bytes, expected: str
    ) -> None:
        assert_rejected(write_config(tmp_path, raw), expected)

    def test_deeply_nested_payload_fails_closed(self, tmp_path: Path) -> None:
        path = write_config(tmp_path, ("[" * 20_000) + ("]" * 20_000))
        assert_rejected(path, E_NOT_JSON)


class TestClosedSchema:
    @pytest.mark.parametrize(
        ("dotted", "value"),
        [
            ("factory", "apps.api_server.app:AgentOSApplication"),
            ("import_path", "importlib:import_module"),
            ("api_key", "value"),
            ("authority_override", "value"),
            ("mandate", {"mandate_id": "mandate-situated-42", "status": "ACTIVE"}),
            ("ratified_mandate", {"correction_epoch": 2, "status": "ACTIVE"}),
            ("source.factory", "pkg.module:build"),
            ("source.api_key", "value"),
            ("provider.factory", "pkg.module:build"),
        ],
    )
    def test_unknown_and_raw_authority_fields_are_rejected(
        self, tmp_path: Path, dotted: str, value: Any
    ) -> None:
        assert_rejected(write_config(tmp_path, mutated(dotted, value)), E_UNKNOWN)

    @pytest.mark.parametrize(
        "dotted",
        [
            "principal_id",
            "source",
            "source.base_url",
            "source.credential_file",
            "provider.policy_file",
        ],
    )
    def test_missing_required_fields_are_rejected(
        self, tmp_path: Path, dotted: str
    ) -> None:
        assert_rejected(write_config(tmp_path, mutated(dotted, REMOVE)), E_MISSING)


class TestMalformedValues:
    @pytest.mark.parametrize(
        ("dotted", "value"),
        [
            ("config_contract", "agent-os.data-agent-situated-startup-config.v1"),
            ("expected_mandate_digest", "A" * 64),
            ("expected_mandate_digest", "a" * 63),
            ("expected_mandate_digest", "sha256:" + "a" * 64),
            ("source.expected_credential_digest", "g" * 64),
            ("expected_mandate_version", 0),
            ("expected_mandate_version", 3.5),
            ("expected_mandate_version", "not-a-number"),
            ("expected_mandate_version", True),
            ("expected_mandate_version", "3"),
            ("expected_correction_epoch", -1),
            ("expected_correction_epoch", False),
            ("expected_correction_epoch", "2"),
            ("source.timeout_seconds", 0),
            ("source.timeout_seconds", "10"),
            ("source.max_response_bytes", 16_777_217),
            ("source.max_response_bytes", "1048576"),
            ("source.freshness_seconds", 86_401),
            ("source.freshness_seconds", "300"),
            ("source.allow_loopback_http", "not-a-bool"),
            ("source.allow_loopback_http", 1),
            ("source.allow_loopback_http", 0),
            ("principal_id", ""),
            ("mandate_id", {"mandate_id": "mandate-situated-42"}),
        ],
    )
    def test_malformed_values_are_rejected(
        self, tmp_path: Path, dotted: str, value: Any
    ) -> None:
        assert_rejected(write_config(tmp_path, mutated(dotted, value)), E_MALFORMED)

    @pytest.mark.parametrize(
        "base_url",
        [
            "http://reports.example",
            "http://127.0.0.1:8043",
            "https://user:pass@reports.example",
            "https://reports.example/reports",
            "ftp://reports.example",
        ],
    )
    def test_non_origin_or_non_loopback_base_urls_are_rejected(
        self, tmp_path: Path, base_url: Any
    ) -> None:
        assert_rejected(
            write_config(tmp_path, mutated("source.base_url", base_url)),
            E_MALFORMED,
        )


class TestEnvironmentBoundary:
    def test_loader_never_reads_the_named_credential_secret(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sentinel = "raw-secret-material-must-stay-opaque"
        monkeypatch.setenv(RESOLVER_ENV_KEY, sentinel)
        config = load(tmp_path, valid_config_data())
        assert config.source.credential_file == "source-credential.json"
        assert sentinel not in json.dumps(config.model_dump(mode="json"))
        assert sentinel not in repr(config)

    def test_resolver_env_key_never_appears_in_loader_errors(
        self, tmp_path: Path
    ) -> None:
        path = write_config(
            tmp_path, mutated("expected_mandate_digest", "not-a-digest")
        )
        with pytest.raises(DataAgentSituatedStartupConfigError) as excinfo:
            load_data_agent_situated_startup_config(path)
        assert RESOLVER_ENV_KEY not in str(excinfo.value)
        assert RESOLVER_ENV_KEY not in repr(excinfo.value)


NOW = datetime(2026, 7, 17, 0, 0, tzinfo=timezone.utc)


def source_credential() -> CredentialRef:
    return CredentialRef(
        credential_ref_id="credref-data-agent-1",
        owner_principal_id="principal-77",
        tenant_id="tenant-golden-1",
        workspace_id="workspace-golden-1",
        provider_id="data-agent-external-report",
        resolver_key=RESOLVER_ENV_KEY,
        scopes=(
            "reports:read",
            "data-agent-origin:https://reports.dataagent.example",
            "data-agent-tenant:upstream-tenant-9",
        ),
        status=CredentialStatus.ACTIVE,
        created_at=NOW,
        expires_at=NOW + timedelta(days=30),
    )


def provider_credential() -> CredentialRef:
    return CredentialRef(
        credential_ref_id="credref-provider-1",
        owner_principal_id="principal-77",
        tenant_id="tenant-golden-1",
        workspace_id="workspace-golden-1",
        provider_id="openai-compatible",
        resolver_key="AGENT_OS_PROVIDER_API_KEY",
        scopes=("chat",),
        status=CredentialStatus.ACTIVE,
        created_at=NOW,
        expires_at=NOW + timedelta(days=30),
    )


def provider_policy(credential: CredentialRef) -> ProviderRelevancePolicy:
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
        adapter_kind="openai-compatible-http",
        transport="https-json",
        base_url="https://provider.example/v1",
        endpoint_path="chat/completions",
        model_id=profile.model_id,
        request_timeout_seconds=profile.request_timeout_seconds,
        temperature=Decimal("0"),
    )
    return ProviderRelevancePolicy(
        assessor_id="assessor:startup",
        version=1,
        provider_invocation=invocation,
        prompt_revision="startup-v1",
        prompt_template_digest="1" * 64,
        output_schema_ref="agent-os://relevance-assessment-draft/v1",
        output_schema_digest="2" * 64,
        request_timeout_seconds=20,
        max_artifact_bytes=16_384,
        failure_attention_budget_seconds=60,
    )


def relevance_context() -> MandateRelevanceContext:
    return MandateRelevanceContext(
        relevance_context_id="context:startup",
        version=1,
        mandate_id="mandate-situated-42",
        mandate_version=3,
        mandate_digest="a" * 64,
        tenant_id="tenant-golden-1",
        workspace_id="workspace-golden-1",
        mission_statement="Assess admitted reports without activating work.",
        desired_outcomes=(
            MandateOutcomeContext(
                outcome_id="outcome:truth",
                statement="Keep operational proposals evidence-bound.",
            ),
        ),
        permanent_constraints=("No task activation.",),
    )


def write_canonical(path: Path, value: Any) -> None:
    path.write_text(canonical_json(value), encoding="utf-8")


def provisioning_config(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    authority = tmp_path / "authority.sqlite3"
    authority.write_bytes(b"SQLite format 3\x00")
    source = source_credential()
    provider = provider_credential()
    policy = provider_policy(provider)
    context = relevance_context()
    write_canonical(tmp_path / "source-credential.json", source)
    write_canonical(tmp_path / "provider-credential.json", provider)
    write_canonical(tmp_path / "provider-policy.json", policy)
    write_canonical(tmp_path / "relevance-context.json", context)
    config = valid_config_data()
    config["authority_database"] = authority.name
    config["source"]["expected_credential_digest"] = content_digest(source)
    config["provider"]["expected_credential_digest"] = content_digest(provider)
    config["provider"]["expected_policy_digest"] = content_digest(policy)
    config["provider"]["expected_context_digest"] = content_digest(context)
    return write_config(tmp_path, config), config


class TestProvisioningMaterial:
    def test_loads_complete_digest_bound_canonical_objects(
        self, tmp_path: Path
    ) -> None:
        path, _ = provisioning_config(tmp_path)
        value = load_data_agent_situated_startup_provisioning(path)
        assert value.provisioning_state == STRUCTURALLY_VALIDATED_PROVISIONING_ONLY
        assert value.source_credential == source_credential()
        assert value.provider_credential == provider_credential()
        assert value.provider_policy == provider_policy(provider_credential())
        assert value.relevance_context == relevance_context()
        assert value.authority_database == tmp_path / "authority.sqlite3"

    def test_does_not_resolve_credential_environment_values(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path, _ = provisioning_config(tmp_path)
        monkeypatch.setenv(RESOLVER_ENV_KEY, "raw-source-secret")
        monkeypatch.setenv("AGENT_OS_PROVIDER_API_KEY", "raw-provider-secret")
        value = load_data_agent_situated_startup_provisioning(path)
        encoded = repr(value)
        assert "raw-source-secret" not in encoded
        assert "raw-provider-secret" not in encoded

    @pytest.mark.parametrize(
        ("field", "filename"),
        [
            ("source.expected_credential_digest", "source-credential.json"),
            ("provider.expected_credential_digest", "provider-credential.json"),
            ("provider.expected_policy_digest", "provider-policy.json"),
            ("provider.expected_context_digest", "relevance-context.json"),
        ],
    )
    def test_rejects_expected_digest_mismatch(
        self, tmp_path: Path, field: str, filename: str
    ) -> None:
        path, config = provisioning_config(tmp_path)
        target: dict[str, Any] = config
        *parents, leaf = field.split(".")
        for parent in parents:
            target = target[parent]
        target[leaf] = "9" * 64
        path.write_text(json.dumps(config), encoding="utf-8")
        with pytest.raises(
            DataAgentSituatedStartupConfigError, match="digest mismatch"
        ):
            load_data_agent_situated_startup_provisioning(path)

    def test_rejects_noncanonical_contract_file(self, tmp_path: Path) -> None:
        path, _ = provisioning_config(tmp_path)
        credential_path = tmp_path / "source-credential.json"
        credential_path.write_text(
            json.dumps(source_credential().model_dump(mode="json"), indent=2),
            encoding="utf-8",
        )
        with pytest.raises(DataAgentSituatedStartupConfigError, match="not canonical"):
            load_data_agent_situated_startup_provisioning(path)

    @pytest.mark.parametrize(
        ("kind", "message"),
        [
            ("missing", "is unavailable"),
            ("symlink", "cannot be a symlink"),
            ("directory", "must be a regular file"),
            ("oversize", "exceeds the size limit"),
        ],
    )
    def test_material_file_boundary_fails_closed(
        self, tmp_path: Path, kind: str, message: str
    ) -> None:
        path, _ = provisioning_config(tmp_path)
        target = tmp_path / "source-credential.json"
        if kind == "missing":
            target.unlink()
        elif kind == "symlink":
            target.unlink()
            target.symlink_to(tmp_path / "provider-credential.json")
        elif kind == "directory":
            target.unlink()
            target.mkdir()
        else:
            target.write_bytes(b"x" * 262_145)
        with pytest.raises(DataAgentSituatedStartupConfigError, match=message):
            load_data_agent_situated_startup_provisioning(path)

    def test_material_closed_schema_rejects_raw_secret_without_leaking_it(
        self, tmp_path: Path
    ) -> None:
        path, _ = provisioning_config(tmp_path)
        payload = source_credential().model_dump(mode="json")
        payload["api_key"] = "raw-secret-must-not-leak"
        (tmp_path / "source-credential.json").write_text(
            json.dumps(payload, separators=(",", ":"), sort_keys=True),
            encoding="utf-8",
        )
        with pytest.raises(DataAgentSituatedStartupConfigError) as excinfo:
            load_data_agent_situated_startup_provisioning(path)
        assert str(excinfo.value).endswith("is malformed")
        assert "raw-secret-must-not-leak" not in str(excinfo.value)
        assert RESOLVER_ENV_KEY not in str(excinfo.value)

    @pytest.mark.parametrize("database", [":memory:", "missing.sqlite3"])
    def test_rejects_non_preexisting_authority_database(
        self, tmp_path: Path, database: str
    ) -> None:
        path, config = provisioning_config(tmp_path)
        config["authority_database"] = database
        path.write_text(json.dumps(config), encoding="utf-8")
        with pytest.raises(
            DataAgentSituatedStartupConfigError, match="authority database"
        ):
            load_data_agent_situated_startup_provisioning(path)

    def test_rejects_authority_database_symlink(self, tmp_path: Path) -> None:
        path, config = provisioning_config(tmp_path)
        link = tmp_path / "authority-link.sqlite3"
        link.symlink_to(tmp_path / "authority.sqlite3")
        config["authority_database"] = link.name
        path.write_text(json.dumps(config), encoding="utf-8")
        with pytest.raises(
            DataAgentSituatedStartupConfigError, match="authority database"
        ):
            load_data_agent_situated_startup_provisioning(path)

    def test_rejects_cross_scope_provider_credential(self, tmp_path: Path) -> None:
        path, config = provisioning_config(tmp_path)
        foreign = provider_credential().model_copy(update={"tenant_id": "foreign"})
        write_canonical(tmp_path / "provider-credential.json", foreign)
        config["provider"]["expected_credential_digest"] = content_digest(foreign)
        path.write_text(json.dumps(config), encoding="utf-8")
        with pytest.raises(
            DataAgentSituatedStartupConfigError, match="binding mismatch"
        ):
            load_data_agent_situated_startup_provisioning(path)

    def test_rejects_provider_policy_credential_mismatch(self, tmp_path: Path) -> None:
        path, config = provisioning_config(tmp_path)
        changed = provider_credential().model_copy(update={"resolver_key": "OTHER_KEY"})
        write_canonical(tmp_path / "provider-credential.json", changed)
        config["provider"]["expected_credential_digest"] = content_digest(changed)
        path.write_text(json.dumps(config), encoding="utf-8")
        with pytest.raises(
            DataAgentSituatedStartupConfigError, match="binding mismatch"
        ):
            load_data_agent_situated_startup_provisioning(path)

    def test_rejects_provider_credential_without_chat_scope(
        self, tmp_path: Path
    ) -> None:
        path, config = provisioning_config(tmp_path)
        changed = provider_credential().model_copy(update={"scopes": ("other",)})
        policy = provider_policy(changed)
        write_canonical(tmp_path / "provider-credential.json", changed)
        write_canonical(tmp_path / "provider-policy.json", policy)
        config["provider"]["expected_credential_digest"] = content_digest(changed)
        config["provider"]["expected_policy_digest"] = content_digest(policy)
        path.write_text(json.dumps(config), encoding="utf-8")
        with pytest.raises(
            DataAgentSituatedStartupConfigError, match="binding mismatch"
        ):
            load_data_agent_situated_startup_provisioning(path)

    @pytest.mark.parametrize(
        "updates",
        [
            {"provider_id": "generic-api-key"},
            {"scopes": ("reports:read",)},
            {
                "scopes": (
                    "reports:read",
                    "data-agent-origin:https://reports.dataagent.example",
                    "data-agent-tenant:other",
                )
            },
        ],
    )
    def test_rejects_source_credential_outside_exact_adapter_envelope(
        self, tmp_path: Path, updates: dict[str, object]
    ) -> None:
        path, config = provisioning_config(tmp_path)
        changed = CredentialRef.model_validate(
            {**source_credential().model_dump(), **updates}
        )
        write_canonical(tmp_path / "source-credential.json", changed)
        config["source"]["expected_credential_digest"] = content_digest(changed)
        path.write_text(json.dumps(config), encoding="utf-8")
        with pytest.raises(
            DataAgentSituatedStartupConfigError, match="binding mismatch"
        ):
            load_data_agent_situated_startup_provisioning(path)

    def test_rejects_same_source_and_provider_credential_ref(
        self, tmp_path: Path
    ) -> None:
        path, config = provisioning_config(tmp_path)
        shared = source_credential()
        policy = provider_policy(shared)
        write_canonical(tmp_path / "provider-credential.json", shared)
        write_canonical(tmp_path / "provider-policy.json", policy)
        config["provider"]["expected_credential_digest"] = content_digest(shared)
        config["provider"]["expected_policy_digest"] = content_digest(policy)
        path.write_text(json.dumps(config), encoding="utf-8")
        with pytest.raises(
            DataAgentSituatedStartupConfigError, match="binding mismatch"
        ):
            load_data_agent_situated_startup_provisioning(path)

    def test_rejects_policy_invocation_digest_drift(self, tmp_path: Path) -> None:
        path, config = provisioning_config(tmp_path)
        policy = provider_policy(provider_credential())
        invocation = policy.provider_invocation.model_copy(
            update={"credential_ref_digest": "8" * 64}
        )
        drifted = policy.model_copy(update={"provider_invocation": invocation})
        write_canonical(tmp_path / "provider-policy.json", drifted)
        config["provider"]["expected_policy_digest"] = content_digest(drifted)
        path.write_text(json.dumps(config), encoding="utf-8")
        with pytest.raises(
            DataAgentSituatedStartupConfigError, match="binding mismatch"
        ):
            load_data_agent_situated_startup_provisioning(path)


class TestLiveCredentialBoundary:
    def test_reader_observes_canonical_revocation_without_reading_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path, _ = provisioning_config(tmp_path)
        value = load_data_agent_situated_startup_provisioning(path)
        reader = value.source_credentials()
        initial = reader.resolve_authorization("credref-data-agent-1")
        assert initial is not None
        assert initial.status is CredentialStatus.ACTIVE

        monkeypatch.setenv(RESOLVER_ENV_KEY, "must-not-be-read")
        revoked = source_credential().model_copy(
            update={"status": CredentialStatus.REVOKED}
        )
        write_canonical(tmp_path / "source-credential.json", revoked)
        current = reader.resolve_authorization("credref-data-agent-1")
        assert current is not None
        assert current.status is CredentialStatus.REVOKED
        assert "must-not-be-read" not in repr(current)

    def test_reader_returns_complete_typed_credential_for_broker_boundary(
        self, tmp_path: Path
    ) -> None:
        path, _ = provisioning_config(tmp_path)
        reader = load_data_agent_situated_startup_provisioning(
            path
        ).provider_credentials()
        assert reader.resolve_credential("credref-provider-1") == provider_credential()
        assert reader.resolve_credential("unknown") is None

    def test_reader_fails_closed_on_identity_drift(self, tmp_path: Path) -> None:
        path, _ = provisioning_config(tmp_path)
        reader = load_data_agent_situated_startup_provisioning(
            path
        ).source_credentials()
        foreign = source_credential().model_copy(update={"tenant_id": "foreign"})
        write_canonical(tmp_path / "source-credential.json", foreign)
        with pytest.raises(
            DataAgentSituatedStartupConfigError, match="binding mismatch"
        ):
            reader.resolve_authorization("credref-data-agent-1")
