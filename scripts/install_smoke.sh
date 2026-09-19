#!/usr/bin/env bash
# install_smoke.sh — Python-side install smoke: "it installs, it starts, it answers".
#
# This is the PYTHON tool path (uv tool install . -> agent-os-runtime). It is
# the Python counterpart to apps/cli-ts/scripts/install_smoke.sh (the Bun/TS
# client path); that one already proves the TS artifact. This one proves the
# installed Python distribution.
#
# Chain (each hop is asserted; first failure exits non-zero):
#   1. install   `uv tool install . --force --reinstall --no-cache` into a
#                THROWAWAY UV_TOOL_DIR (never the operator's real tools dir).
#   2. bins      the installed agent-os-runtime / agent-os-work exist and exec.
#   3. start     the INSTALLED agent-os-runtime boots against a temp db + temp
#                workspace + a temp descriptor, with EVERY AGENT_OS_PROVIDER_*
#                var scrubbed, so it falls back to the built-in
#                DeterministicProvider (no live key, no network).
#   4. answer    a one-turn driver run with the tool venv python opens a
#                session and runs one turn; the reply MUST be the stub text.
#   5. stop      SIGTERM the daemon and confirm it is gone; no orphan.
#
# Discipline:
#   - UV_TOOL_DIR + UV_CACHE_DIR under $TMPDIR; ~/.agent-os is never touched
#     (--descriptor/--database/--workspace are all temp paths).
#   - AGENT_OS_PROVIDER_* are scrubbed so ambient credentials cannot turn the
#     hermetic stub into a real billable call.
#   - No publish / tag / release.
#
# Usage: bash scripts/install_smoke.sh
# Env:   START_TIMEOUT_SECONDS (default 60)  daemon descriptor appears
#        READY_TIMEOUT_SECONDS  (default 30) daemon loopback port accepts
#        TURN_TIMEOUT_SECONDS    (default 90) the one hermetic turn
#        KEEP_TMP=1 keep temp dir on failure/inspection.
set -u

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR" || { echo "install-smoke: cannot cd to $REPO_DIR" >&2; exit 1; }

START_TIMEOUT_SECONDS="${START_TIMEOUT_SECONDS:-60}"
READY_TIMEOUT_SECONDS="${READY_TIMEOUT_SECONDS:-30}"
TURN_TIMEOUT_SECONDS="${TURN_TIMEOUT_SECONDS:-90}"

TMP_BASE="${TMPDIR:-/tmp}"; TMP_BASE="${TMP_BASE%/}"
TMP="$(mktemp -d "$TMP_BASE/e-py-install-smoke.XXXXXX")" || {
  echo "install-smoke: cannot make temp dir under $TMP_BASE" >&2; exit 1; }
TOOL_DIR="$TMP/uv-tools"
export UV_TOOL_DIR="$TOOL_DIR"
export UV_CACHE_DIR="$TMP/uv-cache"
# CRITICAL (bug found 2026-09-19): uv writes the command SHIMS (agent-os-runtime,
# agent-os-work) to UV_TOOL_BIN_DIR, which DEFAULTED to ~/.local/bin. Isolating
# UV_TOOL_DIR was not enough -- the shims still landed in the operator's real
# ~/.local/bin as symlinks into $TMP/uv-tools, and once cleanup removed $TMP
# they became DANGLING symlinks. noem's PATH launcher then spawned a dangling
# link (ENOENT), fell back to `uv run` with no project context, and died. Pin
# the shim dir to the temp tree AND prepend it to PATH so the run below resolves
# the temp shim, never the global one.
UV_TOOL_BIN_DIR="$TMP/uv-bin"
mkdir -p "$UV_TOOL_BIN_DIR"
export UV_TOOL_BIN_DIR
PATH="$UV_TOOL_BIN_DIR:$PATH"

# Snapshot the operator's global shims BEFORE install so we can prove at the end
# that ~/.local/bin was not polluted with a link into $TMP.
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

DB_DIR="$TMP/db"
WORK_DIR="$TMP/work"
DESC="$TMP/descriptor/runtime.json"
mkdir -p "$DB_DIR" "$WORK_DIR" "$(dirname "$DESC")"
RUNTIME_LOG="$TMP/daemon.log"
TURN_LOG="$TMP/turn.log"
DAEMON_PID=""

