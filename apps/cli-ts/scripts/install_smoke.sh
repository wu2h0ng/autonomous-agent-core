#!/usr/bin/env bash
# cli-ts install smoke — "it installs, it starts, it answers", machine-checked.
#
# What this proves, in the order a real user meets it:
#   1. deps      node_modules is installed (this script does NOT install; CI
#                runs `bun install --frozen-lockfile` first): node_modules/ is
#                there, the build toolchain (.bin/tsc) and the test driver
#                (.bin/tsx, which scripts.test registers as `node --import tsx`)
#                are executable, and the npm/bun/python this script drives all
#                resolve
#   2. build     `npm run build` turns src/ into dist/ (tsc, no bundler), from
#                NOTHING: dist/ is deleted first, so a build that quietly turned
#                into a no-op -- or that re-instates an older dist/ -- cannot
#                pass by leaving the previous output in place
#   3. artifact  dist/cli.js exists AND is executable, every `bin` name in
#                package.json (noem / agentos / agent-os / agent-os-ts) resolves
#                to a file that exists and is executable -- a bin that is not
#                executable is what an install would hand the user -- and every
#                file in dist/ is NEWER than the newest build input, so a dist/
#                that was never rebuilt from the current src/ is not mistaken for
#                the artifact under test
#   4. version   `bun dist/cli.js --version` prints the package.json version.
#                There is no second source of truth for that number to compare
#                against: src/version.ts reads package.json at RUN TIME (the
#                build-time --define lives in scripts/compile.ts, which is not on
#                this path), so "the manifest was edited after the build" is
#                caught by the freshness assertion in step 3, and "the shipped
#                copy disagrees with the built one" by the unpacked run in step 5
#   5. pack      `npm run pack:check` (prepack -> build, then `npm pack
#                --dry-run`) runs and writes no tarball; then a REAL `npm pack`
#                into $TMP produces the tarball an install would receive, and that
#                tarball is checked from `npm pack --json` (structured output,
#                never parsed out of npm's human-readable `npm notice` text) for:
#                no source map, README.md + dist/cli.js present, every `bin`
#                target inside it, no src/ or test/ leak, and EXACTLY the file set
#                of the built dist/ -- the module graph, not just the entry point.
#                The tarball is then unpacked and its OWN dist/cli.js is RUN
#                (`bun dist/cli.js --version`, with the declared dependencies
#                beside it as an install would provide them), so "what gets
#                installed actually starts" is measured instead of inferred from a
#                file listing
#   6. start     the hermetic daemon (scripted provider, no network, no
#                credentials) comes UP: it re-writes its descriptor, the
#                descriptor's pid is this script's daemon pid, and the port it
#                names actually accepts a connection
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
# therefore checked on the two things an install would ship or run: the tarball a
# real `npm pack` writes (its contents, the bin targets it must contain, and a RUN
# of the unpacked cli.js with the declared dependencies next to it) and the real
# runtime path a user gets afterwards (`bun dist/cli.js`, the built artifact --
# never `npx tsx src/cli.tsx`, which would test the source tree instead).
#
# Deliberate choices:
#   - the interpreter is `${PY:-python3}`; no `uv`, which CI need not have
#   - every wait is BOUNDED and carries a positive signal (descriptor RE-created,
#     pid matches, port accepts, one reply object). macOS ships no GNU `timeout`,
#     so the deadline is a poll loop of this script's own (see run_capped): with
#     none, a daemon that comes up but never answers a turn holds the whole check
#     open until the CI job's own wall-clock limit fires (measured: still waiting
#     at 40s), which burns runner time and attributes the failure to nothing
#   - the daemon is started as a direct child, so its pid is known and can be
#     matched against the descriptor it writes
#   - temp files live in `mktemp -d` under $TMPDIR, never a fixed top-level
#     path, so parallel runs cannot collide
#   - the turn runs with `--no-daemon`: with auto-start enabled an unhealthy
#     descriptor makes the client spawn its own daemon from ambient config, and
#     on a machine with a live provider that turn answers for real (observed
#     during fault injection), which would let this check pass without the
#     daemon under test
#   - the three daemon-dependent checks (start / answer / stop) are soft: a turn
#     that never returns is recorded as FAIL, the daemon is still stopped, the
#     PASS/FAIL list is still printed, and the script still exits non-zero
#   - the two freshness/identity assertions (dist/ newer than src/; the unpacked
#     cli.js is byte-identical to the built one) assume a tree nothing else is
#     writing to while the check runs -- true under CI, and the point of the
#     assertion: a concurrent writer that rewrites src/ or dist/ mid-run is
#     exactly the case where the artifact must not be reported as verified
#   - any failed check exits non-zero and prints the PASS/FAIL list
#
# Usage: bash apps/cli-ts/scripts/install_smoke.sh
# Env:   PY (default python3)  BUN (default bun)  NPM (default npm)
#        BUILD_TIMEOUT_SECONDS   (default 300)  each `npm run build`
#        PACK_TIMEOUT_SECONDS    (default 300)  each `npm pack` invocation
#        VERSION_TIMEOUT_SECONDS (default 60)   `bun dist/cli.js --version`
#        START_TIMEOUT_SECONDS   (default 60)   daemon descriptor appearing
#        READY_TIMEOUT_SECONDS   (default 30)   daemon port accepting
#        INSTALL_TIMEOUT_SECONDS (default 60)   unpacked cli.js --version
#        TURN_TIMEOUT_SECONDS    (default 90)   the headless turn
set -u

