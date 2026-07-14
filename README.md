# Agent OS

`autonomous-agent-core` is the historical repository name. This repository is the canonical **Agent OS monorepo**, with a Product Track and a separately evidenced Research Track.

Agent OS is a persistent, governed work operating system that turns goals into inspectable commitments, executable work, verified outcomes and reusable learning across models, tools, data and time.

## Start here

1. [`docs/AGENT-OS-PRODUCT-BLUEPRINT.md`](docs/AGENT-OS-PRODUCT-BLUEPRINT.md) — product definition and completion gates.
2. [`docs/CURRENT_STATE.yaml`](docs/CURRENT_STATE.yaml) — current implementation, research truth, active work and blockers.
3. [`docs/PROJECT_PLAN.md`](docs/PROJECT_PLAN.md) — authorized execution order.
4. [`ROADMAP.md`](ROADMAP.md) — dependency horizon.
5. [`codebase_index.md`](codebase_index.md) — module and evidence navigation.
6. [`AGENTS.md`](AGENTS.md) / [`CLAUDE.md`](CLAUDE.md) — repository rules.

Do not use this README for live test counts, branch state or research verdicts.

## Product and research boundary

### Product Track

Owns the Agent Surface, Task Workspace, durable Runtime, providers/credentials, typed capabilities, workflows, evidence/outcomes, knowledge, policy/correction, SDK and domain packs.

```text
packages/contracts/
packages/os_core/
apps/api_server/
apps/cli/
domain_packs/developer_agent/
tests/product/
```

### Research Track

Owns falsifiable mechanism research, formal models, preregistration, simulations/real-data probes, result artifacts and negative-result maps. Research does not become a product dependency or product claim by sharing the repository.

```text
src/aac/
src/envs/
experiments/
tests/
docs/research/
```

Product code must not import raw research modules as authority. Promotion requires a stable contract, named product consumer, held-out comparison and explicit review.

## Canonical product terms

- **Agent OS** — product.
- **Agent Core** — internal provider-neutral Runtime/Kernel.
- **Agent Surface** — one user experience with `Ask` and `Work`.
- **Task Workspace** — durable environment for consequential work.
- **Data Agent** — first enterprise domain pack.
- **Capability** — typed operation; an external “skill” is only a compatibility input.
- **C7** — non-writable, non-bypassable external correction authority.

World models are plural. CWM is optional and evidence-gated; LLMs are probabilistic language/reasoning organs and never hold final execution authority.

## Data Agent transition

`ai-native-business-data-agent-os` remains a physically independent, standing product implementation and migration donor until ADR-0054/SPINE-1 passes its history-safety, provenance, extraction and review gates.

There is no runtime cross-import. Planning authorization does not mean the migration has executed, and it does not authorize push, merge or release.

## Product commands

```bash
uv run --extra product-test pytest tests/product -q
uv run --extra product-test ruff check apps packages/contracts/src packages/os_core/src tests/product
uv run --extra product-test pyright apps packages/contracts/src packages/os_core/src tests/product
uv build --wheel --out-dir /tmp/agent-os-product-wheel packages/contracts
uv build --wheel --out-dir /tmp/agent-os-product-wheel packages/os_core
```

Use the exact commands and source references in `docs/CURRENT_STATE.yaml` when reproducing a dated verification claim.

## Research commands

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

Do not run a result-bearing experiment unless its route, architecture review, preregistration, lock and authority gates are satisfied. A script existing in `experiments/` is not run authorization.

## Hard boundaries

- No business/data-domain semantics in Agent Core.
- No untyped model output directly becomes a consequential command.
- No model, plugin, subagent or learned procedure owns final authority.
- No L4 active-runtime self-modification or L5 safety-substrate self-edit.
- No retuning, reseeding or gate movement to rescue a research result.
- No product, autonomy, generality or superiority claim without a named envelope and evidence.
- No migration, push, merge, automatic execution or release without its own explicit gate.