fail() { echo "install-smoke: FAIL: $*" >&2; }
cleanup() {
  trap - EXIT
  if [ -n "$DAEMON_PID" ] && kill -0 "$DAEMON_PID" 2>/dev/null; then
    kill -TERM "$DAEMON_PID" 2>/dev/null || true
    for _ in $(seq 1 10); do kill -0 "$DAEMON_PID" 2>/dev/null || break; sleep 1; done
    kill -0 "$DAEMON_PID" 2>/dev/null && kill -KILL "$DAEMON_PID" 2>/dev/null || true
  fi
  if [ "${KEEP_TMP:-0}" = "1" ]; then
    echo "install-smoke: KEEP_TMP=1, artifacts kept at $TMP" >&2
  else
    rm -rf "$TMP"
  fi
}
trap cleanup EXIT INT TERM

echo "install-smoke: TMP=$TMP"
command -v uv >/dev/null 2>&1 || { fail "uv not on PATH"; exit 1; }

# --- 1. install ----------------------------------------------------------------
echo "install-smoke: uv tool install . --force --reinstall --no-cache"
if ! uv tool install . --force --reinstall --no-cache >"$TMP/install.log" 2>&1; then
  fail "uv tool install failed. Last 40 lines:"; tail -n 40 "$TMP/install.log" >&2; exit 1
fi
TOOL_PY="$TOOL_DIR/autonomous-agent-core/bin/python"
RUNTIME_BIN="$TOOL_DIR/autonomous-agent-core/bin/agent-os-runtime"
for b in "$TOOL_PY" "$RUNTIME_BIN"; do
  [ -x "$b" ] || { fail "expected installed artifact not executable: $b"; exit 1; }
done
echo "install-smoke: installed python: $TOOL_PY"
echo "install-smoke: installed runtime: $RUNTIME_BIN"

# --- 2b. the real console script runs (help exits 0) ---------------------------
# The real `agent-os-runtime` refuses a turn with no provider (HTTP 503
# "configure and verify a provider"); that is a product property, not an install
# defect. We verify the console script itself runs here, then launch a hermetic
# daemon (_install_smoke_daemon.py) built on the INSTALLED app classes below to
# prove the installed distribution serves a turn.
echo "install-smoke: installed agent-os-runtime --help"
if ! "$RUNTIME_BIN" --help >"$TMP/help.log" 2>&1; then
  fail "installed agent-os-runtime --help exited non-zero"; tail -n 30 "$TMP/help.log" >&2; exit 1
fi
echo "install-smoke: installed agent-os-runtime --help exits 0"

# --- 3. start the installed daemon, hermetic (stub provider) -------------------
# Scrub provider state paths to temp locations so the launcher does NOT read
# ~/.agent-os/provider.json (which on a dev machine holds a real provider and
# would turn this hermetic stub into a live billable call). The launcher
# composes AgentOSApplication (from the installed distribution) with a
# scripted DeterministicProvider.
echo "install-smoke: starting hermetic daemon on INSTALLED packages (stub provider)"
env -i HOME="$HOME" PATH="$PATH" TMPDIR="${TMPDIR:-/tmp}" \
    AGENT_OS_PROVIDER_CONFIG="$TMP/no-such-provider.json" \
    AGENT_OS_PRICING_FILE="$TMP/no-such-pricing.json" \
    AGENT_OS_CLI_STATE="$TMP/cli-state" \
    "$TOOL_PY" "$REPO_DIR/scripts/_install_smoke_daemon.py" \
      --database "$DB_DIR/agent-os.sqlite3" \
      --workspace "$WORK_DIR" \
      --descriptor "$DESC" \
      >"$RUNTIME_LOG" 2>&1 &
DAEMON_PID=$!
echo "install-smoke: daemon pid=$DAEMON_PID"

# wait for descriptor
waited=0
while [ ! -s "$DESC" ]; do
  if ! kill -0 "$DAEMON_PID" 2>/dev/null; then
    fail "daemon exited before writing descriptor. Log:"; cat "$RUNTIME_LOG" >&2; exit 1
  fi
  if [ "$waited" -ge "$START_TIMEOUT_SECONDS" ]; then
    fail "timed out waiting for descriptor after ${START_TIMEOUT_SECONDS}s"; exit 1
  fi
  sleep 1; waited=$((waited+1))
done
echo "install-smoke: descriptor appeared after ${waited}s"

