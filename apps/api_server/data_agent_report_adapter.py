from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from queue import Queue
from types import MappingProxyType
from threading import RLock, Thread
from typing import Callable, Mapping, Protocol
from urllib.parse import SplitResult, quote, urlsplit, urlunsplit

from agent_os_contracts import (
    ArtifactLocationClass,
    ArtifactRef,
    CredentialRef,
    CredentialStatus,
    EnvironmentEvent,
    EvidenceRef,
    EvidenceSourceKind,
    OperationalProjectionRef,
    ProjectionEpistemicStatus,
    canonical_json,
    content_digest,
)
from agent_os_core import EnvCredentialBroker, SituationalBinding


Clock = Callable[[], datetime]
_TRACE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_ADAPTER_VERSION = "data-agent-external-report-adapter:v1"
_PROJECTION_SCHEMA = "schema://operational-projection/data-agent-report-metadata/v1"
_SOURCE_ENVELOPE_CONTRACT = "data-agent.external-report.security-envelope.v1"
_CREDENTIAL_PROVIDER = "data-agent-external-report"


class DataAgentReportAdapterError(RuntimeError):
    """A safe, non-secret-bearing failure at the external observation boundary."""


class DataAgentReportConflict(DataAgentReportAdapterError):
    """The mutable upstream snapshot changed for an already observed trace."""


class CredentialResolver(Protocol):
    def resolve(self, credential: CredentialRef) -> str: ...


@dataclass(frozen=True)
class DataAgentReportHttpRequest:
    url: str
    headers: Mapping[str, str]
    timeout_seconds: int
    max_response_bytes: int


@dataclass(frozen=True)
class DataAgentReportHttpResponse:
    status_code: int
    headers: Mapping[str, str]
    body: bytes
    final_url: str


class DataAgentReportTransport(Protocol):
    def fetch(self, request: DataAgentReportHttpRequest) -> DataAgentReportHttpResponse: ...


class StdlibDataAgentReportTransport:
    """HTTPS-verifying transport with no redirects, hard bytes, and total deadline."""

    def fetch(self, request: DataAgentReportHttpRequest) -> DataAgentReportHttpResponse:
        parsed = urlsplit(request.url)
        if not parsed.hostname or parsed.scheme not in {"http", "https"}:
            raise DataAgentReportAdapterError("external report request URL is invalid")
        connection_type = (
            http.client.HTTPSConnection
            if parsed.scheme == "https"
            else http.client.HTTPConnection
        )
        connection = connection_type(
            parsed.hostname,
            parsed.port,
            timeout=request.timeout_seconds,
        )
        results: Queue[DataAgentReportHttpResponse | BaseException] = Queue(maxsize=1)

        def run() -> None:
            try:
                results.put(self._fetch_blocking(request, parsed, connection))
            except BaseException as exc:
                results.put(exc)

        worker = Thread(target=run, daemon=True)
        worker.start()
        worker.join(timeout=request.timeout_seconds)
        if worker.is_alive():
            connection.close()
            raise DataAgentReportAdapterError(
                "external report total deadline exceeded"
            )
        outcome = results.get_nowait()
        if isinstance(outcome, DataAgentReportHttpResponse):
            return outcome
        if isinstance(outcome, DataAgentReportAdapterError):
            raise outcome
        raise DataAgentReportAdapterError("external report transport failed") from None

    @staticmethod
    def _fetch_blocking(
        request: DataAgentReportHttpRequest,
        parsed: SplitResult,
        connection: http.client.HTTPConnection,
    ) -> DataAgentReportHttpResponse:
        deadline = time.monotonic() + request.timeout_seconds
        path = urlunsplit(("", "", parsed.path, parsed.query, ""))
        try:
            connection.request("GET", path, headers=dict(request.headers))
            response = connection.getresponse()
            headers = MappingProxyType(dict(response.getheaders()))
            declared_length = _header(headers, "Content-Length")
            if declared_length is not None:
                try:
                    parsed_length = int(declared_length)
                except ValueError:
                    raise DataAgentReportAdapterError(
                        "external report content length is invalid"
                    ) from None
                if parsed_length > request.max_response_bytes:
                    raise DataAgentReportAdapterError(
                        "external report response exceeds configured size limit"
                    )
            body_parts: list[bytes] = []
            received = 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise DataAgentReportAdapterError(
                        "external report total deadline exceeded"
                    )
                if connection.sock is not None:
                    connection.sock.settimeout(remaining)
                chunk = response.read(
                    min(65_536, request.max_response_bytes + 1 - received)
                )
                if not chunk:
                    break
                body_parts.append(chunk)
                received += len(chunk)
                if received > request.max_response_bytes:
                    raise DataAgentReportAdapterError(
                        "external report response exceeds configured size limit"
                    )
            return DataAgentReportHttpResponse(
                status_code=int(response.status),
                headers=headers,
                body=b"".join(body_parts),
                final_url=request.url,
            )
        except DataAgentReportAdapterError:
            raise
        except Exception:
            raise DataAgentReportAdapterError(
                "external report transport failed"
            ) from None
        finally:
            connection.close()


