/**
 * Key-routing precedence tests (viewkeys.ts is pure — no renderer needed).
 *
 * These are bypass-detecting for the class of bug that shipped in the first
 * parity-slice revision: the palette branches were nested inside the selector
 * branch, so palette navigation/completion was unreachable. Any reordering that
 * lets the agents panel or a plain Enter win over an open palette fails here.
 */
import assert from "node:assert/strict";
import test from "node:test";
import { resolveViewKey, type ViewKeyContext } from "../src/opentui/viewkeys.js";

function ctx(overrides: Partial<ViewKeyContext> = {}): ViewKeyContext {
  return {
    selectorOpen: false,
    awaitingApproval: false,
    paletteOpen: false,
    mentionOpen: false,
    activePanel: "transcript",
    name: "",
    ctrl: false,
    sequence: "",
    ...overrides,
  };
}

test("an open selector owns every key (Esc cancels, never approves)", () => {
  assert.deepEqual(resolveViewKey(ctx({ selectorOpen: true, name: "escape" })), {
    layer: "selector",
  });
  assert.deepEqual(
    resolveViewKey(ctx({ selectorOpen: true, name: "y", awaitingApproval: true })),
    { layer: "selector" },
  );
  // Even a palette-looking key goes to the selector.
  assert.deepEqual(resolveViewKey(ctx({ selectorOpen: true, name: "tab", paletteOpen: true })), {
    layer: "selector",
  });
});

test("a closed selector is null/undefined and must NOT own keys (regression)", () => {
  // The controller returns `pendingSelector: null` when closed; treating that as
  // "open" routed every key to the selector layer and disabled Enter/movement.
  for (const closed of [null, undefined, false]) {
    assert.deepEqual(resolveViewKey(ctx({ selectorOpen: closed, name: "return" })), {
      layer: "enter",
    });
    assert.deepEqual(
      resolveViewKey(ctx({ selectorOpen: closed, activePanel: "agents", name: "down", ctrl: true })),
      { layer: "agents", action: "move", delta: 1 },
    );
    assert.deepEqual(resolveViewKey(ctx({ selectorOpen: closed, name: "escape" })), {
      layer: "global",
    });
  }
  // A real selector object (truthy) still owns keys.
  const selector = { kind: "theme", title: "theme", items: ["default"] };
  assert.deepEqual(resolveViewKey(ctx({ selectorOpen: selector, name: "return" })), {
    layer: "selector",
  });
});

test("a pending approval answers y/n and ignores everything else", () => {
  assert.deepEqual(resolveViewKey(ctx({ awaitingApproval: true, name: "y" })), {
    layer: "approval",
    action: "approve",
  });
  assert.deepEqual(resolveViewKey(ctx({ awaitingApproval: true, name: "n" })), {
    layer: "approval",
    action: "reject",
  });
  assert.deepEqual(resolveViewKey(ctx({ awaitingApproval: true, name: "return" })), {
    layer: "approval",
    action: "ignore",
  });
});

test("frozen global keys win over palette/agents when no overlay is open", () => {
  assert.deepEqual(resolveViewKey(ctx({ name: "escape" })), { layer: "global" });
  assert.deepEqual(resolveViewKey(ctx({ name: "c", ctrl: true })), { layer: "global" });
  assert.deepEqual(resolveViewKey(ctx({ name: "l", ctrl: true })), { layer: "global" });
});

test("an open palette beats the agents panel and plain Enter", () => {
  assert.deepEqual(resolveViewKey(ctx({ paletteOpen: true, name: "up" })), {
    layer: "palette",
    action: "up",
  });
  assert.deepEqual(resolveViewKey(ctx({ paletteOpen: true, name: "down" })), {
    layer: "palette",
    action: "down",
  });
  assert.deepEqual(resolveViewKey(ctx({ paletteOpen: true, name: "tab" })), {
    layer: "palette",
    action: "complete",
  });
  // Enter on an open palette must run the highlighted command even when the
  // agents panel is selected with a session row under the cursor.
  assert.deepEqual(
    resolveViewKey(ctx({ paletteOpen: true, activePanel: "agents", name: "return" })),
    { layer: "palette", action: "submit" },
  );
  assert.deepEqual(
    resolveViewKey(ctx({ paletteOpen: true, activePanel: "agents", name: "n", ctrl: true })),
    { layer: "palette", action: "ignore" },
  );
});

