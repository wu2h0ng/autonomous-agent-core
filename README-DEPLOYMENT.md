# Deployment Guide — AI Native Business Data Agent OS

## Prerequisites

- **Docker** >= 24.0 (with Compose V2 plugin)
- **Docker Compose** >= 2.20 (`docker compose version`)
- 4 GB RAM minimum (2 GB for PostgreSQL + pgvector, 1 GB for API server, 1 GB for frontend)

## Quick Start

```bash
# 1. Copy the example environment file
cp .env.example .env

# 2. Edit .env to set your API keys and passwords
#    (at minimum, change POSTGRES_PASSWORD for non-local deployments)

# 3. Start all services
docker compose up -d

# 4. Verify everything is running
docker compose ps
```

Services will be available at:

| Service   | URL                                  | Description                     |
|-----------|--------------------------------------|---------------------------------|
| Frontend  | http://localhost:3000                | Workspace UI                    |
| API Docs  | http://localhost:8000/docs           | Swagger UI (interactive)        |
| OpenAPI   | http://localhost:8000/openapi.json   | Machine-readable API schema     |
| Database  | localhost:5432                       | PostgreSQL with pgvector        |

## Environment Variables Reference

### PostgreSQL

| Variable            | Default          | Description                       |
|---------------------|------------------|-----------------------------------|
| `POSTGRES_USER`     | `agent_os`       | Database user                     |
| `POSTGRES_PASSWORD` | `agent_os_secret`| Database password (change me!)    |
| `POSTGRES_DB`       | `agent_os`       | Database name                     |
| `POSTGRES_PORT`     | `5432`           | Host port for database access     |

### API Server

| Variable                    | Default              | Description                                    |
|-----------------------------|----------------------|------------------------------------------------|
| `API_PORT`                  | `8000`               | Host port for API access                       |
| `AGENT_OS_EXECUTOR`         | `sqlite`             | Query executor: `static` or `sqlite`           |
| `AGENT_OS_API_KEY`          | `dev-internal-key`   | Internal API key (X-API-Key header)            |
| `AGENT_OS_EXTERNAL_API_KEY` | `dev-external-key`   | External report-only API key                   |
| `AGENT_OS_OPERATOR_API_KEY` | `dev-operator-key`   | Operator key for approval execution            |
| `LLM_API_KEY`               | _(empty)_            | LLM provider API key (optional)                |
| `EMBEDDING_API_KEY`         | _(empty)_            | Embedding provider API key (optional)          |

### Frontend

| Variable              | Default                | Description                          |
|-----------------------|------------------------|--------------------------------------|
| `FRONTEND_PORT`       | `3000`                 | Host port for frontend access        |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | API base URL (browser-accessible)    |
| `NEXT_PUBLIC_RUN_KEY` | `dev-internal-key`     | API key sent by the frontend         |

## Architecture

```
Browser (:3000)  -->  Frontend (Next.js)
                           |
                           | NEXT_PUBLIC_API_URL
                           v
                      API Server (:8000)
                      (FastAPI / uvicorn)
                           |
                           | AGENT_OS_DATABASE_URL
                           v
                      PostgreSQL (:5432)
                      (pgvector/pgvector:pg16)
```

The API server uses the Trusted Loop runtime with:
- **Persistence**: PostgreSQL-backed stores for knowledge, feedback, traces, approvals
- **Executor**: SQLite over seeded domain-pack data (real SQL with SQL Safety)
- **Domain Pack**: content_commerce (4 metrics: GMV, spend, ROI, conversion rate)

## Configuring Data Sources

The default deployment uses the `content_commerce` domain pack with seeded SQLite data.
To connect to a different data source:

1. Set `AGENT_OS_EXECUTOR=static` in `.env` to use deterministic fixture rows instead of SQL.
2. To add new domain packs, place them under `domain_packs/` and set `AGENT_OS_DOMAIN_PACK` in the API server environment.
3. For PostgreSQL-backed query execution (future), configure a `ProviderContract` pointing to your data plane.

## Authentication

The API uses header-based authentication with three key tiers:

| Header          | Key Variable                | Scopes                                        |
|-----------------|-----------------------------|-----------------------------------------------|
| `X-API-Key`     | `AGENT_OS_API_KEY`          | Full internal access (runs, outcomes, traces) |
| `X-API-Key`     | `AGENT_OS_EXTERNAL_API_KEY` | Report-only external projection               |
| `X-Operator-Key`| `AGENT_OS_OPERATOR_API_KEY` | Approval execution only                       |

All keys must be distinct. If `AGENT_OS_API_KEY` is not set, protected routes return 503.

## Development Mode

For active development with hot reload and source mounting:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

This enables:
- **API Server**: uvicorn `--reload` with source volume mounts
- **Frontend**: `next dev` with source volume mounts
- **Debugger**: Python debug port exposed on 5678
- **Stores**: defaults to in-memory for fast iteration (override with `AGENT_OS_STORE_BACKEND=postgres`)

## Troubleshooting

### "api_server" fails to start

```bash
# Check logs
docker compose logs api_server

# Common issue: database not ready yet
# The healthcheck dependency should handle this, but verify:
docker compose logs postgres
```

### Frontend cannot reach the API

The `NEXT_PUBLIC_API_URL` must be reachable from the **browser**, not from the container. If you change the API port, update:

```env
API_PORT=9000
NEXT_PUBLIC_API_URL=http://localhost:9000
```

### Database connection refused

```bash
# Verify postgres is healthy
docker compose ps postgres

# Reset the database (DESTRUCTIVE)
docker compose down -v
docker compose up -d
```

### Port already in use

```bash
# Override ports in .env
API_PORT=8001
FRONTEND_PORT=3001
POSTGRES_PORT=5433
```

### Rebuild after code changes

```bash
# Rebuild a specific service
docker compose build api_server
docker compose up -d api_server

# Full rebuild
docker compose build --no-cache
docker compose up -d
```

### View all logs

```bash
# Follow all logs
docker compose logs -f

# Follow a specific service
docker compose logs -f api_server
```

## Stopping and Cleanup

```bash
# Stop all services (data persists in volumes)
docker compose down

# Stop and remove all data (DESTRUCTIVE)
docker compose down -v

# Stop and remove images
docker compose down --rmi local
```

## Production Considerations

- **Change all default keys and passwords** before any non-local deployment.
- **TLS**: put a reverse proxy (nginx, Caddy, Traefik) in front for HTTPS termination.
- **`NEXT_PUBLIC_API_URL`**: must be the public-facing API URL (not `http://api_server:8000`).
- **Database backups**: use `pg_dump` or configure a managed PostgreSQL instance.
- **Scaling**: the API server is stateless with PostgreSQL-backed stores; scale horizontally behind a load balancer.
- **Monitoring**: the API server exposes `/docs` (Swagger) and `/openapi.json`; integrate with your APM via OpenTelemetry (the `observability` extras group).
