# ADR-0062: Surface protocol 1.2 — additive `awaiting_approval` and child-agent controls

- Status: Accepted (recorded after the fact; the contract is already merged on the baseline)
- Date: 2026-09-19
- Deciders: agent (slice E documentation; the contract itself landed on `feature/child-agent-stop-recovery-frame-gates` and the `codex/contract-surface-1-2-20260918` work)

## Context

The Surface is the authenticated loopback HTTP/SSE contract between the
terminal client and the runtime daemon (`packages/contracts/src/agent_os_contracts/surface.py`).
By 2026-09-18 two new client-facing needs existed that did not fit protocol 1.1:

1. The `/resume` session list had to tell the operator which sessions are sitting
   on a pending approval, so the TUI could surface them without opening each
   session. That required a new read field on `SurfaceSessionSummary`.
2. The kernel had already gained per-child C7 stop/reconcile authority
   (see ADR-0061), and the terminal client needed commands to stop one in-flight
   child and to declare reconciliation of orphaned children.

Both had to ship WITHOUT breaking a 1.1 reader: the daemon and client can
deploy independently, and a newer daemon must still be readable by an older
client. There was no ADR recording the versioning decision behind this. This
ADR records the design that was already implemented.

The hard constraint driving everything below: the contracts use
`extra="forbid"`. A strict 1.1 reader meeting a field it never declared REJECTS
the payload. So "add a field" cannot mean "add a field and hope the old client
ignores it" — the old client will not.

## Options Considered

- **Option A — Add fields freely, rely on lenient parsing.** Rejected. The
  contracts forbid extra fields by construction; making them lenient to admit one
  optional flag would silently weaken every other contract's strictness. The
  cost (re-opening the strict/forbid firewall) is far higher than the feature.
- **Option B — Bump to a new MAJOR (2.0) and break the wire.** Rejected. Both
  additions are purely additive (a read flag, and new commands a 1.1 client
  never sends). A MAJOR break forces a coordinated redeploy of client and
  daemon, which is exactly the independent-deployment property we refuse to give
  up.
- **Option C (chosen) — additive MINOR (1.2) with a declared field registry and
  server-side projection.** The server negotiates the client's minor and
  PROJECTS the payload down to it: fields added by a newer minor are stripped,
  and the on-wire `protocol_version` is rewritten to the negotiated value. The
  1.2 additions are `awaiting_approval: bool` on `SurfaceSessionSummary` and the
  child-agent stop/reconcile commands. A 1.1 reader is therefore served a
  payload it can actually parse, rather than one it will reject.

The strongest counter-argument to C: projection is bespoke code that can drift
from the field registry. That risk is accepted and bounded —
`SURFACE_PROTOCOL_ADDITIVE_MINORS` is the single source of truth for what is
stripped, and `downgrade_surface_payload` is driven by that registry alone (not
by hand-maintained field lists), so declaring a new minor is also what makes it
negotiable and projectable.

## Decision

Surface protocol moves from 1.1 to **1.2** as an additive MINOR:

- `SurfaceProtocolVersion` is the closed union `Literal["1.1", "1.2"]`; this
  build speaks 1.2 (`SURFACE_PROTOCOL_VERSION`) and still negotiates down to 1.1
  (`SURFACE_PROTOCOL_MIN_SUPPORTED`).
- The ONLY thing a minor may add is listed in
  `SURFACE_PROTOCOL_ADDITIVE_MINORS`: `"1.2": ("awaiting_approval",)`. This
  registry is the sole mechanism — an unregistered field would leak to older
  readers, and the child-agent commands are new endpoints a 1.1 client simply
  never invokes (no field projection needed for them).
- Negotiation is STRICT and bounded: same MAJOR only, minor within
  `[1.1, 1.2]`. A same-MAJOR minor below the floor, a higher MAJOR, and a
  malformed version are all rejected (`SurfaceProtocolVersionError`). There is
  no open-ended tolerance and no silent default.
- When a 1.1 client connects, `downgrade_surface_payload(payload, "1.1")` (a)
  removes every field added above 1.1 — `awaiting_approval` — and (b) rewrites
  any `protocol_version` newer than 1.1 back to 1.1, so the wire version always
  matches the shape actually on the wire.
- A descriptor naming a version this build does not read is reported as a
  VERSION SKEW (`RuntimeDescriptorProtocolError`), not a corrupt file: the
  operator is told to upgrade one side rather than have the daemon overwrite a
  foreign descriptor.

Pre-registration / falsification (the gate this ADR records): the contract tests
assert that (i) every additive field is registered, (ii) a 1.1 projection has
no `awaiting_approval`, (iii) an unregistered field would NOT be stripped, and
(iv) a foreign MAJOR / malformed version is refused. Removing the registration
of `awaiting_approval` reddens the suite.

## Consequences

- A 1.2 client and a 1.1 daemon interoperate: the newer client reads only 1.1
  fields it understands; a 1.1 client and a 1.2 daemon interoperate via
  projection. Independent deployments keep working.
- The cost is the projection machinery and the closed version union: admitting
  1.3 is a one-line registry entry PLUS a deliberate projection review, not a
  free-for-all. That friction is intentional.
- NOT claimed: 1.2 adds NO new capability, authority, or security boundary.
  `awaiting_approval` is a read-only display flag; the child-agent stop command
  drives the SAME per-child C7 correction ADR-0061 already governs (no new
  approve/admit/seal capability).
- Related: `.worktrees/wt-contract-1-2` held the original implementation work
  (read-only reference); this ADR closes the documentation gap that the contract
  shipped without one.
