#!/usr/bin/env bash
# cli-ts install smoke — "it installs, it starts, it answers", machine-checked.
#
# What this proves, in the order a real user meets it:
#   1. deps      node_modules is installed (this script does NOT install; CI
#                runs `bun install --frozen-lockfile` first)
#   2. build     `npm run build` turns src/ into dist/ (tsc, no bundler)
#   3. artifact  dist/cli.js exists AND is executable, and every `bin` name in
#                package.json (noem / agentos / agent-os / agent-os-ts) resolves
#                to a file that exists and is executable -- a bin that is not
#                executable is what an install would hand the user
#   4. version   `bun dist/cli.js --version` prints the package.json version
#   5. pack      `npm run pack:check` (prepack -> build, then `npm pack
#                --dry-run`): the tarball carries dist/ + README.md, carries NO
#                source map, carries every path the `bin` entries name, leaks no
#                src/ or test/, and writes no tarball (dry run)
#   6. start     the hermetic daemon (scripted provider, no network, no
#                credentials) comes UP: it re-writes its descriptor and the
#                descriptor's pid is this script's daemon pid
#   7. answer    `bun dist/cli.js --descriptor <desc> --no-daemon -p <prompt>
#                --output-format json` exits 0 with a non-empty reply and
#                `is_error: false`, and that reply is byte-identical to the
#                hermetic daemon's own scripted turn-1 text, so a turn served by
#                any other daemon/provider cannot satisfy this check
#   8. stop      the daemon is gone afterwards, with no orphan left behind
#
# Why NOT `npm i -g` / `npm i <tarball>`: apps/cli-ts/package.json is
# `private: true`, so this package cannot be published or installed from a
# registry today, and this check deliberately does not publish. "Installed" is
# therefore checked on the two things an install would ship or run: the tarball
# `pack:check` builds (contents + the bin targets it must contain) and the real
# runtime path a user gets afterwards (`bun dist/cli.js`, the built artifact --
# never `npx tsx src/cli.tsx`, which would test the source tree instead).
#
# Deliberate choices:
#   - the interpreter is `${PY:-python3}`; no `uv`, which CI need not have
#   - the daemon is started as a direct child, so its pid is known and can be
#     matched against the descriptor it writes
#   - every wait is a positive signal (descriptor RE-created, pid matches), never
#     a bare sleep: a stale descriptor file is exactly what makes a naive wait
#     loop pass while nothing is listening (cli-ts e2e.sh, iteration-5 flake)
#   - temp files live in `mktemp -d` under $TMPDIR, never a fixed top-level
#     path, so parallel runs cannot collide
#   - the turn runs with `--no-daemon`: with auto-start enabled an unhealthy
#     descriptor makes the client spawn its own daemon from ambient config, and
#     on a machine with a live provider that turn answers for real (observed
#     during fault injection), which would let this check pass without the
#     daemon under test
#   - any failed check exits non-zero and prints the PASS/FAIL list
#
# Usage: bash apps/cli-ts/scripts/install_smoke.sh
# Env:   PY (default python3)  BUN (default bun)  NPM (default npm)
set -u

CLI_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PY:-python3}"
BUN="${BUN:-bun}"
NPM="${NPM:-npm}"

DAEMON_PID=""
DESC=""
FAILED_COUNT=0
RESULT_LOG=""

TMP_BASE="${TMPDIR:-/tmp}"
TMP_BASE="${TMP_BASE%/}"
TMP="$(mktemp -d "$TMP_BASE/cli-ts-install-smoke.XXXXXX")" || {
  echo "[install-smoke] FAIL: could not create a temp dir under $TMP_BASE" >&2
  exit 1
}
RESULT_LOG="$TMP/results.txt"
: > "$RESULT_LOG"

record() { printf '%s  %s\n' "$1" "$2" >> "$RESULT_LOG"; }
pass()   { record PASS "$1"; }
fail()   { record FAIL "$1"; FAILED_COUNT=$((FAILED_COUNT + 1)); }

summary() {
  echo
  echo "[install-smoke] ===== PASS/FAIL ====="
  sed 's/^/[install-smoke]   /' "$RESULT_LOG"
  echo "[install-smoke] $(grep -c '^PASS' "$RESULT_LOG") passed, $FAILED_COUNT failed, $(wc -l < "$RESULT_LOG" | tr -d ' ') checks run"
}

