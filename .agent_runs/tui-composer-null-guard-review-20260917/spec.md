# Spec / Acceptance

## Requirement

In the opentui fullscreen view (`src/opentui/app.tsx`), a plain Enter in the
composer must submit the draft through `<textarea onSubmit={...}>` when no
view overlay owns Enter, and must NOT also fire when a view overlay does own it
(so a single Enter cannot run an action twice).

Owners of Enter per the pure resolver `src/opentui/viewkeys.ts`:
selector > approval > frozen globals > palette > mention(Tab only) > panel >
agents > history > composer submit.

`overlayOwnsEnterRef` is the component-local flag read by `onSubmit` to suppress
the textarea submit when an overlay (palette or selector) or an approval is
active. The agents panel is handled separately by `agentsPanelRef`.

## Invariant the change must satisfy

`overlayOwnsEnterRef.current` must be TRUE iff the view (not the textarea) owns
Enter. `controller.pendingSelector` is typed `PendingSelector | null = null`
(`src/controller.ts`), i.e. `null` when closed, an object when open.

## Regression context

Commit `2832d0d3` ("C2 review fixes (P1 double-submit fixed) but history/mention
regressed") introduced `overlayOwnsEnterRef` with `selector !== undefined`. A
prior commit in slice A hit the identical `!== undefined` vs `null` trap in the
view-key wiring and `viewkeys.ts` lines 24–29 documents it.

Observed consequence on `18110b89` (pre-fix), ordered trace with a unified
counter over key layer → sync → programmatic write:

- `ONSUBMIT {"agentsPanel":false,"overlayOwnsEnter":true,"plain":"hi"}` then no
  `SUBMIT` call at all — the textarea submit path never ran.
- `HISTORY {"action":"prev","mirrorInput":"hi","recalled":"hi","size":0}` —
  history empty, recall was the live draft, no repaint → `HISTORY_PREVIOUS: False`.
- `KEY tab {"layer":"panel","action":"switch"}` — no session existed (nothing
  submitted) so `workspaceFiles()` was empty, the `@` mention list never opened,
  Tab fell through to the panel layer, Enter ran `planEnter` and submitted the raw
  `@zz` → `MENTION_TAB_COMPLETED: False`.

## Acceptance (all must hold on the reviewed commit)

- parity_b: `HISTORY_PREVIOUS`, `MENTION_TAB_COMPLETED`, `MARKDOWN_RENDER_PATH_OK`,
  `SLICE_B_ALL_SIGNALS_VERIFIED` all True
- parity_a: `PALETTE_ENTER_RAN_STATUS`, `SELECTOR_SHOWN` True
- parity_c: `EDITOR_ROUNDTRIP` True
- composer_invariant: `INVARIANT_OK`, `COMMAND_RAN_EXACTLY_ONCE` True
- p3a: `RESUMED`, `TYPABLE_WITH_AGENTS_PANEL` True
- unit: 158 + 19 green; `typecheck` and `build` exit 0

## Explicitly out of scope / not fixed here

- `suppressSyncRef` leak on handled keys (history/mention/palette-complete/editor):
  recorded in PR #63 as a follow-up; its visible effect is a one-keystroke overlay
  mirror lag, NOT the two red signals.
- Tab is consumed by the textarea when the draft is non-empty (recorded C2 §8
  deviation). Do not treat as a new finding solely caused by this change.
