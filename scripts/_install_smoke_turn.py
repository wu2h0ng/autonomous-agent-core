#!/usr/bin/env python3
"""Hermetic one-turn driver for the Python install smoke.

Run with the INSTALLED tool venv python (so `apps.*` and `agent_os_*` come from
the installed distribution, not the source tree):

    <UV_TOOL_DIR>/autonomous-agent-core/bin/python \
        scripts/_install_smoke_turn.py --descriptor <path>

It opens a session against the daemon named by the descriptor, runs ONE turn,
and asserts the reply is the built-in DeterministicProvider text. No provider
key, no network: the daemon under test was started WITHOUT AGENT_OS_PROVIDER_*,
so AgentOSApplication falls back to DeterministicProvider(text=...).

Exit 0 = the installed daemon answered a hermetic turn with the expected text.
Exit 1 = anything else (connection, protocol, wrong text, error turn).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# The hermetic daemon launcher (_install_smoke_daemon.py) feeds this literal
# text through a scripted DeterministicProvider.
EXPECTED_SUBSTRING = "install smoke deterministic reply from the installed daemon"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--descriptor", required=True)
    parser.add_argument(
        "--prompt",
        default="install smoke: say something",
        help="turn text sent to the hermetic daemon (irrelevant to the stub reply).",
    )
    args = parser.parse_args()

    # These imports resolve from the INSTALLED distribution when this script is
    # run with the tool venv python.
    from apps.cli.surface_client import SurfaceClient
    from apps.runtime_daemon.descriptor import load_runtime_descriptor

    descriptor_path = Path(args.descriptor)
    descriptor = load_runtime_descriptor(descriptor_path)
    client = SurfaceClient(descriptor)

    snapshot = client.open_session("install smoke session")
    session_id = snapshot.session.session_id
    print(f"[smoke-turn] opened session {session_id}", flush=True)

    resp = client.run_turn(session_id, args.prompt)
    print(f"[smoke-turn] turn_id={resp.turn_id} stop_reason={resp.stop_reason!r}", flush=True)
    print(f"[smoke-turn] text={resp.text!r}", flush=True)

    if EXPECTED_SUBSTRING not in resp.text:
        print(
            f"[smoke-turn] FAIL: reply did not contain {EXPECTED_SUBSTRING!r}",
            file=sys.stderr,
        )
        return 1
    print(f"[smoke-turn] PASS: hermetic reply contains {EXPECTED_SUBSTRING!r}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
