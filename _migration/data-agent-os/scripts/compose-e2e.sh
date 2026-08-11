#!/usr/bin/env bash
# compose-e2e.sh — start API stack, run Playwright against live compose API, tear down.
#
# Usage:
#   ./scripts/compose-e2e.sh           # start stack, run compose E2E, tear down
#   ./scripts/compose-e2e.sh --no-down # leave stack running after tests
#
# Requires Docker. Does not start the compose frontend service; Playwright serves Next.js locally.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${COMPOSE_E2E_ENV_FILE:-${REPO_ROOT}/.env}"
COMPOSE_FILES=(-f "${REPO_ROOT}/docker-compose.yml")

cd "${REPO_ROOT}"

if [[ ! -f "${ENV_FILE}" ]]; then
    echo "==> Creating .env from .env.example"
    cp "${REPO_ROOT}/.env.example" "${ENV_FILE}"
fi

set -a
# shellcheck source=/dev/null
source "${ENV_FILE}"
set +a

API_PORT="${API_PORT:-8000}"
API_URL="http://localhost:${API_PORT}"
API_KEY="${AGENT_OS_API_KEY:-dev-internal-key}"
OPERATOR_KEY="${AGENT_OS_OPERATOR_API_KEY:-dev-operator-key}"

DO_DOWN=1
for arg in "$@"; do
    case "${arg}" in
        --no-down)
            DO_DOWN=0
            ;;
        --down)
            DO_DOWN=1
            ;;
        *)
            echo "Usage: $0 [--down|--no-down]"
            exit 1
            ;;
    esac
done

cleanup() {
    if [[ "${DO_DOWN}" -eq 1 ]]; then
        echo "==> Stopping compose stack"
        docker compose "${COMPOSE_FILES[@]}" --env-file "${ENV_FILE}" down --volumes
    fi
}
trap cleanup EXIT

wait_for_postgres() {
    echo "==> Waiting for postgres ..."
    for _ in {1..60}; do
        if docker compose "${COMPOSE_FILES[@]}" --env-file "${ENV_FILE}" exec -T postgres \
            pg_isready -U "${POSTGRES_USER:-agent_os}" -d "${POSTGRES_DB:-agent_os}" >/dev/null 2>&1; then
            echo "==> Postgres is ready"
            return 0
        fi
        sleep 1
    done
    echo "==> Postgres did not become ready within 60s"
    return 1
}

run_compose_migrations() {
    echo "==> Running database migrations"
    docker compose "${COMPOSE_FILES[@]}" --env-file "${ENV_FILE}" run --rm --no-deps api_server \
        sh -c 'cd packages/persistence && python -m alembic -c alembic.ini upgrade head'
}

wait_for_health() {
    echo "==> Waiting for ${API_URL}/health ..."
    for _ in {1..60}; do
        if curl -sf "${API_URL}/health" >/dev/null 2>&1; then
            echo "==> API is healthy"
            return 0
        fi
        sleep 1
    done
    echo "==> API did not become healthy within 60s"
    return 1
}

echo "==> Starting postgres"
docker compose "${COMPOSE_FILES[@]}" --env-file "${ENV_FILE}" up -d --build postgres
wait_for_postgres
echo "==> Building api_server image"
docker compose "${COMPOSE_FILES[@]}" --env-file "${ENV_FILE}" build api_server
run_compose_migrations
echo "==> Starting api_server"
docker compose "${COMPOSE_FILES[@]}" --env-file "${ENV_FILE}" up -d api_server
wait_for_health

echo "==> Running Playwright compose live API E2E"
cd "${REPO_ROOT}/apps/workspace/frontend"
export COMPOSE_E2E=1
export CI=1
export NEXT_PUBLIC_API_URL="${API_URL}"
export NEXT_PUBLIC_API_KEY="${API_KEY}"
export NEXT_PUBLIC_RUN_KEY="${API_KEY}"
export NEXT_PUBLIC_OPERATOR_KEY="${OPERATOR_KEY}"
npm install
npm run test:e2e:install
npm run test:e2e -- e2e/workspace.compose-api.spec.ts
playwright_status=$?
if [[ "${playwright_status}" -ne 0 ]]; then
    echo "==> Compose E2E failed (exit ${playwright_status})"
    exit "${playwright_status}"
fi

echo "==> Compose E2E passed"
