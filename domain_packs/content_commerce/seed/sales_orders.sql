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
-- The in-window rows (2026-05-25 <= order_date < 2026-06-01) all fall on 2026-05-31
-- and back the multi-metric examples used across the unit/eval suite:
--   gmv             = sum(paid_amount) = 128800.0
--   spend           = sum(spend)       = 5000.0
--   roi             = sum(paid_amount)/sum(spend) = 25.76
--   conversion_rate = count(orders)/sum(visits)   = 2/250 = 0.008
-- Rows on the boundaries verify the half-open window of the template.

create table if not exists {schema}.orders (
    order_id     integer primary key,
    order_date   text    not null,
    paid_amount  real    not null,
    spend        real    not null default 0.0,
    visits       integer not null default 0
);

delete from {schema}.orders;

insert into {schema}.orders (order_id, order_date, paid_amount, spend, visits) values
    -- before the window -> excluded by start_date bound
    (1, '2026-05-20', 50000.0, 9000.0, 300),
    -- in-window day: paid=128800.0 (GMV), spend=5000.0, orders=2, visits=250
    (2, '2026-05-31', 100000.0, 4000.0, 200),
    (3, '2026-05-31', 28800.0, 1000.0, 50),
    -- on end_date (exclusive upper bound) -> excluded
    (4, '2026-06-01', 77000.0, 8000.0, 400);
