# AI Native Business Data Agent OS

> Independent implementation project for AI Native Business Data Agent OS.  
> Project directory: `ai-native-business-data-agent-os/`.

## Boundary

This repository is the product implementation root.

FaSoLa is only Customer-0, Reference Domain Pack, and Connector source material. OS Core must not import FaSoLa monorepo modules or content-commerce-specific logic.

## First Trusted Loop

The first implementation slice is:

```text
BusinessIntent
  -> MetricContract
  -> SQLTemplate / QueryPlan
  -> SQL Safety
  -> QueryResult
  -> EvidenceChain
  -> ActionProposal
  -> Feedback / Trace
```

Current code provides a pure-Python reference loop with no external runtime dependency.

The application boundary now provides a local runtime factory and CLI smoke entry point:

```bash
set PYTHONPATH=apps/api_server/src;packages/contracts/src;packages/os_core/src
python -m agent_os_api.cli --question "GMV" --start-date 2026-05-25 --end-date 2026-06-01 --limit 100
```

The CLI loads `domain_packs/content_commerce/` and invokes the same Trusted Loop tested by
the unit/eval suite.

## Layout

```text
packages/os_core/       self-developed OS Core and Agent Runtime
packages/contracts/     public contracts and shared data objects
packages/sdk/           external SDK boundary
apps/api_server/        future API application
apps/workspace/         future user workspace UI
domain_packs/           domain-specific packs
providers/              data providers behind contracts
action_connectors/      controlled action connectors
examples/               Customer-0 and integration examples
tests/                  unit, integration, eval, smoke
```

## Local Smoke

```bash
python -m unittest discover -s tests -p "test_*.py"
```

## Core Rule

Agent OS Core and Agent Runtime are self-developed. Open-source Agent frameworks may be studied as references only and must not become product Core runtime dependencies.
