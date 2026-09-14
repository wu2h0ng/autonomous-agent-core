"""Provider-level live smoke (opt-in, real vendor).

Runs ONE streaming completion against the provider resolved from the
environment (``AGENT_OS_PROVIDER_*`` / profile / persisted config + keychain),
exercising the selected native adapter end-to-end (deltas + exact usage). It
skips cleanly when no key is configured, never prints or persists the
credential, and writes redacted evidence.

Examples (one key per vendor):
  AGENT_OS_PROVIDER_PROFILE=deepseek DEEPSEEK_API_KEY=... uv run python scripts/live_provider_smoke.py
  AGENT_OS_PROVIDER_PROFILE=anthropic ANTHROPIC_API_KEY=... uv run python scripts/live_provider_smoke.py --out /tmp/anthropic-live.json
  AGENT_OS_PROVIDER_PROFILE=gemini GEMINI_API_KEY=... uv run python scripts/live_provider_smoke.py
  AGENT_OS_PROVIDER_BASE_URL=https://api.deepseek.com/v1 AGENT_OS_PROVIDER_MODEL=deepseek-chat \
    OPENAI_API_KEY=... uv run python scripts/live_provider_smoke.py

Usage: uv run python scripts/live_provider_smoke.py [--out PATH] [--prompt TEXT]
"""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

_PROMPT = "Reply with the single word: OK"


def run_live_smoke(
    *,
    out: Path | None = None,
    prompt: str = _PROMPT,
) -> dict[str, object]:
    """Return redacted smoke evidence; never raises on a provider failure."""

    from agent_os_contracts import (
        ProviderMessage,
        ProviderMessageRole,
        ProviderRequest,
    )
    from agent_os_core.provider import ProviderResponse

    from apps.api_server.app import AgentOSApplication

    workspace = Path(tempfile.mkdtemp(prefix="agent-os-live-smoke-"))
    app = AgentOSApplication(database=":memory:", workspace=workspace)
    if not app.provider_configured:
        evidence: dict[str, object] = {
            "status": "SKIP",
            "reason": "no provider key/config resolved (set a *_API_KEY and profile)",
        }
        if out is not None:
            out.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        return evidence

    request = ProviderRequest(
        request_id=f"smoke:{uuid4()}",
        task_id="task:live-smoke",
        run_id="run:live-smoke",
        provider_profile_id=app.provider_profile.profile_id,
        messages=(
            ProviderMessage(role=ProviderMessageRole.USER, content=prompt),
        ),
        timeout_seconds=60,
        created_at=datetime.now(timezone.utc),
    )
    deltas: list[str] = []
    started = time.monotonic()
    result = app.provider.complete_streaming(request, on_text_delta=deltas.append)
    duration = round(time.monotonic() - started, 3)

    base: dict[str, object] = {
        "provider_id": app.provider_profile.provider_id,
        "endpoint_class": app.provider_profile.endpoint_class,
        "model_id": app.provider_profile.model_id,
        "duration_s": duration,
    }
    if isinstance(result, ProviderResponse):
        evidence = {
            **base,
            "status": "PASS",
            "delta_count": len(deltas),
            "text_len": len(result.text),
            "text_preview": result.text[:80],
            "finish_reason": result.finish_reason,
            "usage": {
                "input_tokens": result.usage.input_tokens,
                "output_tokens": result.usage.output_tokens,
                "total_tokens": result.usage.total_tokens,
                "cost_status": result.usage.cost_status,
                "estimated_cost_usd": (
                    str(result.usage.estimated_cost_usd)
                    if result.usage.estimated_cost_usd is not None
                    else None
                ),
                "pricing_source_ref": result.usage.pricing_source_ref,
            },
        }
    else:
        evidence = {
            **base,
            "status": "FAIL",
            "code": result.code.value,
            "retryable": result.retryable,
            "safe_message": result.safe_message,
        }
    if out is not None:
        out.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser(prog="live_provider_smoke")
    parser.add_argument("--out", default=None, help="evidence JSON path")
    parser.add_argument("--prompt", default=_PROMPT)
    args = parser.parse_args()
    out = Path(args.out) if args.out else None
    evidence = run_live_smoke(out=out, prompt=args.prompt)
    print(json.dumps(evidence, indent=2))
    raise SystemExit(0 if evidence["status"] in {"PASS", "SKIP"} else 1)


if __name__ == "__main__":
    main()
