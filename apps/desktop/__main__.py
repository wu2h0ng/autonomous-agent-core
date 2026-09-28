from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _wait_for_health(url: str, timeout: float = 12.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.5) as response:
                if response.status == 200:
                    return
        except Exception as exc:  # pragma: no cover - platform/network timing
            last_error = exc
        time.sleep(0.1)
    raise RuntimeError(f"Agent OS runtime did not become ready: {last_error}")


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="agent-desktop",
        description="Start the supervised local Agent OS desktop Surface.",
    )
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--database", default="agent-os.sqlite3")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument(
        "--surface",
        choices=("workspace", "preview"),
        default="workspace",
        help="workspace is live; preview is the deterministic UX fixture",
    )
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()

    command = [
        sys.executable,
        "-m",
        "apps.api_server",
        "--workspace",
        str(Path(args.workspace).expanduser()),
        "--database",
        args.database,
        "--host",
        args.host,
        "--port",
        str(args.port),
    ]
    child_env = dict(os.environ)
    source_paths = [
        str(REPO_ROOT),
        str(REPO_ROOT / "packages" / "contracts" / "src"),
        str(REPO_ROOT / "packages" / "os_core" / "src"),
    ]
    existing_pythonpath = child_env.get("PYTHONPATH")
    if existing_pythonpath:
        source_paths.append(existing_pythonpath)
    child_env["PYTHONPATH"] = ":".join(source_paths)
    process = subprocess.Popen(command, start_new_session=True, env=child_env)
    base = f"http://{args.host}:{args.port}"
    try:
        _wait_for_health(f"{base}/v1/health")
        surface = "/preview-zh" if args.surface == "preview" else "/"
        url = base + surface
        print(f"Agent OS desktop Surface ready: {url}")
        print("Runtime is supervised by this process; press Ctrl-C to stop it.")
        if not args.no_open:
            webbrowser.open(url)
        while process.poll() is None:
            time.sleep(0.25)
        return int(process.returncode or 0)
    except KeyboardInterrupt:
        return 130
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
