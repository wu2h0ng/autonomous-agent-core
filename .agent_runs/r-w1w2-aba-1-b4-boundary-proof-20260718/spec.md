# R-W1W2-ABA-1 B4 Boundary Proof Spec

Status: `SPECIFIED / NOT_RUN`

This spec defines the next admissible action only. It does not create an
external principal, accept B4, authorize experiment implementation, freeze, run
or establish a W1/W2 result.

## Objective

Prove or reject whether B4 can be supplied by an independent non-LLM
scorer/freezer principal with private ingress that current agents cannot read,
control or observe.

## Public Inputs

- Public scaffold code and tests.
- Public B1-B5 closure audit.
- Public canary payloads with no hidden unit, assignment, key, expected outcome,
  mechanical path, arm label or scorer internal.
- Public service digest and schema declaration from the external principal.

## Forbidden Inputs

- Hidden identities or assignments.
- Hidden tests, expected outputs or scorer internals.
- Private file paths, private mount paths, secret names, tokens, keys, cookies,
  SSH material or cloud resource IDs.
- Pre-global-seal arm labels or directional score outputs.

## Required External Boundary

The scorer/freezer candidate must be controlled by an external principal:

- not the current agent user;
- not a same-UID process;
- not a local Docker/Colima daemon controlled by the current user;
- not a same-user SQLite/HMAC/keychain arrangement;
- not ordinary CI with repo-readable secrets or artifacts;
- not a service whose logs, metrics, stdout/stderr, crash output, temp files or
  storage are readable by current agents.

Acceptable examples are an independently controlled host, cloud account, or
human-operated service where credentials and private storage are never exposed
to this transcript, repo, shell history, CI, agent tools or local logs.

## Allowed Public Outputs

Before global seal:

- service subject digest;
- service binary/container/deployment digest;
- closed schema digest;
- nondirectional canary integrity booleans;
- nondirectional eligibility counts;
- fail-closed rejection codes.

After global seal in a future package:

- closed public receipt only, matching the scaffold schema.

## Boundary-Proof Canaries

Run only public canaries:

1. Extra field rejection: unknown fields fail closed and are not logged with
   private payload context.
2. Directional egress rejection: any pre-global directional score, arm ranking
   or candidate/comparator label fails closed.
3. Stdout/stderr silence: canary execution emits no payload, path, key or label
   through stdout/stderr.
4. Replay rejection: repeated package ids or nonce-equivalent canaries fail
   closed.
5. Partial seal rejection: incomplete global seal cannot produce a closed score
   receipt.
6. Log access check: current agents cannot read service private logs, store,
   key material, daemon state or hidden ingress.
7. Caller-root rejection: caller-computed acceptance roots alone cannot mint
   B4 acceptance.

## Acceptance Criteria

Return `B4_BOUNDARY_PROOF_GO` only if all are true:

- external principal identity and control boundary are documented publicly
  without exposing secrets;
- current agents demonstrably lack read/control access to private ingress,
  storage, key material, daemon, logs and observability;
- all public canaries pass;
- allowed outputs match the closed public schema;
- an independent non-LLM reviewer accepts the proof;
- no hidden material entered transcript, repo, CI, logs, shell history or
  agent-readable temp storage.

Return `PARK_ROUTE` if any are true:

- the only available implementation is local same-principal custody;
- proof requires exposing private paths, keys, hidden assignments, hidden tests
  or expected outputs to agents;
- service emits directional output before global seal;
- current agents can read or control private storage, logs, daemon or key
  material;
- no independent reviewer can accept the boundary;
- canaries require changing the public scaffold or moving acceptance criteria.

## Non-Goals

- Implementing B3 arms.
- Implementing B5 executor or one-shot run machinery.
- Choosing units or families.
- Freezing preregistration.
- Running the experiment.
- Scoring W1/W2 performance.
- Producing a result, `REDUCES_TO` claim, product value claim or autonomy claim.

## Next Step

Founder provisions the external principal outside this transcript or declares
that no such principal is available. Without that external boundary, the
correct next state is `PARK_ROUTE`.
