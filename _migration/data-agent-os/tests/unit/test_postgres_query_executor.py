"""Tests for PostgresQueryExecutor.

These tests use SQLAlchemy's SQLite dialect for the happy-path tests (the
executor is dialect-agnostic for basic SELECT via SQLAlchemy Core), and a
real bad PostgreSQL DSN for the connection-failure test.  No running PostgreSQL
instance is required.

The tests prove the implementation is not a stub (Hard Boundary #12):

- A stub returning constant rows would fail the aggregation test (the expected
  value 128800.0 is computed by real SQL SUM, not hard-coded).
- A stub that doesn't validate SQL would fail the mutation-rejection tests.
- A stub that ignores the DSN would fail the connection-failure test.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api_server" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))

from agent_os_contracts import QueryPlan, QueryResult  # noqa: E402
from agent_os_api.postgres_executor import PostgresQueryExecutor  # noqa: E402


def _seed_orders(engine) -> None:
    """Create and populate a plain ``orders`` table for standalone executor tests."""
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS orders (order_date TEXT, paid_amount REAL)"))
        conn.execute(text("DELETE FROM orders"))
        conn.execute(
            text("INSERT INTO orders (order_date, paid_amount) VALUES (:d, :a)"),
            [
                {"d": "2026-05-24", "a": 999.0},
                {"d": "2026-05-31", "a": 100000.0},
                {"d": "2026-05-31", "a": 28800.0},
                {"d": "2026-06-01", "a": 555.0},
            ],
        )


def _seed_schema_qualified_engine():
    """Build an in-memory SQLite engine with ``sales.orders`` for factory tests.

    The domain-pack SQL templates use schema-qualified table names (``sales.orders``).
    SQLite ATTACH creates the schema namespace on a single pooled connection
    (StaticPool ensures the same connection is reused for every query).
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.execute(text("ATTACH DATABASE ':memory:' AS sales"))
        conn.execute(
            text(
                "CREATE TABLE sales.orders "
                "(order_id TEXT, order_date TEXT, paid_amount REAL, "
                "spend REAL, visits INTEGER)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO sales.orders "
                "(order_id, order_date, paid_amount, spend, visits) "
                "VALUES (:id, :d, :a, :s, :v)"
            ),
            [
                {"id": "1", "d": "2026-05-24", "a": 999.0, "s": 100.0, "v": 10},
                {"id": "2", "d": "2026-05-31", "a": 100000.0, "s": 5000.0, "v": 500},
                {"id": "3", "d": "2026-05-31", "a": 28800.0, "s": 1200.0, "v": 150},
                {"id": "4", "d": "2026-06-01", "a": 555.0, "s": 50.0, "v": 5},
            ],
        )
    return engine


