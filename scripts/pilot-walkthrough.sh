#!/usr/bin/env bash
# pilot-walkthrough.sh — M8 internal pilot walkthrough (default or staging profile).
#
# Runs the same governed loop as smoke-test with human-readable checkpoints.
# Use for operator rehearsal before a customer POC.
#
# Usage:
#   ./scripts/pilot-walkthrough.sh              # default pilot (.env, flags off)
#   ./scripts/pilot-walkthrough.sh --staging    # C/D/E flags on via .env.staging
#   ./scripts/pilot-walkthrough.sh --down       # tear down stack after walkthrough
#
# Does not authorize external release; DEPLOYMENT_PUSH may remain HOLD.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

STAGING=0
SMOKE_ARGS=()

for arg in "$@"; do
    case "${arg}" in
        --staging)
            STAGING=1
            ;;
        --down)
            SMOKE_ARGS+=("--down")
            ;;
        *)
            echo "Usage: $0 [--staging] [--down]"
            exit 1
            ;;
    esac
done

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  M8 Internal Pilot Walkthrough                               ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

if [[ "${STAGING}" -eq 1 ]]; then
    echo "Profile: STAGING (C/D/E flags ON — see docker-compose.staging.yml)"
    echo ""
    echo "Step 0 — Copy .env.staging.example if needed:"
    echo "  cp .env.staging.example .env.staging"
    echo ""
    echo "Step 1 — Start stack + verify Trusted Loop + C/D/E trace chain:"
    echo "  make smoke-test-staging SMOKE_ARGS=\"${SMOKE_ARGS[*]}\""
    echo ""
    if [[ ! -f "${REPO_ROOT}/.env.staging" ]]; then
        echo "==> Creating .env.staging from .env.staging.example"
        cp "${REPO_ROOT}/.env.staging.example" "${REPO_ROOT}/.env.staging"
    fi
    make -C "${REPO_ROOT}" smoke-test-staging SMOKE_ARGS="${SMOKE_ARGS[*]:-}"
else
    echo "Profile: DEFAULT PILOT (staged-out flags OFF)"
    echo ""
    echo "Step 1 — Health → Run → Approval execute → Outcome:"
    echo "  ./scripts/smoke-test.sh ${SMOKE_ARGS[*]:-}"
    echo ""
    echo "Step 2 — Workspace UI (optional, separate terminal):"
    echo "  docker compose up -d   # or scripts/start-local.sh"
    echo "  open http://localhost:3000"
    echo "  - Run GMV preset → View run report → Execution Trace"
    echo "  - /knowledge catalog (live API)"
    echo ""
    echo "Step 3 — Compose live API E2E (browser against real API):"
    echo "  ./scripts/compose-e2e.sh ${SMOKE_ARGS[*]:-}"
    echo ""
    "${REPO_ROOT}/scripts/smoke-test.sh" "${SMOKE_ARGS[@]}"
fi

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  Walkthrough complete — record trace_id in pilot log         ║"
echo "║  DEPLOYMENT_PUSH / release tags remain separate gates        ║"
echo "╚══════════════════════════════════════════════════════════════╝"