require() {   # require <label> <function>
  run_step "$1" "$2" || { summary; exit 1; }
}

run_step() {  # run_step <label> <function>  — captures the step's output
  local label="$1"
  local body="$2"
  local log="$TMP/step-$(printf '%s' "$label" | tr ' /' '__').log"
  local status=0
  echo "[install-smoke] $label"
  if "$body" > "$log" 2>&1; then
    pass "$label"
    echo "[install-smoke]   PASS"
    sed 's/^/[install-smoke]   | /' "$log"
  else
    status=$?
    fail "$label"
    echo "[install-smoke]   FAIL (exit $status) — last 30 lines of $log:"
    tail -n 30 "$log" | sed 's/^/[install-smoke]   | /'
  fi
  return "$status"
}

cleanup() {
  local status=$?
  trap - EXIT
  # Idempotent: if the last check already stopped the daemon, this is a no-op.
  stop_daemon >/dev/null 2>&1
  if [ "$FAILED_COUNT" -eq 0 ]; then
    rm -rf "$TMP"
  else
    echo "[install-smoke] FAILED — artifacts kept for inspection: $TMP" >&2
  fi
  exit "$status"
}

check_deps() {
  local tsc="$CLI_DIR/node_modules/.bin/tsc"
  [ -x "$tsc" ] || {
    echo "missing $tsc — install dependencies first: bun install --frozen-lockfile"
    return 1
  }
  echo "tsc: $tsc"
}

build_cli() {
  (cd "$CLI_DIR" && "$NPM" run build)
}

check_artifact() {
  local cli="$CLI_DIR/dist/cli.js"
  [ -f "$cli" ] || { echo "dist/cli.js missing after build"; return 1; }
  [ -x "$cli" ] || {
    echo "dist/cli.js is not executable (scripts.build chmods it 0755)"
    return 1
  }
  ls -l "$cli"
  "$PY" - "$CLI_DIR" <<'PY'
import json
import pathlib
import sys

cli_dir = pathlib.Path(sys.argv[1])
bins = json.loads((cli_dir / "package.json").read_text(encoding="utf-8")).get("bin") or {}
assert bins, "package.json declares no bin entries"
targets = []
for name in sorted(bins):
    target = bins[name].lstrip("./")
    targets.append(target)
    path = cli_dir / target
    assert path.is_file(), f"bin {name!r} -> {target} does not exist"
    assert path.stat().st_mode & 0o111, f"bin {name!r} -> {target} is not executable"
assert "dist/cli.js" in targets, f"no bin entry points at dist/cli.js: {bins}"
built = [p for p in (cli_dir / "dist").rglob("*") if p.is_file()]
print("bin entries: " + ", ".join(f"{n} -> {bins[n]}" for n in sorted(bins)))
print(f"dist/ files: {len(built)}")
PY
}

check_version() {
  local expected printed
  expected="$("$PY" -c 'import json,sys;print(json.load(open(sys.argv[1], encoding="utf-8"))["version"])' "$CLI_DIR/package.json")" || return 1
  printed="$(cd "$CLI_DIR" && "$BUN" dist/cli.js --version)"
  echo "package.json version         : $expected"
  echo "bun dist/cli.js --version    : $printed"
  [ -n "$expected" ] || { echo "package.json has no version"; return 1; }
  case "$printed" in
    [0-9]*.[0-9]*.[0-9]*) ;;
    *) echo "--version did not print a version number"; return 1 ;;
  esac
  [ "$printed" = "$expected" ] || {
    echo "--version printed '$printed' but package.json says '$expected'"
    return 1
  }
  echo "runtimes: $("$BUN" --version 2>/dev/null | head -1) | $("$NPM" --version 2>/dev/null) | $("$PY" -V 2>&1)"
  echo "HEAD: $(git -C "$CLI_DIR" rev-parse --short HEAD 2>/dev/null || echo '<no git>')"
}

