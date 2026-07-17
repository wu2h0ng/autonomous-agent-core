from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from queue import Queue
from types import MappingProxyType
from threading import RLock, Thread
from typing import Callable, Mapping, Protocol, TypedDict
from urllib.parse import SplitResult, quote, urlsplit, urlunsplit

from agent_os_contracts import (
    ArtifactRef,
    CredentialAuthorizationSnapshot,
    CredentialRef,
    CredentialStatus,
    EnvironmentEvent,
    EvidenceRef,
    OperationalProjectionRef,
    canonical_json,
    content_digest,
)
from agent_os_core import (
    CanonicalCredentialAuthorizationReader,
    CredentialAuthorizationReader,
    EnvCredentialBroker,
    SituationalBinding,
)
from apps.api_server.data_agent_report_policy import (
    ADAPTER_VERSION as _ADAPTER_VERSION,
    CREDENTIAL_PROVIDER as _CREDENTIAL_PROVIDER,
    PROJECTION_SCHEMA as _PROJECTION_SCHEMA,
    SOURCE_ENVELOPE_CONTRACT as _SOURCE_ENVELOPE_CONTRACT,
    DataAgentReportEnvelopePolicy,
    DataAgentReportPolicyConfig,
    DataAgentReportPolicyDescriptor,
    DataAgentReportPolicyError,
)


Clock = Callable[[], datetime]
_TRACE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class _DataAgentReportFeedEvent(TypedDict):
    cursor: str
    trace_id: str
    content_sha256: str
    report: dict[str, object]


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
    def fetch(
        self, request: DataAgentReportHttpRequest
    ) -> DataAgentReportHttpResponse: ...


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
            raise DataAgentReportAdapterError("external report total deadline exceeded")
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
            raise DataAgentReportAdapterError(
                "source configuration fields cannot be empty"
            )
        if self.timeout_seconds <= 0:
            raise DataAgentReportAdapterError("timeout must be positive")
        if self.max_response_bytes <= 0:
            raise DataAgentReportAdapterError("response size limit must be positive")
        if self.freshness_seconds <= 0:
            raise DataAgentReportAdapterError("freshness window must be positive")
        if (
            not _TRACE_ID.fullmatch(self.source_tenant_id)
            or ".." in self.source_tenant_id
        ):
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


@dataclass(frozen=True)
class DataAgentReportDispatch:
    dispatch_id: str
    dispatch_digest: str
    namespace_digest: str
    source_id: str
    source_tenant_id: str
    principal_id: str
    tenant_id: str
    workspace_id: str
    mandate_id: str
    environment_binding_id: str
    environment_event_id: str
    projection_id: str
    bundle_digest: str
    status: str
    outcome_kind: str | None = None
    outcome_digest: str | None = None
    completed_at: datetime | None = None
    consumer_id: str | None = None
    authority_snapshot_digest: str | None = None
    completion_digest: str | None = None
    activation_authorized: bool = False
    capability_grant_authorized: bool = False
    external_effects_authorized: bool = False


@dataclass(frozen=True)
class DataAgentReportStoredObservation:
    observation_key: str
    report_trace_id: str
    revision_digest: str
    raw_digest: str
    body: bytes
    bundle: TrustedObservationBundle


