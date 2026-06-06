-- Customer-0 / reference seed data for the content_commerce domain pack.
--
-- This is reference data, NOT OS Core logic. The OS Core SQLiteQueryExecutor is a
-- generic SQL engine; this file is the data plane the application layer "rides"
-- behind ProviderContract. The application/composition layer loads this into a
-- SQLite database whose `{schema}` schema backs the `{schema}.orders` table
-- referenced by the GMV SQL template (sql_templates.json).
--
-- The `{schema}` token is substituted with the provider's schema name (e.g. "sales")
-- by the runtime factory before the script is executed.
--
-- The in-window rows (2026-05-25 <= order_date < 2026-06-01) sum to 128800.0 on
-- 2026-05-31 for paid_amount (the GMV example value used across the unit/eval suite)
-- and to 5000.0 for spend (the multi-metric example). Rows on the boundaries verify
-- the half-open window of the template.

create table if not exists {schema}.orders (
    order_id     integer primary key,
    order_date   text    not null,
    paid_amount  real    not null,
    spend        real    not null default 0.0
);

delete from {schema}.orders;

insert into {schema}.orders (order_id, order_date, paid_amount, spend) values
    -- before the window -> excluded by start_date bound
    (1, '2026-05-20', 50000.0, 9000.0),
    -- in-window day: paid_amount sums to 128800.0 (GMV), spend sums to 5000.0
    (2, '2026-05-31', 100000.0, 4000.0),
    (3, '2026-05-31', 28800.0, 1000.0),
    -- on end_date (exclusive upper bound) -> excluded
    (4, '2026-06-01', 77000.0, 8000.0);
