# SPINE-E2E-3 Result

Date: 2026-07-13

Track: Product evaluation

Verdict: **INVALID — frozen runner-anchor event-schema incompatibility after prepare, not Product failure**

## Result boundary

The single fresh, frozen `SPINE-E2E-3` run completed `prepare`, then failed fail-closed while
verifying the runner-written prepare anchor. It is neither `PASS` nor Product `NOT_PASS` and
supplies no long-horizon evidence. No `evaluation/result.json` was fabricated after the
failure.

- Candidate target: `c6ef5fce9b2d9d30596ecdb10517a2ea60f13539`
- Runner target: `804c8d54bf5b78d9d850edb452db4affe3c1cd22`
- Frozen mechanisms: 58; post-failure prereg verification reported zero drift
- Frozen context: `40db8c36d84561d317c2dc573c2ec707329664b3d2531a271f78e43cbfab34c5`
- Phase chain: `prepare_started -> prepare_completed`, ordinals `0..1`
- Primary failure code: `INVALID_RUNNER_ANCHOR`
- Provider chain: 24 accepted, zero rejected
- Later phases: `interrupt_batch`, `probe_active_lease`, `resume`, and `adjudicate` were not run
- Result JSON and adjudication payload: intentionally absent

## Mechanical evidence

- prereg lock SHA-256: `fecedaf2822e9cc545cd547ee7b39feb572bd6d028d70f8103274693b859f905`
- canonical prereg SHA-256: `32d36b6c317162ec26d8e6e1fab2e968afc30953a43eb14792f1affc95833c31`
- source spec SHA-256: `f0924ef904a384788f2107039b72d0060fa78e68dbf0cbdff6b9984fa1d2c40d`
- exact-content manifest SHA-256: `1703942cd8b2d013a135ba1b9e60d31c4cde7a5ec36f0294fef08ba118d0114c`
- phase ledger SHA-256: `1721af3cb7cd64e7451e68e25d6dee5de92c94ae881218175330252e98a26a9f`
- provider ledger SHA-256: `352229237d74a08c0972de38921f021c8cf66f9c60a9df09246c8855d0bbd535`
- prepare anchor raw-file SHA-256: `07c59bb9ada1b22430650ac988bdedf579c5833660e9be237c09c5c66fc51ed2`
- prepare anchor canonical request SHA-256: `eadc44c6dfe63bd0e6ac4e6a2aebf253a1a4fb323c900c20378452278d1b4277`
- agent-event ledger SHA-256: `b758ebae2adfad1917f89c0dee0083b3c0edef6a7abc1c3ac06b3ef04dc692bc`

## Root cause

The fixed runner successfully wrote the one permitted `EVIDENCE_APPENDED` event. Its event
producer correctly inherited `source_decision_id` and `source_goal_id` from the approved
permission request, producing a 13-field record. The frozen Product-side `_phase_anchor`
consumer retained an exact 11-field set copied from the predecessor instrument. The two extra
governance fields were runner-conformant output, but the stale exact-key predicate excluded the
event and raised `INVALID_RUNNER_ANCHOR`.

The generated provider digests, identity-derived bearer, qualification receipt, anchor
payload, summary digest, artifact reference, evidence reference, permission action, and
approval request ID were not the mismatch. The defect is a frozen cross-repository producer /
consumer contract incompatibility. Existing qualification covered provider-bank construction
and identity closure, but did not execute the pinned runner as the real event producer.

The scratch test manually constructed the same 11-field event expected by the consumer and
mocked the subprocess boundary. It therefore mirrored the stale constant instead of testing
the actual producer contract.

## Binding disposition

- Preserve this run unchanged as `INVALID`.
- Do not continue, retry, delete or rewrite the anchor/event, patch frozen code and resume, or
  fabricate `evaluation/result.json`.
- `SPINE-E2E-3 PASS` is absent.
- `LH-RECOVERY-1A D2` is not constructed.
- Parent `LH-RECOVERY-1` remains `BLOCKED_NOT_RUN`.
- A corrected successor requires a new identity, permission binding, independent reviews,
  freeze, and one fresh run.
- Its pre-freeze qualification must include a real pinned-runner scratch producer-to-consumer
  contract canary and bind the runner schema/fixture/receipt into the digest closure.

Independent read-only mechanical adjudication: **ACCEPT INVALID**.