check_pack() {
  local before after
  before="$(cd "$CLI_DIR" && ls -1 ./*.tgz 2>/dev/null | sort)"
  (cd "$CLI_DIR" && "$NPM" run pack:check) > "$TMP/pack-dry-run.txt" 2>&1 || {
    cat "$TMP/pack-dry-run.txt"
    return 1
  }
  after="$(cd "$CLI_DIR" && ls -1 ./*.tgz 2>/dev/null | sort)"
  [ "$before" = "$after" ] || {
    echo "pack:check wrote a tarball; a dry run must not create one"
    echo "before: $before"
    echo "after : $after"
    return 1
  }
  "$PY" - "$TMP/pack-dry-run.txt" "$CLI_DIR" <<'PY'
import json
import pathlib
import re
import sys

log = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
cli_dir = pathlib.Path(sys.argv[2])

entries: list[str] = []
in_contents = False
for line in log.splitlines():
    if "Tarball Contents" in line:
        in_contents = True
        continue
    if "Tarball Details" in line:
        in_contents = False
        continue
    if not in_contents or not line.startswith("npm notice "):
        continue
    fields = line.split()
    if len(fields) >= 4:
        entries.append(fields[-1])

assert entries, (
    "no 'Tarball Contents' section was found in the npm pack --dry-run output "
    "(npm output format changed, or pack:check did not run)"
)
print(f"tarball entries: {len(entries)}")
print("  " + "\n  ".join(entries))

maps = [e for e in entries if e.endswith(".map")]
assert not maps, f"the tarball ships source maps: {maps}"
assert "README.md" in entries, "the tarball has no README.md"
assert "dist/cli.js" in entries, "the tarball has no dist/cli.js"

bins = json.loads((cli_dir / "package.json").read_text(encoding="utf-8")).get("bin") or {}
for name in sorted(bins):
    target = bins[name].lstrip("./")
    assert target in entries, f"bin {name!r} -> {target} is NOT in the tarball"

leaked = [e for e in entries if re.match(r"^(src|test|scripts)/", e)]
assert not leaked, f"the tarball leaks the dev tree: {leaked}"
PY
}

start_daemon() {
  local waited owner port
  DESC="$TMP/runtime.json"
  # A stale descriptor makes a naive wait loop return instantly while nothing is
  # listening, so require it to be WRITTEN AGAIN by the daemon we start.
  rm -f "$DESC" "$DESC.state.json"
  "$PY" "$CLI_DIR/scripts/dev_daemon.py" \
    --descriptor "$DESC" \
    --database "$TMP/agent-os.sqlite3" \
    --workspace "$TMP/ws" > "$TMP/daemon.log" 2>&1 &
  DAEMON_PID=$!
  # Run it as a disowned process: this script does its own liveness/stop
  # handling, and the shell's job-control notice for the killed child would
  # otherwise land in the middle of the PASS/FAIL output below.
  disown -a 2>/dev/null
  waited=0
  while [ ! -f "$DESC" ]; do
    if ! kill -0 "$DAEMON_PID" 2>/dev/null; then
      echo "the daemon exited (pid $DAEMON_PID) before writing a descriptor:"
      cat "$TMP/daemon.log"
      return 1
    fi
    waited=$((waited + 1))
    if [ "$waited" -ge 120 ]; then
      echo "no descriptor after 60s; daemon log:"
      cat "$TMP/daemon.log"
      return 1
    fi
    sleep 0.5
  done
  sleep 2   # let the surface server settle before the first request
  owner="$("$PY" -c 'import json,sys;print(json.load(open(sys.argv[1], encoding="utf-8"))["pid"])' "$DESC")" || return 1
  [ "$owner" = "$DAEMON_PID" ] || {
    echo "descriptor belongs to pid $owner, not to the daemon this check started ($DAEMON_PID)"
    return 1
  }
  port="$("$PY" -c 'import json,sys;print(json.load(open(sys.argv[1], encoding="utf-8"))["port"])' "$DESC")" || return 1
  [ "$port" != "0" ] && [ -n "$port" ] || {
    echo "descriptor carries no port"
    return 1
  }
  echo "daemon up: pid $DAEMON_PID on 127.0.0.1:$port (descriptor $DESC)"
  echo "database : $TMP/agent-os.sqlite3"
  echo "workspace: $TMP/ws"
}

