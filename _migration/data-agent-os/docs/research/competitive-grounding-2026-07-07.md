# Competitive grounding — terminal product form (2026-07-07)

- Identity: `research-director` view, grounding ADR-0013 concurrent build toward terminal product form.
- Sources: internal `docs/project_baseline/02_竞争格局与商业化/` (Aloudata deep-dive) + external Palantir Foundry/Ontology docs (fetched 2026-07-07, palantir.com/docs/foundry/ontology/why-ontology).
- Purpose: identify which remaining engineering slices are competitive gaps, not just feature parity, so the build moves toward the real end state.

## 1. Palantir Ontology — the four elements + three moats

Palantir's Ontology unifies four elements into one resource that drives decisions:

1. Semantic model / data — objects, links, properties bound to real data.
2. Logic assets — calculations/processes that evaluate decisions.
3. Action / decision capture — executed decisions captured back into the ontology (operational, edge-included).
4. Operational synchronization — executed decisions written back to operational systems.

Three moats: dynamic lineage across data/logic/action/application; security beyond role-based (attribute/markings + change/release mgmt for human and agentic workflows); change management over agentic workflows.

## 2. Aloudata — domestic data-foundation moat

AIR (data fabric) + BIG (active metadata) + CAN (NoETL metric platform) + Agent (analysis). Project verdict: match their data foundation, extend into the action/knowledge loop they lack.

## 3. Mapping — gap matrix

| Capability | Project asset | Gap |
|---|---|---|
| Semantic model | SemanticObject lite, MetricContract | lite only; no link/relation graph |
| Logic assets | QueryRuntime, SQL Safety, DataProductCompiler | OK for MVP |
| Decision capture + writeback | ActionProposal→Approval→OperationTrace, action_record | durable PolicyApprovalRecord + R4/R5 end-to-end wiring = the gap |
| Dynamic lineage data→logic→action→app | 4-layer metadata | C/D OperationTrace not wired = lineage breaks at action layer |
| Security beyond RBAC | minimal principal/scope matrix | not full ABAC; future |
| Change mgmt for agentic workflows | RuntimePolicyGate, CorrigibilityShell, feature flags | runtime selection point (ApprovalLite vs WorkflowRuntime) not wired = routing gap |
| Aloudata CAN NoETL metric auto-derivation | MetricContract + DataProductCompiler v1 | auto-derivation partial |

## 4. Conclusion — the remaining slices ARE the competitive gaps

1. C/D OperationTrace wiring = Palantir dynamic lineage. Without it lineage breaks where Palantir is strongest.
2. Durable PolicyApprovalRecord = Palantir decision capture + audit. In-memory cannot survive restart.
3. Runtime selection point = Palantir agentic-workflow change management. Without routing the BPM engine is unreachable from a real entry point (AGENTS.md boundary #8).

These three are this turn's priority. G (Temporal/OPA/Trino) stays on-demand. ABAC/marking stays future.

## 5. Positioning confirmation

- Slogan valid: AI-ready Data Foundation subset Agent-ready Business Operation.
- vs Palantir: EvidenceChain-first (trust per-number not per-ontology) + lighter/open delivery (Provider/DomainPack/Connector SDK).
- vs Aloudata: closing the loop into governed action + knowledge asset, which their stack stops short of.

## 6. Semantic layer deepening — link/relation graph (next high-leverage slice)

The single largest remaining competitive gap vs Palantir Ontology is the absence
of a typed object-relation graph. Current ``SemanticObject`` is a flat leaf
(name, type, owner, aliases) with no:

- **Object properties** — typed fields bound to real data columns.
- **Link types** — named, typed relations between object types (campaign -> product -> order).
- **Relation traversal** — path queries over the graph for evidence/lineage.

Palantir Ontology's four elements rest on this graph: without it, "dynamic
lineage across data, logic, action" has no skeleton to traverse.

### Design input (accepted)

- Extend ``SemanticObject`` with ``properties: tuple[ObjectProperty, ...]`` (default empty = backward compatible).
- Add ``LinkType`` (named relation between two object types) and ``ObjectLink`` (a concrete instance).
- Implement ``SemanticGraph`` in OS Core: object + link registry, adjacency traversal, path queries.
- Wire ``SemanticRegistry`` to consume the graph so evidence/lineage can traverse object relations.

### Non-goals

- Not a full ontology editor (UI remains future).
- Not auto-inference of links from data (future, needs ADR).
- Not replacing MetricContract (metrics remain the trusted-definition layer).

This slice makes the semantic layer a real graph, not a flat list — the skeleton
Palantir's lineage/action/decision capture traverses.
