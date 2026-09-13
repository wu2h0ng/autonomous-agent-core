# Independent Review Brief — SSE Oracle

- Reviewer identity must differ from builder (`opencode-go/kimi-k3` requested).
- Exact target head: `51ac8d2f` on `codex/selfdev-live-sse-oracle-20260809`.
- Behavioral implementation: `7cc3f6ff`; docs/verification record: `51ac8d2f`.
- Review scope: `packages/os_core/src/agent_os_core/provider.py`,
  `tests/product/test_agent_cli_stream.py`, and the verification evidence.

Review the exact head for:

1. Whether malformed OpenAI-compatible SSE JSON is fail-closed as a typed
   `ProviderFailure(MALFORMED)` without changing valid streaming/tool-call behavior.
2. Whether the exception classification, request binding, retryability, and
   partial-delta behavior are safe and consistent with the provider contract.
3. Whether tests are sufficient and the claim boundary is respected.
4. Any P0/P1/P2 findings, with file/line references.

Run the targeted tests if useful. Write `review.md` in this same directory.
Do not modify source files or commit.
