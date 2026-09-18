#!/usr/bin/env python3
"""P3a multi-session e2e: a REAL cross-session switch from the agents panel.

The hermetic dev daemon exposes the surface API, so this fixture creates a
second session over HTTP, then drives the full-screen client: it opens its own
session by running a turn, selects the agents panel, moves the row cursor and
presses Enter to switch to a different session. The assertion is that the
resumed session id is a listed session AND differs from the client's own
session — i.e. a real cross-session switch, not a no-op.

Read-only/host-local: no provider key, no network, no workspace writes. Run from
apps/cli-ts:

    uv run python scripts/pty_fullscreen_p3a_multisession.py
"""
from __future__ import annotations

import fcntl
import json
import os
import pty
import re
import select
import shutil
import signal
import struct
import subprocess
import tempfile
import termios
import time
import urllib.request
from pathlib import Path

from agent_os_contracts import SURFACE_PROTOCOL_VERSION

ROOT = Path(__file__).resolve().parents[3]
CLI = ROOT / "apps" / "cli-ts"
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
SESSION_ID = re.compile(r"session-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def strip(buf: bytes) -> str:
    return ANSI.sub("", buf.decode(errors="replace")).replace("\x1b", "")


def read(fd: int, seconds: float) -> str:
    end = time.time() + seconds
    buf = b""
    while time.time() < end:
        ready, _, _ = select.select([fd], [], [], 0.2)
        if ready:
            try:
                buf += os.read(fd, 65536)
            except OSError:
                break
    return strip(buf)


def spawn(descriptor: Path, args: list[str]) -> tuple[int, int]:

    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
    env = dict(os.environ)
    env["PATH"] = os.path.expanduser("~/.bun/bin") + ":" + env.get("PATH", "")
    env["TERM"] = "xterm-256color"
    # Pin the client to THIS fixture daemon and its store, so the fixture's HTTP
    # calls and the client cannot end up on different runtimes.
    env["AGENT_OS_RUNTIME_DESCRIPTOR"] = str(descriptor)
    env["AGENT_OS_RUNTIME_DATABASE"] = str(descriptor.parent / "a.sqlite3")
    pid = os.fork()
    if pid == 0:
        os.setsid()
        os.dup2(slave, 0)
        os.dup2(slave, 1)
        os.dup2(slave, 2)
        os.chdir(str(CLI))
        os.execvpe(
            "bun",
            ["bun", "run", "src/opentui/main.tsx", "--descriptor", str(descriptor), *args],
            env,
        )
    os.close(slave)
    return pid, master


def kill(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def api(descriptor_path: Path, method: str, path: str, body: dict | None = None) -> object:
    # Read the descriptor on every call: if the client autostarts its own
    # runtime it rewrites this file, and the fixture must talk to whichever
    # daemon the client actually uses.
    descriptor = json.loads(descriptor_path.read_text())
    request = urllib.request.Request(
        f"http://{descriptor['host']}:{descriptor['port']}{path}",
        method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {descriptor['bearer_token']}",
            "X-Agent-OS-Protocol": SURFACE_PROTOCOL_VERSION,
            **({"Content-Type": "application/json"} if body is not None else {}),
        },
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode())


def client_ref() -> dict:
    return {
        "client_id": "p3a-multisession-fixture",
        "client_type": "TEST",
        "principal_id": "user:local",
        "tenant_id": "tenant:local",
        "workspace_id": "workspace:local",
        "device_id": "device:p3a-fixture",
    }


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="p3a-ms-"))
    descriptor_path = tmp / "r.json"
    workspace = tmp / "ws"
    workspace.mkdir()
    daemon = subprocess.Popen(
        [
            "uv", "run", "python", "apps/cli-ts/scripts/dev_daemon.py",
            "--descriptor", str(descriptor_path),
            "--database", str(tmp / "a.sqlite3"),
            "--workspace", str(workspace),
        ],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(60):
        if descriptor_path.exists():
            break
        time.sleep(0.5)
    time.sleep(1.5)
    frames: list[str] = []
    try:
        before = json.loads(descriptor_path.read_text())
        print("DAEMON_BEFORE_BOOT:", before["pid"], before["port"])
        pid, fd = spawn(descriptor_path, [])
        frames.append(read(fd, 4))
        after = json.loads(descriptor_path.read_text())
        print("DAEMON_AFTER_BOOT:", after["pid"], after["port"])
        print("DAEMON_STABLE:", before["pid"] == after["pid"])
        os.write(fd, b"hi")
        time.sleep(0.4)
        os.write(fd, b"\r")
        turn = read(fd, 6)
        frames.append(turn)
        print("===== TURN (client opens its own session) =====")
        print(turn)
        mine = SESSION_ID.search(turn)
        own_id = mine.group(0) if mine else None
        print("CLIENT_SESSION:", own_id)
        right_after = sorted(
            s["session_id"]
            for s in api(descriptor_path, "GET", "/v1/surface/sessions?limit=50")["sessions"]
        )
        print("LISTED_RIGHT_AFTER_TURN:", right_after)
        print("OWN_SESSION_LISTED_IMMEDIATELY:", own_id in right_after)
        # Create the second session only AFTER the client booted, so it is
        # registered in the same daemon the client is talking to.
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        created = api(descriptor_path, "POST", "/v1/surface/sessions", {
            "protocol_version": SURFACE_PROTOCOL_VERSION,
            "client": client_ref(),
            "statement": "fixture: second session for the multi-session switch",
            "idempotency_key": "p3a-fixture-open-1",
            "requested_at": now,
        })
        created_id = created["snapshot"]["session"]["session_id"]
        print("FIXTURE_SESSION:", created_id)
        after_turn = api(descriptor_path, "GET", "/v1/surface/sessions?limit=50")
        after_ids = sorted(s["session_id"] for s in after_turn["sessions"])
        print("SESSIONS AFTER TURN:", after_ids)
        print("OWN_SESSION_LISTED:", own_id in after_ids)
        print("SESSIONS_FULL:", json.dumps(after_turn["sessions"], ensure_ascii=False)[:600])

        # Determinism: wait until the daemon lists both sessions and the panel
        # has had a full 5s refresh cycle after that, so the tree rows exist
        # before we navigate (otherwise a fast navigation can race the poll).
        deadline = time.time() + 25
        while time.time() < deadline:
            ids = [x["session_id"] for x in api(
                descriptor_path, "GET", "/v1/surface/sessions?limit=50")["sessions"]]
            if len(ids) >= 2:
                break
            time.sleep(1)
        time.sleep(6)

        os.write(fd, b"x")  # liveness probe: input must echo in the composer
        time.sleep(0.4)
        print("LIVENESS_ECHO:", "x" in read(fd, 1.2))
        os.write(fd, b"\x7f")  # backspace the probe char
        time.sleep(0.3)
        os.write(fd, b"\t")  # select the agents panel
        time.sleep(1.5)
        # Let the 5s tree poll pick up the new session before navigating.
        time.sleep(5)
        frames.append(read(fd, 1.5))

        # Walk DOWN the tree one row at a time; Enter switches when the row is a
        # session. (Monotonic: the cursor clamps at the last row, which is a
        # session when the tree has any.)
        print("===== TREE (after refresh) =====")
        print(read(fd, 0.5))
        # Direct read-only probes: does the tree source have data at all?
        print("PROBE_MANDATES_STATUS:", end=" ")
        try:
            api(descriptor_path, "GET", "/v1/mandates")
            print("200")
        except Exception as exc:  # noqa: BLE001 - diagnostic only
            print(type(exc).__name__, exc)
        print("PROBE_SESSIONS:", sorted(
            s["session_id"] for s in api(
                descriptor_path, "GET", "/v1/surface/sessions?limit=50")["sessions"]))
        resumed: list[str] = []
        nav_deadline = time.time() + 45
        while time.time() < nav_deadline and not any(rid != own_id for rid in resumed):
            os.write(fd, b"\x0e")  # ctrl+n = move down inside the panel
            time.sleep(0.3)
            read(fd, 0.3)
            os.write(fd, b"\r")
            out = read(fd, 3)
            frames.append(out)
            # Styling splits words across escape sequences, so normalise to
            # [a-z0-9-] before matching the resumed-session id.
            flat = re.sub(r"[^a-z0-9-]", "", ANSI.sub("", out).lower())
            found = re.findall(r"resumedsession(session-[0-9a-f-]{36})", flat)
            if found:
                resumed.append(found[-1])
            if any(rid != own_id for rid in resumed):
                break

        flat_listed = sorted(s["session_id"] for s in api(
            descriptor_path, "GET", "/v1/surface/sessions?limit=50")["sessions"])
        switched = [rid for rid in resumed if rid != own_id]
        print("===== RESULT =====")
        print("own session            :", own_id)
        print("resumed ids            :", resumed)
        print("fixture-daemon listing :", flat_listed)
        print("SWITCHED_TO_OTHER_SESSION:", bool(switched) and switched[0] in flat_listed)
        print("FIXTURE_DAEMON_SEES_OWN_SESSION:", own_id in flat_listed)
        os.write(fd, b"\x03")
        time.sleep(0.5)
        kill(pid)

        # OPEN ISSUE (2026-09-16): the turn-created session was NOT visible in
        # the fixture daemon's own listing (only sessions created by this
        # fixture's HTTP POST were), while the single-session P3a script did see
        # a session row. Until that is understood this fixture cannot prove a
        # cross-session switch, so it fails loudly instead of passing vacuously.
        proven = bool(switched) and switched[0] in flat_listed
        print("PROVEN_CROSS_SESSION_SWITCH:", proven)
        if not proven:
            print(
                "NOT PROVEN: see OPEN issue - turn-created session absent from the\n"
                "fixture daemon listing; multi-session e2e remains UNVERIFIED."
            )
            raise SystemExit(1)
    finally:
        daemon.terminate()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
