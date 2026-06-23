# Makefile — AI Native Business Data Agent OS CI Local Parity
# All CI checks can be reproduced locally by running: make ci

PYTHON      ?= python
PYTHONPATH   = packages/contracts/src:packages/os_core/src:packages/persistence/src:packages/sdk/src:action_connectors:apps/api_server/src

.PHONY: bootstrap-dev check-dev-env lint format-check unit eval test openapi-contract ci ci-local-full

bootstrap-dev:
	$(PYTHON) -m pip install -e ".[dev,http,postgres]"

check-dev-env:
	$(PYTHON) -c "import os; missing=[m for m in ('fastapi','httpx','sqlalchemy','psycopg','alembic','ruff') if __import__(m) is None]; dsn=os.environ.get('AGENT_OS_DATABASE_URL'); raise SystemExit('AGENT_OS_DATABASE_URL is required for ci-local-full; use a disposable test database') if not dsn else None"

lint:
	$(PYTHON) -m ruff check .

format-check:
	$(PYTHON) -m ruff format --check .

unit:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m unittest discover -s tests -p "test_*.py" -v

eval:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m unittest discover -s tests/eval -p "test_*.py" -v

test: unit eval

openapi-contract:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m agent_os_api.openapi_contract --check

ci: lint format-check unit eval
	@echo "=== All CI checks passed ==="

ci-local-full: check-dev-env ci openapi-contract
	@echo "=== Full local CI parity checks passed ==="
