"""Private provisioning and composition for the situated Data Agent path.

This private module validates a closed startup configuration and the complete,
canonical credential, provider-policy and relevance-context snapshots it names.
The public loader result remains structurally validated provisioning only. The
private application builder additionally resolves pre-provisioned authority and
composes the receipt-required runtime without seeding authority or making a
provider call during startup.
"""

from __future__ import annotations

import json
import math
import os
import stat
from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Final, Literal, NoReturn, TypeVar
from urllib.parse import urlsplit

from pydantic import (
    Field,
    StrictBool,
    StrictInt,
    ValidationError,
    model_validator,
)

from agent_os_contracts import (
    ContractModel,
    CredentialAuthorizationSnapshot,
    CredentialRef,
    CredentialStatus,
    MandateRelevanceContext,
    NonEmptyStr,
    PrincipalIdentity,
    PrincipalRole,
    ProviderInvocationBinding,
    ProviderRelevancePolicy,
    Sha256Digest,
    canonical_json,
    content_digest,
)
from agent_os_core import (
    EnvCredentialBroker,
    InMemoryMandateRelevanceContextRegistry,
    OpenAICompatibleProvider,
    ProviderRelevanceAssessor,
)
from agent_os_core.situated_persistence import SQLiteSituatedAssessmentStore

from .app import AgentOSApplication
from .data_agent_report_admission import (
    SQLiteDataAgentReportAdmissionMaterialStore,
)
from .data_agent_report_adapter import (
    DataAgentReportAdapter,
    DataAgentReportAdapterError,
    DataAgentReportSourceConfig,
    SQLiteDataAgentReportStateStore,
    _normalized_origin,
)
from .data_agent_situated_bootstrap import DataAgentSituatedBootstrap
from .mandate_active_perception import (
    MandateActivePerceptionConfig,
    MandateActivePerceptionService,
    SQLiteMandateActivePerceptionStore,
)

_MAX_CONFIG_BYTES: Final = 65_536
_MAX_MATERIAL_BYTES: Final = 262_144

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

_MATERIAL_PREFIX: Final = "data agent situated startup provisioning material "
_MATERIAL_UNAVAILABLE: Final = _MATERIAL_PREFIX + "is unavailable"
_MATERIAL_SYMLINK: Final = _MATERIAL_PREFIX + "cannot be a symlink"
_MATERIAL_NOT_REGULAR: Final = _MATERIAL_PREFIX + "must be a regular file"
_MATERIAL_OVERSIZE: Final = _MATERIAL_PREFIX + "exceeds the size limit"
_MATERIAL_MALFORMED: Final = _MATERIAL_PREFIX + "is malformed"
_MATERIAL_NOT_CANONICAL: Final = _MATERIAL_PREFIX + "is not canonical"
_MATERIAL_DIGEST_MISMATCH: Final = _MATERIAL_PREFIX + "digest mismatch"
_MATERIAL_BINDING_MISMATCH: Final = _MATERIAL_PREFIX + "binding mismatch"

_AUTHORITY_PREFIX: Final = "data agent situated startup authority database "
_AUTHORITY_UNAVAILABLE: Final = _AUTHORITY_PREFIX + "is unavailable"
_AUTHORITY_SYMLINK: Final = _AUTHORITY_PREFIX + "cannot be a symlink"
_AUTHORITY_NOT_REGULAR: Final = _AUTHORITY_PREFIX + "must be a regular file"
_RUNTIME_PREFIX: Final = "data agent situated startup runtime "
_RUNTIME_IN_MEMORY: Final = _RUNTIME_PREFIX + "cannot use an in-memory database"
_RUNTIME_AUTHORITY: Final = _RUNTIME_PREFIX + "authority resolution failed"
_RUNTIME_BINDING: Final = _RUNTIME_PREFIX + "binding mismatch"
_RUNTIME_COMPOSITION: Final = _RUNTIME_PREFIX + "composition failed"
Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


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
    credential_file: NonEmptyStr
    expected_credential_digest: Sha256Digest

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


class DataAgentSituatedStartupProviderConfig(ContractModel):
    """Complete provider material locators and expected canonical digests."""

    policy_file: NonEmptyStr
    expected_policy_digest: Sha256Digest
    context_file: NonEmptyStr
    expected_context_digest: Sha256Digest
    credential_file: NonEmptyStr
    expected_credential_digest: Sha256Digest


