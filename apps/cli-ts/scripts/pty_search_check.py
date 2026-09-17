'''Ctrl-R reverse search (#14) + multiline display/composer growth (#12 tail).

Two scenarios, each in a FRESH client (the same discipline as
pty_fullscreen_vim.py): reusing one instance means a submitted turn parks the
app on an approval card, which blurs the composer and corrupts the next phase.

Scenario A (#14):
  multiline submit -> /status submit (a local command, so it does not consume a
  scripted provider turn) -> Ctrl-R -> assert the overlay -> nonsense query ->
  Esc restores the draft -> Ctrl-R + query + Enter loads the entry.

Scenario B (multiline):
  type 8 lines into the composer; the composer must grow so all 8 are visible
  (it used to be a fixed 5 rows and showed only the last 3), and the transcript
  must show a submitted multiline draft one row per line.

    uv run python scripts/pty_search_check.py
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
ROWS, COLS = 44, 120

tmp = Path(tempfile.mkdtemp(prefix="search-check-"))
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


def spawn() -> tuple[int, int, Screen]:
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
    return pid, master, Screen(ROWS, COLS)


def pump(master: int, screen: Screen, seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end:
        ready, _, _ = select.select([master], [], [], 0.2)
        if ready:
            try:
                screen.feed(os.read(master, 65536))
            except OSError:
                break


def type_text(master: int, text: str, delay: float = 0.06) -> None:
    for ch in text:
        os.write(master, ch.encode())
        time.sleep(delay)


def kill(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def composer_text(screen: Screen) -> str:
    """Text inside the composer box, located by its `─message` title row."""
    rows = screen.text_rows()
    start = next((i for i, row in enumerate(rows) if "─message" in row), -1)
    if start == -1:
        return ""
    body: list[str] = []
    for row in rows[start + 1 :]:
        if "└" in row:
            break
        body.append(row.strip("│ "))
    return "\n".join(body).strip()


print("############ SCENARIO A: Ctrl-R reverse search ############")
pid, master, screen = spawn()
pump(master, screen, 6)

# 1) multiline draft -> must occupy one transcript row per line
type_text(master, "l1")
os.write(master, b"\n")
time.sleep(0.2)
type_text(master, "l2")
os.write(master, b"\n")
time.sleep(0.2)
type_text(master, "l3")
time.sleep(0.3)
os.write(master, b"\r")
time.sleep(1.0)
pump(master, screen, 6)
transcript_rows = screen.text_rows()
multiline_rows = [row for row in transcript_rows if any(t in row for t in ("l1", "l2", "l3"))]
print("MULTILINE_TRANSCRIPT_ROWS:", len(multiline_rows))

# 2) a local command gives a second history entry without a provider turn
type_text(master, "/status")
time.sleep(0.3)
os.write(master, b"\r")
time.sleep(1.0)
pump(master, screen, 4)

# 3) Ctrl-R opens the overlay
type_text(master, "zz")
time.sleep(0.3)
os.write(master, b"\x12")
time.sleep(0.8)
pump(master, screen, 2)
after_open = "\n".join(screen.text_rows())
print("SEARCH_OVERLAY_SHOWN:", "reverse search (Ctrl-R):" in after_open)
print("SEARCH_MATCH_LISTED:", "/status" in after_open)

# 4) nonsense query -> hint
type_text(master, "qqqq")
time.sleep(0.6)
pump(master, screen, 2)
after_nonsense = "\n".join(screen.text_rows())
print("SEARCH_NO_MATCH_HINT:", "no matching history" in after_nonsense)
print("SEARCH_QUERY_ECHOED:", "reverse search (Ctrl-R): qqqq" in after_nonsense)

# 5) Esc restores the saved draft
os.write(master, b"\x1b")
time.sleep(0.8)
pump(master, screen, 2)
after_esc = "\n".join(screen.text_rows())
print("SEARCH_CLOSED_ON_ESC:", "reverse search (Ctrl-R):" not in after_esc)
print("SEARCH_CANCEL_RESTORES_DRAFT:", composer_text(screen) == "zz")

# 6) Ctrl-R -> query -> Enter loads the entry
os.write(master, b"\x12")
time.sleep(0.8)
pump(master, screen, 1)
type_text(master, "status")
time.sleep(0.6)
pump(master, screen, 2)
os.write(master, b"\r")
time.sleep(0.8)
pump(master, screen, 2)
picked = composer_text(screen)
print("SEARCH_PICK_LOADS_ENTRY:", picked == "/status", repr(picked))
kill(pid)

print()
print("############ SCENARIO B: multiline composer + display ############")
pid2, master2, screen2 = spawn()
pump(master2, screen2, 6)
composer_before = composer_text(screen2)
LINES = 8
for n in range(1, LINES + 1):
    type_text(master2, f"line{n}")
    if n < LINES:
        os.write(master2, b"\n")
        time.sleep(0.2)
time.sleep(0.6)
pump(master2, screen2, 2)
composer_after = composer_text(screen2)
visible = [f"line{n}" for n in range(1, LINES + 1) if f"line{n}" in composer_after]
print("COMPOSER_EMPTY_ROWS:", repr(composer_before))
print("COMPOSER_VISIBLE_LINES:", len(visible), "of", LINES)
kill(pid2)

daemon.terminate()
shutil.rmtree(tmp, ignore_errors=True)

problems: list[str] = []
if len(multiline_rows) < 3:
    problems.append(
        f"multiline draft did not take one row per line (found {len(multiline_rows)} rows for l1/l2/l3)"
    )
if "reverse search (Ctrl-R):" not in after_open:
    problems.append("Ctrl-R did not open the reverse search overlay")
if "/status" not in after_open:
    problems.append("the history entry was not listed as a match")
if "no matching history" not in after_nonsense:
    problems.append("a nonsense query did not show the no-match hint")
if "reverse search (Ctrl-R):" in after_esc or composer_text is None:
    problems.append("Esc did not close the search overlay")
if len(visible) < LINES:
    problems.append(
        f"composer did not grow with the draft (only {len(visible)}/{LINES} lines visible)"
    )

if problems:
    print()
    print("SEARCH_CHECK: FAIL")
    for problem in problems:
        print(f" - {problem}")
    raise SystemExit(1)
print()
print("SEARCH_CHECK: PASS")
