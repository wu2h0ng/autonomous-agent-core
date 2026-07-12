# SPINE-0 Live Provider Acceptance

Date: 2026-07-10

## Result

PASS for the controlled SPINE-0 release gate.

The run used the repository's environment-only credential path with an OpenAI-compatible
Kimi endpoint and model. The API key was loaded from `.env` into the process environment;
it is not recorded in this file, task events, provider payloads, traces or artifacts.

Connectivity verification:

```text
set -a; source .env; set +a
export AGENT_OS_PROVIDER_BASE_URL="${OPENAI_API_URL%/chat/completions}"
export AGENT_OS_PROVIDER_MODEL="$OPENAI_MODEL"
PYTHONPATH=packages/contracts/src:packages/os_core/src:. uv run --extra product-test pytest -q tests/product/test_live_provider_smoke.py -rs
1 passed
```

The original engineering acceptance called the provider and separately exercised the
deterministic golden path. PM correctly rejected interpreting those two checks as one
provider-driven product journey. The remediation re-review then exercised the real Kimi
provider end to end through `AgentOSApplication`, `OpenAICompatibleProvider`,
`RunCoordinator`, exact-digest approval, `PolicyKernel`, `CapabilityBroker`, workspace
capabilities and the deterministic outcome evaluator. The browser supplied no final patch
content. Kimi generated the typed `workspace.apply_patch` proposal; the approved run read,
patched, ran pytest and recorded an evidence-backed VERIFIED outcome.

Recorded PM task:

```text
task-22bf3265-d215-430d-96a2-2395f1a4028c
provider: kimi-k2-0711-preview
provider tokens: 253
result: COMPLETED / SUCCEEDED / VERIFIED
```

The initial attempt returned HTTP 400 because the provider model accepts only
`temperature=1`. The adapter was corrected to use `AGENT_OS_PROVIDER_TEMPERATURE`, then
`OPENAI_TEMPERATURE`, defaulting to `1.0`; the rerun passed. This correction is retained
as a provider compatibility rule, not hidden as a test workaround.

## Boundary

This proves the SPINE-0 controlled provider path. It does not claim production KMS,
SSO, multi-tenant isolation, arbitrary external side effects, provider availability or
Codex/provider quality parity.
