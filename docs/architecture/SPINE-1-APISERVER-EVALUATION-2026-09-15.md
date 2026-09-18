# SPINE-1 APISERVER evaluation — implement vs reduce

> Status: `RECOMMENDATION_ONLY / REQUIRES_FOUNDER_SIGNOFF`
> Date: 2026-09-15
> Scope: `D-APISERVER-DOMAIN`, `D-APISERVER-APP`, `D-APISERVER-HEAVY-INFRA`

## Recon

Donor `apps/api_server` = 8943 lines across 17 files. Monorepo `apps/api_server` already exists
(7076 lines: `app.py`, `server.py`, `surface_routes.py`, plus the extracted
`data_agent_report_*` + `data_agent_situated_*` surface). The domain pack already carries
`report_adapter`/`report_admission`/`report_policy`/`situated`/`runtime`/`query_runtime`.

External deps in the donor app: `fastapi`/`starlette` (same as the monorepo app), `sqlalchemy`
(external warehouse drivers).

## Per-entry verdict

| Entry | Files | Verdict | Rationale |
|---|---|---|---|
| `D-APISERVER-APP` | `http_app.py` (3492 L), `mcp_transport.py` (117 L) | **REDUCE (superseded)** | the monorepo already owns a FastAPI composition app (`apps/api_server`, 7076 L). A second 3.5k-line donor app would duplicate the runtime, not add capability. `mcp_transport` depends on the reduced MCP gateway. |
| `D-APISERVER-HEAVY-INFRA` | `heavy_infra_adapters.py` (110 L) | **REDUCE** | Temporal/OPA/Trino adapters over `heavy_infrastructure` contracts, which were themselves reduced (no consumer). Dead plumbing. |
| `D-APISERVER-DOMAIN` | executors `postgres`/`mysql`/`clickhouse`/`feishu` (103-155 L each), `executor_factory` (136 L), `runtime_factory` (1009 L), `outcome_service` (2693 L), `staged_out_service` (404 L), `cli` (371 L) | **REDUCE now; implement executors on demand** | the service/cli/factory layer is superseded by the monorepo app + the already-extracted domain surface (`report_adapter`/`report_admission`/`report_policy`/`situated`). The four **warehouse executors** are the only genuine gap, but they require real external servers/credentials (postgres/mysql/clickhouse/feishu) → **unverifiable here**, and no runtime consumer is wired. They are ~100-155 L each and can be implemented when a named data-source consumer exists. |

## Conclusion

Recommend **REDUCE all three** APISERVER entries. Grounds: (a) monorepo already owns the app and the
domain report/situated surface; (b) the executors are unverifiable without external infra and have no
consumer; (c) AGENTS.md §10 forbids adding unused/unverifiable code. This is an explicit capability
reduction (the real-warehouse connectors), not a silent drop — implement on demand.

If accepted, the manifest gate has **0 gaps** and can legitimately reach `retirement_ready: True`
(manifest-level only; ADR-0054 gates, the donor pin, and founder retirement authorization remain
separate and open).