class DataAgentSituatedStartupActivePerceptionConfig(ContractModel):
    interval_seconds: StrictInt = Field(ge=1, le=86_400)
    budget_window_seconds: StrictInt = Field(ge=1, le=604_800)
    wake_budget_per_window: StrictInt = Field(ge=1, le=10_000)
    query_budget_per_window: StrictInt = Field(ge=1, le=10_000)
    feed_limit: StrictInt = Field(ge=1, le=100)
    lease_seconds: StrictInt = Field(ge=1, le=3_600)

    @model_validator(mode="after")
    def _validate_window(self) -> DataAgentSituatedStartupActivePerceptionConfig:
        if self.budget_window_seconds < self.interval_seconds:
            raise ValueError("budget window must cover at least one interval")
        return self


class DataAgentSituatedStartupConfig(ContractModel):
    """Closed startup configuration data; direct construction also validates."""

    config_contract: Literal[
        "agent-os.data-agent-situated-startup-config.v2",
        "agent-os.data-agent-situated-startup-config.v3",
    ]
    principal_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    mandate_id: NonEmptyStr
    environment_binding_id: NonEmptyStr
    expected_mandate_version: StrictInt = Field(ge=1)
    expected_correction_epoch: StrictInt = Field(ge=0)
    expected_mandate_digest: Sha256Digest
    expected_binding_digest: Sha256Digest
    authority_database: NonEmptyStr
    source: DataAgentSituatedStartupSourceConfig
    provider: DataAgentSituatedStartupProviderConfig
    active_perception: DataAgentSituatedStartupActivePerceptionConfig | None = None

    @model_validator(mode="after")
    def _validate_contract_version(self) -> DataAgentSituatedStartupConfig:
        if (
            self.config_contract == "agent-os.data-agent-situated-startup-config.v2"
        ) != (self.active_perception is None):
            raise ValueError("active perception does not match config contract")
        return self


