/**
 * Does a real `y`/`n` keystroke actually reach the controller from the rendered
 * view?
 *
 * The gap this closes (verified by the independent review): the whole suite
 * stayed green when `App`'s approval branch was turned into a no-op. Every other
 * test of that path is renderer-free — `opentui-viewkeys.test.ts` asserts only
 * the ROUTING decision — and the Ink-era assertion that a real `y` produced
 * exactly one approval was deleted with Ink.
 *
 * Rendering `<App>` needs OpenTUI's native renderer, which only bun can load, so
 * the assertions live in the bun harness and this (node) test runs it. The
 * harness is `test/fixtures/opentui-approval-key.harness.tsx`; run it directly
 * with `bun run test/fixtures/opentui-approval-key.harness.tsx` to see the
 * underlying failure.
 */
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import test from "node:test";

const PACKAGE_ROOT = fileURLToPath(new URL("..", import.meta.url));
const HARNESS = "test/fixtures/opentui-approval-key.harness.tsx";
const TIMEOUT_MS = 120_000;

test("the approval keystroke hands the decision to the controller (rendered view)", () => {
  const result = spawnSync(process.env.BUN_BIN ?? "bun", ["run", HARNESS], {
    cwd: PACKAGE_ROOT,
    encoding: "utf8",
    timeout: TIMEOUT_MS,
  });
  const output = `${result.stdout ?? ""}${result.stderr ?? ""}`;
  if (result.error !== undefined) {
    assert.fail(
      `cannot run \`bun run ${HARNESS}\`: ${result.error.message}. ` +
        "Rendering the view needs bun (OpenTUI has no node FFI); install bun >= 1.4 or set BUN_BIN.",
    );
  }
  assert.equal(
    result.status,
    0,
    `the approval-key render harness failed:\n${output}`,
  );
  // Guard against a harness that stopped asserting but still exits 0.
  assert.match(output, /OPENTUI_APPROVAL_KEY_HARNESS: PASS/, "the harness did not report a pass");
});
