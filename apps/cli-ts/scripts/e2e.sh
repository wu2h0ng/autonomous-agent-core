#!/usr/bin/env bash
# cli-ts E2E runner — hermetic, no real provider. One command runs:
#   doctor (live) → smoke full (stream/mode/approval/tool-card/auto-allow/
#   /files//task) → headless -p json → daemon restart → smoke resume →
#   doctor (dead daemon must fail).
# Lessons encoded:
#   - readiness = descriptor RE-created (stale descriptor file short-circuits
#     a naive wait loop; iteration-5 flake)
#   - every daemon is killed on exit (no background residue)
set -u
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"

DESC=/tmp/cli-ts-spike-runtime.json
DB=/tmp/cli-ts-spike/agent-os.sqlite3
WS=/tmp/cli-ts-spike/ws
PIDFILE=/tmp/cli-ts-daemon.pid
FAILED=0

cleanup() {
  [ -f "$PIDFILE" ] && kill "$(cat "$PIDFILE")" 2>/dev/null
  rm -f "$PIDFILE"
}
trap cleanup EXIT

start_daemon() {
  rm -f "$DESC"   # force re-creation so the wait loop means "ready"
  uv run python apps/cli-ts/scripts/dev_daemon.py \
    --descriptor "$DESC" --database "$DB" --workspace "$WS" \
    > /tmp/cli-ts-daemon.log 2>&1 &
  echo $! > "$PIDFILE"
  for _ in $(seq 1 60); do [ -f "$DESC" ] && break; sleep 0.5; done
  [ -f "$DESC" ] || { echo "[e2e] daemon never wrote descriptor"; exit 1; }
  sleep 2
}

run() { echo "[e2e] $*"; "$@" || FAILED=1; }

rm -rf /tmp/cli-ts-spike "$DESC" "$DESC.state.json"
mkdir -p "$WS"

start_daemon
run npx --prefix apps/cli-ts tsx apps/cli-ts/src/cli.tsx doctor --descriptor "$DESC"
run npx --prefix apps/cli-ts tsx apps/cli-ts/scripts/smoke.ts --descriptor "$DESC" --phase full
run npx --prefix apps/cli-ts tsx apps/cli-ts/src/cli.tsx --descriptor "$DESC" \
  -p "headless e2e probe" --output-format json

kill "$(cat "$PIDFILE")" 2>/dev/null; sleep 1
echo "[e2e] doctor against dead daemon (expected to fail)"
if npx --prefix apps/cli-ts tsx apps/cli-ts/src/cli.tsx doctor --descriptor "$DESC"; then
  echo "[e2e] FAIL: doctor passed against a dead daemon"; FAILED=1
fi

start_daemon
run npx --prefix apps/cli-ts tsx apps/cli-ts/scripts/smoke.ts --descriptor "$DESC" --phase resume

if [ "$FAILED" -eq 0 ]; then echo "[e2e] ALL PASS"; else echo "[e2e] FAILURES"; exit 1; fi
