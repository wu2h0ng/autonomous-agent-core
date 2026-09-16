# Content Commerce Domain Pack

Reference domain pack for Customer-0 style scenarios.

This package may depend on public contracts but must not be imported by OS Core.

## Files

- `metrics.json`: reference `MetricContract` definitions for the first content commerce loop.
- `providers.json`: reference `ProviderContract` definitions.
- `sql_templates.json`: safe SQL templates for local/eval execution.

The API/application layer may load this pack. `packages/os_core/` must never import it.
