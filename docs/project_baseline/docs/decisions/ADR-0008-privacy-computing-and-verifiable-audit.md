# ADR-0008: Privacy Computing And Verifiable Audit Are Future Architecture Capabilities

> Date: 2026-06-01  
> Status: Accepted  
> Owner: CTO  
> Related: ADR-0002, ADR-0005, ADR-0006, ADR-0007

## Context

AI Native Business Data Agent OS is positioned around trusted data products, EvidenceChain, OperationTrace, controlled actions, and enterprise-grade governance.

Privacy computing and blockchain-related technologies are relevant to this long-term trust architecture:

- Differential privacy can reduce individual privacy leakage in statistical queries.
- Federated analytics can support cross-organization collaboration without raw data sharing.
- TEE can strengthen sensitive execution environments for regulated industries.
- Immutable ledgers can strengthen evidence and operation auditability.
- Smart contracts can support future multi-party approval and non-repudiation workflows.

However, the current MVP goal is still the Trusted Loop:

```text
BusinessIntent
  -> MetricContract
  -> SQL Safety / Eval
  -> EvidenceChain
  -> ActionProposal
  -> Approval lite
  -> Feedback / Trace
```

Introducing blockchain, TEE, federated learning, or smart contracts into the MVP would add significant non-core complexity around key management, infrastructure, legal acceptance, chain/provider selection, customer trust model, cost, privacy leakage, and operational support.

## Decision

Privacy computing and external ledger anchoring are accepted as future architecture capabilities, not MVP dependencies.

MVP must not introduce production dependencies on:

```text
blockchain networks
smart contracts
TEE runtimes
federated learning frameworks
secure multi-party computation frameworks
external ledger anchoring services
```

MVP may implement only:

```text
EvidenceChain.hash
OperationTrace.hash
previous_hash
hash_algorithm
canonical_json
ledger_status = local_only
PrivacyPolicy interface
ProviderContract privacy fields
DataClassification fields
```

The first implementation target is a local verifiable audit hash chain. The purpose is to make tampering detectable without introducing external chain infrastructure.

## Approved Architecture Direction

### P0 / MVP

Implement local verifiable audit primitives:

```text
canonical_json(record)
hash = sha256(canonical_json(record))
previous_hash
trace_id
record_type
created_at
ledger_status = local_only
```

EvidenceChain and OperationTrace should be able to prove whether a record has changed after creation.

### P1 / Enterprise Pilot

Introduce adapter boundaries without external-chain coupling:

```text
LedgerAnchorAdapter
WORMStorageAdapter
CustomerAuditLogAdapter
PrivacyPolicy
ProviderContract.privacy_level
ProviderContract.data_classification
ProviderContract.allowed_privacy_operations
```

Enterprise customers may anchor audit data to their own storage, SIEM, database audit log, object lock, or WORM storage.

### P2 / Privacy Controls

Introduce privacy-preserving query policies only when query semantics are stable:

```text
DifferentialPrivacyPolicy
aggregation_only_policy
epsilon_budget
k_anonymity_threshold
minimum_group_size
privacy_eval_cases
```

Differential privacy must not be implemented as simple post-query noise. It requires query classification, aggregation checks, privacy budget tracking, and regression evaluation.

### P3 / Ecosystem Collaboration

Consider these only after cross-organization scenarios are commercially validated:

```text
federated analytics
secure aggregation
TEE execution profile
external ledger anchoring
smart-contract approval
multi-party data product settlement
```

Each requires a separate ADR and CTO approval.

## Non-Goals

MVP does not:

- Write EvidenceChain hashes to Ethereum, public chains, consortium chains, or vendor chains.
- Use smart contracts for approval.
- Use TEE for query execution.
- Use federated learning or secure multi-party computation.
- Claim cryptographic immutability beyond local tamper-evident hash chaining.
- Store sensitive raw customer data in audit logs or hashes.

## Consequences

Positive:

- Keeps MVP focused on Trusted Loop delivery.
- Preserves long-term trust architecture without premature infrastructure lock-in.
- Gives regulated-enterprise scenarios a clean extension path.
- Avoids chain/vendor/key-management decisions before customer requirements are real.

Tradeoffs:

- MVP audit is tamper-evident, not externally immutable.
- Some regulated customers may still require external anchoring later.
- Privacy controls remain policy interfaces until query semantics and eval cases mature.

## Implementation Rules

1. `EvidenceChain` and `OperationTrace` may add local hash fields.
2. Hashing must use canonical serialization, not ad hoc string concatenation.
3. Hashes must never include secrets, credentials, tokens, or raw sensitive customer payloads.
4. Privacy fields may be added to contracts, but enforcement must be tested before claims.
5. External ledger anchoring, TEE, differential privacy, federated analytics, and smart-contract approval require separate ADRs.
6. No Code Agent may add blockchain, TEE, federated learning, secure multiparty computation, or smart-contract dependencies without CTO approval.

## Validation

Before local audit hash chaining is accepted:

- Same record must produce the same hash under canonical serialization.
- Mutated records must produce different hashes.
- `previous_hash` chain verification must detect deletion, insertion, or mutation.
- Tests must cover EvidenceChain and OperationTrace hash behavior.
- Documentation must clearly say `ledger_status = local_only`.
