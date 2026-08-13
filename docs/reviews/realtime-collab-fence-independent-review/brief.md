# Realtime Collaboration Fence — Independent Exact-Head Review Brief

- Review target: `34d2d376431adb69817c1ed66f0e862801e453e6` (feature/realtime-collab-fence-20260814)
- Base: `c819f75b9ad01850a90850d72da2b621129308a2` (CTO_IMPLEMENTATION_AUTHORIZED spec head)
- Track: Product / Architecture / Engineering review
- Reviewer: OpenCode with `deepseek/deepseek-v4-pro`, read-only
- Builder: Codex
- Authority: `docs/product/CTO-GATE-REALTIME-COLLAB-2026-08-14.md` (P0=0/P1=0/P2=2 test debts)

## Question

Review whether the minimal vertical slice correctly implements the collaboration
fence as a **preflight seam on the ADR-0059 single dispatch spine** (not a second
broker), and whether it closes the four P1s and the two P2 test debts bound by the
CTO gate:

1. REPLAN also blocks the current action (zero reservation, zero connector calls).
2. The fence holds no external-effect truth (no PREPARED/COMMITTED/UNKNOWN).
3. collaboration-required capability fails closed without a preflight, and the
   `collaboration_required` flag is read from the trusted registry, not caller args.
4. exact-base provenance (implementation sits on spec head `c819f75`).
5. P2 debt 1: caller cannot downgrade `collaboration_required=true`.
6. P2 debt 2: a sealed replay outcome is not rewritten by new events, while a new
   action still passes the fence.

The reviewer must not edit implementation files. Findings must cite files/lines and
conclude with `APPROVE`, `APPROVE_WITH_P2`, or `REVISE`.

## Exact-content manifest

`manifest.sha256` binds the four mechanism files. Drift invalidates this review.