CLI_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PY:-python3}"
BUN="${BUN:-bun}"
NPM="${NPM:-npm}"

BUILD_TIMEOUT_SECONDS="${BUILD_TIMEOUT_SECONDS:-300}"
PACK_TIMEOUT_SECONDS="${PACK_TIMEOUT_SECONDS:-300}"
VERSION_TIMEOUT_SECONDS="${VERSION_TIMEOUT_SECONDS:-60}"
START_TIMEOUT_SECONDS="${START_TIMEOUT_SECONDS:-60}"
READY_TIMEOUT_SECONDS="${READY_TIMEOUT_SECONDS:-30}"
INSTALL_TIMEOUT_SECONDS="${INSTALL_TIMEOUT_SECONDS:-60}"
TURN_TIMEOUT_SECONDS="${TURN_TIMEOUT_SECONDS:-90}"

DAEMON_PID=""
DAEMON_READY=0
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

require() {   # require <label> <function>  — a failure here aborts the chain
  run_step "$1" "$2" || { summary; exit 1; }
}

require_soft() {   # require_soft <label> <function>  — records the failure and goes on
  run_step "$1" "$2"
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

run_capped() {   # run_capped <dir> <seconds> <stdout-file> <stderr-file> <command...>
  # A deadline around a command, without GNU `timeout` (absent on macOS; only
  # `gtimeout` with coreutils, which CI need not have). The command runs as a
  # direct child of a subshell that execs it, so $! is the command's own pid and
  # `kill -0` stops succeeding as soon as bash has reaped it (verified). Returns
  # the command's status, or 124 when the deadline killed it.
  local dir="$1"
  local limit="$2"
  local out="$3"
  local err="$4"
  local pid waited=0 status=0
  shift 4
  ( cd "$dir" && exec "$@" ) > "$out" 2> "$err" &
  pid=$!
  while kill -0 "$pid" 2>/dev/null; do
    if [ "$waited" -ge "$limit" ]; then
      echo "TIMEOUT: killed after ${limit}s — this command never returned" >> "$err"
      kill -TERM "$pid" 2>/dev/null
      pkill -TERM -P "$pid" 2>/dev/null
      sleep 1
      kill -KILL "$pid" 2>/dev/null
      pkill -KILL -P "$pid" 2>/dev/null
      wait "$pid" 2>/dev/null
      return 124
    fi
    sleep 1
    waited=$((waited + 1))
  done
  wait "$pid"
  status=$?
  return "$status"
}

cleanup() {
  local status=$?
  trap - EXIT
  # Idempotent: if the last check already stopped the daemon, this is a no-op.
  stop_daemon >/dev/null 2>&1
  # check_pack unpacks a tarball and puts a symlink to the dev tree's real
  # node_modules inside it (the dependencies an install would provide). Unlink it
  # explicitly before any rm -rf below, so nothing here can ever walk into the
  # real dependency tree by accident.
  if [ -n "$TMP" ]; then
    rm -f "$TMP/unpacked/package/node_modules"
  fi
  if [ "$FAILED_COUNT" -eq 0 ]; then
    rm -rf "$TMP"
  else
    echo "[install-smoke] FAILED — artifacts kept for inspection: $TMP" >&2
  fi
  exit "$status"
}

check_deps() {
  local node_modules="$CLI_DIR/node_modules"
  local missing=0
  local tool bin
  [ -d "$node_modules" ] || {
    echo "missing $node_modules — install dependencies first: bun install --frozen-lockfile"
    return 1
  }
  echo "node_modules: $node_modules"
  # tsc builds the artifact; tsx is the driver scripts.test registers
  # (`node --import tsx --test ...`). A tree with one but not the other is a
  # half-installed tree, and the CLI job needs both.
  for tool in tsc tsx; do
    if [ -x "$node_modules/.bin/$tool" ]; then
      echo "$tool: $node_modules/.bin/$tool"
    else
      echo "missing $node_modules/.bin/$tool — install dependencies first: bun install --frozen-lockfile"
      missing=1
    fi
  done
  [ "$missing" -eq 0 ] || return 1
  for bin in "$NPM" "$BUN" "$PY"; do
    if ! command -v "$bin" >/dev/null 2>&1; then
      echo "$bin is not on PATH (override with NPM= / BUN= / PY=)"
      return 1
    fi
    echo "$bin: $(command -v "$bin")"
  done
}

build_cli() {
  local status=0
  # A no-op build, or one that re-instates an older dist/, must not be able to
  # pass by leaving a previous dist/ in place: start from nothing. `npm run build`
  # deletes dist/ itself (scripts.build), so this changes nothing about what the
  # build does -- it only removes what it would otherwise inherit.
  rm -rf "$CLI_DIR/dist"
  run_capped "$CLI_DIR" "$BUILD_TIMEOUT_SECONDS" "$TMP/build.out" "$TMP/build.err" "$NPM" run build
  status=$?
  cat "$TMP/build.out" "$TMP/build.err"
  if [ "$status" -ne 0 ]; then
    echo "npm run build exited $status (limit ${BUILD_TIMEOUT_SECONDS}s)"
    return 1
  fi
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
assert built, "dist/ is empty after the build"
print("bin entries: " + ", ".join(f"{n} -> {bins[n]}" for n in sorted(bins)))
print(f"dist/ files: {len(built)}")

# Freshness: every built file must be NEWER than every build input. This is what
# makes the artifact check an assertion about THIS src/ rather than about
# whatever dist/ happened to be lying around, and it is what covers the version
# check below, whose expected value has no source of its own (package.json is
# read at run time). A `build` that copies a stale dist/ back, or a manifest edit
# that never triggered a rebuild, fails here.
inputs = [
    p
    for p in list((cli_dir / "src").rglob("*"))
    + [cli_dir / "package.json", cli_dir / "tsconfig.json", cli_dir / "tsconfig.build.json"]
    if p.is_file()
]
assert inputs, "no build inputs found under src/ or the tsconfigs"
newest_input = max(p.stat().st_mtime for p in inputs)
stale = sorted(
    str(p.relative_to(cli_dir))
    for p in built
    if p.stat().st_mtime < newest_input
)
assert not stale, (
    f"{len(stale)} file(s) in dist/ are older than the newest build input "
    f"(stale build, or a build that did not recompile): {stale[:10]}"
)
newest_input_name = max(inputs, key=lambda p: p.stat().st_mtime)
print(
    f"dist/ freshness: all {len(built)} built files are newer than the newest "
    f"input ({newest_input_name.relative_to(cli_dir)})"
)
PY
}

check_version() {
  local expected printed status
  expected="$("$PY" -c 'import json,sys;print(json.load(open(sys.argv[1], encoding="utf-8"))["version"])' "$CLI_DIR/package.json")" || return 1
  [ -n "$expected" ] || { echo "package.json has no version"; return 1; }
  run_capped "$CLI_DIR" "$VERSION_TIMEOUT_SECONDS" "$TMP/version.out" "$TMP/version.err" "$BUN" dist/cli.js --version
  status=$?
  printed="$(cat "$TMP/version.out")"
  echo "package.json version         : $expected"
  echo "bun dist/cli.js --version    : $printed"
  if [ "$status" -ne 0 ]; then
    echo "bun dist/cli.js --version exited $status (limit ${VERSION_TIMEOUT_SECONDS}s)"
    cat "$TMP/version.err"
    return 1
  fi
  case "$printed" in
    [0-9]*.[0-9]*.[0-9]*) ;;
    *) echo "--version did not print a version number"; return 1 ;;
  esac
  [ "$printed" = "$expected" ] || {
    echo "--version printed '$printed' but package.json says '$expected'"
    return 1
  }
  echo "note: the manifest is this build's own (freshness asserted above), so a" \
       "version bump that never rebuilt cannot satisfy this check"
  echo "runtimes: $("$BUN" --version 2>/dev/null | head -1) | $("$NPM" --version 2>/dev/null) | $("$PY" -V 2>&1)"
  echo "HEAD: $(git -C "$CLI_DIR" rev-parse --short HEAD 2>/dev/null || echo '<no git>')"
}