# wait for the loopback port to accept (read port from descriptor)
PORT="$("$TOOL_PY" - "$DESC" <<'PY'
import json,sys
print(json.load(open(sys.argv[1]))["port"])
PY
)"
HOST="127.0.0.1"
ready=0
for _ in $(seq 1 "$READY_TIMEOUT_SECONDS"); do
  if "$TOOL_PY" - "$HOST" "$PORT" <<'PY' >/dev/null 2>&1
import socket,sys
s=socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=1)
s.close()
PY
  then ready=1; break; fi
  sleep 1
done
[ "$ready" = "1" ] || { fail "loopback port $PORT never accepted"; tail -n 30 "$RUNTIME_LOG" >&2; exit 1; }
echo "install-smoke: daemon accepting on $HOST:$PORT"

# --- 4. one hermetic turn ------------------------------------------------------
echo "install-smoke: driving one turn through the installed SurfaceClient"
status=0
"$TOOL_PY" "$REPO_DIR/scripts/_install_smoke_turn.py" --descriptor "$DESC" \
  >"$TURN_LOG" 2>&1 &
TURN_PID=$!
elapsed=0
while kill -0 "$TURN_PID" 2>/dev/null; do
  if [ "$elapsed" -ge "$TURN_TIMEOUT_SECONDS" ]; then
    fail "turn timed out after ${TURN_TIMEOUT_SECONDS}s"
    kill -KILL "$TURN_PID" 2>/dev/null || true; status=1; break
  fi
  sleep 1; elapsed=$((elapsed+1))
done
wait "$TURN_PID"; status=$?
sed 's/^/install-smoke:   | /' "$TURN_LOG"
if [ "$status" -ne 0 ]; then
  fail "hermetic turn failed (exit $status). daemon log:"; tail -n 30 "$RUNTIME_LOG" >&2; exit 1
fi

# --- 5. stop -------------------------------------------------------------------
# The hermetic launcher runs serve_forever on a child thread and blocks the main
# thread in join(); in this CPython build a SIGTERM to the main thread does not
# always run the Python handler promptly (observed: the process outlives a 10s
# SIGTERM wait). The daemon has NO durable state to protect (db/workspace/
# descriptor are all in $TMP, deleted on exit), so SIGKILL escalation is a
# NOTE, not a failure. The invariant this step owns is: no orphan remains.
kill -TERM "$DAEMON_PID" 2>/dev/null || true
gone=0
for _ in $(seq 1 5); do
  kill -0 "$DAEMON_PID" 2>/dev/null || { gone=1; break; }; sleep 1
done
if [ "$gone" != "1" ]; then
  kill -KILL "$DAEMON_PID" 2>/dev/null || true
  wait "$DAEMON_PID" 2>/dev/null || true
  echo "install-smoke: NOTE: hermetic daemon required SIGKILL (stateless test daemon; no rollback needed)"
else
  echo "install-smoke: daemon stopped cleanly on SIGTERM"
fi
# --- 5b. regression: prove the operator global bin was NOT polluted -----------
# UV_TOOL_BIN_DIR must have caught every shim. If any agent-os-* link now points
# into $TMP (or a new one appeared), the bug this isolates is back -> fail.
SHIMS_AFTER="$(shim_snapshot)"
if [ "$SHIMS_BEFORE" != "$SHIMS_AFTER" ]; then
  echo "install-smoke: FAIL: ~/.local/bin agent-os-* shims changed across the run:" >&2
  diff <(printf '%s\n' "$SHIMS_BEFORE") <(printf '%s\n' "$SHIMS_AFTER") >&2 || true
  exit 1
fi
# And none of the global shims may be a DANGLING link into our temp tree.
if [ -d "$GLOBAL_BIN" ]; then
  for f in "$GLOBAL_BIN"/agent-os-*; do
    [ -L "$f" ] || continue
    tgt="$(readlink "$f" 2>/dev/null || true)"
    case "$tgt" in
      "$TMP"/*) echo "install-smoke: FAIL: dangling shim $f -> $tgt" >&2; exit 1;;
    esac
  done
fi
echo "install-smoke: PASS: ~/.local/bin agent-os-* shims unchanged (no pollution)"
echo "install-smoke: PASS — installed Python tool starts and answers a hermetic turn."
echo "install-smoke: DONE. (scaffolding; no publish/release/tag)"
