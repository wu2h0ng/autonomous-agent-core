# ADR-20260707: Semantic graph slice (LinkType / SemanticGraph)

- Status: **Accepted — slice delivered (flag-off default unchanged)**
- Date: 2026-07-07
- Parent: `docs/research/competitive-grounding-2026-07-07.md` §6
- Scope: Typed object-relation graph for Palantir Ontology parity (skeleton only)

## Context

Competitive grounding identified the largest remaining gap vs Palantir Ontology as the
absence of a typed object-relation graph. `SemanticObject` was a flat leaf list with no
link types, properties, or traversal.

## Decision

Deliver a **minimal but real** semantic graph slice in OS Core + contracts:

1. `ObjectProperty` on `SemanticObject` (default empty = backward compatible)
2. `LinkType` + `ObjectLink` contracts
3. `SemanticGraph` registry with adjacency + path queries
4. `SemanticRegistry.graph` integration + domain-pack loader (`semantic_objects.json`)

## Non-goals (this slice)

- Ontology editor UI
- Auto-inference of links from data
- Replacing `MetricContract` as the trusted-definition layer

## Verification

- `tests/unit/test_semantic_graph.py` — properties, link types, traversal, path queries
- `tests/unit/test_semantic_registry_graph.py` — registry + graph wiring
- `tests/unit/test_domain_pack_semantic_objects.py` — content_commerce graph load
- `domain_packs/content_commerce/semantic_objects.json` — campaign → product → order chain

## Entry points

- Runtime: `ContentCommerceRuntimeFactory` builds `SemanticRegistry` with graph from domain pack
- Evidence/lineage: `SemanticRegistry.neighbors()` for relation-aware consumers (future slices)

## Boundaries

- OS Core remains domain-independent; graph **data** lives in domain packs only
- No product claim of full Palantir Ontology parity — skeleton + Customer-0 reference graph only

## Next slices (future)

- EvidenceChain lineage fields traversing `SemanticGraph.paths()`
- HTTP read surface for internal semantic graph (optional, ADR required)
- Link inference from provider metadata (research / ADR gate)
