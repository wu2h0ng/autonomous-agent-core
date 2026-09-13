# P-TERMINAL-CODING-AGENT-1 Verification

> Date: 2026-07-26
> Result: `TARGETED_GREEN / FULL_REPOSITORY_BASELINE_NOT_GREEN`
> Claim ceiling: `IMPLEMENTED_LOCAL / TARGETED_TESTED / STUB_PROVIDER_E2E / NOT_REVIEWED`

## Targeted terminal verification

```text
.venv/bin/pytest -q tests/product/test_terminal_chat_loop.py
21 passed in 4.71s
```

Coverage includes multi-turn tool feedback, a deterministic failing-test repair,
proposal whitelist, policy denial, exact-edit failure, search/glob/grep, path escape,
inside/outside symlinks, interactive edit/shell confirmation, headless write denial,
shell allowlist, provider-secret environment exclusion, loop detection, HTTP stub CLI
end to end, REPL smoke, Ctrl-C correction audit, sealed configuration/provider
receipts, least-privilege candidate envelope and closed Session/Turn contracts.

## Related regression verification

The provider/capability/task-configuration/workflow subset produced:

```text
178 passed, 16 failed
```

All 16 failures are in `test_provider_trajectory_binding.py` and fail before the tested
provider path because fixed commitment timestamps have expired relative to
2026-07-26.

Full Product suite:

```text
.venv/bin/pytest tests/product -q
1614 passed, 1 skipped, 18 failed in 74.30s
```

Failure set:

- 16 fixed-date expiry failures in `test_provider_trajectory_binding.py`;
- 2 full-suite order/time-sensitive SPINE-0 failures.

The two SPINE-0 failures pass when run directly:

```text
2 passed in 0.84s
```

No terminal test failed in the full run. The full repository gate remains red and is
not reported as passed.

## Static analysis

```text
.venv/bin/ruff check apps packages/contracts/src packages/os_core/src tests/product
All checks passed!
```

Changed terminal/provider/capability files:

```text
.venv/bin/pyright <changed terminal/provider/capability files>
0 errors, 0 warnings, 0 informations
```

Full Product Pyright:

```text
.venv/bin/pyright apps packages/contracts/src packages/os_core/src tests/product
40 errors, 0 warnings, 0 informations
```

Those errors are outside the terminal slice and concentrate in the pre-existing
`workflow.py`, mandate outcome-portfolio code and related tests. They were not modified
to make this package appear green.

## Build

Both package wheels built successfully:

```text
uv build --wheel ... packages/contracts
Successfully built agent_os_contracts-0.1.0-py3-none-any.whl

uv build --wheel ... packages/os_core
Successfully built agent_os_core-0.1.0-py3-none-any.whl
```

## State and Git checks

```text
git diff --check
passed in the target repository and parent repository

yaml.safe_load(docs/CURRENT_STATE.yaml, ../docs/CURRENT_STATE.yaml)
passed
```

The target branch remains a mixed dirty worktree with unrelated modified/untracked
files. Terminal-package files are unstaged and uncommitted; no commit, push, PR, merge
or release was performed.

## Live-provider and review gates

At verification time:

```text
AGENT_OS_PROVIDER_BASE_URL=unset
AGENT_OS_PROVIDER_MODEL=unset
PROVIDER_API_KEY=unset
```

Therefore:

- real-provider coding task: `NOT_RUN`;
- independent exact-diff technical/security review: `NOT_RUN`;
- usable-alpha claim: `NOT_AUTHORIZED`;
- production sandbox, parity, push, merge and release: `NOT_ESTABLISHED`.
