#!/usr/bin/env bash
# Scoped commits for ADR-0013 productization (founder-authorized).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

commit_pkg() {
  local msg="$1"
  shift
  if git diff --quiet && git diff --cached --quiet && [ -z "$(git ls-files --others --exclude-standard "$@" 2>/dev/null)" ]; then
    echo "==> SKIP (empty): $msg"
    return 0
  fi
  git add "$@"
  if git diff --cached --quiet; then
    echo "==> SKIP (nothing staged): $msg"
    return 0
  fi
  git commit -m "$msg"
  echo "==> OK: $msg"
}

commit_pkg "feat(contracts): ADR-0013 PKG-01 typed contracts and feature flags" \
  packages/contracts/

commit_pkg "feat(persistence): ADR-0013 PKG-02 alembic 0010-0014 and SQL adapters" \
  packages/persistence/

commit_pkg "feat(os-core): ADR-0013 PKG-03 data fabric and federated query compiler" \
  packages/os_core/src/agent_os_core/data_product_compiler/ \
  packages/os_core/src/agent_os_core/query_runtime/csv_executor.py \
  packages/os_core/src/agent_os_core/metric_contract_loader.py \
  packages/os_core/src/agent_os_core/_metric_aliases.py \
  domain_packs/content_commerce/metrics.json \
  domain_packs/content_commerce/metrics/ \
  domain_packs/content_commerce/sql_templates.json

commit_pkg "feat(sdk): ADR-0013 PKG-04 domain pack SDK loader" \
  packages/sdk/ \
  domain_packs/content_commerce/manifest.yaml

commit_pkg "feat(os-core): ADR-0013 PKG-05 semantic graph and evidence lineage" \
  packages/os_core/src/agent_os_core/semantic_runtime/ \
  packages/os_core/src/agent_os_core/evidence_chain/ \
  domain_packs/content_commerce/semantic_objects.json

commit_pkg "feat(os-core): ADR-0013 PKG-06 MCP gateway runtime" \
  packages/os_core/src/agent_os_core/mcp_gateway/ \
  packages/contracts/src/agent_os_contracts/mcp_gateway.py

commit_pkg "feat(os-core): ADR-0013 PKG-07 full BPM workflow engine and store" \
  packages/os_core/src/agent_os_core/workflow.py \
  packages/os_core/src/agent_os_core/workflow_store.py

commit_pkg "feat(os-core): ADR-0013 PKG-08 policy engine and R4/R5 auto-execution" \
  packages/os_core/src/agent_os_core/policy_engine.py \
  packages/os_core/src/agent_os_core/approval_router.py \
  packages/os_core/src/agent_os_core/operation_state_machine.py

commit_pkg "feat(api): ADR-0013 PKG-09 CDE integration, staged-out HTTP, heavy infra adapters" \
  apps/api_server/ \
  packages/os_core/src/agent_os_core/agent_runtime/

commit_pkg "feat(os-core): ADR-0013 PKG-10 phase 2-5 surfaces tenant usage quota deploy" \
  packages/os_core/src/agent_os_core/nl_query/ \
  packages/os_core/src/agent_os_core/conversation/ \
  packages/os_core/src/agent_os_core/alert_agent/ \
  packages/os_core/src/agent_os_core/tenant/ \
  packages/os_core/src/agent_os_core/usage/ \
  packages/os_core/src/agent_os_core/quota_gate/ \
  packages/os_core/src/agent_os_core/dashboard/ \
  packages/os_core/src/agent_os_core/report/ \
  packages/os_core/src/agent_os_core/trusted_loop.py \
  packages/os_core/src/agent_os_core/action_governance/ \
  packages/os_core/src/agent_os_core/approval_lite/ \
  packages/os_core/src/agent_os_core/feedback/ \
  packages/os_core/src/agent_os_core/knowledge_memory/ \
  packages/os_core/src/agent_os_core/knowledge_retrieval/ \
  packages/os_core/src/agent_os_core/adoption/ \
  packages/os_core/src/agent_os_core/snapshot_store/ \
  packages/os_core/src/agent_os_core/sql_safety/ \
  packages/os_core/src/agent_os_core/trace/ \
  packages/os_core/src/agent_os_core/query_runtime/__init__.py \
  packages/os_core/src/agent_os_core/data_product_compiler/__init__.py \
  packages/os_core/src/agent_os_core/__init__.py \
  scripts/migrate.sh scripts/smoke-test.sh scripts/start-local.sh \
  scripts/anti_stub_linter.py scripts/hardcoded_sql_ratio.py \
  Dockerfile docker-compose.yml Makefile pyproject.toml

commit_pkg "feat(frontend): ADR-0013 PKG-11 F3+ live API workspace and Playwright E2E" \
  apps/workspace/frontend/

commit_pkg "test: ADR-0013 PKG-12 unit eval and redteam regression suite" \
  tests/

commit_pkg "docs: ADR-0013 PKG-13 governance ADRs AR freeze and current state" \
  docs/ AGENTS.md

# Any remaining os_core / contracts stragglers
if ! git diff --quiet || ! git diff --cached --quiet || [ -n "$(git ls-files --others --exclude-standard)" ]; then
  commit_pkg "chore: ADR-0013 remaining os_core and workspace stragglers" \
    packages/os_core/ apps/workspace/ || true
fi

git status --short
echo "=== Scoped commits complete ==="
