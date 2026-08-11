# PR-15: Controlled-pilot RC branch record (M9 refresh)

- Date: 2026-07-08
- Status: **RC branch preserved; origin/main @ M9 head**

## Record

- Verified local head: `fed54d620b70cca083bd3c43209c94d79e9bbead`
- RC branch: `rc/phase-1-controlled-pilot-20260704`
- RC branch head: `b8834a644018e070e372be149fb758a928c7a242`
- Remote main head: `a88763989c639516fef33d4b12dbfb37c438f834`

## Notes

M9 operator walkthrough verified at `1f12d69`; release-prep docs landed through `fed54d6` (format-check drift resolved in `2cc86af`). Historical RC branch unchanged. Optional POC pin: `rc/phase-1-internal-pilot-20260708` per PR-32 Option C (not created).

**Founder/CTO decision 2026-07-09:** PR-33 **Option A (HOLD)**. No `origin/main` push. `Remote main head` remained `fed54d6` until a future AUTHORIZED record.

**Update 2026-07-10 (PR-34 then PR-35):** two founder-cast AUTHORIZED single pushes advanced `origin/main` `fed54d6 → 1bdf280` (P1-A, PR-34) → `a887639` (P2 batch A/B/C, PR-35). The `Remote main head` pin above is advanced to the current `origin/main` `a887639`. `DEPLOYMENT_PUSH: HOLD` was restored immediately after each push (committed tokens never flipped). This pin is a local docs commit tracking the current origin/main per this record's own protocol; the controlled-pilot RC branch head is unchanged.