@dataclass(frozen=True)
class DataAgentReportSourceConfig:
    """Owner-frozen source and authority envelope; callers cannot override it."""

    source_id: str
    base_url: str
    source_tenant_id: str
    credential: CredentialRef
    principal_id: str
    target_tenant_id: str
    target_workspace_id: str
    mandate_id: str
    environment_binding_id: str
    scope_ref: str
    allow_loopback_http: bool = False
    timeout_seconds: int = 10
    max_response_bytes: int = 1_048_576
    freshness_seconds: int = 300

    def __post_init__(self) -> None:
        text_fields = (
            self.source_id,
            self.source_tenant_id,
            self.principal_id,
            self.target_tenant_id,
            self.target_workspace_id,
            self.mandate_id,
            self.environment_binding_id,
            self.scope_ref,
        )
        if any(not value.strip() for value in text_fields):
            raise DataAgentReportAdapterError("source configuration fields cannot be empty")
        if self.timeout_seconds <= 0:
            raise DataAgentReportAdapterError("timeout must be positive")
        if self.max_response_bytes <= 0:
            raise DataAgentReportAdapterError("response size limit must be positive")
        if self.freshness_seconds <= 0:
            raise DataAgentReportAdapterError("freshness window must be positive")
        if not _TRACE_ID.fullmatch(self.source_tenant_id) or ".." in self.source_tenant_id:
            raise DataAgentReportAdapterError(
                "source tenant id is not safe for an HTTP header"
            )


@dataclass(frozen=True)
class TrustedObservationBundle:
    artifact: ArtifactRef
    evidence: EvidenceRef
    event: EnvironmentEvent
    projection: OperationalProjectionRef


@dataclass(frozen=True)
class DataAgentReportPollResult:
    bundles: tuple[TrustedObservationBundle, ...]
    next_cursor: str | None
    has_more: bool


class DataAgentReportStateStore(Protocol):
    durable: bool

    def get(
        self,
        namespace_digest: str,
        source_id: str,
        source_tenant_id: str,
        trace_id: str,
    ) -> tuple[str, bytes, TrustedObservationBundle] | None: ...

    def save(
        self,
        namespace_digest: str,
        source_id: str,
        source_tenant_id: str,
        trace_id: str,
        raw_digest: str,
        body: bytes,
        bundle: TrustedObservationBundle,
    ) -> None: ...

    def get_feed_cursor(
        self,
        namespace_digest: str,
        source_id: str,
        source_tenant_id: str,
    ) -> str | None: ...

    def advance_feed_cursor(
        self,
        namespace_digest: str,
        source_id: str,
        source_tenant_id: str,
        *,
        expected_cursor: str | None,
        next_cursor: str | None,
    ) -> bool: ...


