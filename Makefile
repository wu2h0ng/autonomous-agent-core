# Makefile — AI Native Business Data Agent OS CI Local Parity
# All CI checks can be reproduced locally by running: make ci

PYTHON      ?= python
PYTHONPATH   = packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src
EVAL_THRESHOLDS_FILE ?= tests/eval/golden_thresholds.json
EVAL_THRESHOLD_REPORT_OUT ?= .agent_runs/eval-threshold-report/golden-threshold-report.json
PUSH_EXPECTED_HEAD ?= $(shell git rev-parse HEAD 2>/dev/null)
PUSH_EXPECTED_HEAD_ARG = $(if $(PUSH_EXPECTED_HEAD),--expected-head $(PUSH_EXPECTED_HEAD),)

.PHONY: bootstrap-dev check-ci-env check-dev-env lint format-check unit eval eval-threshold-report test openapi-contract push-authorization-check current-state-verification-check rc-branch-verification-check controlled-pilot-readiness-check anti-stub-lint anti-stub-lint-all frontend-e2e-check frontend-e2e ci ci-local-full

bootstrap-dev:
	$(PYTHON) -m pip install -e ".[dev,http,postgres]"

check-ci-env:
	$(PYTHON) -c "import importlib.util, sys; missing=[m for m in ('fastapi','httpx','sqlalchemy','psycopg','alembic','ruff') if importlib.util.find_spec(m) is None]; sys.exit('missing ci dependencies for $(PYTHON): '+', '.join(missing)+'; run make bootstrap-dev PYTHON=$(PYTHON) or pass PYTHON=/path/to/.venv/bin/python') if missing else None"

check-dev-env: check-ci-env
	$(PYTHON) -c "import os, sys; sys.exit('AGENT_OS_DATABASE_URL is required for ci-local-full; use a disposable test database') if not os.environ.get('AGENT_OS_DATABASE_URL') else None"

lint:
	$(PYTHON) -m ruff check .

format-check:
	$(PYTHON) -m ruff format --check .

unit:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m unittest discover -s tests -p "test_*.py" -v

eval:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m unittest discover -s tests/eval -p "test_*.py" -v

eval-threshold-report:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m tests.eval.threshold_report --thresholds-file $(EVAL_THRESHOLDS_FILE) --output $(EVAL_THRESHOLD_REPORT_OUT)

test: unit eval

openapi-contract:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m agent_os_api.openapi_contract --check

anti-stub-lint:
	$(PYTHON) scripts/anti_stub_linter.py

anti-stub-lint-all:
	$(PYTHON) scripts/anti_stub_linter.py --all

push-authorization-check:
	$(PYTHON) scripts/release_gate/push_authorization_check.py $(PUSH_EXPECTED_HEAD_ARG)

current-state-verification-check:
	$(PYTHON) scripts/release_gate/current_state_verification_check.py

rc-branch-verification-check:
	$(PYTHON) scripts/release_gate/rc_branch_verification_check.py

controlled-pilot-readiness-check:
	$(PYTHON) scripts/release_gate/controlled_pilot_readiness_check.py $(PUSH_EXPECTED_HEAD_ARG)

frontend-e2e-check:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m unittest tests.unit.test_frontend_playwright_ci -v

frontend-e2e:
	cd apps/workspace/frontend && npm install && npm run test:e2e:install && npm run test:e2e

ci: check-ci-env lint format-check anti-stub-lint unit eval eval-threshold-report openapi-contract frontend-e2e-check
	@echo "=== All CI checks passed ==="

ci-local-full: check-dev-env ci frontend-e2e
	@echo "=== Full local CI parity checks passed ==="
