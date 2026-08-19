"""Read-only warehouse introspection (composition layer).

Executes SELECT-only ``information_schema.columns`` queries through the
existing :class:`MySqlDataQueryCapability` and maps the result into a typed,
secret-free :class:`SchemaInventory.  No data rows are ever read.

Introspection is a composition-layer internal operation: it bypasses the
capability's SQL safety gate (which is designed for user-facing metric
queries) and calls the driver's fetch hook directly.  The introspection SQL
is a fixed, hard-coded SELECT on ``information_schema`` — no user input
reaches the query string.
"""

from __future__ import annotations

import logging
from typing import Any

from agent_os_contracts.domain_pack_synthesis import (
    ColumnInventory,
    SchemaInventory,
    TableInventory,
)

logger = logging.getLogger(__name__)

_INTROSPECTION_SQL = (
    "select table_schema, table_name, column_name, data_type "
    "from information_schema.columns "
    "where table_schema = :schema_name "
    "order by table_schema, table_name, ordinal_position "
    "limit 20000"
)


def introspect_mysql(
    capability: Any,
    schemas: tuple[str, ...],
) -> SchemaInventory:
    """Build a :class:`SchemaInventory` for ``schemas`` (read-only).

    ``capability`` is a :class:`MySqlDataQueryCapability` (or any object with
    a compatible ``_fetch_rows`` method).  Raises ValueError when the
    executor returns no columns for a requested schema (wrong name or
    missing privileges) so misconfiguration fails loudly instead of
    producing an empty, silently-wrong inventory.
    """
    if not schemas:
        raise ValueError("introspection requires at least one schema name")

    rows: list[dict[str, Any]] = []
    for schema in schemas:
        # Bypass the capability's safety gate: introspection SQL is a fixed,
        # hard-coded SELECT on information_schema — no user input reaches the
        # query string.  The safety gate is designed for user-facing metric
        # queries (LIMIT <= 1000, allowed_schemas), not for composition-layer
        # schema discovery.
        result_rows = capability._fetch_rows(
            _INTROSPECTION_SQL, {"schema_name": schema}
        )
        if not result_rows:
            raise ValueError(
                f"introspection returned no columns for schema {schema!r}; "
                f"check the schema name and the account's "
                f"information_schema privileges"
            )
        rows.extend(result_rows)

    tables: dict[tuple[str, str], list[ColumnInventory]] = {}
    for row in rows:
        key = (str(row["table_schema"]), str(row["table_name"]))
        tables.setdefault(key, []).append(
            ColumnInventory(
                name=str(row["column_name"]),
                data_type=str(row["data_type"]),
            )
        )
    inventory = SchemaInventory(
        tables=tuple(
            TableInventory(schema=schema, table=table, columns=tuple(cols))
            for (schema, table), cols in sorted(tables.items())
        )
    )
    logger.info(
        "introspected %d tables across %d schemas",
        len(inventory.tables),
        len(schemas),
    )
    return inventory
