# Single-file binary build status

Status: MEASURED / SCAFFOLDING. This is a status report, not a build I run as
part of slice E. No binary is built or shipped here.

## What exists today

### TypeScript client (`apps/cli-ts`) — single-file binary EXISTS

The terminal client already has a single-file binary build:

- Entry: `bun run scripts/compile.ts` → `bun build --compile src/cli.tsx
  --outfile dist/noem` (see `apps/cli-ts/scripts/compile.ts`).
- The version is baked in with `--define` so `--version` works when there is no
  `package.json` next to the compiled binary.
- This is the binary the existing self-update path manages. Per
  `docs/CURRENT_STATE.yaml` (self_update_2026_09_18 pin), it was measured end to
  end on this machine: a real compiled ~76 MB arm64 binary self-updated
  0.1.0 → 0.2.0 from a local `file://` source, answered `--version` in a fresh
  process after the swap, and rolled back byte-for-byte on a corrupted-candidate
  case. That proof is already on the unmerged self-update branch; slice E does not
  re-run the ~76 MB compile.

Hermetic verification that binary: the cli-ts `install_smoke.sh` already walks
build → pack → start → answer for the BUN runtime (`bun dist/cli.js`), and the
self-update tests exercise the compiled artifact's `--version` post-swap.

### Python runtime (`apps/runtime_daemon`) — NO single-file binary

There is no PyInstaller, Nuitka, or cx_Freeze spec/wrapper for the Python
runtime, and no `Cargo.toml` for it (the only `Cargo.toml` is
`apps/macos/shell`, a separate macOS wrapper shell). The Python runtime is
distributed as a normal wheel via `uv tool install .` (console scripts
`agent-os-runtime` / `agent-os-work`), which is exactly what
`scripts/install_smoke.sh` verifies.

## Feasibility of a Python single-file binary (assessment only, NOT implemented)

Technically a PyInstaller/Nuitka build of `apps/runtime_daemon/__main__.py` is
possible, but it is NOT done and NOT claimed. Known obstacles that would have to
be solved before it is worth building:

1. **Workspace packages**: `agent-os-contracts` and `agent-os-core` are
   `{ workspace = true }` and unpublished; a freezer would have to bundle them
   explicitly (hidden imports, data files).
2. **Runtime dependencies**: pydantic (with pydantic-core native extension),
   sqlglot, and the API server's `apps/api_server/*.html` package-data all have
   to be collected; missing one silently breaks either the daemon boot or the
   surface it serves.
3. **The daemon needs a provider**: even a compiled daemon refuses a turn with
   no configured provider (HTTP 503), so a "single-file binary answers a turn"
   proof still needs the same hermetic stub launcher this slice uses — it cannot
   be a self-contained `--offline` turn without a product change.
4. **Self-update assumes the binary**: the existing self-update chain was
   written around the compiled Bun image (executable-magic checks, atomic rename
   over the running path). A Python frozen binary would need its own
   shape/magic checks; it is a different artifact and would NOT be covered by
   today's self-update without work.

Given those four points, a Python single-file binary is feasible but a
multi-day packaging effort with no current demand (the wheel install path works
and is what this slice verifies). Status: NOT BUILT, deliberately deferred.

## What slice E actually verified hermetically

Not a single-file binary, but the wheel-installed runtime:
`scripts/install_smoke.sh` installs `.` into a throwaway `UV_TOOL_DIR`, boots
the installed distribution through a hermetic stub-provider launcher, drives one
turn with the installed `SurfaceClient`, and asserts the stub reply. That is the
real, measured install path; the single-file binary above is documented for
completeness only.
