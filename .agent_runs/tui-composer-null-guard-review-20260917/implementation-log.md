# Implementation Log — 60586374

## Change (the only behavioral edit)

File: `apps/cli-ts/src/opentui/app.tsx` (around line 233)

```diff
   agentsPanelRef.current = !awaiting && panels.includes(selected) && selected === "agents";
-  overlayOwnsEnterRef.current = awaiting || selector !== undefined || palette.length > 0;
+  // `selector` is `null` (not `undefined`) when closed (controller.pendingSelector);
+  // test `!== null`, otherwise this is always true and the composer can never submit.
+  overlayOwnsEnterRef.current = awaiting || selector !== null || palette.length > 0;
```

`selector` is `controller.pendingSelector` (`src/controller.ts:266`
`pendingSelector: PendingSelector | null = null`). With `!== undefined`, since
`null !== undefined` is `true`, the ref was always true and the `onSubmit`
guard at `app.tsx` (`if (agentsPanelRef.current || overlayOwnsEnterRef.current) return;`)
always returned early.

## Method

Ordered tracing with a single monotonic counter (`tr(ev, data)` writing
`n\tev\tjson`), instrumenting: key-layer resolution, `setComposerText` writes,
`syncComposer`, `onSubmit`, `submit`, and the history recall. Env-gated; all
instrumentation was removed before the commit (reverted to `18110b89` then the
one-line patch reapplied; `grep` residue = 0).

## Branch context (not part of this commit)

- `2832d0d3`: introduced `overlayOwnsEnterRef` + `suppressSyncRef`; commit message
  already admitted "history/mention regressed".
- `d3bdddd5`: `controller.workspaceFiles()` no-empty-cache + mention fetch-once.
- `18110b89`: removed the earlier diagnostic traces.
- This commit `60586374`: fixes the Enter ownership gate only.

## Not fixed (must stay explicit)

- `suppressSyncRef` leak: handled-key branches set the flag and `return` before the
  trailing `queueMicrotask(syncComposer)`, so there is no pending sync to consume
  it and the next real sync is swallowed (one-keystroke mirror lag). Evidence on
  pre-fix trace: after Up writes `hi`, first backspace `SYNC {suppress:true, plain:"h"}`.
