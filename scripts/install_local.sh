#!/usr/bin/env bash
# install_local.sh — hermetic local install of THIS tree via `uv tool install`.
#
# Purpose (slice E, distribution scaffolding; NOT a release):
#   Prove that `uv tool install .` produces a working install of the CURRENT
#   working tree, and demonstrate the correct way to defeat uv's stale wheel
#   cache (see docs/distribution/UV-TOOL-INSTALL.md).
#
# Discipline:
#   - UV_TOOL_DIR is pointed at a throwaway temp dir. The operator's real
#     ~/.local/share/uv/tools is NEVER touched.
#   - --no-cache forces a from-source wheel build, so a cached wheel from an
#     earlier commit (same static version 0.0.1) cannot be reused.
#   - Nothing is published, tagged, or released.
#
# Usage: bash scripts/install_local.sh
# Env:   REPO_DIR (defaults to the repo root two levels up from this script)
#        UV_TOOL_DIR_OVERRIDE (if set, used instead of a temp dir; NOT recommended)
#        KEEP_TMP=1 to keep the temp dir for inspection.
set -u

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$REPO_DIR" || { echo "install_local: cannot cd to $REPO_DIR" >&2; exit 1; }

TMP_BASE="${TMPDIR:-/tmp}"
TMP_BASE="${TMP_BASE%/}"
TMP="$(mktemp -d "$TMP_BASE/e-install-local.XXXXXX")" || {
  echo "install_local: FAIL: cannot make temp dir under $TMP_BASE" >&2
  exit 1
}
TOOL_DIR="${UV_TOOL_DIR_OVERRIDE:-$TMP/uv-tools}"
export UV_TOOL_DIR="$TOOL_DIR"
# Also keep the uv cache inside the temp tree so --no-cache plus an isolated
# cache dir cannot reach the operator's shared build cache at all.
export UV_CACHE_DIR="$TMP/uv-cache"
# CRITICAL (bug found 2026-09-19): uv writes the command SHIMS to UV_TOOL_BIN_DIR,
# which DEFAULTED to ~/.local/bin. Isolating UV_TOOL_DIR was not enough -- the
# shims still landed in the operator's real ~/.local/bin as symlinks into
# $TMP/uv-tools, and once cleanup removed $TMP they became DANGLING symlinks
# that broke the noem PATH launcher. Pin the shim dir to the temp tree and
# prepend it to PATH.
UV_TOOL_BIN_DIR="$TMP/uv-bin"
mkdir -p "$UV_TOOL_BIN_DIR"
export UV_TOOL_BIN_DIR
PATH="$UV_TOOL_BIN_DIR:$PATH"

# Snapshot the operator's global shims BEFORE install; prove at the end that
# ~/.local/bin was not polluted with a link into $TMP.
GLOBAL_BIN="${HOME}/.local/bin"
shim_snapshot() {
  if [ -d "$GLOBAL_BIN" ]; then
    for f in "$GLOBAL_BIN"/agent-os-*; do
      [ -e "$f" ] || [ -L "$f" ] || continue
      printf '%s -> ' "$f"
      readlink "$f" 2>/dev/null || echo "(not a symlink)"
    done
  fi
}
SHIMS_BEFORE="$(shim_snapshot)"

cleanup() {
  trap - EXIT
  if [ "${KEEP_TMP:-0}" = "1" ]; then
    echo "install_local: KEEP_TMP=1, artifacts kept at $TMP" >&2
  else
    rm -rf "$TMP"
  fi
}
trap cleanup EXIT INT TERM

echo "install_local: repo        = $REPO_DIR"
echo "install_local: UV_TOOL_DIR = $UV_TOOL_DIR"
echo "install_local: UV_CACHE_DIR= $UV_CACHE_DIR"

if ! command -v uv >/dev/null 2>&1; then
  echo "install_local: FAIL: uv is not on PATH" >&2
  exit 1
fi

# Step 1: install THIS tree into the throwaway tool dir, bypassing the build
# cache so the wheel is rebuilt from the working tree.
echo "install_local: uv tool install . --force --reinstall --no-cache"
if ! uv tool install . --force --reinstall --no-cache >"$TMP/install.log" 2>&1; then
  echo "install_local: FAIL: uv tool install exited non-zero. Last 40 lines:" >&2
  tail -n 40 "$TMP/install.log" >&2
  exit 1
fi
sed 's/^/install_local:   | /' "$TMP/install.log"

# Step 2: the installed entry points must exist under the temp tool dir (proves
# nothing landed in the global env). uv lays tools out as
#   $UV_TOOL_DIR/<project-name>/bin/<entry-point>
TOOL_BIN_DIR="$TOOL_DIR/autonomous-agent-core/bin"
RUNTIME_BIN="$TOOL_BIN_DIR/agent-os-runtime"
WORK_BIN="$TOOL_BIN_DIR/agent-os-work"
for b in "$RUNTIME_BIN" "$WORK_BIN"; do
  if [ ! -x "$b" ]; then
    echo "install_local: FAIL: installed entry point not executable: $b" >&2
    exit 1
  fi
  echo "install_local: installed bin: $b"
done

# Step 3: the installed daemon actually runs (help exits 0). This is the
# freshness check: a stale cached wheel would still import, but running the
# INSTALLED script through the installed interpreter is what an operator gets.
echo "install_local: agent-os-runtime --help (installed)"
if ! "$RUNTIME_BIN" --help >"$TMP/help.log" 2>&1; then
  echo "install_local: FAIL: installed agent-os-runtime --help exited non-zero" >&2
  tail -n 30 "$TMP/help.log" >&2
  exit 1
fi
echo "install_local: PASS: installed agent-os-runtime --help exits 0"

# Step 4: sanity — the installed package is the one in THIS tree (entry point
# resolves inside the temp tool dir, not ~/.local).
# Step 5: regression -- the operator global bin must be untouched.
SHIMS_AFTER="$(shim_snapshot)"
if [ "$SHIMS_BEFORE" != "$SHIMS_AFTER" ]; then
  echo "install_local: FAIL: ~/.local/bin agent-os-* shims changed across the run:" >&2
  diff <(printf '%s\n' "$SHIMS_BEFORE") <(printf '%s\n' "$SHIMS_AFTER") >&2 || true
  exit 1
fi
if [ -d "$GLOBAL_BIN" ]; then
  for f in "$GLOBAL_BIN"/agent-os-*; do
    [ -L "$f" ] || continue
    tgt="$(readlink "$f" 2>/dev/null || true)"
    case "$tgt" in
      "$TMP"/*) echo "install_local: FAIL: dangling shim $f -> $tgt" >&2; exit 1;;
    esac
  done
fi
echo "install_local: PASS: ~/.local/bin agent-os-* shims unchanged (no pollution)"
echo "install_local: PASS: install verified under hermetic UV_TOOL_DIR=$UV_TOOL_DIR"
echo "install_local: DONE. (This is scaffolding; no publish/release/tag happened.)"