class _DataAgentSituatedStartupProvisioningView:
    """Private read-only view over inputs validated by the startup loader.

    This is deliberately not a Pydantic contract or an authority token. Python
    process-level reflection is outside its security boundary.
    """

    __slots__ = (
        "config",
        "config_path",
        "authority_database",
        "source_credential_path",
        "provider_credential_path",
        "provider_policy_path",
        "relevance_context_path",
        "source_credential",
        "provider_credential",
        "provider_policy",
        "relevance_context",
    )

    config: DataAgentSituatedStartupConfig
    config_path: Path
    authority_database: Path
    source_credential_path: Path
    provider_credential_path: Path
    provider_policy_path: Path
    relevance_context_path: Path
    source_credential: CredentialRef
    provider_credential: CredentialRef
    provider_policy: ProviderRelevancePolicy
    relevance_context: MandateRelevanceContext

    def __init__(self) -> NoReturn:
        raise TypeError("startup provisioning view is loader-private")

    def __setattr__(self, name: str, value: object) -> NoReturn:
        raise AttributeError("startup provisioning view is read-only")

    def source_credentials(self) -> DataAgentSituatedCredentialFileReader:
        """Create a live metadata reader; no credential secret is resolved."""
        return DataAgentSituatedCredentialFileReader(
            self.source_credential_path, self.source_credential
        )

    def provider_credentials(self) -> DataAgentSituatedCredentialFileReader:
        """Create a live metadata reader; no credential secret is resolved."""
        return DataAgentSituatedCredentialFileReader(
            self.provider_credential_path, self.provider_credential
        )

    @classmethod
    def _from_validated(
        cls,
        *,
        config: DataAgentSituatedStartupConfig,
        config_path: Path,
        authority_database: Path,
        source_credential_path: Path,
        provider_credential_path: Path,
        provider_policy_path: Path,
        relevance_context_path: Path,
        source_credential: CredentialRef,
        provider_credential: CredentialRef,
        provider_policy: ProviderRelevancePolicy,
        relevance_context: MandateRelevanceContext,
    ) -> _DataAgentSituatedStartupProvisioningView:
        canonical_config_path = Path(os.path.abspath(config_path))
        expected_paths = (
            canonical_config_path,
            _validate_authority_database(
                canonical_config_path, config.authority_database
            ),
            _resolve_locator(canonical_config_path, config.source.credential_file),
            _resolve_locator(canonical_config_path, config.provider.credential_file),
            _resolve_locator(canonical_config_path, config.provider.policy_file),
            _resolve_locator(canonical_config_path, config.provider.context_file),
        )
        actual_paths = (
            config_path,
            authority_database,
            source_credential_path,
            provider_credential_path,
            provider_policy_path,
            relevance_context_path,
        )
        if actual_paths != expected_paths:
            _fail(_MATERIAL_BINDING_MISMATCH)
        reloaded_config = _validated_config(
            _parse_strict_json(_read_config_bytes(config_path))
        )
        reloaded_materials = (
            _load_canonical_material(
                source_credential_path,
                CredentialRef,
                config.source.expected_credential_digest,
            ),
            _load_canonical_material(
                provider_credential_path,
                CredentialRef,
                config.provider.expected_credential_digest,
            ),
            _load_canonical_material(
                provider_policy_path,
                ProviderRelevancePolicy,
                config.provider.expected_policy_digest,
            ),
            _load_canonical_material(
                relevance_context_path,
                MandateRelevanceContext,
                config.provider.expected_context_digest,
            ),
        )
        if reloaded_config != config or reloaded_materials != (
            source_credential,
            provider_credential,
            provider_policy,
            relevance_context,
        ):
            _fail(_MATERIAL_BINDING_MISMATCH)
        expected_scope = (
            config.principal_id,
            config.tenant_id,
            config.workspace_id,
        )
        for credential in (source_credential, provider_credential):
            actual_scope = (
                credential.owner_principal_id,
                credential.tenant_id,
                credential.workspace_id,
            )
            if actual_scope != expected_scope:
                _fail(_MATERIAL_BINDING_MISMATCH)
        try:
            source_origin = _normalized_origin(
                config.source.base_url,
                allow_loopback_http=config.source.allow_loopback_http,
            )
        except DataAgentReportAdapterError:
            _fail(_MATERIAL_BINDING_MISMATCH)
        required_source_scopes = {
            "reports:read",
            f"data-agent-origin:{source_origin}",
            f"data-agent-tenant:{config.source.source_tenant_id}",
        }
        if config.active_perception is not None:
            required_source_scopes.add("report-events:read")
        if (
            source_credential.provider_id != "data-agent-external-report"
            or tuple(source_credential.scopes) != tuple(sorted(required_source_scopes))
            or source_credential.credential_ref_id
            == provider_credential.credential_ref_id
            or source_credential.resolver_key == provider_credential.resolver_key
        ):
            _fail(_MATERIAL_BINDING_MISMATCH)
        invocation = provider_policy.provider_invocation
        if (
            invocation.credential_ref_id != provider_credential.credential_ref_id
            or invocation.credential_ref_digest != content_digest(provider_credential)
            or invocation.provider_id != provider_credential.provider_id
            or provider_credential.scopes != ("chat",)
        ):
            _fail(_MATERIAL_BINDING_MISMATCH)
        context = relevance_context
        if (
            context.mandate_id != config.mandate_id
            or context.mandate_version != config.expected_mandate_version
            or context.mandate_digest != config.expected_mandate_digest
            or context.tenant_id != config.tenant_id
            or context.workspace_id != config.workspace_id
        ):
            _fail(_MATERIAL_BINDING_MISMATCH)
        view = object.__new__(cls)
        for name, value in (
            ("config", config),
            ("config_path", config_path),
            ("authority_database", authority_database),
            ("source_credential_path", source_credential_path),
            ("provider_credential_path", provider_credential_path),
            ("provider_policy_path", provider_policy_path),
            ("relevance_context_path", relevance_context_path),
            ("source_credential", source_credential),
            ("provider_credential", provider_credential),
            ("provider_policy", provider_policy),
            ("relevance_context", relevance_context),
        ):
            object.__setattr__(view, name, value)
        return view


