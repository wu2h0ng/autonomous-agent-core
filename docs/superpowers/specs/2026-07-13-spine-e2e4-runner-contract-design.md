# SPINE-E2E-4 Runner Contract Qualification Design

Date: 2026-07-13

Track: Product evaluation infrastructure

Status: FOUNDER_AUTHORIZED_DESIGN — NOT_IMPLEMENTED, NOT_REVIEWED, NOT_FROZEN, NOT_RUN

## 1. Problem lock

`SPINE-E2E-3` is immutable `INVALID`. Its provider identity and request digests were generated
correctly, but its frozen anchor consumer retained a predecessor 11-field event set and rejected
the pinned runner's conformant 13-field governed event. Byte pinning proved that both sides were
unchanged; it did not prove producer/consumer compatibility.

The corrected successor must prevent both classes of semantic staleness:

1. internally copied identity/model/bearer/request digest constants; and
2. externally copied runner schema, enum, permission-lineage, or emitted-fixture assumptions.

It must not repair, resume, or reuse E2E-3.

## 2. Considered approaches

### A. Runner-owned schema plus real producer-to-consumer canary — selected

Pin a runner commit that exports a closed, versioned TeamEvent JSON Schema. Before freeze, invoke
that exact runner through subprocess in a scratch workspace, create a synthetic approved
permission fixture, write a real event, validate it with the Product-side generic schema consumer,
and bind the schema and normalized emitted fixture into qualification.

This costs one small meta contract and one real cross-process canary, but it tests semantic
compatibility rather than only shared prose or bytes.

### B. Projection-only Product validation — rejected

Check only required semantic values and ignore extra runner fields. This would have accepted the
E2E-3 event, but it silently tolerates unknown contract expansion and weakens fail-closed
behavior. It converts stale constants into open-world ambiguity.

### C. Commit a runner schema snapshot without executing the producer — rejected

A schema snapshot and digest would remove handwritten field sets, but still would not prove the
pinned runner emits records conforming to the snapshot. It repeats the E2E-3 mistake at a higher
level: integrity without compatibility.

## 3. Architecture

### 3.1 Pinned producer

The successor binds runner branch `codex/team-event-contract-v1-20260713` at exact commit
`3a3224a7af7da724d8b6ec82d34ed47d938620e4` and invokes it only through its interpreter and CLI.
No workflow package may be imported into Product or evaluation runtime.

The runner supplies:

- `team event-schema` subprocess export;
- `team-event-v1` schema version;
- closed field set and one event-type enum;
- actual `TeamWorkspace.append_event` producer behavior;
- timestamp-normalized fixture and digest semantics used to create the qualification receipt.

### 3.2 Product-side schema consumer

Add one small stdlib-only evaluation adapter that consumes an exported JSON Schema rather than
embedding runner field names. It supports exactly the schema keywords emitted by the pinned
runner and rejects unsupported keywords, malformed schemas, unknown record fields, missing
required fields, enum/const/type/pattern/minLength/item violations, and schema-version mismatch.

The adapter is evaluation infrastructure, not `packages/os_core` Product runtime.

### 3.3 Typed authority binding

Permission verification returns an immutable `AuthorityBinding` containing:

- request and approval canonical hashes;
- request ID, action, affected path, decision, and decider;
- source decision ID, source goal ID, and source decision type;
- ordered request/approval timestamps.

Formal anchor construction and verification both consume this binding. The runner command passes
the three source fields explicitly; the consumer requires exact equality to the verified binding.
No literal founder-decision or goal value is duplicated in the anchor verifier.

### 3.4 Qualification receipt closure

The pre-freeze receipt binds all of:

- successor identity and case/template/provider-bank digests;
- provider qualification source digests and bearer canary;
- pinned runner branch, head, interpreter, and common-dir identity;
- raw and canonical exported schema SHA-256;
- normalized real emitted-fixture SHA-256;
- Product-side schema-consumer source SHA-256;
- authority-binding verifier source SHA-256;
- scratch request, approval, event, and evidence relationships;
- proof that scratch paths cannot alias the formal run ledgers.

Receipt reverification reruns both the provider canary and the real runner contract canary and
compares the exact receipt. A digest mismatch or semantic mismatch fails before evaluation
genesis.

## 4. Formal anchor flow

For each completed phase:

1. Product writes the anchor request once from frozen phase/provider/context/authority bindings.
2. The pinned runner writes exactly one governed TeamEvent record.
3. Product validates the row against the bound exported schema.
4. Product checks exact semantic values: type, agent, task, summary, artifact/evidence,
   permission action/request, and all authority source fields.
5. Product checks exactly one match and re-verifies permission, runner identity, schema digest,
   and qualification receipt.

No handwritten `event_fields = {...}` or predecessor-numbered identity literal is permitted
outside compatibility tombstones/tests.

## 5. Failure and result rules

- Any qualification mismatch before genesis leaves formal phase/provider ledgers absent.
- Any post-genesis schema, anchor, timing, binding, permission, runner, provider, or Product
  protocol failure makes the single run `INVALID` or `NOT_PASS` according to the frozen
  adjudication table.
- Failed records are terminal. No retry, repair, resume, result fabrication, or identity reuse.
- Only a complete frozen `PASS` may authorize D2 construction; otherwise parent
  `LH-RECOVERY-1` remains blocked.

## 6. Test strategy

Tests are written and observed RED before implementation:

- generic schema consumer accepts the live exported schema and real scratch event;
- mutated/unsupported schema, extra event field, missing source field, wrong source value,
  unknown type, and empty approval ID fail;
- real subprocess producer is not mocked;
- scratch/formal ledger alias fails;
- runner head/schema/fixture/consumer mutation invalidates the receipt;
- predecessor manual 11-field fixture fails;
- existing E2E-1/2/3 evidence remains byte-identical;
- formal-path scratch test covers resolver, phase ordering, anchor, adjudication, and finalize
  without calling predecessor helpers.

## 7. Claim boundary

Passing qualification proves only that the successor instrument is constructable against its
pinned runner producer. A later formal PASS would support only the frozen local recovery claim.
Neither result establishes multi-day advantage, 7x24 autonomy, physical exactly-once, CWM,
continual learning, self-evolution, AGI, D2, or the parent LH verdict by implication.

## 8. Self-review

- Placeholder scan: no TBD/TODO or unresolved identity value.
- Internal consistency: producer schema, real canary, typed authority, receipt, and formal anchor
  consume the same pinned contract.
- Scope: Product evaluation infrastructure only; no Product runtime or Research Track change.
- Ambiguity: E2E-3 reuse, post-failure retry, schema open-world acceptance, and cross-repo import
  are explicitly forbidden.
