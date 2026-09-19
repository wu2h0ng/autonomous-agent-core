# uv tool install: stale wheel cache and how to force a clean install

Status: SCAFFOLD / VERIFICATION ONLY. This document and `scripts/install_local.sh`
exist to prove the local install path works and to document the wheel-cache trap.
Nothing here publishes, tags, or releases anything.

## The problem

`uv tool install . --force --reinstall` reinstalls the *tool*, but uv builds
wheels into a global cache keyed by the sdist/build inputs. When the project
itself (`.`) is the target, uv can serve a previously-built wheel for the same
project version from that cache instead of rebuilding from the working tree.
Because this repo's `pyproject.toml` is still `version = "0.0.1"`, every local
install has the SAME version string — so a cached wheel from an earlier commit
can be silently reused, and `--force --reinstall` alone does NOT guarantee the
installed code is the code on disk.

Symptom: you edit `apps/`, run `uv tool install . --force --reinstall`, and the
installed `agent-os-runtime` still behaves like the old build.

## Why this bites here specifically

- The project version is static (`0.0.1`), so uv's cache key cannot distinguish
  "this commit" from "last commit".
- `uv tool install .` builds a wheel from the source tree; the build cache is
  shared across every `uv` invocation on the machine, not scoped to this repo.
- `--reinstall` reinstalls the *installed tool* (it removes and recreates the
  tool environment) but does not necessarily rebuild the wheel from source when
  the cache already has a matching artifact.

## The cache layers (what to clear)

uv keeps two relevant caches:

1. **Build/wheel cache** (`uv cache`): built wheels and intermediate build
   artifacts. This is the one that serves a stale wheel for `.`.
2. **Tool dir** (`UV_TOOL_DIR`, default `~/.local/share/uv/tools`): the
   installed tool environments themselves.

To force a from-source build of the current tree, combine:

| Lever | Effect |
|-------|--------|
| `--no-cache` on the install | uv does not read OR write the build cache for this invocation; it rebuilds every wheel from source. Strongest, most hermetic. |
| `uv cache clean autonomous-agent-core` | drops only this project's cached wheels (keeps everything else). |
| `uv cache clean` | wipes the whole uv cache (heavy; forces re-download of all deps next time). |
| `--reinstall` | reinstalls the tool env; does NOT by itself rebuild a cached wheel. |
| `--refresh-package <name>` | forces re-resolution/rebuild of one package (here: `--refresh-package autonomous-agent-core`). |

## Recommended clean install (what `scripts/install_local.sh` does)

The script installs into a THROWAWAY `UV_TOOL_DIR` under a temp dir so it never
touches the operator's real `~/.local/share/uv/tools`, and uses `--no-cache` so
the wheel is rebuilt from the working tree every time:

```bash
# hermetic: tool dir is a temp dir, build cache bypassed
export UV_TOOL_DIR="$(mktemp -d)/uv-tools"
uv tool install . --force --reinstall --no-cache
```

Then it verifies the installed entry point actually runs and reports the
current tree (e.g. `agent-os-runtime --help`), and prints the installed path
under the temp `UV_TOOL_DIR` so you can see nothing landed in the global env.

## When you DO want to clear the shared cache instead

If you are iterating on the same machine and want to keep the dependency cache
but drop only this project's stale wheel:

```bash
uv cache clean autonomous-agent-core
uv tool install . --force --reinstall
```

`--no-cache` is the safe default for a verification run; `uv cache clean
<project>` is the lighter option for day-to-day iteration.

## Verification that the install is current

Because the version string does not move, the only reliable check is to RUN the
installed entry point and confirm it behaves like the current tree — `agent-os-runtime
--help` exits 0, and (in the install smoke) the installed daemon answers a
hermetic turn. A version string alone cannot prove freshness here.