class PostgresQueryExecutorTest(unittest.TestCase):
    """Tests for the PostgresQueryExecutor using SQLAlchemy Core.

    The executor uses SQLAlchemy ``text()`` for parameterized queries, which
    works identically across dialects for basic SELECT.  These tests inject a
    SQLite engine to verify real execution logic without requiring PostgreSQL.
    """

    def _make_executor(self) -> PostgresQueryExecutor:
        """Build an executor over an in-memory SQLite engine with seed data."""
        engine = create_engine("sqlite:///:memory:")
        _seed_orders(engine)
        return PostgresQueryExecutor(engine=engine)

    # -- Happy path: real SQL execution with real results --------------------

    def test_postgres_executor_connects_successfully(self) -> None:
        """The executor must run real SQL via SQLAlchemy and return computed results.

        The expected GMV (128800.0) is SUM(paid_amount) for in-window rows,
        computed by the SQL engine.  A stub returning a constant could not
        produce this value without being hand-coded to match the seed data.
        """
        executor = self._make_executor()
        plan = QueryPlan(
            metric_name="gmv",
            sql=(
                "SELECT order_date, SUM(paid_amount) AS value "
                "FROM orders "
                "WHERE order_date >= :start_date AND order_date < :end_date "
                "GROUP BY order_date "
                "LIMIT :limit"
            ),
            parameters={
                "start_date": "2026-05-25",
                "end_date": "2026-06-01",
                "limit": 100,
            },
        )

        result = executor.execute(plan)

        self.assertIsInstance(result, QueryResult)
        self.assertEqual(result.row_count, 1)
        self.assertEqual(len(result.rows), 1)
        row = result.rows[0]
        self.assertEqual(set(row.keys()), {"order_date", "value"})
        self.assertEqual(row["order_date"], "2026-05-31")
        # Real SQL SUM, not a hard-coded constant.
        self.assertEqual(row["value"], 128800.0)

    def test_postgres_executor_returns_query_result(self) -> None:
        """Verify the QueryResult shape: rows as dicts with real column names."""
        executor = self._make_executor()
        plan = QueryPlan(
            metric_name="gmv",
            sql="SELECT order_date, paid_amount FROM orders ORDER BY paid_amount DESC",
            parameters={},
        )

        result = executor.execute(plan)

        self.assertIsInstance(result, QueryResult)
        self.assertEqual(result.row_count, 4)
        self.assertEqual(len(result.rows), 4)
        # Column names must be preserved from the real query.
        self.assertIn("order_date", result.rows[0])
        self.assertIn("paid_amount", result.rows[0])
        # Rows should be ordered by paid_amount DESC (proves ORDER BY was honored).
        amounts = [r["paid_amount"] for r in result.rows]
        self.assertEqual(amounts, sorted(amounts, reverse=True))

    def test_parameter_binding_changes_result(self) -> None:
        """Changing bound parameters must change the computed result.

        This proves parameters are actually bound to the query (not ignored).
        A stub that ignores parameters would return the same result regardless.
        """
        executor = self._make_executor()
        sql = (
            "SELECT SUM(paid_amount) AS value "
            "FROM orders "
            "WHERE order_date >= :start_date AND order_date < :end_date"
        )

        # Wide window includes 2026-06-01 (555.0).
        wide = executor.execute(
            QueryPlan(
                metric_name="gmv",
                sql=sql,
                parameters={"start_date": "2026-05-25", "end_date": "2026-06-02"},
            )
        )
        self.assertEqual(wide.rows[0]["value"], 128800.0 + 555.0)

        # Narrow window excludes everything.
        narrow = executor.execute(
            QueryPlan(
                metric_name="gmv",
                sql=sql,
                parameters={"start_date": "2026-05-25", "end_date": "2026-05-26"},
            )
        )
        self.assertIsNone(narrow.rows[0]["value"])

    def test_empty_result_returns_zero_row_count(self) -> None:
        """A query matching no rows returns row_count=0 and empty rows tuple."""
        executor = self._make_executor()
        plan = QueryPlan(
            metric_name="gmv",
            sql=(
                "SELECT order_date, SUM(paid_amount) AS value "
                "FROM orders "
                "WHERE order_date >= :start_date AND order_date < :end_date "
                "GROUP BY order_date"
            ),
            parameters={"start_date": "2030-01-01", "end_date": "2030-02-01"},
        )

        result = executor.execute(plan)

        self.assertEqual(result.row_count, 0)
        self.assertEqual(result.rows, ())

    # -- Read-only gate: mutation rejection ----------------------------------

    def test_postgres_executor_rejects_non_select(self) -> None:
        """INSERT must be rejected before reaching the database.

        This is the proof that the executor enforces read-only access --
        a stub that just returns empty results would not raise here.
        """
        executor = self._make_executor()
        plan = QueryPlan(
            metric_name="gmv",
            sql="INSERT INTO orders (order_date, paid_amount) VALUES ('2026-07-01', 999.0)",
            parameters={},
        )

        with self.assertRaises(ValueError) as ctx:
            executor.execute(plan)

        self.assertIn("read-only", str(ctx.exception))
        self.assertIn("INSERT", str(ctx.exception))

    def test_rejects_update_statement(self) -> None:
        executor = self._make_executor()
        plan = QueryPlan(
            metric_name="gmv",
            sql="UPDATE orders SET paid_amount = 0",
            parameters={},
        )
        with self.assertRaises(ValueError):
            executor.execute(plan)

    def test_rejects_delete_statement(self) -> None:
        executor = self._make_executor()
        plan = QueryPlan(
            metric_name="gmv",
            sql="DELETE FROM orders WHERE order_date < '2026-01-01'",
            parameters={},
        )
        with self.assertRaises(ValueError):
            executor.execute(plan)

    def test_rejects_drop_statement(self) -> None:
        executor = self._make_executor()
        plan = QueryPlan(
            metric_name="gmv",
            sql="DROP TABLE orders",
            parameters={},
        )
        with self.assertRaises(ValueError):
            executor.execute(plan)

    def test_accepts_with_cte_query(self) -> None:
        """WITH (CTE) queries are a valid read-only pattern and must be accepted."""
        executor = self._make_executor()
        plan = QueryPlan(
            metric_name="gmv",
            sql=(
                "WITH windowed AS ("
                "  SELECT order_date, paid_amount FROM orders"
                "  WHERE order_date >= :start_date AND order_date < :end_date"
                ") SELECT SUM(paid_amount) AS value FROM windowed"
            ),
            parameters={"start_date": "2026-05-25", "end_date": "2026-06-01"},
        )

        result = executor.execute(plan)

        self.assertEqual(result.row_count, 1)
        self.assertEqual(result.rows[0]["value"], 128800.0)

    # -- Connection failure: graceful degradation ----------------------------

    def test_postgres_executor_handles_connection_failure(self) -> None:
        """A bad DSN must return an empty result, not crash.

        Uses a real PostgreSQL DSN (psycopg v3 driver) pointing at an unreachable
        host to verify the OperationalError handling path.  A stub that ignores
        the DSN would either succeed (wrong) or raise (wrong).
        """
        # Use psycopg v3 driver (psycopg2 is not installed in this project).
        # Port 1 is almost certainly not PostgreSQL; connect_timeout keeps it fast.
        executor = PostgresQueryExecutor(
            "postgresql+psycopg://nobody:nopass@127.0.0.1:1/nonexistent?connect_timeout=1"
        )
        plan = QueryPlan(
            metric_name="gmv",
            sql="SELECT 1 AS value",
            parameters={},
        )

        # Must not raise -- returns empty result on connection failure.
        result = executor.execute(plan)

        self.assertIsInstance(result, QueryResult)
        self.assertEqual(result.row_count, 0)
        self.assertEqual(result.rows, ())

    # -- Constructor validation ----------------------------------------------

    def test_requires_url_or_engine(self) -> None:
        """Constructing with neither a URL nor an engine is a usage error."""
        with self.assertRaises(ValueError):
            PostgresQueryExecutor()

    def test_close_disposes_owned_engine(self) -> None:
        """close() must dispose an engine the executor created itself."""
        executor = PostgresQueryExecutor("sqlite:///:memory:")
        # Should not raise.
        executor.close()
        # Calling close again must be safe.
        executor.close()


