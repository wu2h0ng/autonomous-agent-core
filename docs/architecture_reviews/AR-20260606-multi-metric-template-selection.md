# AR-20260606 Multi-metric SQL template selection

> Status: Accepted
> Scope: `TrustedLoopRuntime` public constructor + query-planning behavior, `query_runtime.TemplateRegistry`, content_commerce domain pack.

## Problem

`TrustedLoopRuntime` was constructed with a single `sql_template` and `run()` used
`self.sql_template` unconditionally, regardless of which metric the intent resolved to.
With a domain pack that defines multiple metrics (gmv, roi, conversion_rate, spend) but
only one template, asking for any non-gmv metric would execute the gmv SQL while labelling
the evidence with the requested metric — a correctness and trust defect (the EvidenceChain
would not reproduce the stated metric).

## Decision

Introduce `TemplateRegistry` (in `agent_os_core.query_runtime`): a metric-keyed resolver of
`SQLTemplate`.

- `TrustedLoopRuntime` accepts `template_registry: TemplateRegistry | None` OR a single
  `sql_template: SQLTemplate | None` (exactly one must be provided).
- Back-compat: when only `sql_template` is given, the runtime builds a single-entry registry
  via `TemplateRegistry.from_single(template)`, where that template is also the **default**
  fallback — preserving the prior "always use the one template" behavior for existing callers.
- `run()` resolves the metric first, then `template = template_registry.resolve(metric_name)`
  and uses THAT template for the QueryPlan and all SQL-safety parameters.
- **Failure path:** in multi-template mode (no default), resolving a metric with no registered
  template raises `ValueError("No SQL template registered for metric '<m>'")` — a metric that
  the pack does not yet support fails loudly instead of silently running the wrong SQL.

The runtime factory now loads ALL templates from the domain pack and builds a strict
`TemplateRegistry` (no default). The content_commerce pack gains a real second template
(`spend`) plus a `spend` column in the reference seed, so the factory genuinely serves two
metrics with different SQL against real data.

## Compatibility

- All existing callers pass `sql_template=` (single) → unchanged behavior (single-entry registry
  with default fallback). Verified by the existing unit/eval suite staying green.
- `roi` and `conversion_rate` were template-less at first (asking for them raised the explicit
  failure above); their templates and the `visits` seed column were added in a follow-up slice, so
  the content_commerce pack now serves gmv, spend, roi, conversion_rate. A metric defined in the
  pack but still without a template continues to block with `NO_TEMPLATE`.

## Verification

- `TemplateRegistry` unit tests (resolve hit, miss raises, single-default fallback, duplicate-metric guard).
- Runtime selection test: a 2-template registry makes `run()` emit the metric-matching SQL in the
  EvidenceChain QueryPlan; missing metric raises.
- Factory sqlite test: gmv and spend questions return different real aggregates from the seed.
