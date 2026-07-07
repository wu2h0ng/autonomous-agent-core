#!/usr/bin/env bash
# migrate.sh — run Alembic migrations for the Agent OS persistence layer.
#
# Usage:
#   ./scripts/migrate.sh           # upgrade to latest revision (head)
#   ./scripts/migrate.sh --dry     # print the command without executing
#   AGENT_OS_DATABASE_URL=... ./scripts/migrate.sh
#
# The script runs from the repository root so the Alembic config at
# packages/persistence/alembic.ini resolves correctly.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ALEMBIC_INI="${REPO_ROOT}/packages/persistence/alembic.ini"

# Allow callers to override the Python interpreter (e.g. `PYTHON=/path/to/python`).
PYTHON="${PYTHON:-python}"

if [[ ! -f "${ALEMBIC_INI}" ]]; then
    echo "Error: Alembic config not found at ${ALEMBIC_INI}" >&2
    exit 1
fi

cd "${REPO_ROOT}"

CMD=("${PYTHON}" -m alembic -c "${ALEMBIC_INI}" upgrade head)

if [[ "${1:-}" == "--dry" ]]; then
    echo "Would run: ${CMD[*]}"
    exit 0
fi

echo "==> Running Alembic migrations: ${CMD[*]}"
"${CMD[@]}"