class DataAgentSituatedCredentialFileReader:
    """Live canonical credential metadata boundary with stable identity binding.

    `resolve_credential` returns the typed reference a separately authorized
    broker may consume. This reader never resolves the `resolver_key` value.
    """

    __slots__ = ("_anchor", "_path")

    def __init__(self, path: Path, anchor: CredentialRef) -> None:
        self._path = path
        self._anchor = anchor

    @staticmethod
    def _identity(value: CredentialRef) -> tuple[object, ...]:
        return (
            value.credential_ref_id,
            value.owner_principal_id,
            value.tenant_id,
            value.workspace_id,
            value.provider_id,
            value.resolver_key,
            value.scopes,
            value.created_at,
            value.expires_at,
        )

    def resolve_credential(self, credential_ref_id: str) -> CredentialRef | None:
        if credential_ref_id != self._anchor.credential_ref_id:
            return None
        current = _load_canonical_material(self._path, CredentialRef, None)
        if self._identity(current) != self._identity(self._anchor):
            _fail(_MATERIAL_BINDING_MISMATCH)
        return current

    def resolve_authorization(
        self, credential_ref_id: str
    ) -> CredentialAuthorizationSnapshot | None:
        current = self.resolve_credential(credential_ref_id)
        if current is None:
            return None
        return CredentialAuthorizationSnapshot(
            credential_ref_id=current.credential_ref_id,
            credential_ref_digest=content_digest(current),
            owner_principal_id=current.owner_principal_id,
            tenant_id=current.tenant_id,
            workspace_id=current.workspace_id,
            provider_id=current.provider_id,
            scopes=current.scopes,
            status=current.status,
            created_at=current.created_at,
            expires_at=current.expires_at,
        )


def _read_config_bytes(path: Path) -> bytes:
    try:
        info = os.lstat(path)
    except (OSError, TypeError, ValueError):
        _fail(_ERROR_UNAVAILABLE)
    if stat.S_ISLNK(info.st_mode):
        _fail(_ERROR_SYMLINK)
    if not stat.S_ISREG(info.st_mode):
        _fail(_ERROR_NOT_REGULAR)
    if info.st_size > _MAX_CONFIG_BYTES:
        _fail(_ERROR_OVERSIZE)
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except (OSError, TypeError, ValueError):
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
            except (OSError, TypeError, ValueError):
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