class SQLiteDataAgentReportStateStore:
    """Durable first-seen identity and exact-byte store shared across processes."""

    durable = True

    def __init__(self, database: str | Path) -> None:
        self._database = str(database)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS data_agent_report_observations (
                    namespace_digest TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    source_tenant_id TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    raw_digest TEXT NOT NULL,
                    body BLOB NOT NULL,
                    bundle_json TEXT NOT NULL,
                    PRIMARY KEY (namespace_digest, trace_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS data_agent_report_feed_cursors (
                    namespace_digest TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    source_tenant_id TEXT NOT NULL,
                    cursor TEXT,
                    PRIMARY KEY (namespace_digest, source_id, source_tenant_id)
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database, timeout=10)
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    @staticmethod
    def _serialize(bundle: TrustedObservationBundle) -> str:
        return canonical_json(
            {
                "artifact": bundle.artifact.model_dump(mode="json"),
                "evidence": bundle.evidence.model_dump(mode="json"),
                "event": bundle.event.model_dump(mode="json"),
                "projection": bundle.projection.model_dump(mode="json"),
            }
        )

    @staticmethod
    def _deserialize(payload: str) -> TrustedObservationBundle:
        try:
            parsed = json.loads(payload)
            if not isinstance(parsed, dict):
                raise ValueError
            return TrustedObservationBundle(
                artifact=ArtifactRef.model_validate(parsed["artifact"]),
                evidence=EvidenceRef.model_validate(parsed["evidence"]),
                event=EnvironmentEvent.model_validate(parsed["event"]),
                projection=OperationalProjectionRef.model_validate(parsed["projection"]),
            )
        except Exception:
            raise DataAgentReportAdapterError(
                "durable external report state is invalid"
            ) from None

    def get(
        self,
        namespace_digest: str,
        source_id: str,
        source_tenant_id: str,
        trace_id: str,
    ) -> tuple[str, bytes, TrustedObservationBundle] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT raw_digest, body, bundle_json
                FROM data_agent_report_observations
                WHERE namespace_digest = ?
                  AND source_id = ? AND source_tenant_id = ? AND trace_id = ?
                """,
                (namespace_digest, source_id, source_tenant_id, trace_id),
            ).fetchone()
        if row is None:
            return None
        return str(row[0]), bytes(row[1]), self._deserialize(str(row[2]))

    def save(
        self,
        namespace_digest: str,
        source_id: str,
        source_tenant_id: str,
        trace_id: str,
        raw_digest: str,
        body: bytes,
        bundle: TrustedObservationBundle,
    ) -> None:
        serialized = self._serialize(bundle)
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    """
                    SELECT raw_digest, body, bundle_json
                    FROM data_agent_report_observations
                    WHERE namespace_digest = ?
                      AND source_id = ? AND source_tenant_id = ? AND trace_id = ?
                    """,
                    (namespace_digest, source_id, source_tenant_id, trace_id),
                ).fetchone()
                if existing is None:
                    connection.execute(
                        """
                        INSERT INTO data_agent_report_observations (
                            namespace_digest, source_id, source_tenant_id, trace_id,
                            raw_digest, body, bundle_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            namespace_digest,
                            source_id,
                            source_tenant_id,
                            trace_id,
                            raw_digest,
                            sqlite3.Binary(body),
                            serialized,
                        ),
                    )
                    return
                if (
                    str(existing[0]) != raw_digest
                    or bytes(existing[1]) != body
                ):
                    raise DataAgentReportConflict(
                        "durable external report identity conflict"
                    )
        except DataAgentReportConflict:
            raise
        except sqlite3.Error:
            raise DataAgentReportAdapterError(
                "durable external report state is unavailable"
            ) from None

    def get_feed_cursor(
        self,
        namespace_digest: str,
        source_id: str,
        source_tenant_id: str,
    ) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT cursor FROM data_agent_report_feed_cursors
                WHERE namespace_digest = ?
                  AND source_id = ? AND source_tenant_id = ?
                """,
                (namespace_digest, source_id, source_tenant_id),
            ).fetchone()
        return str(row[0]) if row is not None and row[0] is not None else None

    def advance_feed_cursor(
        self,
        namespace_digest: str,
        source_id: str,
        source_tenant_id: str,
        *,
        expected_cursor: str | None,
        next_cursor: str | None,
    ) -> bool:
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    """
                    SELECT cursor FROM data_agent_report_feed_cursors
                    WHERE namespace_digest = ?
                      AND source_id = ? AND source_tenant_id = ?
                    """,
                    (namespace_digest, source_id, source_tenant_id),
                ).fetchone()
                current = (
                    str(row[0]) if row is not None and row[0] is not None else None
                )
                if current != expected_cursor:
                    return False
                if row is None:
                    connection.execute(
                        """
                        INSERT INTO data_agent_report_feed_cursors (
                            namespace_digest, source_id, source_tenant_id, cursor
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (
                            namespace_digest,
                            source_id,
                            source_tenant_id,
                            next_cursor,
                        ),
                    )
                else:
                    connection.execute(
                        """
                        UPDATE data_agent_report_feed_cursors SET cursor = ?
                        WHERE namespace_digest = ?
                          AND source_id = ? AND source_tenant_id = ?
                        """,
                        (
                            next_cursor,
                            namespace_digest,
                            source_id,
                            source_tenant_id,
                        ),
                    )
                return True
        except sqlite3.Error:
            raise DataAgentReportAdapterError(
                "durable external report cursor state is unavailable"
            ) from None


class _InMemoryDataAgentReportStateStore:
    durable = False

    def __init__(self) -> None:
        self._rows: dict[
            tuple[str, str, str, str], tuple[str, bytes, TrustedObservationBundle]
        ] = {}
        self._feed_cursors: dict[tuple[str, str, str], str | None] = {}

    def get(
        self,
        namespace_digest: str,
        source_id: str,
        source_tenant_id: str,
        trace_id: str,
    ) -> tuple[str, bytes, TrustedObservationBundle] | None:
        return self._rows.get(
            (namespace_digest, source_id, source_tenant_id, trace_id)
        )

    def save(
        self,
        namespace_digest: str,
        source_id: str,
        source_tenant_id: str,
        trace_id: str,
        raw_digest: str,
        body: bytes,
        bundle: TrustedObservationBundle,
    ) -> None:
        key = (namespace_digest, source_id, source_tenant_id, trace_id)
        value = (raw_digest, bytes(body), bundle)
        existing = self._rows.get(key)
        if existing is not None and existing != value:
            raise DataAgentReportConflict("external report identity conflict")
        self._rows[key] = value

    def get_feed_cursor(
        self,
        namespace_digest: str,
        source_id: str,
        source_tenant_id: str,
    ) -> str | None:
        return self._feed_cursors.get(
            (namespace_digest, source_id, source_tenant_id)
        )

    def advance_feed_cursor(
        self,
        namespace_digest: str,
        source_id: str,
        source_tenant_id: str,
        *,
        expected_cursor: str | None,
        next_cursor: str | None,
    ) -> bool:
        key = (namespace_digest, source_id, source_tenant_id)
        if self._feed_cursors.get(key) != expected_cursor:
            return False
        self._feed_cursors[key] = next_cursor
        return True


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DataAgentReportAdapterError("adapter clock must be timezone-aware")
    return value.astimezone(timezone.utc)


def _normalized_origin(base_url: str, *, allow_loopback_http: bool) -> str:
    parsed = urlsplit(base_url)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise DataAgentReportAdapterError(
            "external report origin cannot contain userinfo, query, or fragment"
        )
    if parsed.path not in ("", "/"):
        raise DataAgentReportAdapterError("external report base_url must be an origin")
    if not parsed.hostname:
        raise DataAgentReportAdapterError("external report origin requires a host")
    host = parsed.hostname.lower()
    is_loopback = False
    try:
        is_loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        is_loopback = host == "localhost"
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and is_loopback and allow_loopback_http
    ):
        raise DataAgentReportAdapterError(
            "external report origin requires HTTPS except explicit loopback tests"
        )
    try:
        port = parsed.port
    except ValueError:
        raise DataAgentReportAdapterError("external report origin port is invalid") from None
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = host if port is None else f"{host}:{port}"
    return urlunsplit((parsed.scheme.lower(), netloc, "", "", ""))


