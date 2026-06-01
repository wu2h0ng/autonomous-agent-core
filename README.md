# AI Native Business Data Agent OS

> Independent implementation project for AI Native Business Data Agent OS.  
> Project directory: `data-agent-os/`.

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
