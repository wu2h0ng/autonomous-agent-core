#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../../.."

echo "=== ruff ==="
ruff check packages/os_core/src/agent_os_core/srl_*.py tests/product/test_srl_runtime_invariants.py

echo "=== pyright ==="
pyright packages/os_core/src/agent_os_core/srl_*.py tests/product/test_srl_runtime_invariants.py

echo "=== RED tests ==="
pytest tests/product/test_srl_runtime_invariants.py -v

echo "=== Product regression ==="
pytest tests/product/ -q

echo "=== M0 verification complete ==="
