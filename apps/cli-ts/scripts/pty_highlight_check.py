'''Syntax-highlighting check (#16): are fenced code tokens COLOURED?

The hermetic stub replies with a fenced python block, so this asserts the
rendered SGR of code tokens via the frame reader.

Passes since the #16 fix. Before it, every code token was default white: the
bundled tree-sitter grammars are only {javascript, typescript, markdown,
markdown_inline, zig}, so a ```python fence had no parser and produced no
highlights for the SyntaxStyle scopes to style (measured; see
docs/product/TUI-PARITY-CHECKLIST-2026-09-16.md). The block is now highlighted
by highlight.js through CodeRenderable's `onHighlight`, and this asserts that
the tokens land on >= 3 distinct non-default colours (keyword / string / title /
comment families) rather than merely "something is not white".

Note: the terminal advertises 256 colours, so the palette index - not the theme
hex - is what arrives on the wire. frame_reader maps 38;5;N through the real
palette; asserting exact hexes here would be wrong.

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

# Located, not hard-coded: the absolute path into the author's `os-sandbox`
# worktree that used to be here made this check drive THAT tree from any other
# checkout and made it unrunnable anywhere else (CI included).
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from frame_reader import Screen  # noqa: E402

ROOT = HERE.parents[2]
CLI = ROOT / "apps" / "cli-ts"
tmp = Path(tempfile.mkdtemp(prefix="hl-check-"))
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
distinct = sorted({s[1] for s in coloured})
print("CODE_TOKEN_COUNT:", len(code_styles))
print("CODE_DISTINCT_COLOURS:", len(distinct), distinct)
print("CODE_COLOURED:", len(coloured) > 0)
print("FENCED_CODE_RENDERED:", screen.find_row("def ") != -1)

# A single coloured token would only prove "one scope happened to apply". The
# fix must land the keyword / string / title / comment families on separate
# theme colours, and keep the block itself intact.
problems: list[str] = []
if len(coloured) == 0:
    problems.append(
        "no code token is coloured: every token is painted with the default\n"
        "foreground, i.e. the registered SyntaxStyle scopes are not applied."
    )
if len(distinct) < 3:
    problems.append(f"expected >= 3 distinct code colours, saw {len(distinct)}: {distinct}")
if screen.find_row("def ") == -1:
    problems.append("the fenced block itself is missing from the frame ('def ' not found)")

if problems:
    print("NOT COLOURED:")
    for problem in problems:
        print(f" - {problem}")
    raise SystemExit(1)
print("HIGHLIGHT_OK: True")

try:
    os.kill(pid, signal.SIGKILL)
except ProcessLookupError:
    pass
daemon.terminate()
shutil.rmtree(tmp, ignore_errors=True)
