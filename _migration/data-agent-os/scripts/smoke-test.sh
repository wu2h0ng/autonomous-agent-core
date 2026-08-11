#!/usr/bin/env bash
# smoke-test.sh — end-to-end smoke test for the containerized Agent OS stack.
#
# Usage:
#   ./scripts/smoke-test.sh          # start stack, run tests, leave it up
#   ./scripts/smoke-test.sh --down   # stop and remove containers/volumes after tests
#   ./scripts/smoke-test.sh --no-start  # assume stack is already running
#
# The script exercises the public API surface: health probe, governed run that
# produces an approval-required business action, operator approval execution,
# and outcome recording. It exits non-zero on the first failed step.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${SMOKE_ENV_FILE:-${REPO_ROOT}/.env}"
COMPOSE_FILES=(-f "${REPO_ROOT}/docker-compose.yml")

PYTHON="${PYTHON:-python}"

cd "${REPO_ROOT}"

if [[ ! -f "${ENV_FILE}" ]]; then
    echo "==> Creating .env from .env.example"
    cp "${REPO_ROOT}/.env.example" "${ENV_FILE}"
fi

set -a
# shellcheck source=/dev/null
source "${ENV_FILE}"
set +a

if [[ "${AGENT_OS_SMOKE_STAGED_OUT:-false}" == "true" ]]; then
    COMPOSE_FILES+=(-f "${REPO_ROOT}/docker-compose.staging.yml")
    echo "==> Staging overlay enabled (C/D/E flags on via docker-compose.staging.yml)"
fi

API_PORT="${API_PORT:-8000}"
API_URL="http://localhost:${API_PORT}"
API_KEY="${AGENT_OS_API_KEY:-dev-internal-key}"
OPERATOR_KEY="${AGENT_OS_OPERATOR_API_KEY:-dev-operator-key}"

DO_START=1
DO_DOWN=0

for arg in "$@"; do
    case "${arg}" in
        --down)
            DO_DOWN=1
            ;;
        --no-start)
            DO_START=0
            ;;
        *)
            echo "Usage: $0 [--down] [--no-start]"
            exit 1
            ;;
    esac
done

cleanup() {
    if [[ "${DO_DOWN}" -eq 1 ]]; then
        echo "==> Stopping stack"
        docker compose "${COMPOSE_FILES[@]}" --env-file "${ENV_FILE}" down --volumes
    fi
}
trap cleanup EXIT

api_call() {
    local method="$1"
    local path="$2"
    local body="${3:-}"
    local extra_headers="${4:-}"
    local url="${API_URL}${path}"
    local headers=(-H "X-API-Key: ${API_KEY}" -H "X-Tenant-Id: default")
    if [[ -n "${extra_headers}" ]]; then
        # shellcheck disable=SC2206
        headers+=(${extra_headers})
    fi
    if [[ "${method}" == "GET" ]]; then
        curl -sf "${headers[@]}" "${url}"
    elif [[ "${method}" == "PUT" ]]; then
        curl -sf -X PUT "${url}" "${headers[@]}" -H "Content-Type: application/json" -d "${body}"
    else
        if [[ -n "${body}" ]]; then
            curl -sf -X "${method}" "${url}" "${headers[@]}" -H "Content-Type: application/json" -d "${body}"
        else
            curl -sf -X "${method}" "${url}" "${headers[@]}"
        fi
    fi
}

operator_api_call() {
    local method="$1"
    local path="$2"
    local body="${3:-}"
    local url="${API_URL}${path}"
    local headers=(-H "X-Operator-Key: ${OPERATOR_KEY}" -H "X-Tenant-Id: default")
    curl -sf -X "${method}" "${url}" "${headers[@]}" -H "Content-Type: application/json" -d "${body}"
}

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
    echo "==> Running database migrations (one-shot api_server container)"
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

if [[ "${DO_START}" -eq 1 ]]; then
    echo "==> Starting postgres"
    docker compose "${COMPOSE_FILES[@]}" --env-file "${ENV_FILE}" up -d --build postgres
    wait_for_postgres
    echo "==> Building api_server image (migrations run inside this image)"
    docker compose "${COMPOSE_FILES[@]}" --env-file "${ENV_FILE}" build api_server
    run_compose_migrations
    echo "==> Starting api_server (API smoke does not require frontend)"
    docker compose "${COMPOSE_FILES[@]}" --env-file "${ENV_FILE}" up -d api_server
fi

wait_for_health

echo "==> Smoke test: health"
api_call GET /health | "${PYTHON}" -m json.tool

echo "==> Smoke test: run that produces approval-required action"
RUN_RESPONSE=$(api_call POST /runs '{
    "question": "GMV 记录行动",
    "parameters": {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100}
}')
echo "${RUN_RESPONSE}" | "${PYTHON}" -m json.tool
TRACE_ID=$(echo "${RUN_RESPONSE}" | "${PYTHON}" -c 'import json,sys; print(json.load(sys.stdin)["trace_id"])')
APPROVAL_ID=$(echo "${RUN_RESPONSE}" | "${PYTHON}" -c 'import json,sys; print(json.load(sys.stdin)["user_result"]["business_action"]["approval_id"])')

