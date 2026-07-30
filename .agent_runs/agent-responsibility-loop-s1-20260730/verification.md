# Verification

Pre-implementation RED:

```text
ModuleNotFoundError: No module named 'agent_os_core.responsibility_loop'
```

Post-implementation targeted test:

```text
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
uv run --extra product-test pytest tests/product/test_responsibility_loop.py -q
8 passed
```

Quality:

```text
uv run ruff check packages/os_core/src/agent_os_core/responsibility_loop.py \
  tests/product/test_responsibility_loop.py
All checks passed
```

Pyright is rerun after the test narrowing assertion in the final verification
step. No full Product suite, CLI fixture, merge or release is claimed here.
