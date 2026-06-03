# Makefile — data-agent-os CI Local Parity
# All CI checks can be reproduced locally by running: make ci

PYTHON      ?= python
PYTHONPATH   = packages/contracts/src:packages/os_core/src:packages/sdk/src:action_connectors

.PHONY: lint format-check unit eval test ci

lint:
	$(PYTHON) -m ruff check .

format-check:
	$(PYTHON) -m ruff format --check .

unit:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m unittest discover -s tests -p "test_*.py" -v

eval:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m unittest discover -s tests/eval -p "test_*.py" -v

test: unit eval

ci: lint format-check unit eval
	@echo "=== All CI checks passed ==="