echo "==> Smoke test: execute approval ${APPROVAL_ID}"
EXECUTE_RESPONSE=$(operator_api_call POST "/approvals/${APPROVAL_ID}/execute" '{
    "reason": "approved by smoke-test",
    "approved_by": "smoke-test@example.com"
}')
echo "${EXECUTE_RESPONSE}" | "${PYTHON}" -m json.tool
EXECUTED_STATE=$(echo "${EXECUTE_RESPONSE}" | "${PYTHON}" -c 'import json,sys; print(json.load(sys.stdin)["state"])')
if [[ "${EXECUTED_STATE}" != "executed" ]]; then
    echo "==> Approval execution did not reach 'executed' state: ${EXECUTED_STATE}"
    exit 1
fi

echo "==> Smoke test: record outcome for trace ${TRACE_ID}"
OUTCOME_RESPONSE=$(api_call POST /outcomes "{\"trace_id\": \"${TRACE_ID}\", \"outcome\": \"resolved\", \"reviewer\": \"smoke-test\"}")
echo "${OUTCOME_RESPONSE}" | "${PYTHON}" -m json.tool
FEEDBACK_ID=$(echo "${OUTCOME_RESPONSE}" | "${PYTHON}" -c 'import json,sys; print(json.load(sys.stdin)["feedback_id"])')

echo ""
if [[ "${AGENT_OS_SMOKE_STAGED_OUT:-false}" != "true" ]]; then
    echo "==> Smoke test: staged-out management plane (default flags off)"
    STAGED_OUT_CODE=$(curl -s -o /dev/null -w "%{http_code}" -H "X-API-Key: ${API_KEY}" -H "X-Tenant-Id: default" "${API_URL}/workflows")
    if [[ "${STAGED_OUT_CODE}" != "503" ]]; then
        echo "==> Expected /workflows to return 503 when AGENT_OS_FULL_BPM_WORKFLOW is off; got ${STAGED_OUT_CODE}"
        exit 1
    fi
    echo "==> /workflows correctly disabled (503)"
fi

if [[ "${AGENT_OS_SMOKE_STAGED_OUT:-false}" == "true" ]]; then
    echo "==> Smoke test: staged-out C/D/E management plane + trace chain"
    for path in /workflows /mcp/servers; do
        code=$(curl -s -o /dev/null -w "%{http_code}" -H "X-API-Key: ${API_KEY}" -H "X-Tenant-Id: default" "${API_URL}${path}")
        if [[ "${code}" == "503" ]]; then
            echo "==> ${path} still disabled (503) — enable staging overlay + flags"
            exit 1
        fi
    done
    echo "==> Staged-out list endpoints reachable with flags on"

    echo "==> Register workflow (D)"
    api_call POST /workflows '{
        "workflow_id": "wf-smoke-staging",
        "name": "Smoke Staging Workflow",
        "action_type": "execute",
        "risk_levels": ["R3"],
        "state": "active",
        "steps": [{"step_id": "s1", "step_type": "approval", "approver_role": "manager"}]
    }' | "${PYTHON}" -m json.tool

    echo "==> Register MCP server (C)"
    api_call POST /mcp/servers '{
        "server_id": "mcp-smoke-staging",
        "name": "Smoke MCP",
        "state": "active",
        "allowed_scopes": ["read"],
        "risk_ceiling": "R3"
    }' | "${PYTHON}" -m json.tool

    echo "==> Register auto-execution policy (E)"
    api_call PUT /tenants/default/auto-execution-policy '{
        "version": "smoke-v1",
        "owner": "smoke-test",
        "default_mode": "proposal_only",
        "rules": []
    }' | "${PYTHON}" -m json.tool

    echo "==> Start workflow instance bound to trace ${TRACE_ID} (D trace sink)"
    INSTANCE_RESPONSE=$(api_call POST /workflows/wf-smoke-staging/instances "{
        \"proposal_id\": \"${TRACE_ID}\",
        \"started_by\": \"smoke-test\"
    }")
    echo "${INSTANCE_RESPONSE}" | "${PYTHON}" -m json.tool

    echo "==> Verify workflow.started in RunTrace lineage"
    TRACE_RESPONSE=$(api_call GET "/traces/${TRACE_ID}")
    echo "${TRACE_RESPONSE}" | "${PYTHON}" -m json.tool
    if ! echo "${TRACE_RESPONSE}" | "${PYTHON}" -c 'import json,sys; events=json.load(sys.stdin).get("events",[]); sys.exit(0 if any(e.get("step")=="workflow.started" for e in events) else 1)'; then
        echo "==> Expected workflow.started in /traces/${TRACE_ID} events"
        exit 1
    fi
    echo "==> C/D/E trace chain verified on trace ${TRACE_ID}"
fi

echo ""
echo "==> Smoke test passed"
echo "    trace_id:    ${TRACE_ID}"
echo "    approval_id: ${APPROVAL_ID}"
echo "    feedback_id: ${FEEDBACK_ID}"