test("Tab switches panels and PgUp/PgDn scroll, unless a palette is open", () => {
  // Regression pin: an earlier revision dropped these branches entirely and
  // silently disabled panel switching/scrolling (and with it agents navigation).
  assert.deepEqual(resolveViewKey(ctx({ name: "tab" })), {
    layer: "panel",
    action: "switch",
  });
  assert.deepEqual(resolveViewKey(ctx({ name: "pageup" })), {
    layer: "panel",
    action: "scroll",
    delta: -1,
  });
  assert.deepEqual(resolveViewKey(ctx({ name: "pagedown" })), {
    layer: "panel",
    action: "scroll",
    delta: 1,
  });
  // An open palette keeps Tab for command completion.
  assert.deepEqual(resolveViewKey(ctx({ name: "tab", paletteOpen: true })), {
    layer: "palette",
    action: "complete",
  });
});

test("agents panel moves on ctrl+arrows/pn or plain arrows; Enter submits otherwise", () => {
  assert.deepEqual(resolveViewKey(ctx({ activePanel: "agents", name: "down", ctrl: true })), {
    layer: "agents",
    action: "move",
    delta: 1,
  });
  assert.deepEqual(resolveViewKey(ctx({ activePanel: "agents", name: "p", ctrl: true })), {
    layer: "agents",
    action: "move",
    delta: -1,
  });
  assert.deepEqual(resolveViewKey(ctx({ activePanel: "agents", name: "up" })), {
    layer: "agents",
    action: "move",
    delta: -1,
  });
  // A plain letter in the agents panel is still composer input, not movement.
  assert.deepEqual(resolveViewKey(ctx({ activePanel: "agents", name: "j" })), {
    layer: "ignore",
  });
  assert.deepEqual(resolveViewKey(ctx({ name: "return" })), { layer: "enter" });
  assert.deepEqual(resolveViewKey(ctx({ name: "x", sequence: "x" })), { layer: "ignore" });
});

test("an open @mention list takes Tab but leaves typing to the composer", () => {
  assert.deepEqual(resolveViewKey(ctx({ mentionOpen: true, name: "tab" })), {
    layer: "mention",
    action: "complete",
  });
  // A letter must still reach the composer while the mention list is open.
  assert.deepEqual(resolveViewKey(ctx({ mentionOpen: true, name: "a", sequence: "a" })), {
    layer: "mention",
    action: "ignore",
  });
  // Enter must still submit (Ink parity): the list does not trap the key.
  assert.deepEqual(resolveViewKey(ctx({ mentionOpen: true, name: "return" })), {
    layer: "enter",
  });
  // The palette still wins over the mention list.
  assert.deepEqual(
    resolveViewKey(ctx({ mentionOpen: true, paletteOpen: true, name: "tab" })),
    { layer: "palette", action: "complete" },
  );
});

test("up/down are history for the composer unless the agents panel owns them", () => {
  assert.deepEqual(resolveViewKey(ctx({ name: "up" })), { layer: "history", action: "prev" });
  assert.deepEqual(resolveViewKey(ctx({ name: "down" })), { layer: "history", action: "next" });
  assert.deepEqual(
    resolveViewKey(ctx({ activePanel: "agents", name: "up" })),
    { layer: "agents", action: "move", delta: -1 },
  );
  // An open mention list leaves arrows to the composer input (no-op there for a
  // single-line composer), i.e. they are not routed to history.
  assert.deepEqual(resolveViewKey(ctx({ mentionOpen: true, name: "up" })), {
    layer: "mention",
    action: "ignore",
  });
});
