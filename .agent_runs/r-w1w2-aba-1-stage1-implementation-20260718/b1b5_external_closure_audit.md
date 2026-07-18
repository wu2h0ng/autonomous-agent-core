# R-W1W2-ABA-1 B1-B5 External Closure Audit

- Auditor: `aba_b1b5_closure_audit`
- Mode: read-only; no hidden identities, assignments, keys, tests, outcomes,
  provider calls, freeze, run or custody material inspected or generated.
- Live head: `ed2f5d99fad8d532881a6d07934b3433e812aa31`
- Verdict: `CONTINUE_EXTERNAL_CLOSURE`
- Constraint: only a time-boxed external-boundary proof is justified. If a
  truly independent B4 principal/private channel cannot be established, the
  route should become `PARK_ROUTE`.

## Findings

P0:

- B4 has no real independent custody boundary. Local Docker/Colima, same-UID
  processes, same-user files, local HMAC/SQLite and ordinary CI remain in the
  current agent or admin principal trust domain.
- B2 has no prospective candidate-blind frame. Current agents have seen the
  route design and cannot retrospectively act as blind curator.
- B3 has no accepted five-arm treatment/liveness implementation. Legacy heads
  are `CHARACTERIZATION_ONLY` and cannot be reused as-is.
- B5 has no external freeze, global one-shot execution integrity or run
  authorization. Existing workflow and runtime primitives can support integrity
  after an external boundary exists, but cannot replace it.

P1:

- B1 has useful public material: exact design, draft preregistration, negative
  map, closed disposition grammar and independent scaffold approval. It still
  lacks final methodology acceptance, SESOI/value rationale and role-separation
  receipt.
- The public scaffold checks equality to an externally supplied root; it does
  not authenticate the root supplier.
- Prior HMAC-custody negative evidence remains binding: mathematical gates do
  not repair transcript leakage, and the opened non-oracle package cannot be
  re-keyed or rescued.

## Package Decisions

| Bundle | Decision | Minimum closure |
|---|---|---|
| B1 | `GO` | external SESOI rationale, exact methodology review and role receipt |
| B2 | `GO_EXTERNAL_ONLY` | blind curator plus independent novelty/difficulty/provenance verifier |
| B3 | `PARK_NOW` | do not implement until B2 and B4 are accepted |
| B4 | `GO_EXTERNAL_PROVISIONING / PARK_ALL_LOCAL_VARIANTS` | independent host/account/service with private ingress outside agent-readable channels |
| B5 | `PARK_NOW` | do not implement until B2-B4 are accepted |

## Minimum Next Action

Run only `B4_BOUNDARY_PROOF`, time-boxed to one day:

1. Founder provisions an independent principal/private ingress outside this
   transcript and outside agent-readable credentials.
2. The service exposes only a public service digest and closed output schema.
3. Public canaries verify fail-closed behavior for extra fields, stdout/stderr,
   pre-global directional output, replay and partial seal.
4. If current agents can read private store, key, daemon, logs or hidden input,
   mark `PARK_ROUTE`.
5. Only after B4 passes should B1 and B2 closure proceed. B3 and B5 remain
   parked until then.

This audit does not accept B1-B5, authorize experiment implementation, freeze,
run or establish any W1/W2 mechanism result.
