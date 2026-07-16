"""Structurally validated local startup configuration for the situated path.

This private module reads one bounded local JSON file and validates it into a
frozen closed-schema contract built from the canonical contract types. The
result is STRUCTURALLY_VALIDATED_CONFIG_ONLY: opaque locators, credential
metadata plus resolver environment-key name, and expected version/digest/epoch
bindings. It resolves no authority, instantiates no application, principal,
mandate, binding, steward, store, writer, provider or assessor, and never
reads the credential secret named by the resolver environment key.
"""

from __future__ import annotations

import json
import math
import os
import stat
from datetime import datetime
from pathlib import Path
from typing import Final, Literal, NoReturn

from pydantic import (
    Field,
    StrictBool,
    StrictInt,
    ValidationError,
    field_validator,
    model_validator,
)

from agent_os_contracts import (
    ContractModel,
    NonEmptyStr,
    Sha256Digest,
    UtcDateTime,
)

from .data_agent_report_adapter import (
    DataAgentReportAdapterError,
    _normalized_origin,
)

STRUCTURALLY_VALIDATED_CONFIG_ONLY: Final = "STRUCTURALLY_VALIDATED_CONFIG_ONLY"

_MAX_CONFIG_BYTES: Final = 65_536

_PREFIX: Final = "data agent situated startup configuration "
_ERROR_UNAVAILABLE: Final = _PREFIX + "is unavailable"
_ERROR_SYMLINK: Final = _PREFIX + "cannot be a symlink"
_ERROR_NOT_REGULAR: Final = _PREFIX + "must be a regular file"
_ERROR_OVERSIZE: Final = _PREFIX + "exceeds the size limit"
_ERROR_NOT_JSON: Final = _PREFIX + "must be strict UTF-8 JSON"
_ERROR_DUPLICATE_KEYS: Final = _PREFIX + "contains duplicate JSON keys"
_ERROR_NON_FINITE: Final = _PREFIX + "contains a non-finite number"
_ERROR_ROOT: Final = _PREFIX + "root must be an object"
_ERROR_UNKNOWN_FIELD: Final = _PREFIX + "contains an unknown field"
_ERROR_MISSING_FIELD: Final = _PREFIX + "is missing a required field"
_ERROR_MALFORMED: Final = _PREFIX + "field is malformed"


class DataAgentSituatedStartupConfigError(RuntimeError):
    """Fixed safe startup configuration failure; carries no file content."""


def _fail(message: str) -> NoReturn:
    raise DataAgentSituatedStartupConfigError(message) from None


class DataAgentSituatedStartupSourceConfig(ContractModel):
    """Non-secret Data Agent source locators using the adapter origin rules."""

    source_id: NonEmptyStr
    base_url: NonEmptyStr
    source_tenant_id: NonEmptyStr
    scope_ref: NonEmptyStr
    allow_loopback_http: StrictBool = False
    timeout_seconds: StrictInt = Field(ge=1, le=300)
    max_response_bytes: StrictInt = Field(ge=1, le=16_777_216)
    freshness_seconds: StrictInt = Field(ge=1, le=86_400)

    @model_validator(mode="after")
    def _validate_origin(self) -> DataAgentSituatedStartupSourceConfig:
        try:
            _normalized_origin(
                self.base_url,
                allow_loopback_http=self.allow_loopback_http,
            )
        except DataAgentReportAdapterError:
            raise ValueError(
                "base_url is not an acceptable external report origin"
            ) from None
        return self


class DataAgentSituatedStartupCredentialConfig(ContractModel):
    """Credential metadata and resolver key name; never the secret value."""

    credential_ref_id: NonEmptyStr
    provider_id: NonEmptyStr
    resolver_env_key: NonEmptyStr
    scopes: tuple[NonEmptyStr, ...] = Field(min_length=1)
    expected_credential_digest: Sha256Digest
    expected_expires_at: UtcDateTime

    @field_validator("scopes", mode="after")
    @classmethod
    def _normalize_scopes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))

    @field_validator("expected_expires_at", mode="before")
    @classmethod
    def _require_iso_datetime_string(cls, value: object) -> datetime:
        if not isinstance(value, str):
            raise ValueError("expected_expires_at must be an ISO datetime string")
        return datetime.fromisoformat(value)


