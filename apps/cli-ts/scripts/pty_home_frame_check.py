'''Home panel check (#18): does the welcome panel own the FIRST frame?

Two gaps are covered here, because they share the same evidence (the first frame
before any input):

  * #18 - the full-screen view rendered an EMPTY transcript before the first
    turn, while Ink greeted the user with `HomeView`. The panel must appear on
    the first frame and must be gone once a turn has produced messages.
  * the chrome defect found while wiring it (#3) - the top status line and the
    footer were laid out with zero height, so the status line never appeared at
    all (the transcript's border drew over it) and the footer was painted on top
    of the composer box's bottom border. Both `<text>` rows now carry an
    explicit height.

The controller opens its session lazily (`ensureSession` is only called by
runTurn), so the panel is not a flash: it persists until the first turn.

    uv run python scripts/pty_home_frame_check.py
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

HERE = Path("/Users/mima1234/Documents/AI-Agent-Projects/autonomous-agent-core/.worktrees/os-sandbox/apps/cli-ts/scripts")
sys.path.insert(0, str(HERE))
from frame_reader import Screen  # noqa: E402

ROOT = HERE.parents[2]
CLI = ROOT / "apps" / "cli-ts"
ROWS, COLS = 40, 120
tmp = Path(tempfile.mkdtemp(prefix="home-check-"))
desc = tmp / "r.json"
ws = tmp / "ws"
ws.mkdir()
daemon = subprocess.Popen(
    ["uv", "run", "python", "apps/cli-ts/scripts/dev_daemon.py",
     "--descriptor", str(desc), "--database", str(tmp / "a.sqlite3"), "--workspace", str(ws)],
    cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
for _ in range(60):
    if desc.exists():
        break
    time.sleep(0.5)
time.sleep(1.5)

master, slave = pty.openpty()
fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))
env = dict(os.environ)
env["PATH"] = os.path.expanduser("~/.bun/bin") + ":" + env.get("PATH", "")
env["TERM"] = "xterm-256color"
env["AGENT_OS_RUNTIME_DESCRIPTOR"] = str(desc)
env["AGENT_OS_RUNTIME_DATABASE"] = str(tmp / "a.sqlite3")
pid = os.fork()
if pid == 0:
    os.setsid()
    os.dup2(slave, 0)
    os.dup2(slave, 1)
    os.dup2(slave, 2)
    os.chdir(str(CLI))
    os.execvpe("bun", ["bun", "run", "src/opentui/main.tsx", "--descriptor", str(desc)], env)
os.close(slave)

screen = Screen(ROWS, COLS)


def pump(seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end:
        ready, _, _ = select.select([master], [], [], 0.2)
        if ready:
            try:
                screen.feed(os.read(master, 65536))
            except OSError:
                break


pump(6)
first_rows = screen.text_rows()
first = "\n".join(first_rows)
print("=== FIRST FRAME (no input) ===")
for index, text in enumerate(first_rows):
    if text.strip():
        print(f"{index:02d}|{text}")

FIELD_LABELS = ("workspace", "path", "git", "provider", "version")
panel_rows = [row for row in first_rows if "governed terminal agent" in row]
fields_found = [label for label in FIELD_LABELS if f" {label} " in first]
header_row = next((row for row in first_rows if "◆ noem v" in row), "")
footer_row = next((row for row in first_rows if "❯" in row), "")

print()
print("HOME_PANEL_FIRST_FRAME:", bool(panel_rows))
print("HOME_FIELDS_FOUND:", len(fields_found), list(fields_found))
print("HOME_TIP_TITLE:", "Quick start" in first)
print("HOME_TIP_MODE_INSTRUCTION:", "/mode switches permission mode" in first)
print("HEADER_RENDERED:", header_row != "")
print("HEADER: ", repr(header_row))
print("FOOTER: ", repr(footer_row))
print("FOOTER_NOT_OVER_BORDER:", bool(footer_row) and "┘" not in footer_row)

# ---- one turn, then the panel must be gone -------------------------------
os.write(master, b"hi")
time.sleep(0.4)
os.write(master, b"\r")
time.sleep(1.0)
pump(7)
after = "\n".join(screen.text_rows())
print()
print("=== AFTER ONE TURN (panel must be gone) ===")
for index, text in enumerate(screen.text_rows()):
    if text.strip() and index < 6:
        print(f"{index:02d}|{text}")
print("HOME_PANEL_GONE_AFTER_TURN:", "Quick start" not in after and "governed terminal agent" not in after)
print("TURN_RENDERED:", "session" in after and "opened" in after)

problems: list[str] = []
if not panel_rows:
    problems.append("no home panel on the first frame (expected the NOEM card)")
if len(fields_found) != len(FIELD_LABELS):
    problems.append(f"missing home fields: {sorted(set(FIELD_LABELS) - set(fields_found))}")
if "Quick start" not in first:
    problems.append("the Quick start block is missing from the first frame")
if not header_row:
    problems.append("the top status line did not render (chrome defect)")
if footer_row and "┘" in footer_row:
    problems.append("the footer is painted over the composer box border (chrome defect)")
if "Quick start" in after or "governed terminal agent" in after:
    problems.append("the home panel is still on screen after a turn")
if "session" not in after or "opened" not in after:
    problems.append("the turn did not render (test harness problem, not a UI verdict)")

try:
    os.kill(pid, signal.SIGKILL)
except ProcessLookupError:
    pass
daemon.terminate()
shutil.rmtree(tmp, ignore_errors=True)

if problems:
    print()
    print("HOME_PANEL_CHECK: FAIL")
    for problem in problems:
        print(f" - {problem}")
    raise SystemExit(1)
print()
print("HOME_PANEL_CHECK: PASS")
