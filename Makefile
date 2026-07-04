# Makefile — AI Native Business Data Agent OS CI Local Parity
# All CI checks can be reproduced locally by running: make ci

PYTHON      ?= python
PYTHONPATH   = packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src
EVAL_THRESHOLDS_FILE ?= tests/eval/golden_thresholds.json
EVAL_THRESHOLD_REPORT_OUT ?= .agent_runs/eval-threshold-report/golden-threshold-report.json
PUSH_EXPECTED_HEAD ?= $(shell git rev-parse HEAD 2>/dev/null)
PUSH_EXPECTED_HEAD_ARG = $(if $(PUSH_EXPECTED_HEAD),--expected-head $(PUSH_EXPECTED_HEAD),)

.PHONY: bootstrap-dev check-ci-env check-dev-env lint format-check unit eval eval-threshold-report test openapi-contract push-authorization-check current-state-verification-check rc-branch-verification-check ci ci-local-full

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

push-authorization-check:
	$(PYTHON) scripts/release_gate/push_authorization_check.py $(PUSH_EXPECTED_HEAD_ARG)

current-state-verification-check:
	$(PYTHON) scripts/release_gate/current_state_verification_check.py

rc-branch-verification-check:
	$(PYTHON) scripts/release_gate/rc_branch_verification_check.py

ci: check-ci-env lint format-check unit eval eval-threshold-report openapi-contract
	@echo "=== All CI checks passed ==="

ci-local-full: check-dev-env ci
	@echo "=== Full local CI parity checks passed ==="