class DataAgentSituatedStartupProviderConfig(ContractModel):
    """Opaque provider policy and context locators; not provider objects."""

    policy_ref: NonEmptyStr
    context_ref: NonEmptyStr


class DataAgentSituatedStartupConfig(ContractModel):
    """Closed structural startup contract; direct construction also validates.

    The claim is STRUCTURALLY_VALIDATED_CONFIG_ONLY: fields are shape-checked
    against the canonical contract types, but no mandate, binding, credential
    or provider authority has been resolved or verified.
    """

    config_contract: Literal["agent-os.data-agent-situated-startup-config.v1"]
    principal_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    mandate_id: NonEmptyStr
    environment_binding_id: NonEmptyStr
    expected_mandate_version: StrictInt = Field(ge=1)
    expected_correction_epoch: StrictInt = Field(ge=0)
    expected_mandate_digest: Sha256Digest
    expected_binding_digest: Sha256Digest
    source: DataAgentSituatedStartupSourceConfig
    credential: DataAgentSituatedStartupCredentialConfig
    provider: DataAgentSituatedStartupProviderConfig

    @property
    def config_state(self) -> str:
        return STRUCTURALLY_VALIDATED_CONFIG_ONLY


def _read_config_bytes(path: Path) -> bytes:
    try:
        info = os.lstat(path)
    except OSError:
        _fail(_ERROR_UNAVAILABLE)
    if stat.S_ISLNK(info.st_mode):
        _fail(_ERROR_SYMLINK)
    if not stat.S_ISREG(info.st_mode):
        _fail(_ERROR_NOT_REGULAR)
    if info.st_size > _MAX_CONFIG_BYTES:
        _fail(_ERROR_OVERSIZE)
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError:
        _fail(_ERROR_UNAVAILABLE)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            _fail(_ERROR_NOT_REGULAR)
        if opened.st_size > _MAX_CONFIG_BYTES:
            _fail(_ERROR_OVERSIZE)
        chunks: list[bytes] = []
        received = 0
        while received <= _MAX_CONFIG_BYTES:
            try:
                chunk = os.read(descriptor, _MAX_CONFIG_BYTES + 1 - received)
            except OSError:
                _fail(_ERROR_UNAVAILABLE)
            if not chunk:
                break
            chunks.append(chunk)
            received += len(chunk)
    finally:
        os.close(descriptor)
    data = b"".join(chunks)
    if len(data) > _MAX_CONFIG_BYTES:
        _fail(_ERROR_OVERSIZE)
    return data


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            _fail(_ERROR_DUPLICATE_KEYS)
        result[key] = value
    return result


def _reject_non_finite_constant(value: str) -> NoReturn:
    _fail(_ERROR_NON_FINITE)


def _parse_finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        _fail(_ERROR_NON_FINITE)
    return value


def _parse_strict_json(raw: bytes) -> dict[str, object]:
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        _fail(_ERROR_NOT_JSON)
    try:
        parsed: object = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite_constant,
            parse_float=_parse_finite_float,
        )
    except DataAgentSituatedStartupConfigError:
        raise
    except (ValueError, RecursionError):
        _fail(_ERROR_NOT_JSON)
    if not isinstance(parsed, dict):
        _fail(_ERROR_ROOT)
    return parsed


def _validated_config(parsed: dict[str, object]) -> DataAgentSituatedStartupConfig:
    try:
        return DataAgentSituatedStartupConfig.model_validate(parsed)
    except ValidationError as error:
        kinds = {item["type"] for item in error.errors()}
        if "extra_forbidden" in kinds:
            _fail(_ERROR_UNKNOWN_FIELD)
        if "missing" in kinds:
            _fail(_ERROR_MISSING_FIELD)
        _fail(_ERROR_MALFORMED)


def load_data_agent_situated_startup_config(
    path: str | Path,
) -> DataAgentSituatedStartupConfig:
    """Load and structurally validate the local startup configuration file.

    The result is STRUCTURALLY_VALIDATED_CONFIG_ONLY. It grants nothing,
    resolves no authority and never reads the named credential secret.
    """
    raw = _read_config_bytes(Path(path))
    return _validated_config(_parse_strict_json(raw))
