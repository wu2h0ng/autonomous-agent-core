# CI patch: Python install smoke (uv tool install path)

Status: **APPLIED on branch `feat/l4-audit-closure-20260919` (draft PR, 2026-09-19)**.
The step below was added as the last step of the existing `test` job in
`.github/workflows/ci.yml`, after the `Terminal coding eval` step, with
`astral-sh/setup-uv@v5` added after `actions/setup-python@v5` to provide `uv`.
The cli-ts job already runs the Bun/TS install smoke (`apps/cli-ts/scripts/
install_smoke.sh`); this step adds the PYTHON counterpart (`scripts/
install_smoke.sh`, `uv tool install .`). Measured locally (macOS arm64):
`bash scripts/install_smoke.sh` exits 0, one hermetic turn completes with
`stop_reason=completed`, daemon SIGKILLed cleanly. The original proposed step
is kept below for record.

## What it proves

The existing `cli-ts` job already proves the Bun/TS artifact
(`apps/cli-ts/scripts/install_smoke.sh`: build -> pack -> start -> answer).
This step proves the PYTHON tool path that the gates in `AGENTS.md` never
exercised in CI: `uv tool install .` produces an install under a throwaway
`UV_TOOL_DIR`, the installed `agent-os-runtime` console script runs, and the
installed distribution serves a hermetic turn through the installed
`SurfaceClient` with a stub provider (no live key, no network).

## Why a separate step (not folded into the existing product-suite step)

The existing product-suite step does `pip install --no-deps .` from a PYTHONPATH
workspace — it never exercises `uv tool install .`, the wheel build the tool
path produces, or the installed console scripts on a clean tool dir. This step
is the only CI coverage of the `uv tool install .` distribution shape.

## Proposed step (drop into the `test` job after the product-suite step)

```yaml
      - name: Install smoke (uv tool install . -> start -> hermetic turn)
        run: |
          # Hermetic Python tool-path smoke.
          # - UV_TOOL_DIR + UV_CACHE_DIR are pointed at $RUNNER_TEMP so the
          #   operator/runner's real uv tools dir is never touched.
          # -- --no-cache forces a from-source wheel build (the project version is
          #    static 0.0.1, so a cached wheel from an earlier commit would
          #    otherwise be reused; see docs/distribution/UV-TOOL-INSTALL.md).
          # - AGENT_OS_PROVIDER_CONFIG / AGENT_OS_PRICING_FILE / AGENT_OS_CLI_STATE
          #    are pointed at non-existent temp paths so the daemon cannot read a
          #    real ~/.agent-os/provider.json and become a billable live call.
          # - No `uv` install needed beyond what actions/setup-python gives? No:
          #   this step needs uv. Add `oven-sh/setup-uv` or pipx-install uv
          #   before this step (the cli-ts job already pins a toolchain; mirror
          #   that choice here).
          UV_TOOL_DIR="$RUNNER_TEMP/e-uv-tools" \
          UV_CACHE_DIR="$RUNNER_TEMP/e-uv-cache" \
            bash scripts/install_smoke.sh
```

## Required runner additions

- Install `uv` on the runner (e.g. `astral-sh/setup-uv@v5`), since the
  existing `test` job uses raw `pip` and has no uv.
- No provider key, no network egress required beyond resolving/building the
  workspace packages (they are `{ workspace = true }`, so no index hits for the
  project itself; third-party wheels are already cached by the runner).

## Deliberately NOT claimed

- This is a smoke, not a release gate. It does NOT publish, tag, or build a
  release artifact.
- The hermetic daemon is a launcher (`scripts/_install_smoke_daemon.py`) that
  composes the installed `AgentOSApplication` with a scripted
  `DeterministicProvider`. The real `agent-os-runtime` console script itself
  refuses a turn with no configured provider (HTTP 503 "configure and verify a
  provider"); that is a product property, and this step additionally verifies
  `agent-os-runtime --help` exits 0.
- Measured locally (macOS, this branch): install_smoke.sh exits 0, one turn
  completes with `stop_reason=completed` and the stub text; the daemon is
  SIGKILLed at the end (stateless test daemon).