check_pack() {
  local before after pack_dir tgz unpacked expected printed status
  before="$(cd "$CLI_DIR" && ls -1 ./*.tgz 2>/dev/null | sort)"
  run_capped "$CLI_DIR" "$PACK_TIMEOUT_SECONDS" "$TMP/pack-check.log" "$TMP/pack-check.err" "$NPM" run pack:check
  status=$?
  cat "$TMP/pack-check.log" "$TMP/pack-check.err"
  if [ "$status" -ne 0 ]; then
    echo "pack:check exited $status (limit ${PACK_TIMEOUT_SECONDS}s)"
    return 1
  fi
  after="$(cd "$CLI_DIR" && ls -1 ./*.tgz 2>/dev/null | sort)"
  [ "$before" = "$after" ] || {
    echo "pack:check wrote a tarball; a dry run must not create one"
    echo "before: $before"
    echo "after : $after"
    return 1
  }

  # The real tarball, from the repo at the state the checks above just verified.
  # `--ignore-scripts` because prepack would only run `npm run build` a second
  # time: the dry run above already did that, and what the tarball contains is
  # decided by package.json `files`, not by the build.
  pack_dir="$TMP/pack"
  mkdir -p "$pack_dir"
  run_capped "$CLI_DIR" "$PACK_TIMEOUT_SECONDS" "$TMP/pack.json" "$TMP/pack.err" \
    "$NPM" pack --json --ignore-scripts --pack-destination "$pack_dir"
  status=$?
  if [ "$status" -ne 0 ]; then
    echo "npm pack exited $status (limit ${PACK_TIMEOUT_SECONDS}s)"
    cat "$TMP/pack.err"
    echo "--- stdout ---"
    cat "$TMP/pack.json"
    return 1
  fi
  tgz="$(ls -1 "$pack_dir"/*.tgz 2>/dev/null)"
  [ -n "$tgz" ] || {
    echo "npm pack wrote no tarball into $pack_dir"
    ls -l "$pack_dir"
    return 1
  }
  [ "$(printf '%s\n' "$tgz" | wc -l | tr -d ' ')" = "1" ] || {
    echo "npm pack wrote more than one tarball into $pack_dir:"
    printf '%s\n' "$tgz"
    return 1
  }

  unpacked="$TMP/unpacked"
  mkdir -p "$unpacked"
  tar -xzf "$tgz" -C "$unpacked" || {
    echo "could not unpack $tgz"
    return 1
  }

  "$PY" - "$TMP/pack.json" "$CLI_DIR" "$unpacked/package" "$tgz" <<'PY'
import json
import pathlib
import sys
import tarfile

pack_json = pathlib.Path(sys.argv[1])
cli_dir = pathlib.Path(sys.argv[2])
root = pathlib.Path(sys.argv[3])
tgz = pathlib.Path(sys.argv[4])

data = json.loads(pack_json.read_text(encoding="utf-8"))
assert isinstance(data, list) and len(data) == 1, (
    f"unexpected `npm pack --json` shape: {type(data).__name__} — the structured "
    "output this check reads is not what npm produced"
)
record = data[0]
listed = record.get("files")
assert listed, f"`npm pack --json` listed no files: {record!r}"
entries = [f["path"] for f in listed]
print(f"tarball {record['filename']} ({record.get('size')} bytes), {len(entries)} entries")
print("  " + "\n  ".join(entries))

# The listing is not the archive. Cross-check every path against the bytes.
with tarfile.open(tgz) as tar:
    archived = sorted(
        m.name[len("package/"):] for m in tar.getmembers() if m.isfile()
    )
assert sorted(entries) == archived, (
    "`npm pack --json` and the tarball itself disagree about their contents: "
    f"only in the listing {sorted(set(entries) - set(archived))}, "
    f"only in the archive {sorted(set(archived) - set(entries))}"
)
print(f"listing matches the archive: {len(archived)} files")

maps = [e for e in entries if e.endswith(".map")]
assert not maps, f"the tarball ships source maps: {maps}"
assert "README.md" in entries, "the tarball has no README.md"
assert "dist/cli.js" in entries, "the tarball has no dist/cli.js"

bins = json.loads((cli_dir / "package.json").read_text(encoding="utf-8")).get("bin") or {}
assert bins, "package.json declares no bin entries"
for name in sorted(bins):
    target = bins[name].lstrip("./")
    assert target in entries, f"bin {name!r} -> {target} is NOT in the tarball"

leaked = [e for e in entries if e.split("/")[0] in {"src", "test", "tests", "scripts"}]
assert not leaked, f"the tarball leaks the dev tree: {leaked}"

# The module graph, not just the entry point. A `files` list narrowed to
# e.g. ["dist/cli.js"] satisfies every assertion above while shipping a client
# that dies on `Cannot find module './client.js'` the moment it is installed, so
# the tarball must carry the WHOLE built dist/ (minus source maps).
shipped = sorted(e for e in entries if e.startswith("dist/"))
built = sorted(
    str(p.relative_to(cli_dir))
    for p in (cli_dir / "dist").rglob("*")
    if p.is_file() and not p.name.endswith(".map")
)
missing = sorted(set(built) - set(shipped))
unexpected = sorted(set(shipped) - set(built))
assert not missing, (
    f"the tarball's dist/ is missing {len(missing)} of the {len(built)} built "
    f"file(s) — the installed client's module graph has holes in it: {missing}"
)
assert not unexpected, f"the tarball carries dist/ files that were not built: {unexpected}"
print(f"dist/ complete: all {len(shipped)} built files are in the tarball")

# Every bin target must survive the round trip as an executable FILE.
for name in sorted(bins):
    target = bins[name].lstrip("./")
    path = root / target
    assert path.is_file(), f"bin {name!r} -> {target} did not survive unpacking"
    assert path.stat().st_mode & 0o111, f"unpacked bin {name!r} -> {target} lost its exec bit"
print("unpacked bin targets: present and executable")
PY
  [ $? -eq 0 ] || return 1

  # The installed thing must actually START. Nothing above proves that: a
  # complete file LIST can still be a client that dies on its first import.
  expected="$("$PY" -c 'import json,sys;print(json.load(open(sys.argv[1], encoding="utf-8"))["version"])' "$CLI_DIR/package.json")" || return 1
  # Dependencies next to the package, as an install would provide them: there is
  # no registry here (package.json is private:true and this check never
  # publishes), so the tree the lockfile produced stands in. The files under test
  # are the ones that came out of the tarball.
  rm -f "$unpacked/package/node_modules"
  ln -s "$CLI_DIR/node_modules" "$unpacked/package/node_modules"
  run_capped "$unpacked/package" "$INSTALL_TIMEOUT_SECONDS" "$TMP/installed.out" "$TMP/installed.err" \
    "$BUN" dist/cli.js --version
  status=$?
  printed="$(cat "$TMP/installed.out")"
  echo "unpacked tree: $unpacked/package"
  echo "  bun dist/cli.js --version -> $printed"
  if [ "$status" -ne 0 ]; then
    echo "the unpacked tarball does not start: exited $status (limit ${INSTALL_TIMEOUT_SECONDS}s)"
    echo "--- stderr ---"
    cat "$TMP/installed.err"
    return 1
  fi
  [ "$printed" = "$expected" ] || {
    echo "the unpacked tarball reports '$printed' but the dev tree's package.json says '$expected'"
    return 1
  }
  # And it is THIS build's artifact, not a snapshot of an older dist/.
  "$PY" - "$unpacked/package/dist/cli.js" "$CLI_DIR/dist/cli.js" <<'PY'
import pathlib
import sys

shipped = pathlib.Path(sys.argv[1]).read_bytes()
built = pathlib.Path(sys.argv[2]).read_bytes()
assert shipped == built, (
    "the tarball's dist/cli.js differs from the dist/cli.js this run built "
    f"({len(shipped)} vs {len(built)} bytes)"
)
print(f"unpacked dist/cli.js is byte-identical to the built one ({len(shipped)} bytes)")
PY
  [ $? -eq 0 ] || return 1
}

