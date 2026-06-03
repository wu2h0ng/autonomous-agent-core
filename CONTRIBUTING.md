# Contributing

## Development Boundary

`data-agent-os/` is the independent product implementation root.

FaSoLa and other customer systems are Customer-0 or reference sources only. Do not import customer-specific code into `packages/os_core/`.

## Local Checks

Run before every PR:

```bash
make ci
```

Or run individual checks:

```bash
make lint            # ruff check .
make format-check    # ruff format --check .
make unit            # unit tests
make eval            # eval tests
make test            # unit + eval
```

CI uses the same commands. If CI fails, the failure must not be overridden by local results.

## Workflow

1. Start from a scoped issue or approved task.
2. Update contracts before implementation when behavior crosses module boundaries.
3. Add or update tests before claiming completion.
4. Keep OS Core independent from domain packs, providers, connectors, and examples.
5. Submit a PR with the template completed.

## Pull Request Requirements

Every PR must explain:

- What changed.
- Why it changed.
- Which module boundary it touches.
- Whether contracts changed.
- Which tests or eval cases were added or updated.
- Whether SQL Safety, EvidenceChain, Trace, permissions, or actions are affected.

## Architecture Changes

Changes touching architecture, contracts, security, Agent Runtime, SQL Safety, EvidenceChain, action governance, providers, connectors, deployment, or R4/R5 behavior require an ADR or architecture review before implementation.

## Code Agent Rules

Code agents must follow `AGENTS.md`.

Do not:

- Bypass Contract, SQL Safety, EvidenceChain, Eval, Trace, CI, or review.
- Add external Agent frameworks as product Core runtime dependencies.
- Store or emit secrets.
- Claim delivery without tests.
