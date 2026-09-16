/**
 * Theme colour bridge tests (pure): the view must render CONCRETE colours that
 * differ between themes, otherwise `/theme` would keep only changing a name.
 */
import assert from "node:assert/strict";
import test from "node:test";
import { hexFor, viewTheme } from "../src/opentui/theme-colors.js";

test("every theme token resolves to a hex colour", () => {
  for (const name of ["default", "ansi", "mono", null]) {
    const theme = viewTheme(name);
    for (const value of Object.values(theme)) {
      assert.match(value, /^#[0-9a-f]{6}$/, `${name}: ${value}`);
    }
  }
  assert.equal(hexFor("cyan"), "#11a8cd");
  // An unknown name falls through unchanged rather than throwing.
  assert.equal(hexFor("#123456"), "#123456");
});

test("themes are actually distinguishable (not just a label)", () => {
  const base = viewTheme("default");
  const mono = viewTheme("mono");
  assert.notEqual(base.user, mono.user, "user colour must differ");
  assert.notEqual(base.accent, mono.accent, "accent colour must differ");
  // default vs ansi intentionally share most tokens; the accent differs.
  assert.notEqual(viewTheme("default").accent, viewTheme("ansi").accent);
});
