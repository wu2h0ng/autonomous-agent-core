# R-W1W2-ABA-1 B4 Boundary Proof Research

Status: `SPEC_BY_CODEX_AFTER_CLAUDE_UNAVAILABLE`

Claude Code note: local `claude` was attempted in read-only mode, but the
organization has disabled Claude subscription access for Claude Code. No Claude
research output was produced.

## Facts

- Agent OS main is `c1e159e6f95250bcfa3b50d8ab0e8ed652fa36b5`.
- The public R-W1W2-ABA-1 scaffold is approved at exact code head
  `24280fc46879a2b4a4f9884af6bf10fb179406e7`.
- The experiment remains `EXPERIMENT_IMPLEMENTATION_DENIED / PREREG_REVISE /
  NOT_IMPLEMENTATION_READY / NOT_FROZEN / NOT_RUN`.
- The B1-B5 closure audit permits only a time-boxed B4 independent custody
  boundary proof before B3 or B5 implementation work.
- Local Docker/Colima, same-UID services, same-user files, local SQLite/HMAC and
  ordinary CI are not accepted as independent scorer/freezer custody.
- The public scaffold validates equality to an externally supplied acceptance
  root; it does not authenticate the root supplier.

## Inferences

- B4 is the route-killing dependency. If independent private custody cannot be
  established, B2/B3/B5 work cannot produce a valid experiment.
- A local service can still be useful as a protocol canary target, but not as
  the accepted scorer/freezer principal.
- The proof must test observability and egress behavior before any real hidden
  unit, assignment, key, expected output or scorer rule exists.

## Assumptions

- Founder can provision an external account, host, service, or human-controlled
  machine outside current agent-readable credentials and daemon control.
- The boundary service can publish a public digest and closed schema without
  revealing private storage, hidden data or directional outputs.
- Public canaries are sufficient to test fail-closed protocol shape, but not to
  prove scoring correctness.

## Risks

- A same-admin local service may look operational while still being readable or
  controllable by current agents.
- Logs, stdout/stderr, crash reports, metrics labels, shell history, temporary
  files and container inspect output can leak hidden material.
- A service that signs receipts but accepts caller-computed roots only moves the
  self-mint problem outward.
- Overbuilding B3/B5 before B4 passes would waste effort and create pressure to
  rescue an invalid experiment.

## Open Questions

- What external principal will own the private ingress and key material?
- How will founder verify that current agents have no credential, SSH, sudo,
  API, daemon, storage, log or observability access to that principal?
- What public service digest format is acceptable: binary hash, container image
  digest, signed deployment manifest, or hardware/service attestation?
- Who performs the non-LLM acceptance review of the boundary proof?

## Current Verdict

`B4_BOUNDARY_PROOF_NOT_ESTABLISHED`

Continue only to a time-boxed public boundary proof. If the external principal
cannot be provisioned and verified without agent-readable exposure, set
`PARK_ROUTE`.