def _read_material_bytes(path: Path) -> bytes:
    try:
        info = os.lstat(path)
    except (OSError, TypeError, ValueError):
        _fail(_MATERIAL_UNAVAILABLE)
    if stat.S_ISLNK(info.st_mode):
        _fail(_MATERIAL_SYMLINK)
    if not stat.S_ISREG(info.st_mode):
        _fail(_MATERIAL_NOT_REGULAR)
    if info.st_size > _MAX_MATERIAL_BYTES:
        _fail(_MATERIAL_OVERSIZE)
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except (OSError, TypeError, ValueError):
        _fail(_MATERIAL_UNAVAILABLE)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            _fail(_MATERIAL_NOT_REGULAR)
        chunks: list[bytes] = []
        received = 0
        while received <= _MAX_MATERIAL_BYTES:
            try:
                chunk = os.read(descriptor, _MAX_MATERIAL_BYTES + 1 - received)
            except (OSError, TypeError, ValueError):
                _fail(_MATERIAL_UNAVAILABLE)
            if not chunk:
                break
            chunks.append(chunk)
            received += len(chunk)
    finally:
        os.close(descriptor)
    data = b"".join(chunks)
    if len(data) > _MAX_MATERIAL_BYTES:
        _fail(_MATERIAL_OVERSIZE)
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

    The returned configuration is data, not an authority or validation token.
    This loader resolves no authority and never reads named credential secrets.
    """
    try:
        config_path = Path(path)
    except (TypeError, ValueError):
        _fail(_ERROR_UNAVAILABLE)
    raw = _read_config_bytes(config_path)
    return _validated_config(_parse_strict_json(raw))


_ContractT = TypeVar("_ContractT", bound=ContractModel)


def _resolve_locator(config_path: Path, locator: str) -> Path:
    try:
        path = Path(locator)
        selected = path if path.is_absolute() else config_path.parent / path
        return Path(os.path.abspath(selected))
    except (OSError, TypeError, ValueError):
        _fail(_MATERIAL_UNAVAILABLE)


def _load_canonical_material(
    path: Path,
    model_type: type[_ContractT],
    expected_digest: str | None,
) -> _ContractT:
    raw = _read_material_bytes(path)
    try:
        value = model_type.model_validate_json(raw, strict=True)
    except (ValidationError, ValueError):
        _fail(_MATERIAL_MALFORMED)
    try:
        canonical = canonical_json(value).encode("utf-8")
    except (TypeError, ValueError):
        _fail(_MATERIAL_MALFORMED)
    if raw != canonical:
        _fail(_MATERIAL_NOT_CANONICAL)
    if expected_digest is not None and content_digest(value) != expected_digest:
        _fail(_MATERIAL_DIGEST_MISMATCH)
    return value


def _validate_authority_database(config_path: Path, locator: str) -> Path:
    if locator == ":memory:":
        _fail(_AUTHORITY_UNAVAILABLE)
    try:
        raw_path = Path(locator)
        selected = raw_path if raw_path.is_absolute() else config_path.parent / raw_path
        path = Path(os.path.abspath(selected))
    except (OSError, TypeError, ValueError):
        _fail(_AUTHORITY_UNAVAILABLE)
    try:
        info = os.lstat(path)
    except (OSError, TypeError, ValueError):
        _fail(_AUTHORITY_UNAVAILABLE)
    if stat.S_ISLNK(info.st_mode):
        _fail(_AUTHORITY_SYMLINK)
    if not stat.S_ISREG(info.st_mode):
        _fail(_AUTHORITY_NOT_REGULAR)
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except (OSError, TypeError, ValueError):
        _fail(_AUTHORITY_UNAVAILABLE)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            _fail(_AUTHORITY_NOT_REGULAR)
    finally:
        os.close(descriptor)
    return path


def load_data_agent_situated_startup_provisioning(
    path: str | Path,
) -> _DataAgentSituatedStartupProvisioningView:
    """Load canonical provisioning inputs without resolving runtime authority."""
    try:
        config_path = Path(os.path.abspath(Path(path)))
    except (OSError, TypeError, ValueError):
        _fail(_ERROR_UNAVAILABLE)
    config = load_data_agent_situated_startup_config(config_path)
    authority_database = _validate_authority_database(
        config_path, config.authority_database
    )
    source_credential_path = _resolve_locator(
        config_path, config.source.credential_file
    )
    provider_credential_path = _resolve_locator(
        config_path, config.provider.credential_file
    )
    provider_policy_path = _resolve_locator(config_path, config.provider.policy_file)
    relevance_context_path = _resolve_locator(config_path, config.provider.context_file)
    source_credential = _load_canonical_material(
        source_credential_path,
        CredentialRef,
        config.source.expected_credential_digest,
    )
    provider_credential = _load_canonical_material(
        provider_credential_path,
        CredentialRef,
        config.provider.expected_credential_digest,
    )
    provider_policy = _load_canonical_material(
        provider_policy_path,
        ProviderRelevancePolicy,
        config.provider.expected_policy_digest,
    )
    relevance_context = _load_canonical_material(
        relevance_context_path,
        MandateRelevanceContext,
        config.provider.expected_context_digest,
    )
    return _DataAgentSituatedStartupProvisioningView._from_validated(
        config=config,
        config_path=config_path,
        authority_database=authority_database,
        source_credential_path=source_credential_path,
        provider_credential_path=provider_credential_path,
        provider_policy_path=provider_policy_path,
        relevance_context_path=relevance_context_path,
        source_credential=source_credential,
        provider_credential=provider_credential,
        provider_policy=provider_policy,
        relevance_context=relevance_context,
    )


def _resolve_live_credential_secret(
    reader: DataAgentSituatedCredentialFileReader,
    credential: CredentialRef,
    *,
    required_scope: str,
    clock: Clock,
) -> str:
    try:
        current = reader.resolve_credential(credential.credential_ref_id)
        evaluated_at = clock()
        if (
            current is None
            or current != credential
            or current.status is not CredentialStatus.ACTIVE
            or evaluated_at < current.created_at
            or evaluated_at >= current.expires_at
            or required_scope not in current.scopes
        ):
            raise RuntimeError
        value = os.environ.get(current.resolver_key)
        if not value:
            raise RuntimeError
        return value
    except Exception:
        raise RuntimeError("credential is unavailable") from None


class _LiveSourceCredentialFileBroker:
    """Source-secret resolver behind the adapter's typed credential port."""

    __slots__ = ("_clock", "_reader")

    def __init__(
        self,
        reader: DataAgentSituatedCredentialFileReader,
        *,
        clock: Clock,
    ) -> None:
        self._reader = reader
        self._clock = clock

    def resolve(self, credential: CredentialRef) -> str:
        return _resolve_live_credential_secret(
            self._reader,
            credential,
            required_scope="reports:read",
            clock=self._clock,
        )


