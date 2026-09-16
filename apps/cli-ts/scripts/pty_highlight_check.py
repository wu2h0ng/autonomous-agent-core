'''Syntax-highlighting check (#16): are fenced code tokens COLOURED?

The hermetic stub now replies with a fenced python block, so this asserts the
rendered SGR of code tokens via the frame reader. It currently FAILS (exit 1):
the block renders but every token is default white, i.e. the registered
SyntaxStyle scopes are not applied - kept as an honest reproducer.

    uv run python scripts/pty_highlight_check.py
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
tmp = Path(tempfile.mkdtemp(prefix="hl-check-"))
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
fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
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

screen = Screen(40, 120)


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
os.write(master, b"hi")
time.sleep(0.4)
os.write(master, b"\r")
time.sleep(1.0)
pump(7)


print("=== CODE ROWS ===")
code_styles: list[tuple] = []
for index, text in enumerate(screen.text_rows()):
    if "def " in text or "return" in text or "highlighted fixture" in text:
        for span_text, fg, _bg, _bold in screen.spans(index):
            if span_text.strip():
                code_styles.append((span_text.strip(), fg))
                print(f"{index:02d} {span_text.strip()[:32]!r} fg={fg}")

coloured = [s for s in code_styles if s[1] not in (None, (255, 255, 255))]
print("CODE_TOKEN_COUNT:", len(code_styles))
print("CODE_COLOURED:", len(coloured) > 0)
print("FENCED_CODE_RENDERED:", screen.find_row("def ") != -1)
# Honest reproducer: fails until the SyntaxStyle scopes actually apply.
if not coloured:
    print(
        "NOT COLOURED: the reply's fenced code block renders (def/return visible) but every\n"
        "code token is painted with the default white - the registered SyntaxStyle scopes\n"
        "(keyword/string/comment/function) are NOT applied by the markdown renderable.\n"
        "Next: inspect opentui's highlighter for the scope vocabulary/shape it expects."
    )
    raise SystemExit(1)

try:
    os.kill(pid, signal.SIGKILL)
except ProcessLookupError:
    pass
daemon.terminate()
shutil.rmtree(tmp, ignore_errors=True)
