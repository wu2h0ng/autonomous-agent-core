"""The committed OpenAPI snapshot IS the API contract (AR-20260611).

``apps/api_server/openapi.json`` is generated deterministically from the app and
committed; the drift-gate unit test fails whenever the live schema and the snapshot
disagree, so every API change ships with a reviewable contract diff in the same PR.

Regenerate after an intentional API change:

    python -m agent_os_api.openapi_contract

Verify without writing (exits 1 on drift):

    python -m agent_os_api.openapi_contract --check
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, TextIO

# apps/api_server/openapi.json (this file lives in apps/api_server/src/agent_os_api/).
SNAPSHOT_PATH = Path(__file__).resolve().parents[2] / "openapi.json"


def generate_openapi_spec() -> dict[str, Any]:
    """Build the app and return its OpenAPI schema.

    The schema depends only on route/model declarations, so dummy runtime/retriever
    sentinels are injected: no domain pack, store backend, or API key is needed and
    generation stays deterministic.
    """
    from .http_app import create_app

    app = create_app(object(), retriever=object(), api_key="schema-generation-only")
    return app.openapi()


def render(spec: dict[str, Any]) -> str:
    # sort_keys + fixed indent => byte-stable snapshot, reviewable diffs.
    return json.dumps(spec, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None, stdout: TextIO = sys.stdout) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if the committed snapshot drifts from the live schema (writes nothing)",
    )
    args = parser.parse_args(argv)

    rendered = render(generate_openapi_spec())
    if args.check:
        committed = SNAPSHOT_PATH.read_text(encoding="utf-8") if SNAPSHOT_PATH.exists() else ""
        if committed != rendered:
            print(
                f"OpenAPI contract drift: {SNAPSHOT_PATH} does not match the live schema. "
                "Run `python -m agent_os_api.openapi_contract` and commit the diff.",
                file=stdout,
            )
            return 1
        print("OpenAPI contract is up to date.", file=stdout)
        return 0

    SNAPSHOT_PATH.write_text(rendered, encoding="utf-8")
    print(f"Wrote {SNAPSHOT_PATH}", file=stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