class _LiveProviderCredentialFileBroker(EnvCredentialBroker):
    """Provider-secret resolver that preserves the provider's broker contract."""

    __slots__ = ("_clock", "_reader")

    def __init__(
        self,
        reader: DataAgentSituatedCredentialFileReader,
        *,
        clock: Clock,
    ) -> None:
        self._reader = reader
        self._clock = clock

    def resolve(self, ref: CredentialRef) -> str:
        return _resolve_live_credential_secret(
            self._reader,
            ref,
            required_scope="chat",
            clock=self._clock,
        )


def _provider_endpoint_is_secure(base_url: str) -> bool:
    try:
        parsed = urlsplit(base_url)
        return bool(
            parsed.scheme == "https"
            and parsed.hostname
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
        )
    except (TypeError, ValueError):
        return False


def _canonical_provider_temperature(
    invocation: ProviderInvocationBinding,
) -> int | float:
    """Return the constructor value that preserves the ratified binding bytes."""
    if type(invocation) is not ProviderInvocationBinding:
        _fail(_RUNTIME_BINDING)
    temperature = invocation.temperature
    if not isinstance(temperature, Decimal) or not temperature.is_finite():
        _fail(_RUNTIME_BINDING)
    candidate: int | float
    if temperature.as_tuple().exponent == 0:
        candidate = int(temperature)
    else:
        candidate = float(temperature)
        if not math.isfinite(candidate):
            _fail(_RUNTIME_BINDING)
    reconstructed = invocation.model_copy(
        update={"temperature": Decimal(str(candidate))}
    )
    if content_digest(reconstructed) != content_digest(invocation):
        _fail(_RUNTIME_BINDING)
    return candidate


