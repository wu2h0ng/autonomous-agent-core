from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from apps.api_server._data_agent_situated_startup import (
    STRUCTURALLY_VALIDATED_CONFIG_ONLY,
    DataAgentSituatedStartupConfig,
    DataAgentSituatedStartupConfigError,
    load_data_agent_situated_startup_config,
)

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
        "config_contract": "agent-os.data-agent-situated-startup-config.v1",
        "principal_id": "principal-77",
        "tenant_id": "tenant-golden-1",
        "workspace_id": "workspace-golden-1",
        "mandate_id": "mandate-situated-42",
        "environment_binding_id": "binding-situated-42",
        "expected_mandate_version": 3,
        "expected_correction_epoch": 2,
        "expected_mandate_digest": "a" * 64,
        "expected_binding_digest": "b" * 64,
        "source": {
            "source_id": "data-agent-source-main",
            "base_url": "https://reports.dataagent.example",
            "source_tenant_id": "upstream-tenant-9",
            "scope_ref": "scope:data-agent-reports",
            "allow_loopback_http": False,
            "timeout_seconds": 10,
            "max_response_bytes": 1_048_576,
            "freshness_seconds": 300,
        },
        "credential": {
            "credential_ref_id": "credref-data-agent-1",
            "provider_id": "data-agent-external-report",
            "resolver_env_key": RESOLVER_ENV_KEY,
            "scopes": ["situated:read"],
            "expected_credential_digest": "c" * 64,
            "expected_expires_at": "2026-12-31T00:00:00Z",
        },
        "provider": {
            "policy_ref": "policy://situated-assessment/v1",
            "context_ref": "context://data-agent-report/v1",
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
        assert config.credential.resolver_env_key == RESOLVER_ENV_KEY
        assert config.credential.scopes == ("situated:read",)
        assert config.credential.expected_credential_digest == "c" * 64
        assert config.provider.policy_ref == "policy://situated-assessment/v1"

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
            ("credential.resolver_env_key", "X"),
            ("credential.resolver_env_key", "opaque-key-ref"),
            ("provider.policy_ref", "urn:agent-os:policy:situated-assessment:v1"),
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

    def test_accepts_arbitrary_nonempty_scopes_sorted_deduplicated(
        self, tmp_path: Path
    ) -> None:
        scopes = ["situated:read", "read data", "situated:read"]
        config = load(tmp_path, mutated("credential.scopes", scopes))
        assert config.credential.scopes == ("read data", "situated:read")

    def test_accepts_aware_non_utc_time_and_normalizes(self, tmp_path: Path) -> None:
        config = load(
            tmp_path,
            mutated("credential.expected_expires_at", "2026-12-31T02:00:00+02:00"),
        )
        assert config.credential.expected_expires_at == datetime(
            2026, 12, 31, tzinfo=timezone.utc
        )

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
            ("credential.api_key", "value"),
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
            "credential.resolver_env_key",
            "provider.policy_ref",
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
            ("config_contract", "agent-os.data-agent-situated-startup-config.v2"),
            ("expected_mandate_digest", "A" * 64),
            ("expected_mandate_digest", "a" * 63),
            ("expected_mandate_digest", "sha256:" + "a" * 64),
            ("credential.expected_credential_digest", "g" * 64),
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
            ("credential.expected_expires_at", "2026-12-31T00:00:00"),
            ("credential.expected_expires_at", "not-a-time"),
            ("credential.expected_expires_at", 1_735_603_200),
            ("credential.expected_expires_at", 1_735_603_200.5),
            ("credential.scopes", []),
            ("credential.scopes", [""]),
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
        assert config.credential.resolver_env_key == RESOLVER_ENV_KEY
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
