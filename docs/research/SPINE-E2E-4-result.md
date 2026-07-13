# SPINE-E2E-4 Result

Date: 2026-07-13

Track: Product evaluation

Verdict: **PASS — bounded frozen local same-boot recovery equivalence**

## Result boundary

The single frozen `SPINE-E2E-4` run completed all five phases exactly once. All twelve public
Agent OS developer tasks reached verified terminal outcomes in both uninterrupted and
interrupted/restarted arms. The interrupted arm preserved exactly one `workspace.apply_patch`
idempotency key through interruption, active-lease denial, natural lease expiry, resume, and
terminal replay. No rejected or excess provider call, duplicate apply receipt, retry, rescue,
policy regression, or correction regression was observed.

This is one local same-boot Product-evaluation result. It does not establish multi-hour/day or
multi-week advantage, background 7x24 operation, autonomy, AGI, continual learning,
self-evolution, live-provider robustness, production exactly-once, or Blueprint completion.

## Frozen identity and mechanical evidence

- Product target: `b2bc9f5b4eb3e90c46527075346ab3b0178aafb4`
- Runner target: `50eb4d27b17688f0943f80207dddb702983afd51`
- Source spec raw SHA-256: `b29c9f477122c409165c113df6eaac1b9d71ae2407266e84bea95469ec484219`
- Canonical spec SHA-256: `3846810fbe7c63bb264f9869af02a33c4b4224d00e9cfd781101c9dfb1ea6495`
- Prereg lock SHA-256: `bc99dbfe82ed935a9277a6a28272908b970744a519b7a67001c418e5acd5582b`
- Result raw SHA-256: `14f388383af717d99a76b70380569e2a94550459869f48febb7eff322c5e1470`
- Frozen context SHA-256: `5c3a1118eddb8f2e4b30a7cc6d7c3f450c852864c7d81d9cc7f670c8ede21ac1`
- Phase ledger SHA-256: `977adfeb80896177b5fd93b3026b22c4e57ba77a2a3f2f703a28669804fa466e`
- Provider ledger SHA-256: `465f88a5c423fcaf73649f160a7a5c3636be6b1576c98bb40c93c6a4baec4b68`
- Agent-event ledger SHA-256: `0d19c6ae545be58d17419497baccbda1fa2dd96e4e1fce835dddaa3059b9b3ab`
- Adjudication payload canonical SHA-256: `0c106d6f6491ec445af12481eea35544e74d4883fb58dea3c9ea3009b12864ae`
- Verified cases: `12/12 PASS`; result reason codes: none
- Phase chain: ten ordered started/completed records, no failure or duplicate record
- Timing: interrupt-completed to resume-started `381.467s`; prepare-started to
  adjudicate-started `404.905s`; probe window `2.7s`
- Provider chain: `24` accepted, `0` rejected, twelve request digests appearing exactly twice
- Runner anchors: five exact canonical requests bound to the founder permission and source
- External prereg/result verification: `intact=true`, `drift=[]`

## Independent adjudication

- Kimi result reviewer: `ACCEPT`; artifact SHA-256
  `6201b1968e4bf432beb87986cd4f74c1b3b8c7c63be2e99a9b35d9e4ed8111a0`
- OpenCode mechanical result reviewer: `ACCEPT`; artifact SHA-256
  `384142ce684c6bee31435f74d12dfab5446e996121f1df85f401c7db729aae49`
- Claude Opus completed the exact-head code/architecture review before freeze with `ACCEPT`.
  Its post-result review attempt hit the subscription session limit before producing a verdict
  and is not counted as result-adjudication evidence.

## Binding disposition

- Preserve `SPINE-E2E-1`, `SPINE-E2E-2`, and `SPINE-E2E-3` unchanged as `INVALID` predecessor
  evidence. This PASS does not rewrite them.
- `SPINE-E2E-4` satisfies the SPINE prerequisite for the child route only.
- `LH-RECOVERY-1A D2` is **not yet constructed**: its frozen plan additionally requires the
  missing D1-E/D1-F/combined-D1 lock, dual nonce commitments and reveals, corpus
  materialization, and a one-shot `432/432` oracle result.
- Parent `LH-RECOVERY-1` remains `OPEN/BLOCKED`, not preregistered, not frozen, and not run.
  The child route cannot pass the parent by implication.
- The next admissible action is D1 artifact construction under the already recorded
  `D1_ARTIFACT_CONSTRUCTION_ALLOWED` boundary, followed by D2 only if every preregistered
  prerequisite remains valid.