def _build_data_agent_situated_application(
    config_path: str | Path,
    *,
    database: str | Path,
    workspace: str | Path,
    clock: Clock = _utc_now,
) -> AgentOSApplication:
    """Compose the private receipt-required runtime from pre-provisioned authority."""
    if str(database) == ":memory:":
        _fail(_RUNTIME_IN_MEMORY)
    provisioned = load_data_agent_situated_startup_provisioning(config_path)
    config = provisioned.config
    try:
        evaluated_at = clock()
        authority_database = _validate_authority_database(
            provisioned.config_path, config.authority_database
        )
        if authority_database != provisioned.authority_database:
            raise RuntimeError
        control = SQLiteSituatedAssessmentStore(provisioned.authority_database)
        mandate, binding = control.resolve_active(
            config.mandate_id,
            config.environment_binding_id,
            principal_id=config.principal_id,
            tenant_id=config.tenant_id,
            workspace_id=config.workspace_id,
            evaluated_at=evaluated_at,
        )
    except Exception:
        _fail(_RUNTIME_AUTHORITY)
    policy = provisioned.provider_policy
    context = provisioned.relevance_context
    if (
        mandate.version != config.expected_mandate_version
        or mandate.mandate_digest != config.expected_mandate_digest
        or mandate.correction_epoch != config.expected_correction_epoch
        or binding.environment_binding_id != config.environment_binding_id
        or binding.binding_digest != config.expected_binding_digest
        or mandate.relevance_assessor != policy.assessor_ref()
        or mandate.relevance_context != context.ref()
        or context.mandate_id != mandate.mandate_id
        or context.mandate_version != mandate.version
        or context.mandate_digest != mandate.mandate_digest
    ):
        _fail(_RUNTIME_BINDING)
    invocation = policy.provider_invocation
    if not _provider_endpoint_is_secure(invocation.base_url):
        _fail(_RUNTIME_BINDING)
    try:
        provider_temperature = _canonical_provider_temperature(invocation)
        source_reader = provisioned.source_credentials()
        source_credential = source_reader.resolve_credential(
            provisioned.source_credential.credential_ref_id
        )
        provider_reader = provisioned.provider_credentials()
        provider_credential = provider_reader.resolve_credential(
            provisioned.provider_credential.credential_ref_id
        )
        if (
            source_credential is None
            or provider_credential is None
            or source_credential != provisioned.source_credential
            or provider_credential != provisioned.provider_credential
            or source_credential.status is not CredentialStatus.ACTIVE
            or provider_credential.status is not CredentialStatus.ACTIVE
            or evaluated_at < source_credential.created_at
            or evaluated_at >= source_credential.expires_at
            or evaluated_at < provider_credential.created_at
            or evaluated_at >= provider_credential.expires_at
            or policy.provider_invocation.credential_ref_digest
            != content_digest(provider_credential)
        ):
            _fail(_RUNTIME_COMPOSITION)

        source = config.source
        adapter = DataAgentReportAdapter(
            DataAgentReportSourceConfig(
                source_id=source.source_id,
                base_url=source.base_url,
                source_tenant_id=source.source_tenant_id,
                credential=source_credential,
                principal_id=config.principal_id,
                target_tenant_id=config.tenant_id,
                target_workspace_id=config.workspace_id,
                mandate_id=config.mandate_id,
                environment_binding_id=config.environment_binding_id,
                scope_ref=source.scope_ref,
                allow_loopback_http=source.allow_loopback_http,
                timeout_seconds=source.timeout_seconds,
                max_response_bytes=source.max_response_bytes,
                freshness_seconds=source.freshness_seconds,
            ),
            credential_broker=_LiveSourceCredentialFileBroker(
                source_reader, clock=clock
            ),
            credential_authorizations=source_reader,
            state_store=SQLiteDataAgentReportStateStore(authority_database),
            clock=clock,
        )

        provider = OpenAICompatibleProvider(
            base_url=invocation.base_url,
            model=invocation.model_id,
            credential=provider_credential,
            credentials=_LiveProviderCredentialFileBroker(provider_reader, clock=clock),
            timeout_seconds=invocation.request_timeout_seconds,
            temperature=provider_temperature,
            provider_profile=invocation.provider_profile,
        )
        if content_digest(provider.invocation_binding) != content_digest(invocation):
            _fail(_RUNTIME_BINDING)
        assessor = ProviderRelevanceAssessor(
            provider=provider,
            provider_profile=invocation.provider_profile,
            policy=policy,
            trust=adapter,
            contexts=InMemoryMandateRelevanceContextRegistry((context,)),
        )
        material_store = SQLiteDataAgentReportAdmissionMaterialStore(
            database,
            principal_id=config.principal_id,
            tenant_id=config.tenant_id,
            workspace_id=config.workspace_id,
        )
        runtime = DataAgentSituatedBootstrap.compose(
            adapter=adapter,
            material_store=material_store,
            credentials=source_reader,
            control=control,
            assessor=assessor,
            admission_database=database,
            clock=clock,
        )
        principal = PrincipalIdentity(
            principal_id=config.principal_id,
            tenant_id=config.tenant_id,
            workspace_id=config.workspace_id,
            role=PrincipalRole.PRINCIPAL,
            authenticated_at=evaluated_at,
        )
        active_perception_service = None
        if config.active_perception is not None:
            active = config.active_perception
            active_config = MandateActivePerceptionConfig(
                schedule_id=(
                    f"active-perception:{config.principal_id}:{config.tenant_id}:"
                    f"{config.workspace_id}:{config.mandate_id}:"
                    f"{config.environment_binding_id}"
                ),
                principal_id=config.principal_id,
                tenant_id=config.tenant_id,
                workspace_id=config.workspace_id,
                mandate_id=config.mandate_id,
                environment_binding_id=config.environment_binding_id,
                interval_seconds=active.interval_seconds,
                budget_window_seconds=active.budget_window_seconds,
                wake_budget_per_window=active.wake_budget_per_window,
                query_budget_per_window=active.query_budget_per_window,
                feed_limit=active.feed_limit,
                lease_seconds=active.lease_seconds,
            )
            active_perception_service = MandateActivePerceptionService(
                config=active_config,
                store=SQLiteMandateActivePerceptionStore(authority_database),
                adapter=adapter,
                runtime=runtime,
                clock=clock,
            )
            active_perception_service.ensure_schedule(first_wake_at=evaluated_at)
        return AgentOSApplication._with_data_agent_situated_runtime(
            situated_runtime=runtime,
            principal=principal,
            active_perception_service=active_perception_service,
            database=database,
            workspace=workspace,
            clock=clock,
        )
    except Exception:
        _fail(_RUNTIME_COMPOSITION)
