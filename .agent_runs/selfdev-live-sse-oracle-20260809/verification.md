# SELFDEV Live SSE Oracle Verification

- Run: `selfdev-live-sse-oracle-20260809`
- Branch: `codex/selfdev-live-sse-oracle-20260809`
- Parent: `2f44e7042cfd274f1e2a9afc3d71bf0012950e8c`
- Implementation: `7cc3f6ff` (`fix(provider): fail closed on malformed SSE deltas`)
- Scope: OpenAI-compatible streaming provider only; no merge, push, release, or promotion

## Change

`OpenAICompatibleProvider._parse_sse_stream` now returns a typed
`ProviderFailure(code=MALFORMED)` when an SSE `data:` payload contains invalid
JSON, instead of silently discarding the payload and returning partial text as
a successful `ProviderResponse`. The streaming test also narrows the normal
response before accessing response-only fields.

## Verification

| Check | Result |
|---|---|
| `pytest tests/product/test_agent_cli_stream.py tests/product/test_provider_http_adapter.py tests/product/test_provider_relevance_assessor.py -q` | `65 passed` |
| `uv run --extra product-test pyright packages/os_core/src/agent_os_core/provider.py tests/product/test_agent_cli_stream.py` | `0 errors, 0 warnings, 0 informations` |
| `ruff check` on changed files | passed |
| `git diff --check` | passed |
| Full `pytest tests/product -q` | `19 failed, 1814 passed, 1 skipped`; failure set identical to existing `/tmp/main_failures.txt` baseline, zero new failures |
| `ruff format --check` on changed files | both files were already unformatted at branch baseline; zero new format debt |

## Boundary

This is a narrow Product Track provider failure-path fix. It does not establish
live-provider evidence, HCW evidence, self-improvement, autonomy, release
readiness, or general intelligence. b32f2cb and this lane remain unmerged into
local main pending independent exact-head review and the user's requested joint
integration decision.