wait_for_port() {   # wait_for_port <port>  — bounded TCP-connect poll
  local port="$1"
  local waited=0
  while [ "$waited" -lt "$((READY_TIMEOUT_SECONDS * 2))" ]; do
    if "$PY" - "$port" <<'PY' >/dev/null 2>&1
import socket
import sys

socket.create_connection(("127.0.0.1", int(sys.argv[1])), timeout=1).close()
PY
    then
      return 0
    fi
    waited=$((waited + 1))
    sleep 0.5
  done
  return 1
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
    if [ "$waited" -ge "$((START_TIMEOUT_SECONDS * 2))" ]; then
      echo "no descriptor after ${START_TIMEOUT_SECONDS}s; daemon log:"
      cat "$TMP/daemon.log"
      return 1
    fi
    sleep 0.5
  done
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
  # A descriptor on disk is a claim, not a listener: wait (bounded) for the port
  # it names to accept a connection. This replaces the bare `sleep 2` that used
  # to stand in for "the surface server has settled" -- same intent, but it is a
  # positive signal and it cannot outlive its deadline.
  if ! wait_for_port "$port"; then
    echo "no connection accepted on 127.0.0.1:$port within ${READY_TIMEOUT_SECONDS}s; daemon log:"
    cat "$TMP/daemon.log"
    return 1
  fi
  echo "daemon up: pid $DAEMON_PID on 127.0.0.1:$port (descriptor $DESC, port accepts)"
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
  # Bounded: a daemon that is up but never answers must FAIL this check, not hold
  # the whole run open until the CI job's own timeout fires.
  run_capped "$CLI_DIR" "$TURN_TIMEOUT_SECONDS" "$TMP/headless.json" "$TMP/headless.err" \
    "$BUN" dist/cli.js --descriptor "$DESC" --no-daemon \
    -p "install smoke: prove the installed client answers" \
    --output-format json
  status=$?
  if [ "$status" -eq 124 ]; then
    echo "the turn never returned: killed after ${TURN_TIMEOUT_SECONDS}s (the daemon is up — its descriptor and port were just verified — but it did not answer)"
    echo "--- stderr ---"
    cat "$TMP/headless.err"
    echo "--- stdout ---"
    cat "$TMP/headless.json"
    return 1
  fi
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
echo "[install-smoke] limits (s): build=$BUILD_TIMEOUT_SECONDS pack=$PACK_TIMEOUT_SECONDS version=$VERSION_TIMEOUT_SECONDS start=$START_TIMEOUT_SECONDS ready=$READY_TIMEOUT_SECONDS install=$INSTALL_TIMEOUT_SECONDS turn=$TURN_TIMEOUT_SECONDS"

require "deps installed (node_modules, .bin/tsc, .bin/tsx, npm/bun/python)" check_deps
require "build (npm run build -> dist/, starting from no dist/)" build_cli
require "artifact (dist/cli.js executable, all bin entries resolve, dist/ newer than src/)" check_artifact
require "version (bun dist/cli.js --version)" check_version
require "pack (pack:check + real tarball: complete dist/, unpacks and runs)" check_pack
# From here on a failure must not skip the wrap-up: the daemon this run started
# has to be stopped and the orphan sweep has to run whatever happened above.
require_soft "start (hermetic daemon: descriptor, pid, port accepts)" start_daemon && DAEMON_READY=1
if [ "$DAEMON_READY" -eq 1 ]; then
  require_soft "answer (headless -p json: non-empty text, is_error false)" check_turn
else
  fail "answer (skipped: the hermetic daemon never came up)"
fi
require_soft "stop (daemon gone, no orphan)" stop_daemon

summary
if [ "$FAILED_COUNT" -ne 0 ]; then
  echo "[install-smoke] FAILED" >&2
  exit 1
fi
echo "[install-smoke] ALL PASS"
