# PM Product Acceptance: SPINE-0

> Date: 2026-07-10
> Scope: independent-developer repository golden path
> Reviewer role: Product Management
> First review: `REJECT / REMEDIATION REQUIRED`
> Re-review verdict: **ACCEPT**

## Decision

SPINE-0 passes PM Product Acceptance for the bounded local independent-developer slice.
The accepted job is: attach a repository, connect an OpenAI-compatible provider, create
and commit a repository task, receive a provider-generated typed patch proposal, review
the before/after content, approve the bound action, execute the patch, run an allowlisted
test command, inspect evidence and recover from a pre-effect failure.

This verdict does not claim Codex parity, market parity, production multi-tenancy,
production secret management, arbitrary shell access, visual workflow editing, Data Agent
migration, CWM promotion, subagent swarms or Agent OS blueprint completion.

## Re-review evidence

The product was restarted from the current source and exercised at
`http://127.0.0.1:8787` against a clean controlled workspace at
`/tmp/agent-os-pm-acceptance`.

Browser journey:

1. The Task Workspace displayed the effective repository root and configured provider
   model (`kimi-k2-0711-preview`) without displaying the API key.
2. The user supplied only the goal, `fixture.txt` target and `python -m pytest` verifier.
   No final patch content was supplied by the user, browser or test inputs.
3. The runtime read `before\n`, sent the bounded repository context to the real provider
   and received one `workspace.apply_patch` tool proposal containing `after\n`.
4. The proposal was server-bound to the reviewed target and current SHA-256, compiled
   into an `ActionContract`, persisted and shown as a before/after review.
5. Before approval the file remained unchanged and the run was `WAITING_APPROVAL`.
6. `Approve and run` recorded an approval bound to the exact action digest. The broker
   then applied the patch, ran pytest and recorded a content-addressed test artifact.
7. The final state was task `COMPLETED`, run `SUCCEEDED`, outcome `VERIFIED`; all seven
   workflow stages were complete and terminal controls were disabled.
8. Desktop and 390x844 mobile views rendered without overlap or console warnings/errors.

Recorded successful browser task:

```text
task_id: task-22bf3265-d215-430d-96a2-2395f1a4028c
provider_tokens: 253
workflow: read -> provider -> approve -> apply -> tests -> evaluate -> done
result: COMPLETED / SUCCEEDED / VERIFIED
```

Failure and recovery evidence:

- Browser: a task targeting `missing.txt` failed at `workspace.read`, displayed the typed
  error and `Retry`; changing the target to `fixture.txt` resumed the same task/run to a
  fresh provider proposal and `WAITING_APPROVAL`, with the old error cleared.
- Machine: malformed provider output produced no `workspace.apply_patch` receipt and no
  file effect; replacing the provider and retrying the same failed run reached
  `WAITING_APPROVAL`.
- Machine: an injected worker interruption after `workspace.read`, process restart and
  explicit stale-lease recovery resumed without rerunning completed effects.

Verification:

```text
uv run --extra product-test ruff check apps packages/os_core/src packages/contracts/src tests/product
All checks passed

uv run --extra product-test pyright apps packages/os_core/src packages/contracts/src tests/product
0 errors, 0 warnings, 0 informations

PYTHONPATH=packages/contracts/src:packages/os_core/src:. uv run --extra product-test pytest tests/product -q
96 passed, 1 skipped

PYTHONPATH=packages/contracts/src:packages/os_core/src:. uv run --extra product-test pytest -q
1321 passed, 14 skipped, 9 warnings, 5 subtests passed
```

## P0 disposition

### PM-P0-1: provider output did not drive the proposed patch

**CLOSED.** `RunCoordinator` now requests only `workspace.apply_patch`, validates exactly
one matching provider proposal, rejects malformed/path-mismatched output, server-binds the
read SHA-256 and persists the resulting `ActionContract`. The apply node refuses any patch
without that provider-bound contract and exact approval digest.

### PM-P0-2: no repository/workspace onboarding

**CLOSED.** `GET/POST /v1/workspace` and the Task Workspace attach flow expose and validate
an absolute, allowlisted, non-symlink local repository root. The browser empty state can
attach a repository and create a runnable task without hidden fixture assumptions.

### PM-P0-3: provider/API-key setup was not a product flow

**CLOSED for the local SPINE-0 scope.** `GET/POST /v1/provider` and the Integration Center
form validate HTTPS or local HTTP endpoints, model and temperature, create a non-secret
`CredentialRef`, perform a live connection test, return typed safe failures and never
return the key. The password field is cleared after success or failure.

### PM-P0-4: default UI could not complete and explain the golden path

**CLOSED.** The Codex-style Task Workspace now has recent task navigation, setup status,
goal/target/verifier commitment, stage progression, patch review, approval, failure retry,
terminal outcome, usage, events, workflow and clickable evidence views. The user no longer
types final patch content.

## Residual product debt

- Provider credentials are process-local development references, not persistent encrypted
  storage, KMS-backed rotation or organization policy.
- Provider cost remains adapter-reported estimate (`0` for the current compatible adapter);
  real billing and budget forecasting remain unimplemented.
- The accepted patch path is one complete-file replacement, not a multi-file unified diff,
  arbitrary shell, browser automation or general coding-agent parity.
- Natural-language workflow generation and visual drag/drop editing remain later Blueprint
  requirements.
- Production auth, tenancy, SSO, deployment, marketplace, enterprise connectors and Data
  Agent migration remain outside SPINE-0.

## Authorized product statement

```text
SPINE-0 is PM-accepted for the bounded local independent-developer repository golden path.
Agent OS Blueprint completion, Codex parity and product superiority remain NOT ESTABLISHED.
```
