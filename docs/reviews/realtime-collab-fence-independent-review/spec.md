# Review Specification

Authoritative inputs:

- `docs/product/GC-REALTIME-COLLAB-NATIVE-SURFACE-2026-08-14.md`
- `docs/product/CP-REALTIME-COLLAB-NATIVE-SURFACE-2026-08-14.md`
- `docs/product/CTO-GATE-REALTIME-COLLAB-2026-08-14.md`
- `docs/architecture/T-P-REALTIME-COLLAB-FENCE-2026-08-14.md`
- `docs/adr/ADR-0059-merged-capability-execution-authority.md`

Required invariants:

1. **Single dispatch path.** `CapabilityBroker.invoke(action, permit, attempt, *,
   execution_claim)` remains the only production dispatch; no second broker, no
   changed signature. Collaboration is a preflight seam inside the broker.
2. **REPLAN blocks.** Any non-CONTINUE disposition (REPLAN/CONFLICT/CANCEL) raises
   before `outcomes.reserve`, producing zero reservation and zero connector calls.
   REPLAN raises typed `ReplanRequired` (replanning signal), never a success result.
3. **No effect truth in fence.** The fence stores only lease/event/cursor/decision;
   it has no PREPARED/COMMITTED/UNKNOWN state and no `dispatch`. External-effect
   reservation/outcome/UNKNOWN belong solely to `DurableActionOutcomeRepository +
   CapabilityBroker`.
4. **Trusted registry only.** `collaboration_required` is read from
   `CapabilityPort.specs()`; a capability marked collaboration-required dispatched
   through a broker without a preflight fails closed. Caller arguments/model output
   cannot downgrade it.
5. **Replay before preflight.** A sealed replay outcome is returned by `replay()`
   before `_enforce_collaboration`; preflight never rewrites it. New actions still
   pass the fence.
6. **Same-origin lease binding.** `WorkspaceCollaborationPreflight` verifies
   `claim.run_id/owner/fence` against the stored `WorkLease` before authorizing.
7. **Domain boundary.** Core holds only the generic preflight port + broker
   injection; `ResourceScope`/`WorkspaceEvent`/fence semantics live in contracts and
   the developer domain pack. Core does not parse file/workspace formats.
8. **Claims local.** Unpushed, unmerged, unreleased; no production/commercial/
   self-improvement/autonomy claim.

Deliverable is a verdict plus findings, not implementation edits.
