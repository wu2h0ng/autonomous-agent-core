'''Unified-entry check: does `src/cli.tsx` behave correctly on BOTH runtimes?

The entry now serves every mode, but only the interactive TUI needs native FFI:

  * view-free paths (--version / --help / doctor / daemon / provider / session /
    headless -p) must work on a runtime WITHOUT native FFI — that is what lets
    the node-only unit suite keep driving `src/cli.tsx`. It only holds while the
    view stays a LAZY import.
  * the interactive TUI must run on Bun and, on a runtime that cannot do FFI,
    print actionable advice instead of a raw `OpenTUI native FFI is not
    available` stack.

Sibling check to scripts/pty_home_frame_check.py, which drives the dev entry
(`src/opentui/main.tsx`) that the pty net uses. This one drives the REAL entry.

    uv run python scripts/pty_entry_check.py
'''
import fcntl
import os
import pty
import select
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time
from pathlib import Path

# This directory, located rather than hard-coded. It used to be an absolute
# path into the author's `os-sandbox` worktree, which made the check test THAT
# tree from any other checkout (measured: the header row printed
# `docs/terminal-gc-subagents-hooks-mcp-20260918` while the caller was on a
# different branch) and made it unrunnable anywhere else -- including CI, where
# the path does not exist and the daemon's `cwd=ROOT` raises FileNotFoundError.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from frame_reader import Screen  # noqa: E402

ROOT = HERE.parents[2]
CLI = ROOT / "apps" / "cli-ts"
ROWS, COLS = 40, 120
BUN = os.path.expanduser("~/.bun/bin/bun")

problems: list[str] = []
tmp = Path(tempfile.mkdtemp(prefix="entry-check-"))
desc = tmp / "r.json"
ws = tmp / "ws"
ws.mkdir()
daemon = subprocess.Popen(
    [sys.executable, "apps/cli-ts/scripts/dev_daemon.py",
     "--descriptor", str(desc), "--database", str(tmp / "a.sqlite3"), "--workspace", str(ws)],
    cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
for _ in range(60):
    if desc.exists():
        break
    time.sleep(0.5)
time.sleep(1.5)

env = dict(os.environ)
env["PATH"] = os.path.expanduser("~/.bun/bin") + ":" + env.get("PATH", "")
env["TERM"] = "xterm-256color"
env["AGENT_OS_RUNTIME_DESCRIPTOR"] = str(desc)
env["AGENT_OS_RUNTIME_DATABASE"] = str(tmp / "a.sqlite3")


def run_in_pty(argv: list[str], seconds: float = 8.0) -> str:
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))
    pid = os.fork()
    if pid == 0:
        os.setsid()
        os.dup2(slave, 0)
        os.dup2(slave, 1)
        os.dup2(slave, 2)
        os.chdir(str(CLI))
        os.execvpe(argv[0], argv, env)
    os.close(slave)
    screen = Screen(ROWS, COLS)
    end = time.time() + seconds
    while time.time() < end:
        ready, _, _ = select.select([master], [], [], 0.2)
        if ready:
            try:
                screen.feed(os.read(master, 65536))
            except OSError:
                break
    text = "\n".join(screen.text_rows())
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    return text


def run_plain(argv: list[str], seconds: int = 120) -> tuple[int, str]:
    done = subprocess.run(argv, cwd=str(CLI), env=env, capture_output=True,
                          text=True, timeout=seconds)
    return done.returncode, f"{done.stdout}{done.stderr}"


node = shutil.which("node")

print("=== view-free paths on node (no native FFI) ===")
code, out = run_plain([node, "--import", "tsx", "src/cli.tsx", "--version"])
print("--version            exit:", code, "out:", out.strip()[:60])
print("ENTRY_VERSION_NODE:", code == 0 and out.strip().count(".") == 2)
if not (code == 0 and out.strip().count(".") == 2):
    problems.append("--version did not print a bare version on node")

code, out = run_plain([node, "--import", "tsx", "src/cli.tsx", "--help"])
print("--help               exit:", code)
print("ENTRY_HELP_NODE:", code == 0 and "usage:" in out)
if not (code == 0 and "usage:" in out):
    problems.append("--help did not print usage on node")

print()
print("=== interactive on node must give advice, not a stack ===")
text = run_in_pty([node, "--import", "tsx", "src/cli.tsx", "--descriptor", str(desc)], 6.0)
flat = " ".join(text.split())
advised = "needs a runtime with native FFI" in flat and "Bun" in flat
stacked = "at Object.<anonymous>" in flat or "chunk-node" in flat
print("ENTRY_FFI_ADVICE_NODE:", advised)
print("ENTRY_NO_RAW_STACK_NODE:", not stacked)
if not advised:
    problems.append("the interactive path on node did not explain the FFI requirement")
if stacked:
    problems.append("the interactive path on node leaked a raw stack trace")

print()
print("=== interactive on bun (the shipped path) ===")
text = run_in_pty([BUN, "run", "src/cli.tsx", "--descriptor", str(desc)], 8.0)
rows = text.split("\n")
for index, row in enumerate(rows[:20]):
    if row.strip():
        print(f"{index:02d}|{row}")
provider_row = next((r.strip() for r in rows if " provider " in r), "")
print("ENTRY_TUI_BUN:", "governed terminal agent" in text)
print("ENTRY_TUI_BUN_HEADER:", any("◆ noem v" in r for r in rows))
print("ENTRY_TUI_BUN_PROVIDER_ROW:", repr(provider_row))
if "governed terminal agent" not in text:
    problems.append("the unified entry did not render the home panel on bun")
if not provider_row:
    problems.append("the provider row is missing from the home panel")

try:
    os.kill(daemon.pid, signal.SIGKILL)
except ProcessLookupError:
    pass
shutil.rmtree(tmp, ignore_errors=True)

if problems:
    print()
    print("ENTRY_CHECK: FAIL")
    for problem in problems:
        print(f" - {problem}")
    raise SystemExit(1)
print()
print("ENTRY_CHECK: PASS")
