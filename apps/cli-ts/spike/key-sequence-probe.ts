/**
 * What does opentui actually report for Ctrl-R / Ctrl-G / Ctrl-J?
 *
 * Keybindings in this repo have been wrong twice because the CONTROL BYTE was
 * assumed instead of measured (see the Ctrl-G history in the parity checklist).
 * `parseKeypress` is the parser opentui itself uses, so this is authoritative.
 *
 * Run: bun run spike/key-sequence-probe.ts
 */
import { parseKeypress } from "@opentui/core";

const CASES: Array<[string, string]> = [
  ["ctrl+r (0x12)", "\u0012"],
  ["ctrl+g (0x07)", "\u0007"],
  ["ctrl+j (0x0a)", "\n"],
  ["return (\\r)", "\r"],
  ["ctrl+n (0x0e)", "\u000e"],
  ["ctrl+p (0x10)", "\u0010"],
  ["plain r", "r"],
  ["tab", "\t"],
  ["escape", "\u001b"],
  ["ctrl+c (0x03)", "\u0003"],
  ["ctrl+l (0x0c)", "\u000c"],
];

for (const [label, bytes] of CASES) {
  const parsed = parseKeypress(bytes);
  console.log(
    label.padEnd(16),
    parsed === null
      ? "(null)"
      : `name=${JSON.stringify(parsed.name)} ctrl=${parsed.ctrl} shift=${parsed.shift} seq=${JSON.stringify(parsed.sequence)} raw=${JSON.stringify(parsed.raw)}`,
  );
}
