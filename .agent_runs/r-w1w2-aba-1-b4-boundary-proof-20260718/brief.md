# R-W1W2-ABA-1 B4 Boundary Proof Brief

Task type: Research infrastructure / custody feasibility.

Goal: define the smallest falsifiable B4 Boundary Proof for the R-W1W2-ABA-1
route. The proof must decide whether an independent non-LLM scorer/freezer
principal and private ingress can exist outside current agent-readable channels.

Scope:

- Public information only.
- Read `docs/CURRENT_STATE.yaml` and the task-local R-W1W2-ABA-1 public
  artifacts.
- Do not inspect, generate or request hidden identities, assignments, keys,
  tests, expected outcomes, mechanical paths, pre-seal arm labels or scorer
  internals.
- Do not call a provider, freeze, run, execute arms or implement custody code.
- Local Docker/Colima, same-UID services, local SQLite/HMAC and ordinary CI are
  presumed not independent unless the spec proves otherwise.

Required output:

- `research.md`: facts, inferences, assumptions, risks and open questions.
- `spec.md`: implementation-ready boundary-proof protocol, public-only inputs,
  allowed outputs, fail-closed canaries, acceptance criteria and PARK rules.

Decision required:

- `B4_BOUNDARY_PROOF_GO`: a real external principal/private channel can be
  provisioned and tested without hidden-material exposure to agents.
- `PARK_ROUTE`: the proof cannot establish that boundary.