check_turn() {
  local status=0
  # The built artifact, on the declared runtime (package.json engines.bun).
  # `--no-daemon` is not cosmetic: with auto-start enabled, a turn whose
  # descriptor is missing/unhealthy makes the client START ITS OWN daemon from
  # the ambient configuration, and on a machine with a live provider that turn
  # answers for real (observed during fault injection: a real provider call
  # served by `agent-os-runtime` with the default ~/.agent-os database). This
  # check must fail instead of borrowing someone else's daemon.
  (cd "$CLI_DIR" && "$BUN" dist/cli.js --descriptor "$DESC" --no-daemon \
    -p "install smoke: prove the installed client answers" \
    --output-format json) > "$TMP/headless.json" 2> "$TMP/headless.err"
  status=$?
  if [ "$status" -ne 0 ]; then
    echo "headless turn exited $status (frozen table: 0 ok, 1 error, 2 approval_required, 3 not_completed)"
    echo "--- stderr ---"
    cat "$TMP/headless.err"
    echo "--- stdout ---"
    cat "$TMP/headless.json"
    return 1
  fi
  "$PY" - "$TMP/headless.json" "$CLI_DIR" <<'PY'
import importlib.util
import json
import pathlib
import sys

raw = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
cli_dir = pathlib.Path(sys.argv[2])
payload = json.loads(raw)   # exactly one result object; extra output fails here
assert payload.get("type") == "result", f"not a result object: {payload}"
assert payload.get("subtype") == "success", f"subtype is {payload.get('subtype')!r}"
assert payload.get("is_error") is False, f"is_error is {payload.get('is_error')!r}"
session = payload.get("session_id")
assert session, "result carries no session_id (the turn did not reach the daemon)"
text = payload.get("text") or ""
assert text.strip(), "result text is empty — the client started but did not answer"

# Hermeticity: the reply must be the hermetic daemon's own scripted fixture,
# read from dev_daemon.py rather than duplicated here. Any other answer means
# the turn was served by something else (a real provider, another daemon).
daemon_py = cli_dir / "scripts" / "dev_daemon.py"
spec = importlib.util.spec_from_file_location("cli_ts_dev_daemon", daemon_py)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
expected = module.TURN1_TEXT
assert text == expected, (
    "the reply is not the hermetic daemon's scripted turn-1 text "
    f"({len(text)} chars vs {len(expected)} expected): {text[:120]!r}"
)
print(f"session_id : {session}")
print(f"stop_reason: {payload.get('stop_reason')}")
print(f"tokens     : {payload.get('total_tokens')}")
print(f"text       : {len(text)} chars, identical to dev_daemon.TURN1_TEXT")
print(f"             first line: {text.splitlines()[0][:80]!r}")
PY
}

stop_daemon() {
  local waited survivors
  if [ -n "$DAEMON_PID" ]; then
    kill "$DAEMON_PID" 2>/dev/null
    waited=0
    while kill -0 "$DAEMON_PID" 2>/dev/null; do
      waited=$((waited + 1))
      if [ "$waited" -ge 20 ]; then
        echo "daemon $DAEMON_PID ignored SIGTERM for 10s; sending SIGKILL"
        kill -9 "$DAEMON_PID" 2>/dev/null
        break
      fi
      sleep 0.5
    done
    # The process was disowned above, so there is no job entry to reap here;
    # the pgrep sweep below is what proves it is really gone.
    sleep 0.5
  fi  # Only ever sweep THIS run's daemon: the pattern carries this run's descriptor
  # path, and an empty $DESC is never swept (that pattern would match others).
  if [ -n "$DESC" ]; then
    pkill -f "dev_daemon.py --descriptor $DESC" 2>/dev/null
    sleep 1
    survivors="$(pgrep -f "dev_daemon.py --descriptor $DESC" 2>/dev/null)"
    if [ -n "$survivors" ]; then
      echo "orphan daemon processes still alive: $survivors"
      return 1
    fi
    echo "daemon pid ${DAEMON_PID:-<none>} stopped; no process matches 'dev_daemon.py --descriptor $DESC'"
  else
    echo "no daemon was started; nothing to stop"
  fi
}

trap cleanup EXIT

echo "[install-smoke] cli-ts in $CLI_DIR"
echo "[install-smoke] temp dir: $TMP"
echo "[install-smoke] python=$PY bun=$BUN npm=$NPM"

require "deps installed (node_modules/.bin/tsc)" check_deps
require "build (npm run build -> dist/)" build_cli
require "artifact (dist/cli.js executable, all bin entries resolve)" check_artifact
require "version (bun dist/cli.js --version)" check_version
require "pack (npm run pack:check: dist + README, no .map, no tarball)" check_pack
require "start (hermetic daemon writes its own descriptor)" start_daemon
require "answer (headless -p json: non-empty text, is_error false)" check_turn
require "stop (daemon gone, no orphan)" stop_daemon

summary
echo "[install-smoke] ALL PASS"
