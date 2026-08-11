# AR-20260624: MCP protocol-induced leakage risk

- Status: Risk card / research intake. Not an ADR and not an implementation claim.
- Date: 2026-06-24
- Layer: Enterprise OS deployment layer.
- Source: "What Happens Locally, Leaks Globally": Detecting Privacy Leakage Risks in MCP Servers
- URL: https://arxiv.org/abs/2606.21338
- Source date: 2026-06-19
- Evidence level: paper_only (E1). Primary arXiv metadata and abstract read; no code read or local reproduction.
- Boundary: This record identifies a deployment-layer risk for future connector/tool protocol work. It does not claim that full MCP support, full DLP, full RBAC, tenant isolation, or external release exists.

## 1. Judgment

```text
covered_before:
  partial — connector execution semantics, report redaction, and principal/scope policy exist, but MCP protocol-induced leakage was not separately tracked.
evidence_level:
  paper_only
primary_value:
  security risk model + eval pattern
our_layer:
  product_layer
admission:
  admit_with_boundary
```

Protocol-induced leakage should be tracked as a first-class connector risk. The paper's useful distinction is that MCP leakage can arise from protocol/resource exposure and tool composition even when there is no conventional exfiltration bug.

## 2. Local product boundary

Relevant current product surfaces:

- `ConnectorExecutionSemantics`
- action execution audit projection
- HTTP principal/scope/redaction policy
- external-report-key cap
- EvidenceChain / report cards / source projections
- operator-only approval execution

Non-claims preserved:

- no full RBAC;
- no tenant isolation;
- no field/row-level authorization;
- no full DLP;
- no external release;
- no automatic R4/R5 execution;
- no durable arbitrary external connector recovery;
- no general MCP runtime in product core.

## 3. Risk statement

If future connector or MCP-like tool servers expose local resources, credentials, prompts, file handles, database metadata, or evidence payloads through generic resource discovery, an agent can leak sensitive context globally through ordinary-looking tool calls. This can happen even when each individual tool call appears authorized.

The risk is compositional:

- resource discovery can reveal more than intended;
- tool outputs can carry sensitive local context into model-visible traces;
- evidence/report projections can accidentally join safe and unsafe sources;
- external-report projections can become a laundering channel if redaction is not source-aware;
- approval-bound execution context can leak if tool metadata is copied into user-facing reports.

## 4. Required future controls

Any future MCP or MCP-like connector integration must add a separate SPEC/ADR or AR section covering:

1. Resource inventory: every exposed resource, scope, and sensitivity label.
2. Source-aware redaction: redaction decisions tied to source provenance, not only field names.
3. Tool-output tainting: outputs from sensitive tools carry taint into traces and reports.
4. Principal checks before discovery: unauthorized principals cannot enumerate sensitive resources.
5. Evidence boundary tests: external reports cannot reveal physical source names, SQL metadata, credentials, raw previews, or sensitive provenance.
6. Prompt/tool injection tests: malicious tool descriptions and resource names cannot request broader context.
7. Audit projection: leakage-relevant decisions are trace-visible without exposing secrets.

## 5. Suggested regression cases

- external_report principal attempts to discover internal-only tool resources;
- tool output contains a credential-like token and report generation must redact it;
- safe report field is derived from unsafe source and must retain taint;
- blocked run must not expose trace detail to external_report;
- approval execution trace must not copy raw action parameters to `user_result.business_action`;
- connector name changes must not bypass execution semantics or redaction rules.

## 6. Relation to autonomous-core

This is not an autonomous-core mechanism. It may inform C7/C6 safety language as a deployment analogy, but it must not be used to change `autonomous-agent-core` gates, self-modification boundaries, or world-model/organ permissions.

## 7. Decision

Admit with boundary as a deployment-layer risk card. Use it when drafting any future MCP connector, external-report projection, tool protocol, or source-aware evidence feature. Do not treat it as implemented capability.

## 8. References

- https://arxiv.org/abs/2606.21338