def _header(headers: Mapping[str, str], name: str) -> str | None:
    target = name.lower()
    for key, value in headers.items():
        if key.lower() == target:
            return value.strip()
    return None


def _strict_json_object(body: bytes) -> dict[str, object]:
    def reject_constant(value: str) -> object:
        raise DataAgentReportAdapterError(
            f"external report contains non-JSON numeric constant {value}"
        )

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise DataAgentReportAdapterError(
                    "external report contains duplicate JSON keys"
                )
            result[key] = value
        return result

    try:
        decoded = body.decode("utf-8", errors="strict")
        parsed = json.loads(
            decoded,
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except DataAgentReportAdapterError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise DataAgentReportAdapterError(
            "external report must be strict UTF-8 JSON"
        ) from None
    if not isinstance(parsed, dict):
        raise DataAgentReportAdapterError("external report root must be an object")
    return parsed


def _object(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise DataAgentReportAdapterError(f"external report {name} must be an object")
    return value


def _contains_secret(value: object, secret: str) -> bool:
    if isinstance(value, str):
        return secret in value
    if isinstance(value, dict):
        return any(
            _contains_secret(key, secret) or _contains_secret(item, secret)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_secret(item, secret) for item in value)
    return False


class DataAgentReportAdapter:
    """Read-only Data Agent observation adapter and in-process trust resolver.

    The source report remains opaque. Only scope, redaction, trace and exact-byte
    identity are interpreted; no Data Agent decision or action field gains Agent OS
    task, grant, approval, connector, or effect authority.
    """

    def __init__(
        self,
        config: DataAgentReportSourceConfig,
        *,
        credential_broker: CredentialResolver | None = None,
        transport: DataAgentReportTransport | None = None,
        state_store: DataAgentReportStateStore | None = None,
        clock: Clock,
    ) -> None:
        self._config = config
        self._origin = _normalized_origin(
            config.base_url,
            allow_loopback_http=config.allow_loopback_http,
        )
        self._validate_credential_contract()
        self._state_namespace = content_digest(
            {
                "adapter_version": _ADAPTER_VERSION,
                "projection_schema": _PROJECTION_SCHEMA,
                "source_envelope_contract": _SOURCE_ENVELOPE_CONTRACT,
                "source_id": config.source_id,
                "origin": self._origin,
                "source_tenant_id": config.source_tenant_id,
                "credential_ref_id": config.credential.credential_ref_id,
                "principal_id": config.principal_id,
                "target_tenant_id": config.target_tenant_id,
                "target_workspace_id": config.target_workspace_id,
                "mandate_id": config.mandate_id,
                "environment_binding_id": config.environment_binding_id,
                "scope_ref": config.scope_ref,
            }
        )
        self._credentials = credential_broker or EnvCredentialBroker()
        self._transport = transport or StdlibDataAgentReportTransport()
        self._state_store = state_store or _InMemoryDataAgentReportStateStore()
        self._clock = clock
        self._binding: SituationalBinding = (
            config.principal_id,
            config.target_tenant_id,
            config.target_workspace_id,
            config.mandate_id,
            config.environment_binding_id,
        )
        self._artifacts: dict[str, tuple[ArtifactRef, bytes]] = {}
        self._evidence: dict[str, EvidenceRef] = {}
        self._events: dict[str, EnvironmentEvent] = {}
        self._projections: dict[str, OperationalProjectionRef] = {}
        self._bundles_by_observation: dict[str, TrustedObservationBundle] = {}
        self._digests_by_observation: dict[str, str] = {}
        self._registry_lock = RLock()
        self._poll_lock = RLock()

    @property
    def registry_counts(self) -> tuple[int, int, int, int]:
        with self._registry_lock:
            return (
                len(self._artifacts),
                len(self._evidence),
                len(self._events),
                len(self._projections),
            )

    @property
    def principal_scope(self) -> tuple[str, str, str]:
        return (
            self._config.principal_id,
            self._config.target_tenant_id,
            self._config.target_workspace_id,
        )

    @property
    def has_durable_state(self) -> bool:
        return self._state_store.durable

    @property
    def feed_cursor(self) -> str | None:
        return self._state_store.get_feed_cursor(
            self._state_namespace,
            self._config.source_id,
            self._config.source_tenant_id,
        )

    def _validate_credential_contract(self) -> None:
        credential = self._config.credential
        required_scopes = {
            "reports:read",
            f"data-agent-origin:{self._origin}",
            f"data-agent-tenant:{self._config.source_tenant_id}",
        }
        if credential.provider_id != _CREDENTIAL_PROVIDER:
            raise DataAgentReportAdapterError(
                "credential provider is not bound to external report access"
            )
        if (
            credential.tenant_id != self._config.target_tenant_id
            or credential.workspace_id != self._config.target_workspace_id
            or credential.owner_principal_id != self._config.principal_id
        ):
            raise DataAgentReportAdapterError("credential scope does not match target owner")
        if not required_scopes.issubset(set(credential.scopes)):
            raise DataAgentReportAdapterError(
                "credential is not bound to the frozen origin, tenant, and report scope"
            )

    def pull(self, trace_id: str) -> TrustedObservationBundle:
        if not _TRACE_ID.fullmatch(trace_id) or ".." in trace_id:
            raise DataAgentReportAdapterError("trace_id is not a safe single segment")
        now = _utc(self._clock())
        credential = self._config.credential
        if (
            credential.status is not CredentialStatus.ACTIVE
            or now < credential.created_at
            or now >= credential.expires_at
        ):
            raise DataAgentReportAdapterError("credential is inactive or expired")
        path_trace = quote(trace_id, safe="")
        expected_url = (
            f"{self._origin}/runs/{path_trace}/report?audience=external"
        )
        try:
            secret = self._credentials.resolve(credential)
        except Exception:
            raise DataAgentReportAdapterError("external report credential is unavailable") from None
        if not secret:
            raise DataAgentReportAdapterError("external report credential is unavailable")
        request = DataAgentReportHttpRequest(
            url=expected_url,
            headers=MappingProxyType(
                {
                    "Accept": "application/json",
                    "Accept-Encoding": "identity",
                    "X-API-Key": secret,
                    "X-Tenant-Id": self._config.source_tenant_id,
                }
            ),
            timeout_seconds=self._config.timeout_seconds,
            max_response_bytes=self._config.max_response_bytes,
        )
        try:
            response = self._transport.fetch(request)
        except Exception:
            raise DataAgentReportAdapterError("external report transport failed") from None
        self._validate_http_response(response, expected_url)
        if secret.encode("utf-8") in response.body:
            raise DataAgentReportAdapterError(
                "external report reflected credential material"
            )
        payload = _strict_json_object(response.body)
        if _contains_secret(payload, secret):
            raise DataAgentReportAdapterError(
                "external report reflected credential material"
            )
        self._validate_report_contract(payload, trace_id)
        raw_digest = hashlib.sha256(response.body).hexdigest()
        return self._ingest_report(
            observation_key=f"trace:{trace_id}",
            trace_id=trace_id,
            body=response.body,
            raw_digest=raw_digest,
            observed_at=now,
        )

    def poll_once(self, *, limit: int = 50) -> DataAgentReportPollResult:
        if isinstance(limit, bool) or not 1 <= limit <= 100:
            raise DataAgentReportAdapterError("feed limit must be between 1 and 100")
        if "report-events:read" not in self._config.credential.scopes:
            raise DataAgentReportAdapterError(
                "credential is not authorized to read report events"
            )
        with self._poll_lock:
            prior_cursor = self.feed_cursor
            query = f"limit={limit}"
            if prior_cursor is not None:
                query = f"after={quote(prior_cursor, safe='')}&{query}"
            expected_url = f"{self._origin}/external/report-events?{query}"
            now = _utc(self._clock())
            credential = self._config.credential
            if (
                credential.status is not CredentialStatus.ACTIVE
                or now < credential.created_at
                or now >= credential.expires_at
            ):
                raise DataAgentReportAdapterError("credential is inactive or expired")
            try:
                secret = self._credentials.resolve(credential)
            except Exception:
                raise DataAgentReportAdapterError(
                    "external report credential is unavailable"
                ) from None
            if not secret:
                raise DataAgentReportAdapterError(
                    "external report credential is unavailable"
                )
            request = DataAgentReportHttpRequest(
                url=expected_url,
                headers=MappingProxyType(
                    {
                        "Accept": "application/json",
                        "Accept-Encoding": "identity",
                        "X-API-Key": secret,
                    }
                ),
                timeout_seconds=self._config.timeout_seconds,
                max_response_bytes=self._config.max_response_bytes,
            )
            try:
                response = self._transport.fetch(request)
            except Exception:
                raise DataAgentReportAdapterError(
                    "external report transport failed"
                ) from None
            self._validate_http_response(response, expected_url)
            if secret.encode("utf-8") in response.body:
                raise DataAgentReportAdapterError(
                    "external report feed reflected credential material"
                )
            payload = _strict_json_object(response.body)
            if _contains_secret(payload, secret):
                raise DataAgentReportAdapterError(
                    "external report feed reflected credential material"
                )
            events, next_cursor, has_more = self._validate_feed_contract(
                payload,
                prior_cursor=prior_cursor,
                limit=limit,
            )
            bundles: list[TrustedObservationBundle] = []
            for event in events:
                trace_id = event["trace_id"]
                report = event["report"]
                supplied_digest = event["content_sha256"]
                body = canonical_json(report).encode("utf-8")
                actual_digest = hashlib.sha256(body).hexdigest()
                if actual_digest != supplied_digest:
                    raise DataAgentReportAdapterError(
                        "external report event digest mismatch"
                    )
                self._validate_report_contract(report, trace_id)
                bundles.append(
                    self._ingest_report(
                        observation_key=f"feed:{trace_id}:{actual_digest}",
                        trace_id=trace_id,
                        body=body,
                        raw_digest=actual_digest,
                        observed_at=now,
                    )
                )
            if not self._state_store.advance_feed_cursor(
                self._state_namespace,
                self._config.source_id,
                self._config.source_tenant_id,
                expected_cursor=prior_cursor,
                next_cursor=next_cursor,
            ):
                raise DataAgentReportConflict(
                    "external report feed cursor changed concurrently"
                )
            return DataAgentReportPollResult(
                bundles=tuple(bundles),
                next_cursor=next_cursor,
                has_more=has_more,
            )

    @staticmethod
    def _validate_feed_contract(
        payload: dict[str, object],
        *,
        prior_cursor: str | None,
        limit: int,
    ) -> tuple[tuple[dict[str, object], ...], str | None, bool]:
        if set(payload) != {
            "schema_version",
            "audience",
            "events",
            "next_cursor",
            "has_more",
        }:
            raise DataAgentReportAdapterError(
                "external report feed fields are invalid"
            )
        if payload.get("schema_version") != "external-report-events.v1":
            raise DataAgentReportAdapterError(
                "external report feed schema is unsupported"
            )
        if payload.get("audience") != "external":
            raise DataAgentReportAdapterError(
                "external report feed audience is not external"
            )
        raw_events = payload.get("events")
        if not isinstance(raw_events, list) or len(raw_events) > limit:
            raise DataAgentReportAdapterError(
                "external report feed events are invalid"
            )
        has_more = payload.get("has_more")
        if not isinstance(has_more, bool):
            raise DataAgentReportAdapterError(
                "external report feed has_more is invalid"
            )
        next_cursor = payload.get("next_cursor")
        if next_cursor is not None and (
            not isinstance(next_cursor, str)
            or not next_cursor
            or len(next_cursor) > 1024
        ):
            raise DataAgentReportAdapterError(
                "external report feed cursor is invalid"
            )
        events: list[dict[str, object]] = []
        cursors: set[str] = set()
        for raw_event in raw_events:
            if not isinstance(raw_event, dict) or set(raw_event) != {
                "cursor",
                "trace_id",
                "content_sha256",
                "report",
            }:
                raise DataAgentReportAdapterError(
                    "external report feed event is invalid"
                )
            cursor = raw_event.get("cursor")
            trace_id = raw_event.get("trace_id")
            digest = raw_event.get("content_sha256")
            report = raw_event.get("report")
            if (
                not isinstance(cursor, str)
                or not cursor
                or len(cursor) > 1024
                or cursor in cursors
            ):
                raise DataAgentReportAdapterError(
                    "external report feed event cursor is invalid"
                )
            if (
                not isinstance(trace_id, str)
                or not _TRACE_ID.fullmatch(trace_id)
                or ".." in trace_id
            ):
                raise DataAgentReportAdapterError(
                    "external report feed event trace_id is invalid"
                )
            if (
                not isinstance(digest, str)
                or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            ):
                raise DataAgentReportAdapterError(
                    "external report feed event digest is invalid"
                )
            if not isinstance(report, dict):
                raise DataAgentReportAdapterError(
                    "external report feed event report is invalid"
                )
            cursors.add(cursor)
            events.append(
                {
                    "cursor": cursor,
                    "trace_id": trace_id,
                    "content_sha256": digest,
                    "report": report,
                }
            )
        if events:
            if next_cursor != events[-1]["cursor"]:
                raise DataAgentReportAdapterError(
                    "external report feed next cursor is not the page tail"
                )
            if prior_cursor is not None and (
                next_cursor == prior_cursor
                or any(event["cursor"] == prior_cursor for event in events)
            ):
                raise DataAgentReportAdapterError(
                    "external report feed page did not make cursor progress"
                )
        elif next_cursor != prior_cursor:
            raise DataAgentReportAdapterError(
                "external report empty page changed the cursor"
            )
        if has_more and not events:
            raise DataAgentReportAdapterError(
                "external report feed cannot have more after an empty page"
            )
        return tuple(events), next_cursor, has_more

    def _ingest_report(
        self,
        *,
        observation_key: str,
        trace_id: str,
        body: bytes,
        raw_digest: str,
        observed_at: datetime,
    ) -> TrustedObservationBundle:
        with self._registry_lock:
            previous_digest = self._digests_by_observation.get(observation_key)
            if previous_digest is not None:
                if previous_digest != raw_digest:
                    raise DataAgentReportConflict(
                        "external report changed for an already observed identity"
                    )
                return self._bundles_by_observation[observation_key]

            stored = self._state_store.get(
                self._state_namespace,
                self._config.source_id,
                self._config.source_tenant_id,
                observation_key,
            )
            if stored is not None:
                stored_digest, stored_body, stored_bundle = stored
                if stored_digest != raw_digest or stored_body != body:
                    raise DataAgentReportConflict(
                        "external report changed for an already observed identity"
                    )
                self._register_atomically(
                    observation_key,
                    trace_id,
                    stored_digest,
                    stored_body,
                    stored_bundle,
                )
                return stored_bundle

            candidate = self._build_bundle(trace_id, body, raw_digest, observed_at)
            self._state_store.save(
                self._state_namespace,
                self._config.source_id,
                self._config.source_tenant_id,
                observation_key,
                raw_digest,
                body,
                candidate,
            )
            canonical = self._state_store.get(
                self._state_namespace,
                self._config.source_id,
                self._config.source_tenant_id,
                observation_key,
            )
            if canonical is None:
                raise DataAgentReportAdapterError(
                    "durable external report state was not committed"
                )
            canonical_digest, canonical_body, canonical_bundle = canonical
            if canonical_digest != raw_digest or canonical_body != body:
                raise DataAgentReportConflict(
                    "external report changed during durable registration"
                )
            self._register_atomically(
                observation_key,
                trace_id,
                canonical_digest,
                canonical_body,
                canonical_bundle,
            )
            return canonical_bundle

    def _validate_http_response(
        self,
        response: DataAgentReportHttpResponse,
        expected_url: str,
    ) -> None:
        if response.final_url != expected_url:
            raise DataAgentReportAdapterError(
                "external report response destination changed"
            )
        if response.status_code != 200:
            raise DataAgentReportAdapterError(
                "external report returned an unsupported status"
            )
        media_type = (_header(response.headers, "Content-Type") or "").split(
            ";", 1
        )[0].strip().lower()
        if media_type != "application/json":
            raise DataAgentReportAdapterError(
                "external report returned an unsupported media type"
            )
        encoding = (_header(response.headers, "Content-Encoding") or "identity").lower()
        if encoding != "identity":
            raise DataAgentReportAdapterError(
                "external report returned an unsupported content encoding"
            )
        content_length = _header(response.headers, "Content-Length")
        if content_length is not None:
            try:
                declared_length = int(content_length)
            except ValueError:
                raise DataAgentReportAdapterError(
                    "external report content length is invalid"
                ) from None
            if declared_length != len(response.body):
                raise DataAgentReportAdapterError(
                    "external report content length does not match body"
                )
        if len(response.body) > self._config.max_response_bytes:
            raise DataAgentReportAdapterError(
                "external report response exceeds configured size limit"
            )

    @staticmethod
    def _validate_report_contract(payload: dict[str, object], trace_id: str) -> None:
        if payload.get("trace_id") != trace_id:
            raise DataAgentReportAdapterError("external report trace binding mismatch")
        if payload.get("audience") != "external":
            raise DataAgentReportAdapterError("external report audience is not external")
        result = _object(payload.get("user_result"), "user_result")
        if result.get("trace_id") != trace_id:
            raise DataAgentReportAdapterError("external result trace binding mismatch")
        if result.get("audience") != "external":
            raise DataAgentReportAdapterError("external result audience is not external")
        redaction = _object(result.get("redaction"), "redaction")
        if redaction.get("audience") != "external" or redaction.get("applied") is not True:
            raise DataAgentReportAdapterError(
                "external result does not carry an applied external redaction"
            )
        business_action = _object(result.get("business_action"), "business_action")
        if business_action.get("trace_id") != trace_id:
            raise DataAgentReportAdapterError(
                "external business action trace binding mismatch"
            )

    def _stable_identity(self, trace_id: str, raw_digest: str) -> dict[str, object]:
        return {
            "adapter_version": _ADAPTER_VERSION,
            "source_id": self._config.source_id,
            "source_tenant_id": self._config.source_tenant_id,
            "trace_id": trace_id,
            "raw_digest": raw_digest,
            "principal_id": self._config.principal_id,
            "target_tenant_id": self._config.target_tenant_id,
            "target_workspace_id": self._config.target_workspace_id,
            "mandate_id": self._config.mandate_id,
            "environment_binding_id": self._config.environment_binding_id,
            "scope_ref": self._config.scope_ref,
        }

    def _build_bundle(
        self,
        trace_id: str,
        body: bytes,
        raw_digest: str,
        observed_at: datetime,
    ) -> TrustedObservationBundle:
        stable_identity = self._stable_identity(trace_id, raw_digest)
        dedupe_digest = content_digest(stable_identity)
        record_identity = {
            **stable_identity,
            "observed_at": observed_at.isoformat(),
        }
        identity_digest = content_digest(record_identity)
        artifact_id = f"artifact:data-agent-report:{identity_digest}"
        evidence_id = f"evidence:data-agent-report:{identity_digest}"
        event_id = f"event:data-agent-report:{identity_digest}"
        projection_payload = {
            "kind": "data-agent-external-report-metadata-projection",
            "version": 1,
            "source_identity": stable_identity,
            "source_artifact_id": artifact_id,
            "source_content_digest": raw_digest,
            "authority": "none",
        }
        projection_bytes = canonical_json(projection_payload).encode("utf-8")
        projection_digest = hashlib.sha256(projection_bytes).hexdigest()
        projection_identity = content_digest(
            {
                **record_identity,
                "projection_digest": projection_digest,
                "schema": _PROJECTION_SCHEMA,
            }
        )
        projection_artifact_id = f"artifact:data-agent-projection:{projection_identity}"
        projection_evidence_id = f"evidence:data-agent-projection:{projection_identity}"
        projection_id = f"projection:data-agent-report:{projection_identity}"
        created_by = _ADAPTER_VERSION
        artifact = ArtifactRef(
            artifact_id=artifact_id,
            tenant_id=self._config.target_tenant_id,
            workspace_id=self._config.target_workspace_id,
            content_digest=raw_digest,
            media_type="application/json",
            location_class=ArtifactLocationClass.OBJECT_STORE,
            location_ref=f"data-agent-report://{self._config.source_id}/{trace_id}/{raw_digest}",
            acl_scopes=("situated:read",),
            retention_policy="retain-source-observation",
            created_by=created_by,
            created_at=observed_at,
        )
        evidence = EvidenceRef(
            evidence_id=evidence_id,
            tenant_id=self._config.target_tenant_id,
            workspace_id=self._config.target_workspace_id,
            source_kind=EvidenceSourceKind.EXTERNAL_OBSERVATION,
            source_ref=f"{self._config.source_id}:{self._config.source_tenant_id}:{trace_id}",
            relation="observed-exact-external-report-bytes",
            artifact_ids=(artifact_id,),
            created_by=created_by,
            created_at=observed_at,
        )
        event = EnvironmentEvent(
            environment_event_id=event_id,
            environment_binding_id=self._config.environment_binding_id,
            mandate_id=self._config.mandate_id,
            tenant_id=self._config.target_tenant_id,
            workspace_id=self._config.target_workspace_id,
            event_type_ref="data-agent.external-report-observed.v1",
            dedupe_key=f"data-agent-report:{dedupe_digest}",
            observation=artifact,
            evidence=(evidence,),
            occurred_at=observed_at,
            recorded_at=observed_at,
        )
        projection_artifact = ArtifactRef(
            artifact_id=projection_artifact_id,
            tenant_id=self._config.target_tenant_id,
            workspace_id=self._config.target_workspace_id,
            content_digest=projection_digest,
            media_type="application/json",
            location_class=ArtifactLocationClass.OBJECT_STORE,
            location_ref=f"data-agent-projection://{projection_identity}",
            acl_scopes=("situated:read",),
            retention_policy="retain-derived-projection",
            created_by=created_by,
            created_at=observed_at,
        )
        projection_evidence = EvidenceRef(
            evidence_id=projection_evidence_id,
            tenant_id=self._config.target_tenant_id,
            workspace_id=self._config.target_workspace_id,
            source_kind=EvidenceSourceKind.ARTIFACT,
            source_ref=artifact_id,
            relation="projects-source-observation-metadata-without-authority",
            artifact_ids=(projection_artifact_id, artifact_id),
            created_by=created_by,
            created_at=observed_at,
        )
        projection = OperationalProjectionRef(
            projection_id=projection_id,
            environment_binding_id=self._config.environment_binding_id,
            mandate_id=self._config.mandate_id,
            tenant_id=self._config.target_tenant_id,
            workspace_id=self._config.target_workspace_id,
            source_event_ids=(event_id,),
            projection_artifact=projection_artifact,
            schema_uri=_PROJECTION_SCHEMA,
            version=1,
            scope_ref=self._config.scope_ref,
            valid_from=observed_at,
            recorded_at=observed_at,
            fresh_until=observed_at + timedelta(seconds=self._config.freshness_seconds),
            evidence=(evidence, projection_evidence),
            epistemic_status=ProjectionEpistemicStatus.UNKNOWN,
            uncertainty_summary=(
                "Source bytes and external redaction are verified; domain significance "
                "and upstream snapshot immutability are not."
            ),
            conflict_refs=(),
            compatibility_digest=content_digest(
                {
                    "adapter_version": _ADAPTER_VERSION,
                    "schema": _PROJECTION_SCHEMA,
                    "source_envelope_contract": _SOURCE_ENVELOPE_CONTRACT,
                }
            ),
        )
        return TrustedObservationBundle(
            artifact=artifact,
            evidence=evidence,
            event=event,
            projection=projection,
        )

    def _register_atomically(
        self,
        observation_key: str,
        trace_id: str,
        raw_digest: str,
        body: bytes,
        bundle: TrustedObservationBundle,
    ) -> None:
        projection_artifact = bundle.projection.projection_artifact
        projection_bytes = canonical_json(
            {
                "kind": "data-agent-external-report-metadata-projection",
                "version": 1,
                "source_identity": self._stable_identity(trace_id, raw_digest),
                "source_artifact_id": bundle.artifact.artifact_id,
                "source_content_digest": raw_digest,
                "authority": "none",
            }
        ).encode("utf-8")
        pending_artifacts = {
            bundle.artifact.artifact_id: (bundle.artifact, bytes(body)),
            projection_artifact.artifact_id: (
                projection_artifact,
                projection_bytes,
            ),
        }
        pending_evidence = {
            item.evidence_id: item
            for item in (*bundle.event.evidence, *bundle.projection.evidence)
        }
        for key, value in pending_artifacts.items():
            if key in self._artifacts and self._artifacts[key] != value:
                raise DataAgentReportConflict("trusted artifact identity conflict")
        for key, value in pending_evidence.items():
            if key in self._evidence and self._evidence[key] != value:
                raise DataAgentReportConflict("trusted evidence identity conflict")
        existing_event = self._events.get(bundle.event.environment_event_id)
        if existing_event is not None and existing_event != bundle.event:
            raise DataAgentReportConflict("trusted event identity conflict")
        existing_projection = self._projections.get(bundle.projection.projection_id)
        if existing_projection is not None and existing_projection != bundle.projection:
            raise DataAgentReportConflict("trusted projection identity conflict")
        self._artifacts.update(pending_artifacts)
        self._evidence.update(pending_evidence)
        self._events[bundle.event.environment_event_id] = bundle.event
        self._projections[bundle.projection.projection_id] = bundle.projection
        self._digests_by_observation[observation_key] = raw_digest
        self._bundles_by_observation[observation_key] = bundle

    def binding_is_authorized(self, binding: SituationalBinding) -> bool:
        return binding == self._binding

    def resolve_artifact(self, artifact_id: str) -> tuple[ArtifactRef, bytes] | None:
        with self._registry_lock:
            return self._artifacts.get(artifact_id)

    def resolve_evidence(self, evidence_id: str) -> EvidenceRef | None:
        with self._registry_lock:
            return self._evidence.get(evidence_id)

    def resolve_event(self, event_id: str) -> EnvironmentEvent | None:
        with self._registry_lock:
            return self._events.get(event_id)

    def resolve_projection(
        self, projection_id: str
    ) -> OperationalProjectionRef | None:
        with self._registry_lock:
            return self._projections.get(projection_id)
