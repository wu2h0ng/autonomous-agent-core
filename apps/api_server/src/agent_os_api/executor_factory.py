"""ProviderContract-aware query executor factory.

Builds concrete query executors from a :class:`ProviderContract`'s
``connection`` field.  Executors that need third-party drivers live in the
composition layer (``apps/api_server/``) so OS Core remains dependency-free.
"""

from __future__ import annotations

from agent_os_contracts import ProviderConnection, ProviderContract
from agent_os_core.query_runtime import CsvQueryExecutor, SQLiteQueryExecutor, StaticQueryExecutor

from .clickhouse_executor import ClickHouseQueryExecutor
from .feishu_executor import FeishuQueryExecutor
from .mysql_executor import MySqlQueryExecutor
from .postgres_executor import PostgresQueryExecutor


class ExecutorFactory:
    """Create a query executor matching a provider's connection specification."""

    _SUPPORTED_TYPES = frozenset(
        {
            "static",
            "sqlite",
            "csv",
            "postgresql",
            "postgres",
            "mysql",
            "clickhouse",
            "feishu",
        }
    )

    @classmethod
    def supported_types(cls) -> frozenset[str]:
        return cls._SUPPORTED_TYPES

    @classmethod
    def from_provider_contract(
        cls,
        provider_contract: ProviderContract,
        *,
        static_rows: tuple[dict, ...] = (),
    ) -> object:
        """Return an executor instance appropriate for ``provider_contract``.

        Parameters
        ----------
        provider_contract:
            The selected provider.  If it has no ``connection``, a
            :class:`StaticQueryExecutor` is returned for backward compatibility.
        static_rows:
            Fixture rows used when falling back to a static executor.

        Raises
        ------
        ValueError
            If the connection type is unsupported or required connection fields
            are missing.
        ImportError
            If the connection type needs a driver that is not installed.
        """
        connection = provider_contract.connection
        if connection is None:
            return StaticQueryExecutor(static_rows)

        conn_type = connection.connection_type.lower()
        if conn_type not in cls._SUPPORTED_TYPES:
            raise ValueError(
                f"Unsupported provider connection_type: {connection.connection_type!r}"
            )

        if conn_type in ("static",):
            return StaticQueryExecutor(static_rows)

        if conn_type == "sqlite":
            if not connection.path:
                raise ValueError("SQLite provider connection requires 'path'.")
            return SQLiteQueryExecutor(database=connection.path)

        if conn_type == "csv":
            if not connection.path:
                raise ValueError("CSV provider connection requires 'path'.")
            return CsvQueryExecutor(connection.path)

        if conn_type in ("postgresql", "postgres"):
            if not connection.database:
                raise ValueError("PostgreSQL provider connection requires 'database'.")
            database_url = cls._build_postgres_url(connection)
            return PostgresQueryExecutor(database_url=database_url)

        if conn_type == "mysql":
            if not connection.database:
                raise ValueError("MySQL provider connection requires 'database'.")
            database_url = cls._build_mysql_url(connection)
            return MySqlQueryExecutor(database_url=database_url)

        if conn_type == "clickhouse":
            return ClickHouseQueryExecutor(
                host=connection.host,
                port=connection.port,
                database=connection.database,
                username=connection.username,
                password=connection.password,
            )

        if conn_type == "feishu":
            if not connection.app_token or not connection.table_id or not connection.api_token:
                raise ValueError(
                    "Feishu provider connection requires 'app_token', 'table_id', and 'api_token'."
                )
            return FeishuQueryExecutor(
                app_token=connection.app_token,
                table_id=connection.table_id,
                api_token=connection.api_token,
            )

        # Should never reach here because of the membership check above.
        raise ValueError(f"Unsupported provider connection_type: {connection.connection_type!r}")

    @classmethod
    def _build_postgres_url(cls, connection: ProviderConnection) -> str:
        host = connection.host or "localhost"
        port = connection.port or 5432
        user = connection.username or "postgres"
        password_part = f":{connection.password}" if connection.password else ""
        return f"postgresql://{user}{password_part}@{host}:{port}/{connection.database}"

    @classmethod
    def _build_mysql_url(cls, connection: ProviderConnection) -> str:
        host = connection.host or "localhost"
        port = connection.port or 3306
        user = connection.username or "root"
        password_part = f":{connection.password}" if connection.password else ""
        return f"mysql+pymysql://{user}{password_part}@{host}:{port}/{connection.database}"
