#!/usr/bin/env bash
# start-local.sh — one-command local launch for AI Native Business Data Agent OS
#
# Usage:
#   ./scripts/start-local.sh          # start all services in detached mode
#   ./scripts/start-local.sh --down   # stop and remove containers/volumes
#   ./scripts/start-local.sh --logs   # tail logs after starting
#
# This script is a thin wrapper around `docker compose` that:
#   1. Ensures a local .env file exists (copies .env.example if missing).
#   2. Builds/starts postgres + api_server + frontend.
#   3. Waits for the API server health check.
#   4. Prints the local URLs.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

COMPOSE_FILES=(-f "${REPO_ROOT}/docker-compose.yml")
ENV_FILE="${REPO_ROOT}/.env"

cd "${REPO_ROOT}"

# Ensure .env exists so docker compose has variables to substitute.
if [[ ! -f "${ENV_FILE}" ]]; then
    echo "==> Creating .env from .env.example (edit it to change secrets)"
    cp "${REPO_ROOT}/.env.example" "${ENV_FILE}"
fi

# Source .env so this script can use the same defaults.
set -a
# shellcheck source=/dev/null
source "${ENV_FILE}"
set +a

show_urls() {
    echo ""
    echo "==> Agent OS is running locally"
    echo "    Frontend UI: http://localhost:${FRONTEND_PORT:-3000}"
    echo "    API docs:    http://localhost:${API_PORT:-8000}/docs"
    echo "    OpenAPI:     http://localhost:${API_PORT:-8000}/openapi.json"
    echo "    Database:    localhost:${POSTGRES_PORT:-5432}"
}

wait_for_api() {
    local url="http://localhost:${API_PORT:-8000}/docs"
    echo "==> Waiting for API server at ${url} ..."
    for _ in {1..60}; do
        if curl -sf "${url}" >/dev/null 2>&1; then
            echo "==> API server is healthy"
            return 0
        fi
        sleep 1
    done
    echo "==> API server did not become healthy within 60s; check logs with: docker compose logs api_server"
    return 1
}

main() {
    case "${1:-up}" in
        --down | down)
            echo "==> Stopping and removing local Agent OS services"
            docker compose "${COMPOSE_FILES[@]}" --env-file "${ENV_FILE}" down --volumes
            ;;
        --logs | logs)
            docker compose "${COMPOSE_FILES[@]}" --env-file "${ENV_FILE}" logs -f
            ;;
        up | --up | "")
            echo "==> Building and starting Agent OS services"
            docker compose "${COMPOSE_FILES[@]}" --env-file "${ENV_FILE}" up -d --build
            wait_for_api
            show_urls
            ;;
        *)
            echo "Usage: $0 [up|--down|--logs]"
            exit 1
            ;;
    esac
}

main "$@"