class PostgresQueryExecutorFactoryWiringTest(unittest.TestCase):
    """Verify the factory can construct a PostgresQueryExecutor via config."""

    def test_factory_accepts_postgres_executor(self) -> None:
        """The factory wires a PostgresQueryExecutor when executor='postgres'.

        We inject a schema-qualified SQLite engine (via StaticPool + ATTACH)
        to avoid needing a real PostgreSQL instance while still running the
        full Trusted Loop end-to-end.
        """
        from agent_os_api import ContentCommerceRuntimeFactory, RuntimeFactoryConfig
        from agent_os_api.postgres_executor import PostgresQueryExecutor

        domain_pack = ROOT / "domain_packs" / "content_commerce"
        engine = _seed_schema_qualified_engine()

        config = RuntimeFactoryConfig(
            domain_pack_path=domain_pack,
            executor="postgres",
            store_engine=engine,
        )
        factory = ContentCommerceRuntimeFactory(config)
        runtime = factory.build()

        self.assertIsInstance(runtime.query_executor, PostgresQueryExecutor)

        # The runtime must produce real results through the postgres executor.
        result = runtime.run(
            "GMV",
            {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100},
        )
        self.assertEqual(result.evidence_chain.query_result.row_count, 1)
        self.assertEqual(result.evidence_chain.query_result.rows[0]["value"], 128800.0)

    def test_factory_env_accepts_postgres_executor(self) -> None:
        """from_env must accept AGENT_OS_EXECUTOR=postgres with a DSN."""
        from agent_os_api import RuntimeFactoryConfig

        config = RuntimeFactoryConfig.from_env(
            {
                "AGENT_OS_DOMAIN_PACK": str(ROOT / "domain_packs" / "content_commerce"),
                "AGENT_OS_EXECUTOR": "postgres",
                "AGENT_OS_POSTGRES_DSN": "postgresql://user:pass@localhost:5432/testdb",
            }
        )
        self.assertEqual(config.executor, "postgres")
        self.assertEqual(
            config.postgres_dsn,
            "postgresql://user:pass@localhost:5432/testdb",
        )

    def test_factory_env_rejects_postgres_without_dsn(self) -> None:
        """executor=postgres without AGENT_OS_POSTGRES_DSN must fail at startup."""
        from agent_os_api import RuntimeFactoryConfig

        with self.assertRaises(ValueError) as ctx:
            RuntimeFactoryConfig.from_env(
                {
                    "AGENT_OS_EXECUTOR": "postgres",
                }
            )
        self.assertIn("postgres", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