class DataAgentReportStateStore(Protocol):
    durable: bool

    def get(
        self,
        namespace_digest: str,
        source_id: str,
        source_tenant_id: str,
        observation_key: str,
    ) -> DataAgentReportStoredObservation | None: ...

    def get_by_object_id(
        self,
        namespace_digest: str,
        source_id: str,
        source_tenant_id: str,
        *,
        object_kind: str,
        object_id: str,
    ) -> DataAgentReportStoredObservation | None: ...

    def save(
        self,
        namespace_digest: str,
        source_id: str,
        source_tenant_id: str,
        observation_key: str,
        report_trace_id: str,
        revision_digest: str,
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

    def stage_feed_dispatches(
        self,
        namespace_digest: str,
        source_id: str,
        source_tenant_id: str,
        *,
        expected_cursor: str | None,
        next_cursor: str | None,
        consumed_cursors: tuple[str, ...],
        dispatches: tuple[DataAgentReportDispatch, ...],
    ) -> bool: ...

    def list_dispatches(
        self,
        namespace_digest: str,
        source_id: str,
        source_tenant_id: str,
        *,
        status: str,
    ) -> tuple[DataAgentReportDispatch, ...]: ...

    def complete_dispatch(
        self,
        dispatch: DataAgentReportDispatch,
        *,
        outcome_kind: str,
        outcome_digest: str,
        completed_at: datetime,
        consumer_id: str,
        authority_snapshot_digest: str,
    ) -> DataAgentReportDispatch: ...

    def get_dispatch(
        self,
        namespace_digest: str,
        dispatch_id: str,
    ) -> DataAgentReportDispatch | None: ...


class SQLiteDataAgentReportStateStore:
    """Durable first-seen identity and exact-byte store shared across processes."""

    durable = True
    _SCHEMA_VERSION = 4
    _SCHEMA_COMPONENT = "data-agent-report-adapter"
    _OBJECT_KINDS = frozenset({"artifact", "evidence", "event", "projection"})

    def __init__(self, database: str | Path) -> None:
        self._database = str(database)
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                schema_version = self._create_schema(connection)
                if schema_version != self._SCHEMA_VERSION:
                    self._migrate_legacy_rows(connection)
                self._write_schema_version(connection)
        except DataAgentReportAdapterError:
            raise
        except sqlite3.Error:
            raise DataAgentReportAdapterError(
                "durable external report state schema is unavailable"
            ) from None

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database, timeout=10)
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    @staticmethod
    def _body_bytes(value: object) -> bytes:
        if not isinstance(value, (bytes, bytearray, memoryview)):
            raise DataAgentReportAdapterError(
                "durable external report body encoding is invalid"
            )
        return bytes(value)

    @staticmethod
    def _table_contract(
        connection: sqlite3.Connection,
        table: str,
    ) -> dict[str, tuple[str, int, int]]:
        return {
            str(row[1]): (str(row[2]).upper(), int(row[3]), int(row[5]))
            for row in connection.execute(f"PRAGMA table_info({table})")
        }

    @staticmethod
    def _require_table_contract(
        actual: dict[str, tuple[str, int, int]],
        expected: dict[str, tuple[str, int, int]],
    ) -> None:
        if actual != expected:
            raise DataAgentReportAdapterError(
                "durable external report state schema is invalid"
            )

    @classmethod
    def _create_schema(cls, connection: sqlite3.Connection) -> int | None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS data_agent_report_schema_metadata (
                component TEXT NOT NULL PRIMARY KEY,
                schema_version INTEGER NOT NULL
            )
            """
        )
        cls._require_table_contract(
            cls._table_contract(connection, "data_agent_report_schema_metadata"),
            {
                "component": ("TEXT", 1, 1),
                "schema_version": ("INTEGER", 1, 0),
            },
        )
        version_row = connection.execute(
            """
            SELECT schema_version FROM data_agent_report_schema_metadata
            WHERE component = ?
            """,
            (cls._SCHEMA_COMPONENT,),
        ).fetchone()
        schema_version: int | None = None
        if version_row is not None:
            if (
                not isinstance(version_row[0], int)
                or isinstance(version_row[0], bool)
                or int(version_row[0]) < 1
                or int(version_row[0]) > cls._SCHEMA_VERSION
            ):
                raise DataAgentReportAdapterError(
                    "durable external report state schema is unsupported"
                )
            schema_version = int(version_row[0])
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS data_agent_report_observations (
                namespace_digest TEXT NOT NULL,
                source_id TEXT NOT NULL,
                source_tenant_id TEXT NOT NULL,
                trace_id TEXT NOT NULL,
                report_trace_id TEXT,
                revision_digest TEXT,
                event_id TEXT,
                projection_id TEXT,
                raw_digest TEXT NOT NULL,
                body BLOB NOT NULL,
                bundle_json TEXT NOT NULL,
                PRIMARY KEY (namespace_digest, trace_id)
            )
            """
        )
        columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(data_agent_report_observations)"
            )
        }
        required_columns = {
            "namespace_digest",
            "source_id",
            "source_tenant_id",
            "trace_id",
            "raw_digest",
            "body",
            "bundle_json",
        }
        if not required_columns.issubset(columns):
            raise DataAgentReportAdapterError(
                "durable external report state schema is invalid"
            )
        for column in (
            "report_trace_id",
            "revision_digest",
            "event_id",
            "projection_id",
        ):
            if column not in columns:
                connection.execute(
                    f"ALTER TABLE data_agent_report_observations ADD COLUMN {column} TEXT"
                )
        cls._require_table_contract(
            cls._table_contract(connection, "data_agent_report_observations"),
            {
                "namespace_digest": ("TEXT", 1, 1),
                "source_id": ("TEXT", 1, 0),
                "source_tenant_id": ("TEXT", 1, 0),
                "trace_id": ("TEXT", 1, 2),
                "report_trace_id": ("TEXT", 0, 0),
                "revision_digest": ("TEXT", 0, 0),
                "event_id": ("TEXT", 0, 0),
                "projection_id": ("TEXT", 0, 0),
                "raw_digest": ("TEXT", 1, 0),
                "body": ("BLOB", 1, 0),
                "bundle_json": ("TEXT", 1, 0),
            },
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS data_agent_report_bundle_index (
                namespace_digest TEXT NOT NULL,
                source_id TEXT NOT NULL,
                source_tenant_id TEXT NOT NULL,
                object_kind TEXT NOT NULL,
                object_id TEXT NOT NULL,
                observation_key TEXT NOT NULL,
                report_trace_id TEXT NOT NULL,
                revision_digest TEXT NOT NULL,
                PRIMARY KEY (namespace_digest, object_kind, object_id)
            )
            """
        )
        cls._require_table_contract(
            cls._table_contract(connection, "data_agent_report_bundle_index"),
            {
                "namespace_digest": ("TEXT", 1, 1),
                "source_id": ("TEXT", 1, 0),
                "source_tenant_id": ("TEXT", 1, 0),
                "object_kind": ("TEXT", 1, 2),
                "object_id": ("TEXT", 1, 3),
                "observation_key": ("TEXT", 1, 0),
                "report_trace_id": ("TEXT", 1, 0),
                "revision_digest": ("TEXT", 1, 0),
            },
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS data_agent_report_event_ids
            ON data_agent_report_observations(namespace_digest, event_id)
            WHERE event_id IS NOT NULL
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS data_agent_report_projection_ids
            ON data_agent_report_observations(namespace_digest, projection_id)
            WHERE projection_id IS NOT NULL
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
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS data_agent_report_feed_cursor_history (
                namespace_digest TEXT NOT NULL,
                source_id TEXT NOT NULL,
                source_tenant_id TEXT NOT NULL,
                cursor TEXT NOT NULL,
                PRIMARY KEY (
                    namespace_digest, source_id, source_tenant_id, cursor
                )
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS data_agent_report_dispatch_outbox (
                dispatch_id TEXT NOT NULL PRIMARY KEY,
                dispatch_digest TEXT NOT NULL,
                namespace_digest TEXT NOT NULL,
                source_id TEXT NOT NULL,
                source_tenant_id TEXT NOT NULL,
                principal_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                mandate_id TEXT NOT NULL,
                environment_binding_id TEXT NOT NULL,
                environment_event_id TEXT NOT NULL,
                projection_id TEXT NOT NULL,
                bundle_digest TEXT NOT NULL,
                status TEXT NOT NULL,
                outcome_kind TEXT,
                outcome_digest TEXT,
                completed_at TEXT,
                consumer_id TEXT,
                authority_snapshot_digest TEXT,
                completion_digest TEXT,
                activation_authorized INTEGER NOT NULL,
                capability_grant_authorized INTEGER NOT NULL,
                external_effects_authorized INTEGER NOT NULL
            )
            """
        )
        outbox_columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(data_agent_report_dispatch_outbox)"
            )
        }
        for column in (
            "consumer_id",
            "authority_snapshot_digest",
            "completion_digest",
        ):
            if column not in outbox_columns:
                connection.execute(
                    f"ALTER TABLE data_agent_report_dispatch_outbox ADD COLUMN {column} TEXT"
                )
        cls._require_table_contract(
            cls._table_contract(connection, "data_agent_report_dispatch_outbox"),
            {
                "dispatch_id": ("TEXT", 1, 1),
                "dispatch_digest": ("TEXT", 1, 0),
                "namespace_digest": ("TEXT", 1, 0),
                "source_id": ("TEXT", 1, 0),
                "source_tenant_id": ("TEXT", 1, 0),
                "principal_id": ("TEXT", 1, 0),
                "tenant_id": ("TEXT", 1, 0),
                "workspace_id": ("TEXT", 1, 0),
                "mandate_id": ("TEXT", 1, 0),
                "environment_binding_id": ("TEXT", 1, 0),
                "environment_event_id": ("TEXT", 1, 0),
                "projection_id": ("TEXT", 1, 0),
                "bundle_digest": ("TEXT", 1, 0),
                "status": ("TEXT", 1, 0),
                "outcome_kind": ("TEXT", 0, 0),
                "outcome_digest": ("TEXT", 0, 0),
                "completed_at": ("TEXT", 0, 0),
                "consumer_id": ("TEXT", 0, 0),
                "authority_snapshot_digest": ("TEXT", 0, 0),
                "completion_digest": ("TEXT", 0, 0),
                "activation_authorized": ("INTEGER", 1, 0),
                "capability_grant_authorized": ("INTEGER", 1, 0),
                "external_effects_authorized": ("INTEGER", 1, 0),
            },
        )
        return schema_version

    @classmethod
    def _write_schema_version(cls, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            INSERT INTO data_agent_report_schema_metadata (
                component, schema_version
            ) VALUES (?, ?)
            ON CONFLICT(component) DO UPDATE SET
                schema_version = excluded.schema_version
            """,
            (cls._SCHEMA_COMPONENT, cls._SCHEMA_VERSION),
        )

    @staticmethod
    def _legacy_report_trace_id(observation_key: str, raw_digest: str) -> str:
        if observation_key.startswith("trace:"):
            trace_id = observation_key.removeprefix("trace:")
        elif observation_key.startswith("feed:") and observation_key.endswith(
            f":{raw_digest}"
        ):
            trace_id = observation_key.removeprefix("feed:")[: -(len(raw_digest) + 1)]
        else:
            raise DataAgentReportAdapterError(
                "durable external report observation identity is invalid"
            )
        if not _TRACE_ID.fullmatch(trace_id) or ".." in trace_id:
            raise DataAgentReportAdapterError(
                "durable external report trace identity is invalid"
            )
        return trace_id

    @staticmethod
    def _object_ids(bundle: TrustedObservationBundle) -> dict[str, tuple[str, ...]]:
        evidence = {
            item.evidence_id: item
            for item in (*bundle.event.evidence, *bundle.projection.evidence)
        }
        if any(
            item.evidence_id in evidence and evidence[item.evidence_id] != item
            for item in (*bundle.event.evidence, *bundle.projection.evidence)
        ):
            raise DataAgentReportAdapterError(
                "durable external report evidence identity is invalid"
            )
        return {
            "artifact": (
                bundle.artifact.artifact_id,
                bundle.projection.projection_artifact.artifact_id,
            ),
            "evidence": tuple(sorted(evidence)),
            "event": (bundle.event.environment_event_id,),
            "projection": (bundle.projection.projection_id,),
        }

    @classmethod
    def _validate_stored_observation(
        cls,
        *,
        observation_key: str,
        report_trace_id: str,
        revision_digest: str,
        raw_digest: str,
        body: bytes,
        bundle: TrustedObservationBundle,
    ) -> None:
        if (
            re.fullmatch(r"[0-9a-f]{64}", raw_digest) is None
            or revision_digest != raw_digest
            or hashlib.sha256(body).hexdigest() != raw_digest
        ):
            raise DataAgentReportAdapterError(
                "durable external report revision digest is invalid"
            )
        expected_trace = cls._legacy_report_trace_id(observation_key, raw_digest)
        if report_trace_id != expected_trace:
            raise DataAgentReportAdapterError(
                "durable external report trace binding is invalid"
            )
        if bundle.artifact.content_digest != raw_digest:
            raise DataAgentReportAdapterError(
                "durable external report artifact digest is invalid"
            )
        if bundle.event.observation != bundle.artifact:
            raise DataAgentReportAdapterError(
                "durable external report event artifact binding is invalid"
            )
        if bundle.projection.source_event_ids != (bundle.event.environment_event_id,):
            raise DataAgentReportAdapterError(
                "durable external report projection event binding is invalid"
            )
        if bundle.evidence not in bundle.event.evidence:
            raise DataAgentReportAdapterError(
                "durable external report evidence binding is invalid"
            )

    @classmethod
    def _insert_index_rows(
        cls,
        connection: sqlite3.Connection,
        *,
        namespace_digest: str,
        source_id: str,
        source_tenant_id: str,
        observation_key: str,
        report_trace_id: str,
        revision_digest: str,
        bundle: TrustedObservationBundle,
    ) -> None:
        for object_kind, object_ids in cls._object_ids(bundle).items():
            for object_id in object_ids:
                existing = connection.execute(
                    """
                    SELECT source_id, source_tenant_id, observation_key,
                           report_trace_id, revision_digest
                    FROM data_agent_report_bundle_index
                    WHERE namespace_digest = ? AND object_kind = ? AND object_id = ?
                    """,
                    (namespace_digest, object_kind, object_id),
                ).fetchone()
                expected = (
                    source_id,
                    source_tenant_id,
                    observation_key,
                    report_trace_id,
                    revision_digest,
                )
                if existing is not None:
                    if tuple(str(value) for value in existing) != expected:
                        raise DataAgentReportConflict(
                            "durable external report object identity conflict"
                        )
                    continue
                connection.execute(
                    """
                    INSERT INTO data_agent_report_bundle_index (
                        namespace_digest, source_id, source_tenant_id,
                        object_kind, object_id, observation_key,
                        report_trace_id, revision_digest
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        namespace_digest,
                        source_id,
                        source_tenant_id,
                        object_kind,
                        object_id,
                        observation_key,
                        report_trace_id,
                        revision_digest,
                    ),
                )

    @classmethod
    def _migrate_legacy_rows(cls, connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            """
            SELECT namespace_digest, source_id, source_tenant_id, trace_id,
                   report_trace_id, revision_digest, event_id, projection_id,
                   raw_digest, body, bundle_json
            FROM data_agent_report_observations
            """
        ).fetchall()
        expected_index_rows: set[tuple[str, ...]] = set()
        for row in rows:
            observation_key = str(row[3])
            raw_digest = str(row[8])
            body = cls._body_bytes(row[9])
            payload = str(row[10])
            bundle = cls._deserialize(payload)
            if cls._serialize(bundle) != payload:
                raise DataAgentReportAdapterError(
                    "durable external report bundle encoding is invalid"
                )
            inferred_trace = cls._legacy_report_trace_id(observation_key, raw_digest)
            report_trace_id = str(row[4]) if row[4] is not None else inferred_trace
            revision_digest = str(row[5]) if row[5] is not None else raw_digest
            event_id = bundle.event.environment_event_id
            projection_id = bundle.projection.projection_id
            if row[6] is not None and str(row[6]) != event_id:
                raise DataAgentReportAdapterError(
                    "durable external report event index is invalid"
                )
            if row[7] is not None and str(row[7]) != projection_id:
                raise DataAgentReportAdapterError(
                    "durable external report projection index is invalid"
                )
            cls._validate_stored_observation(
                observation_key=observation_key,
                report_trace_id=report_trace_id,
                revision_digest=revision_digest,
                raw_digest=raw_digest,
                body=body,
                bundle=bundle,
            )
            connection.execute(
                """
                UPDATE data_agent_report_observations
                SET report_trace_id = ?, revision_digest = ?,
                    event_id = ?, projection_id = ?
                WHERE namespace_digest = ? AND trace_id = ?
                """,
                (
                    report_trace_id,
                    revision_digest,
                    event_id,
                    projection_id,
                    str(row[0]),
                    observation_key,
                ),
            )
            cls._insert_index_rows(
                connection,
                namespace_digest=str(row[0]),
                source_id=str(row[1]),
                source_tenant_id=str(row[2]),
                observation_key=observation_key,
                report_trace_id=report_trace_id,
                revision_digest=revision_digest,
                bundle=bundle,
            )
            for object_kind, object_ids in cls._object_ids(bundle).items():
                expected_index_rows.update(
                    (
                        str(row[0]),
                        str(row[1]),
                        str(row[2]),
                        object_kind,
                        object_id,
                        observation_key,
                        report_trace_id,
                        revision_digest,
                    )
                    for object_id in object_ids
                )
        actual_index_rows = {
            tuple(str(value) for value in row)
            for row in connection.execute(
                """
                SELECT namespace_digest, source_id, source_tenant_id,
                       object_kind, object_id, observation_key,
                       report_trace_id, revision_digest
                FROM data_agent_report_bundle_index
                """
            )
        }
        if actual_index_rows != expected_index_rows:
            raise DataAgentReportAdapterError(
                "durable external report object index is invalid"
            )

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
                projection=OperationalProjectionRef.model_validate(
                    parsed["projection"]
                ),
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
        observation_key: str,
    ) -> DataAgentReportStoredObservation | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT report_trace_id, revision_digest, event_id, projection_id,
                       raw_digest, body, bundle_json
                FROM data_agent_report_observations
                WHERE namespace_digest = ?
                  AND source_id = ? AND source_tenant_id = ? AND trace_id = ?
                """,
                (namespace_digest, source_id, source_tenant_id, observation_key),
            ).fetchone()
        if row is None:
            return None
        return self._read_observation(observation_key, row)

    def get_by_object_id(
        self,
        namespace_digest: str,
        source_id: str,
        source_tenant_id: str,
        *,
        object_kind: str,
        object_id: str,
    ) -> DataAgentReportStoredObservation | None:
        if object_kind not in self._OBJECT_KINDS:
            raise DataAgentReportAdapterError(
                "durable external report object kind is invalid"
            )
        with self._connect() as connection:
            index_rows = connection.execute(
                """
                SELECT source_id, source_tenant_id, observation_key,
                       report_trace_id, revision_digest
                FROM data_agent_report_bundle_index
                WHERE namespace_digest = ? AND object_kind = ? AND object_id = ?
                """,
                (
                    namespace_digest,
                    object_kind,
                    object_id,
                ),
            ).fetchall()
            if not index_rows:
                return None
            if len(index_rows) != 1:
                raise DataAgentReportAdapterError(
                    "durable external report object index is ambiguous"
                )
            index_row = index_rows[0]
            if (str(index_row[0]), str(index_row[1])) != (
                source_id,
                source_tenant_id,
            ):
                raise DataAgentReportAdapterError(
                    "durable external report object index scope is invalid"
                )
            observation_key = str(index_row[2])
            observation_row = connection.execute(
                """
                SELECT report_trace_id, revision_digest, event_id, projection_id,
                       raw_digest, body, bundle_json
                FROM data_agent_report_observations
                WHERE namespace_digest = ? AND source_id = ?
                  AND source_tenant_id = ? AND trace_id = ?
                """,
                (
                    namespace_digest,
                    source_id,
                    source_tenant_id,
                    observation_key,
                ),
            ).fetchone()
            if observation_row is not None and observation_key.startswith("feed:"):
                committed = connection.execute(
                    """
                    SELECT 1 FROM data_agent_report_dispatch_outbox
                    WHERE namespace_digest = ? AND source_id = ?
                      AND source_tenant_id = ? AND environment_event_id = ?
                      AND projection_id = ?
                    """,
                    (
                        namespace_digest,
                        source_id,
                        source_tenant_id,
                        str(observation_row[2]),
                        str(observation_row[3]),
                    ),
                ).fetchone()
                if committed is None:
                    return None
        if observation_row is None:
            raise DataAgentReportAdapterError(
                "durable external report object index target is unavailable"
            )
        stored = self._read_observation(observation_key, observation_row)
        if stored.report_trace_id != str(index_row[3]) or stored.revision_digest != str(
            index_row[4]
        ):
            raise DataAgentReportAdapterError(
                "durable external report object index binding is invalid"
            )
        if object_id not in self._object_ids(stored.bundle)[object_kind]:
            raise DataAgentReportAdapterError(
                "durable external report object index target is invalid"
            )
        return stored

    @classmethod
    def _read_observation(
        cls,
        observation_key: str,
        row: tuple[object, ...],
    ) -> DataAgentReportStoredObservation:
        if row[0] is None or row[1] is None:
            raise DataAgentReportAdapterError(
                "durable external report state migration is incomplete"
            )
        payload = str(row[6])
        bundle = cls._deserialize(payload)
        if cls._serialize(bundle) != payload:
            raise DataAgentReportAdapterError(
                "durable external report bundle encoding is invalid"
            )
        stored = DataAgentReportStoredObservation(
            observation_key=observation_key,
            report_trace_id=str(row[0]),
            revision_digest=str(row[1]),
            raw_digest=str(row[4]),
            body=cls._body_bytes(row[5]),
            bundle=bundle,
        )
        if str(row[2]) != bundle.event.environment_event_id:
            raise DataAgentReportAdapterError(
                "durable external report event index is invalid"
            )
        if str(row[3]) != bundle.projection.projection_id:
            raise DataAgentReportAdapterError(
                "durable external report projection index is invalid"
            )
        cls._validate_stored_observation(
            observation_key=stored.observation_key,
            report_trace_id=stored.report_trace_id,
            revision_digest=stored.revision_digest,
            raw_digest=stored.raw_digest,
            body=stored.body,
            bundle=stored.bundle,
        )
        return stored

    def save(
        self,
        namespace_digest: str,
        source_id: str,
        source_tenant_id: str,
        observation_key: str,
        report_trace_id: str,
        revision_digest: str,
        raw_digest: str,
        body: bytes,
        bundle: TrustedObservationBundle,
    ) -> None:
        serialized = self._serialize(bundle)
        self._validate_stored_observation(
            observation_key=observation_key,
            report_trace_id=report_trace_id,
            revision_digest=revision_digest,
            raw_digest=raw_digest,
            body=body,
            bundle=bundle,
        )
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    """
                    SELECT report_trace_id, revision_digest, raw_digest, body, bundle_json
                    FROM data_agent_report_observations
                    WHERE namespace_digest = ?
                      AND source_id = ? AND source_tenant_id = ? AND trace_id = ?
                    """,
                    (namespace_digest, source_id, source_tenant_id, observation_key),
                ).fetchone()
                if existing is None:
                    connection.execute(
                        """
                        INSERT INTO data_agent_report_observations (
                            namespace_digest, source_id, source_tenant_id, trace_id,
                            report_trace_id, revision_digest, event_id, projection_id,
                            raw_digest, body, bundle_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            namespace_digest,
                            source_id,
                            source_tenant_id,
                            observation_key,
                            report_trace_id,
                            revision_digest,
                            bundle.event.environment_event_id,
                            bundle.projection.projection_id,
                            raw_digest,
                            sqlite3.Binary(body),
                            serialized,
                        ),
                    )
                elif (
                    str(existing[0]) != report_trace_id
                    or str(existing[1]) != revision_digest
                    or str(existing[2]) != raw_digest
                    or self._body_bytes(existing[3]) != body
                    or str(existing[4]) != serialized
                ):
                    raise DataAgentReportConflict(
                        "durable external report identity conflict"
                    )
                self._insert_index_rows(
                    connection,
                    namespace_digest=namespace_digest,
                    source_id=source_id,
                    source_tenant_id=source_tenant_id,
                    observation_key=observation_key,
                    report_trace_id=report_trace_id,
                    revision_digest=revision_digest,
                    bundle=bundle,
                )
        except DataAgentReportConflict:
            raise
        except sqlite3.IntegrityError:
            raise DataAgentReportConflict(
                "durable external report object identity conflict"
            ) from None
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
                if next_cursor is not None and next_cursor != expected_cursor:
                    seen = connection.execute(
                        """
                        SELECT 1 FROM data_agent_report_feed_cursor_history
                        WHERE namespace_digest = ? AND source_id = ?
                          AND source_tenant_id = ? AND cursor = ?
                        """,
                        (
                            namespace_digest,
                            source_id,
                            source_tenant_id,
                            next_cursor,
                        ),
                    ).fetchone()
                    if seen is not None:
                        raise DataAgentReportConflict(
                            "external report feed cursor was already consumed"
                        )
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
                if next_cursor is not None and next_cursor != expected_cursor:
                    connection.execute(
                        """
                        INSERT INTO data_agent_report_feed_cursor_history (
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
                return True
        except DataAgentReportConflict:
            raise
        except sqlite3.Error:
            raise DataAgentReportAdapterError(
                "durable external report cursor state is unavailable"
            ) from None

    @staticmethod
    def _dispatch_payload(dispatch: DataAgentReportDispatch) -> dict[str, object]:
        return {
            "namespace_digest": dispatch.namespace_digest,
            "source_id": dispatch.source_id,
            "source_tenant_id": dispatch.source_tenant_id,
            "principal_id": dispatch.principal_id,
            "tenant_id": dispatch.tenant_id,
            "workspace_id": dispatch.workspace_id,
            "mandate_id": dispatch.mandate_id,
            "environment_binding_id": dispatch.environment_binding_id,
            "environment_event_id": dispatch.environment_event_id,
            "projection_id": dispatch.projection_id,
            "bundle_digest": dispatch.bundle_digest,
            "activation_authorized": False,
            "capability_grant_authorized": False,
            "external_effects_authorized": False,
        }

    @classmethod
    def _validate_dispatch(cls, dispatch: DataAgentReportDispatch) -> None:
        digest = content_digest(cls._dispatch_payload(dispatch))
        if (
            dispatch.dispatch_id != f"data-agent-dispatch:{digest}"
            or dispatch.dispatch_digest != digest
            or dispatch.status not in {"PENDING", "COMPLETED"}
            or dispatch.activation_authorized
            or dispatch.capability_grant_authorized
            or dispatch.external_effects_authorized
        ):
            raise DataAgentReportAdapterError(
                "durable external report dispatch binding is invalid"
            )
        if dispatch.status == "PENDING":
            if any(
                value is not None
                for value in (
                    dispatch.outcome_kind,
                    dispatch.outcome_digest,
                    dispatch.completed_at,
                    dispatch.consumer_id,
                    dispatch.authority_snapshot_digest,
                    dispatch.completion_digest,
                )
            ):
                raise DataAgentReportAdapterError(
                    "durable external report dispatch state is invalid"
                )
        elif (
            dispatch.outcome_kind not in {"TASK_DRAFT", "HELP_REQUEST", "NO_PROPOSAL"}
            or dispatch.outcome_digest is None
            or re.fullmatch(r"[0-9a-f]{64}", dispatch.outcome_digest) is None
            or dispatch.completed_at is None
            or dispatch.consumer_id is None
            or not dispatch.consumer_id.strip()
            or dispatch.authority_snapshot_digest is None
            or re.fullmatch(r"[0-9a-f]{64}", dispatch.authority_snapshot_digest) is None
            or dispatch.completion_digest
            != content_digest(
                {
                    "dispatch_id": dispatch.dispatch_id,
                    "dispatch_digest": dispatch.dispatch_digest,
                    "outcome_kind": dispatch.outcome_kind,
                    "outcome_digest": dispatch.outcome_digest,
                    "completed_at": dispatch.completed_at,
                    "consumer_id": dispatch.consumer_id,
                    "authority_snapshot_digest": (dispatch.authority_snapshot_digest),
                }
            )
        ):
            raise DataAgentReportAdapterError(
                "durable external report dispatch state is invalid"
            )

    @classmethod
    def _dispatch_from_row(cls, row: tuple[object, ...]) -> DataAgentReportDispatch:
        completed_at: datetime | None = None
        if row[16] is not None:
            try:
                completed_at = _utc(datetime.fromisoformat(str(row[16])))
            except (TypeError, ValueError):
                raise DataAgentReportAdapterError(
                    "durable external report dispatch timestamp is invalid"
                ) from None
        try:
            dispatch = DataAgentReportDispatch(
                dispatch_id=str(row[0]),
                dispatch_digest=str(row[1]),
                namespace_digest=str(row[2]),
                source_id=str(row[3]),
                source_tenant_id=str(row[4]),
                principal_id=str(row[5]),
                tenant_id=str(row[6]),
                workspace_id=str(row[7]),
                mandate_id=str(row[8]),
                environment_binding_id=str(row[9]),
                environment_event_id=str(row[10]),
                projection_id=str(row[11]),
                bundle_digest=str(row[12]),
                status=str(row[13]),
                outcome_kind=None if row[14] is None else str(row[14]),
                outcome_digest=None if row[15] is None else str(row[15]),
                completed_at=completed_at,
                consumer_id=None if row[17] is None else str(row[17]),
                authority_snapshot_digest=(None if row[18] is None else str(row[18])),
                completion_digest=None if row[19] is None else str(row[19]),
                activation_authorized=bool(row[20]),
                capability_grant_authorized=bool(row[21]),
                external_effects_authorized=bool(row[22]),
            )
        except (TypeError, ValueError):
            raise DataAgentReportAdapterError(
                "durable external report dispatch encoding is invalid"
            ) from None
        if any(
            type(row[index]) is not int or row[index] != 0 for index in (20, 21, 22)
        ):
            raise DataAgentReportAdapterError(
                "durable external report dispatch authority is invalid"
            )
        cls._validate_dispatch(dispatch)
        return dispatch

    @staticmethod
    def _dispatch_select() -> str:
        return """
            SELECT dispatch_id, dispatch_digest, namespace_digest, source_id,
                   source_tenant_id, principal_id, tenant_id, workspace_id,
                   mandate_id, environment_binding_id, environment_event_id,
                   projection_id, bundle_digest, status, outcome_kind,
                   outcome_digest, completed_at, consumer_id,
                   authority_snapshot_digest, completion_digest,
                   activation_authorized,
                   capability_grant_authorized, external_effects_authorized
            FROM data_agent_report_dispatch_outbox
        """

    def _validate_dispatch_observation(
        self,
        connection: sqlite3.Connection,
        dispatch: DataAgentReportDispatch,
    ) -> None:
        observation = connection.execute(
            """
            SELECT bundle_json FROM data_agent_report_observations
            WHERE namespace_digest = ? AND source_id = ?
              AND source_tenant_id = ? AND event_id = ? AND projection_id = ?
            """,
            (
                dispatch.namespace_digest,
                dispatch.source_id,
                dispatch.source_tenant_id,
                dispatch.environment_event_id,
                dispatch.projection_id,
            ),
        ).fetchone()
        if observation is None:
            raise DataAgentReportAdapterError(
                "durable external report dispatch observation is unavailable"
            )
        bundle = self._deserialize(str(observation[0]))
        if (
            bundle.event.environment_event_id != dispatch.environment_event_id
            or bundle.event.tenant_id != dispatch.tenant_id
            or bundle.event.workspace_id != dispatch.workspace_id
            or bundle.event.mandate_id != dispatch.mandate_id
            or bundle.event.environment_binding_id != dispatch.environment_binding_id
            or bundle.projection.projection_id != dispatch.projection_id
            or content_digest({"event": bundle.event, "projection": bundle.projection})
            != dispatch.bundle_digest
        ):
            raise DataAgentReportAdapterError(
                "durable external report dispatch bundle is invalid"
            )

    def stage_feed_dispatches(
        self,
        namespace_digest: str,
        source_id: str,
        source_tenant_id: str,
        *,
        expected_cursor: str | None,
        next_cursor: str | None,
        consumed_cursors: tuple[str, ...],
        dispatches: tuple[DataAgentReportDispatch, ...],
    ) -> bool:
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                cursor_row = connection.execute(
                    """
                    SELECT cursor FROM data_agent_report_feed_cursors
                    WHERE namespace_digest = ? AND source_id = ?
                      AND source_tenant_id = ?
                    """,
                    (namespace_digest, source_id, source_tenant_id),
                ).fetchone()
                current = (
                    str(cursor_row[0])
                    if cursor_row is not None and cursor_row[0] is not None
                    else None
                )
                if current != expected_cursor:
                    return False
                for consumed_cursor in consumed_cursors:
                    seen = connection.execute(
                        """
                        SELECT 1 FROM data_agent_report_feed_cursor_history
                        WHERE namespace_digest = ? AND source_id = ?
                          AND source_tenant_id = ? AND cursor = ?
                        """,
                        (
                            namespace_digest,
                            source_id,
                            source_tenant_id,
                            consumed_cursor,
                        ),
                    ).fetchone()
                    if seen is not None:
                        raise DataAgentReportConflict(
                            "external report feed cursor was already consumed"
                        )
                for dispatch in dispatches:
                    self._validate_dispatch(dispatch)
                    if (
                        dispatch.namespace_digest != namespace_digest
                        or dispatch.source_id != source_id
                        or dispatch.source_tenant_id != source_tenant_id
                        or dispatch.status != "PENDING"
                    ):
                        raise DataAgentReportAdapterError(
                            "durable external report dispatch scope is invalid"
                        )
                    self._validate_dispatch_observation(connection, dispatch)
                    connection.execute(
                        """
                        INSERT INTO data_agent_report_dispatch_outbox (
                            dispatch_id, dispatch_digest, namespace_digest,
                            source_id, source_tenant_id, principal_id, tenant_id,
                            workspace_id, mandate_id, environment_binding_id,
                            environment_event_id, projection_id, bundle_digest,
                            status, outcome_kind, outcome_digest, completed_at,
                            consumer_id, authority_snapshot_digest,
                            completion_digest,
                            activation_authorized, capability_grant_authorized,
                            external_effects_authorized
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                                  NULL, NULL, NULL, NULL, NULL, NULL, 0, 0, 0)
                        ON CONFLICT(dispatch_id) DO NOTHING
                        """,
                        (
                            dispatch.dispatch_id,
                            dispatch.dispatch_digest,
                            dispatch.namespace_digest,
                            dispatch.source_id,
                            dispatch.source_tenant_id,
                            dispatch.principal_id,
                            dispatch.tenant_id,
                            dispatch.workspace_id,
                            dispatch.mandate_id,
                            dispatch.environment_binding_id,
                            dispatch.environment_event_id,
                            dispatch.projection_id,
                            dispatch.bundle_digest,
                            dispatch.status,
                        ),
                    )
                    row = connection.execute(
                        self._dispatch_select() + " WHERE dispatch_id = ?",
                        (dispatch.dispatch_id,),
                    ).fetchone()
                    if row is None or self._dispatch_from_row(row) != dispatch:
                        raise DataAgentReportConflict(
                            "durable external report dispatch identity conflict"
                        )
                if cursor_row is None:
                    connection.execute(
                        """
                        INSERT INTO data_agent_report_feed_cursors (
                            namespace_digest, source_id, source_tenant_id, cursor
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (namespace_digest, source_id, source_tenant_id, next_cursor),
                    )
                else:
                    connection.execute(
                        """
                        UPDATE data_agent_report_feed_cursors SET cursor = ?
                        WHERE namespace_digest = ? AND source_id = ?
                          AND source_tenant_id = ?
                        """,
                        (next_cursor, namespace_digest, source_id, source_tenant_id),
                    )
                for consumed_cursor in consumed_cursors:
                    connection.execute(
                        """
                        INSERT INTO data_agent_report_feed_cursor_history (
                            namespace_digest, source_id, source_tenant_id, cursor
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (
                            namespace_digest,
                            source_id,
                            source_tenant_id,
                            consumed_cursor,
                        ),
                    )
                return True
        except DataAgentReportAdapterError:
            raise
        except sqlite3.Error:
            raise DataAgentReportAdapterError(
                "durable external report dispatch state is unavailable"
            ) from None

    def list_dispatches(
        self,
        namespace_digest: str,
        source_id: str,
        source_tenant_id: str,
        *,
        status: str,
    ) -> tuple[DataAgentReportDispatch, ...]:
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    self._dispatch_select()
                    + " WHERE namespace_digest = ? AND status = ? ORDER BY dispatch_id",
                    (namespace_digest, status),
                ).fetchall()
                dispatches = tuple(self._dispatch_from_row(row) for row in rows)
                for dispatch in dispatches:
                    self._validate_dispatch_observation(connection, dispatch)
        except sqlite3.Error:
            raise DataAgentReportAdapterError(
                "durable external report dispatch state is unavailable"
            ) from None
        if any(
            item.source_id != source_id
            or item.source_tenant_id != source_tenant_id
            or item.namespace_digest != namespace_digest
            for item in dispatches
        ):
            raise DataAgentReportAdapterError(
                "durable external report dispatch scope is invalid"
            )
        return dispatches

    def complete_dispatch(
        self,
        dispatch: DataAgentReportDispatch,
        *,
        outcome_kind: str,
        outcome_digest: str,
        completed_at: datetime,
        consumer_id: str,
        authority_snapshot_digest: str,
    ) -> DataAgentReportDispatch:
        self._validate_dispatch(dispatch)
        if dispatch.status != "PENDING":
            raise DataAgentReportAdapterError(
                "durable external report dispatch is not pending"
            )
        completion_payload = {
            "dispatch_id": dispatch.dispatch_id,
            "dispatch_digest": dispatch.dispatch_digest,
            "outcome_kind": outcome_kind,
            "outcome_digest": outcome_digest,
            "completed_at": _utc(completed_at),
            "consumer_id": consumer_id,
            "authority_snapshot_digest": authority_snapshot_digest,
        }
        completed = DataAgentReportDispatch(
            **{
                **dispatch.__dict__,
                "status": "COMPLETED",
                "outcome_kind": outcome_kind,
                "outcome_digest": outcome_digest,
                "completed_at": _utc(completed_at),
                "consumer_id": consumer_id,
                "authority_snapshot_digest": authority_snapshot_digest,
                "completion_digest": content_digest(completion_payload),
            }
        )
        self._validate_dispatch(completed)
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    self._dispatch_select() + " WHERE dispatch_id = ?",
                    (dispatch.dispatch_id,),
                ).fetchone()
                if row is None:
                    raise DataAgentReportAdapterError(
                        "durable external report dispatch is unavailable"
                    )
                current = self._dispatch_from_row(row)
                self._validate_dispatch_observation(connection, current)
                if current.status == "COMPLETED":
                    if current == completed:
                        return current
                    raise DataAgentReportConflict(
                        "durable external report dispatch completion conflict"
                    )
                if current != dispatch:
                    raise DataAgentReportConflict(
                        "durable external report dispatch changed concurrently"
                    )
                connection.execute(
                    """
                    UPDATE data_agent_report_dispatch_outbox
                    SET status = 'COMPLETED', outcome_kind = ?, outcome_digest = ?,
                        completed_at = ?, consumer_id = ?,
                        authority_snapshot_digest = ?, completion_digest = ?
                    WHERE dispatch_id = ? AND status = 'PENDING'
                    """,
                    (
                        outcome_kind,
                        outcome_digest,
                        _utc(completed_at).isoformat(),
                        consumer_id,
                        authority_snapshot_digest,
                        completed.completion_digest,
                        dispatch.dispatch_id,
                    ),
                )
                return completed
        except DataAgentReportAdapterError:
            raise
        except sqlite3.Error:
            raise DataAgentReportAdapterError(
                "durable external report dispatch state is unavailable"
            ) from None

    def get_dispatch(
        self,
        namespace_digest: str,
        dispatch_id: str,
    ) -> DataAgentReportDispatch | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    self._dispatch_select()
                    + " WHERE namespace_digest = ? AND dispatch_id = ?",
                    (namespace_digest, dispatch_id),
                ).fetchone()
                if row is None:
                    return None
                dispatch = self._dispatch_from_row(row)
                self._validate_dispatch_observation(connection, dispatch)
        except sqlite3.Error:
            raise DataAgentReportAdapterError(
                "durable external report dispatch state is unavailable"
            ) from None
        return dispatch


class _InMemoryDataAgentReportStateStore:
    durable = False

    def __init__(self) -> None:
        self._rows: dict[
            tuple[str, str, str, str], DataAgentReportStoredObservation
        ] = {}
        self._object_index: dict[tuple[str, str, str], tuple[str, str, str, str]] = {}
        self._feed_cursors: dict[tuple[str, str, str], str | None] = {}
        self._feed_cursor_history: set[tuple[str, str, str, str]] = set()
        self._dispatches: dict[str, DataAgentReportDispatch] = {}

    def get(
        self,
        namespace_digest: str,
        source_id: str,
        source_tenant_id: str,
        observation_key: str,
    ) -> DataAgentReportStoredObservation | None:
        return self._rows.get(
            (namespace_digest, source_id, source_tenant_id, observation_key)
        )

    def get_by_object_id(
        self,
        namespace_digest: str,
        source_id: str,
        source_tenant_id: str,
        *,
        object_kind: str,
        object_id: str,
    ) -> DataAgentReportStoredObservation | None:
        row_key = self._object_index.get((namespace_digest, object_kind, object_id))
        if row_key is None or row_key[1:3] != (source_id, source_tenant_id):
            return None
        return self._rows.get(row_key)

    def save(
        self,
        namespace_digest: str,
        source_id: str,
        source_tenant_id: str,
        observation_key: str,
        report_trace_id: str,
        revision_digest: str,
        raw_digest: str,
        body: bytes,
        bundle: TrustedObservationBundle,
    ) -> None:
        key = (namespace_digest, source_id, source_tenant_id, observation_key)
        value = DataAgentReportStoredObservation(
            observation_key=observation_key,
            report_trace_id=report_trace_id,
            revision_digest=revision_digest,
            raw_digest=raw_digest,
            body=bytes(body),
            bundle=bundle,
        )
        existing = self._rows.get(key)
        if existing is not None and existing != value:
            raise DataAgentReportConflict("external report identity conflict")
        pending_index: dict[tuple[str, str, str], tuple[str, str, str, str]] = {}
        for object_kind, object_ids in SQLiteDataAgentReportStateStore._object_ids(
            bundle
        ).items():
            for object_id in object_ids:
                index_key = (namespace_digest, object_kind, object_id)
                indexed = self._object_index.get(index_key)
                if indexed is not None and indexed != key:
                    raise DataAgentReportConflict(
                        "external report object identity conflict"
                    )
                pending_index[index_key] = key
        self._rows[key] = value
        self._object_index.update(pending_index)

    def get_feed_cursor(
        self,
        namespace_digest: str,
        source_id: str,
        source_tenant_id: str,
    ) -> str | None:
        return self._feed_cursors.get((namespace_digest, source_id, source_tenant_id))

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
        history_key = (
            namespace_digest,
            source_id,
            source_tenant_id,
            next_cursor or "",
        )
        if (
            next_cursor is not None
            and next_cursor != expected_cursor
            and history_key in self._feed_cursor_history
        ):
            raise DataAgentReportConflict(
                "external report feed cursor was already consumed"
            )
        self._feed_cursors[key] = next_cursor
        if next_cursor is not None and next_cursor != expected_cursor:
            self._feed_cursor_history.add(history_key)
        return True

    def stage_feed_dispatches(
        self,
        namespace_digest: str,
        source_id: str,
        source_tenant_id: str,
        *,
        expected_cursor: str | None,
        next_cursor: str | None,
        consumed_cursors: tuple[str, ...],
        dispatches: tuple[DataAgentReportDispatch, ...],
    ) -> bool:
        key = (namespace_digest, source_id, source_tenant_id)
        if self._feed_cursors.get(key) != expected_cursor:
            return False
        pending = dict(self._dispatches)
        for dispatch in dispatches:
            SQLiteDataAgentReportStateStore._validate_dispatch(dispatch)
            existing = pending.get(dispatch.dispatch_id)
            if existing is not None and existing != dispatch:
                raise DataAgentReportConflict(
                    "durable external report dispatch identity conflict"
                )
            pending[dispatch.dispatch_id] = dispatch
        if any(
            (namespace_digest, source_id, source_tenant_id, cursor)
            in self._feed_cursor_history
            for cursor in consumed_cursors
        ):
            raise DataAgentReportConflict(
                "external report feed cursor was already consumed"
            )
        if not self.advance_feed_cursor(
            namespace_digest,
            source_id,
            source_tenant_id,
            expected_cursor=expected_cursor,
            next_cursor=next_cursor,
        ):
            return False
        self._dispatches = pending
        self._feed_cursor_history.update(
            (namespace_digest, source_id, source_tenant_id, cursor)
            for cursor in consumed_cursors
        )
        return True

    def list_dispatches(
        self,
        namespace_digest: str,
        source_id: str,
        source_tenant_id: str,
        *,
        status: str,
    ) -> tuple[DataAgentReportDispatch, ...]:
        return tuple(
            sorted(
                (
                    item
                    for item in self._dispatches.values()
                    if item.namespace_digest == namespace_digest
                    and item.source_id == source_id
                    and item.source_tenant_id == source_tenant_id
                    and item.status == status
                ),
                key=lambda item: item.dispatch_id,
            )
        )

    def complete_dispatch(
        self,
        dispatch: DataAgentReportDispatch,
        *,
        outcome_kind: str,
        outcome_digest: str,
        completed_at: datetime,
        consumer_id: str,
        authority_snapshot_digest: str,
    ) -> DataAgentReportDispatch:
        current = self._dispatches.get(dispatch.dispatch_id)
        completion_payload = {
            "dispatch_id": dispatch.dispatch_id,
            "dispatch_digest": dispatch.dispatch_digest,
            "outcome_kind": outcome_kind,
            "outcome_digest": outcome_digest,
            "completed_at": _utc(completed_at),
            "consumer_id": consumer_id,
            "authority_snapshot_digest": authority_snapshot_digest,
        }
        completed = DataAgentReportDispatch(
            **{
                **dispatch.__dict__,
                "status": "COMPLETED",
                "outcome_kind": outcome_kind,
                "outcome_digest": outcome_digest,
                "completed_at": _utc(completed_at),
                "consumer_id": consumer_id,
                "authority_snapshot_digest": authority_snapshot_digest,
                "completion_digest": content_digest(completion_payload),
            }
        )
        SQLiteDataAgentReportStateStore._validate_dispatch(completed)
        if current == completed:
            return completed
        if current != dispatch:
            raise DataAgentReportConflict(
                "durable external report dispatch changed concurrently"
            )
        self._dispatches[dispatch.dispatch_id] = completed
        return completed

    def get_dispatch(
        self,
        namespace_digest: str,
        dispatch_id: str,
    ) -> DataAgentReportDispatch | None:
        dispatch = self._dispatches.get(dispatch_id)
        if dispatch is None or dispatch.namespace_digest != namespace_digest:
            return None
        return dispatch


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
        raise DataAgentReportAdapterError(
            "external report origin port is invalid"
        ) from None
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
        credential_authorizations: CredentialAuthorizationReader | None = None,
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
        self._admission_policy = DataAgentReportEnvelopePolicy(
            DataAgentReportPolicyConfig(
                source_id=config.source_id,
                normalized_origin=self._origin,
                source_tenant_id=config.source_tenant_id,
                credential=config.credential,
                principal_id=config.principal_id,
                target_tenant_id=config.target_tenant_id,
                target_workspace_id=config.target_workspace_id,
                mandate_id=config.mandate_id,
                environment_binding_id=config.environment_binding_id,
                scope_ref=config.scope_ref,
                allow_loopback_http=config.allow_loopback_http,
                timeout_seconds=config.timeout_seconds,
                max_response_bytes=config.max_response_bytes,
                freshness_seconds=config.freshness_seconds,
            )
        )
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
        self._credential_authorizations = (
            credential_authorizations
            or CanonicalCredentialAuthorizationReader((config.credential,))
        )
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
    def admission_policy_descriptor(self) -> DataAgentReportPolicyDescriptor:
        return self._admission_policy.descriptor

    @property
    def _admission_policy_for_composition(self) -> DataAgentReportEnvelopePolicy:
        return self._admission_policy

    @property
    def _credential_authorization_reader_for_composition(
        self,
    ) -> CredentialAuthorizationReader:
        return self._credential_authorizations

    def _assert_current_credential_unreflected(
        self, body: bytes, *, assessed_at: datetime
    ) -> None:
        credential = self._config.credential
        if (
            credential.status is not CredentialStatus.ACTIVE
            or assessed_at < credential.created_at
            or assessed_at >= credential.expires_at
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
        if secret.encode("utf-8") in body or _contains_secret(
            _strict_json_object(body), secret
        ):
            raise DataAgentReportAdapterError(
                "external report reflected credential material"
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

    def pending_dispatches(self) -> tuple[DataAgentReportDispatch, ...]:
        return self._state_store.list_dispatches(
            self._state_namespace,
            self._config.source_id,
            self._config.source_tenant_id,
            status="PENDING",
        )

    def completed_dispatch(self, dispatch_id: str) -> DataAgentReportDispatch | None:
        dispatch = self._state_store.get_dispatch(
            self._state_namespace,
            dispatch_id,
        )
        if dispatch is None or dispatch.status != "COMPLETED":
            return None
        return dispatch

    def complete_dispatch(
        self,
        dispatch: DataAgentReportDispatch,
        *,
        outcome_kind: str,
        outcome_digest: str,
        completed_at: datetime,
        consumer_id: str,
        authority_snapshot_digest: str,
    ) -> DataAgentReportDispatch:
        if (
            dispatch.namespace_digest != self._state_namespace
            or dispatch.source_id != self._config.source_id
            or dispatch.source_tenant_id != self._config.source_tenant_id
            or dispatch.principal_id != self._config.principal_id
            or dispatch.tenant_id != self._config.target_tenant_id
            or dispatch.workspace_id != self._config.target_workspace_id
            or dispatch.mandate_id != self._config.mandate_id
            or dispatch.environment_binding_id != self._config.environment_binding_id
        ):
            raise DataAgentReportAdapterError(
                "external report dispatch scope does not match adapter"
            )
        return self._state_store.complete_dispatch(
            dispatch,
            outcome_kind=outcome_kind,
            outcome_digest=outcome_digest,
            completed_at=completed_at,
            consumer_id=consumer_id,
            authority_snapshot_digest=authority_snapshot_digest,
        )

    def _dispatch_for_bundle(
        self, bundle: TrustedObservationBundle
    ) -> DataAgentReportDispatch:
        bundle_digest = content_digest(
            {"event": bundle.event, "projection": bundle.projection}
        )
        payload = {
            "namespace_digest": self._state_namespace,
            "source_id": self._config.source_id,
            "source_tenant_id": self._config.source_tenant_id,
            "principal_id": self._config.principal_id,
            "tenant_id": self._config.target_tenant_id,
            "workspace_id": self._config.target_workspace_id,
            "mandate_id": self._config.mandate_id,
            "environment_binding_id": self._config.environment_binding_id,
            "environment_event_id": bundle.event.environment_event_id,
            "projection_id": bundle.projection.projection_id,
            "bundle_digest": bundle_digest,
            "activation_authorized": False,
            "capability_grant_authorized": False,
            "external_effects_authorized": False,
        }
        digest = content_digest(payload)
        return DataAgentReportDispatch(
            dispatch_id=f"data-agent-dispatch:{digest}",
            dispatch_digest=digest,
            status="PENDING",
            **payload,
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
            raise DataAgentReportAdapterError(
                "credential scope does not match target owner"
            )
        if not required_scopes.issubset(set(credential.scopes)):
            raise DataAgentReportAdapterError(
                "credential is not bound to the frozen origin, tenant, and report scope"
            )

    def _assert_live_credential_authorized(self, *, evaluated_at: datetime) -> None:
        frozen = self._config.credential
        try:
            current = self._credential_authorizations.resolve_authorization(
                frozen.credential_ref_id
            )
        except Exception:
            raise DataAgentReportAdapterError(
                "current credential authorization is unavailable"
            ) from None
        if current is None or type(current) is not CredentialAuthorizationSnapshot:
            raise DataAgentReportAdapterError(
                "current credential authorization is unavailable"
            )
        try:
            canonical = CredentialAuthorizationSnapshot.model_validate_json(
                canonical_json(current).encode("utf-8"), strict=True
            )
        except (TypeError, ValueError):
            raise DataAgentReportAdapterError(
                "current credential authorization is invalid"
            ) from None
        if canonical != current:
            raise DataAgentReportAdapterError(
                "current credential authorization is invalid"
            )
        if (
            current.credential_ref_id != frozen.credential_ref_id
            or current.credential_ref_digest != content_digest(frozen)
            or current.owner_principal_id != frozen.owner_principal_id
            or current.tenant_id != frozen.tenant_id
            or current.workspace_id != frozen.workspace_id
            or current.provider_id != frozen.provider_id
            or current.scopes != frozen.scopes
            or current.created_at != frozen.created_at
            or current.expires_at != frozen.expires_at
        ):
            raise DataAgentReportAdapterError(
                "current credential authorization does not match frozen source"
            )
        if (
            current.status is not CredentialStatus.ACTIVE
            or evaluated_at < current.created_at
            or evaluated_at >= current.expires_at
        ):
            raise DataAgentReportAdapterError(
                "current credential authorization is inactive or expired"
            )

    def pull(self, trace_id: str) -> TrustedObservationBundle:
        if not _TRACE_ID.fullmatch(trace_id) or ".." in trace_id:
            raise DataAgentReportAdapterError("trace_id is not a safe single segment")
        now = _utc(self._clock())
        credential = self._config.credential
        self._assert_live_credential_authorized(evaluated_at=now)
        path_trace = quote(trace_id, safe="")
        expected_url = f"{self._origin}/runs/{path_trace}/report?audience=external"
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
                    "X-Tenant-Id": self._config.source_tenant_id,
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
                "external report reflected credential material"
            )
        payload = _strict_json_object(response.body)
        if _contains_secret(payload, secret):
            raise DataAgentReportAdapterError(
                "external report reflected credential material"
            )
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
            self._assert_live_credential_authorized(evaluated_at=now)
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
                bundles.append(
                    self._ingest_report(
                        observation_key=f"feed:{trace_id}:{actual_digest}",
                        trace_id=trace_id,
                        body=body,
                        raw_digest=actual_digest,
                        observed_at=now,
                        register=False,
                    )
                )
            dispatches = tuple(self._dispatch_for_bundle(bundle) for bundle in bundles)
            if not self._state_store.stage_feed_dispatches(
                self._state_namespace,
                self._config.source_id,
                self._config.source_tenant_id,
                expected_cursor=prior_cursor,
                next_cursor=next_cursor,
                consumed_cursors=tuple(event["cursor"] for event in events),
                dispatches=dispatches,
            ):
                raise DataAgentReportConflict(
                    "external report feed cursor changed concurrently"
                )
            for event, bundle in zip(events, bundles, strict=True):
                raw_digest = event["content_sha256"]
                self._register_atomically(
                    f"feed:{event['trace_id']}:{raw_digest}",
                    event["trace_id"],
                    raw_digest,
                    canonical_json(event["report"]).encode("utf-8"),
                    bundle,
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
    ) -> tuple[tuple[_DataAgentReportFeedEvent, ...], str | None, bool]:
        if set(payload) != {
            "schema_version",
            "audience",
            "events",
            "next_cursor",
            "has_more",
        }:
            raise DataAgentReportAdapterError("external report feed fields are invalid")
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
            raise DataAgentReportAdapterError("external report feed events are invalid")
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
            raise DataAgentReportAdapterError("external report feed cursor is invalid")
        events: list[_DataAgentReportFeedEvent] = []
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
        register: bool = True,
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
                if (
                    stored.report_trace_id != trace_id
                    or stored.revision_digest != raw_digest
                    or stored.raw_digest != raw_digest
                    or stored.body != body
                ):
                    raise DataAgentReportConflict(
                        "external report changed for an already observed identity"
                    )
                if register:
                    self._register_atomically(
                        stored.observation_key,
                        stored.report_trace_id,
                        stored.raw_digest,
                        stored.body,
                        stored.bundle,
                    )
                return stored.bundle

            candidate = self._build_bundle(trace_id, body, raw_digest, observed_at)
            self._state_store.save(
                self._state_namespace,
                self._config.source_id,
                self._config.source_tenant_id,
                observation_key,
                trace_id,
                raw_digest,
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
            if (
                canonical.report_trace_id != trace_id
                or canonical.revision_digest != raw_digest
                or canonical.raw_digest != raw_digest
                or canonical.body != body
            ):
                raise DataAgentReportConflict(
                    "external report changed during durable registration"
                )
            if register:
                self._register_atomically(
                    canonical.observation_key,
                    canonical.report_trace_id,
                    canonical.raw_digest,
                    canonical.body,
                    canonical.bundle,
                )
            return canonical.bundle

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
        media_type = (
            (_header(response.headers, "Content-Type") or "")
            .split(";", 1)[0]
            .strip()
            .lower()
        )
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

    def _stable_identity(self, trace_id: str, raw_digest: str) -> dict[str, object]:
        return self._admission_policy.stable_identity(trace_id, raw_digest)

    def _build_bundle(
        self,
        trace_id: str,
        body: bytes,
        raw_digest: str,
        observed_at: datetime,
    ) -> TrustedObservationBundle:
        if hashlib.sha256(body).hexdigest() != raw_digest:
            raise DataAgentReportAdapterError("external report digest mismatch")
        try:
            envelope = self._admission_policy.build(trace_id, body, observed_at)
        except DataAgentReportPolicyError as exc:
            raise DataAgentReportAdapterError(str(exc)) from None
        return TrustedObservationBundle(
            artifact=envelope.artifact,
            evidence=envelope.evidence,
            event=envelope.event,
            projection=envelope.projection,
        )

    def _register_atomically(
        self,
        observation_key: str,
        trace_id: str,
        raw_digest: str,
        body: bytes,
        bundle: TrustedObservationBundle,
    ) -> None:
        self._validate_bundle_binding(
            observation_key=observation_key,
            trace_id=trace_id,
            raw_digest=raw_digest,
            body=body,
            bundle=bundle,
        )
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

    def _validate_bundle_binding(
        self,
        *,
        observation_key: str,
        trace_id: str,
        raw_digest: str,
        body: bytes,
        bundle: TrustedObservationBundle,
    ) -> None:
        SQLiteDataAgentReportStateStore._validate_stored_observation(
            observation_key=observation_key,
            report_trace_id=trace_id,
            revision_digest=raw_digest,
            raw_digest=raw_digest,
            body=body,
            bundle=bundle,
        )
        try:
            self._admission_policy.validate(
                body=body,
                artifact=bundle.artifact,
                evidence=bundle.evidence,
                event=bundle.event,
                projection=bundle.projection,
            )
        except DataAgentReportPolicyError as exc:
            raise DataAgentReportAdapterError(
                f"durable external report bundle binding is invalid: {exc}"
            ) from None

    def _rehydrate_object(self, object_kind: str, object_id: str) -> None:
        stored = self._state_store.get_by_object_id(
            self._state_namespace,
            self._config.source_id,
            self._config.source_tenant_id,
            object_kind=object_kind,
            object_id=object_id,
        )
        if stored is None:
            return
        self._register_atomically(
            stored.observation_key,
            stored.report_trace_id,
            stored.raw_digest,
            stored.body,
            stored.bundle,
        )

    def binding_is_authorized(self, binding: SituationalBinding) -> bool:
        return binding == self._binding

    def resolve_artifact(self, artifact_id: str) -> tuple[ArtifactRef, bytes] | None:
        with self._registry_lock:
            if artifact_id not in self._artifacts:
                self._rehydrate_object("artifact", artifact_id)
            return self._artifacts.get(artifact_id)

    def resolve_evidence(self, evidence_id: str) -> EvidenceRef | None:
        with self._registry_lock:
            if evidence_id not in self._evidence:
                self._rehydrate_object("evidence", evidence_id)
            return self._evidence.get(evidence_id)

    def resolve_event(self, event_id: str) -> EnvironmentEvent | None:
        with self._registry_lock:
            if event_id not in self._events:
                self._rehydrate_object("event", event_id)
            return self._events.get(event_id)

    def resolve_projection(self, projection_id: str) -> OperationalProjectionRef | None:
        with self._registry_lock:
            if projection_id not in self._projections:
                self._rehydrate_object("projection", projection_id)
            return self._projections.get(projection_id)
