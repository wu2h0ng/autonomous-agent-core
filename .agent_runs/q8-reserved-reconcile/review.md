# Q8 reserved-effect reconciliation — 2026-09-26
Status: RED_TEST_ONLY / implementation rejected and reverted.

True gap: APPLIED workspace.apply_patch snapshot + actual expected bytes + durable reservation, but no sealed outcome. A successor worker with a fresh lease cannot currently recover the proven effect; existing code safely emits RESERVATION_WITHOUT_OUTCOME.

Rejected CLI draft:
- P0: ordinary connector output marker bypassed reservation/permit fence consistency.
- P0: C7 guard ended before outcome seal.
- P0: no atomic actual lease owner/fence/expiry check before seal.
- P1: workspace.edit rebuilt intent from already-edited bytes.

Next implementation: typed, bound reconciliation evidence; atomic lease+C7-guarded durable outcome and reconciliation record; validate old reservation/new claim/action/proof bindings; read-only APPLIED snapshot proof; do not redispatch. Keep unsupported, PREPARED, tampered, expired/taken-over lease and corrected epochs UNKNOWN. Test fresh successor fence, C7 race, takeover, digest mismatch and tampered target. No generic retry or output-authority bypass.

Authoritative red test: tests/product/test_terminal_chat_loop.py::test_applied_patch_reservation_without_outcome_is_proven_and_sealed_once — fails at RESERVATION_WITHOUT_OUTCOME; actual patch effect count remains one.
