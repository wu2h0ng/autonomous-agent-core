# PR-07 Frontend Workspace F3 Re-Rehearsal Verification

Date: 2026-06-24
Branch: `codex/workspace-f3-rerehearsal-current`
Base: local `main` `77c7b07`
Scope: conflict rehearsal plus CI/browser verification only

## Verdict

PASS for local merge-readiness rehearsal.

This branch replaces the stale F3 integration rehearsal evidence at `d46bd45`.
It replays the product integration stack from current local `main` `77c7b07`,
then verifies the combined successor branch before any founder/CTO merge
decision. It is not merged to `main`, not pushed, not released, and not deployed.

## Replay Sequence

1. `7282b2f` merged `codex/enterprise-integration-reconcile`
2. `0151d57` merged `codex/workspace-f1-contract-surface`
3. `81f6567` merged `codex/workspace-f2-api-report-surface`
4. `465ee3f` merged `codex/workspace-f3-live-run-surface`

The replayed stack contains:

- ADR-0002 report-read/postgres snapshot durability and connector-semantics cleanup.
- Frontend Workspace F1 static DataProduct/KnowledgeAsset candidate surface.
- Frontend Workspace F2 read-only `GET /runs/{trace_id}/report` projection.
- Frontend Workspace F3a limited `POST /runs` live-run submit surface.
- Current local-main ADR-0003 runtime hardening, including context risk ceiling
  and checkpoint replay-boundary hardening.

## Conflict Resolution

Conflicts were limited to `README.md` and `docs/CURRENT_STATE.yaml`.

Resolution rule:

- Preserve the current re-rehearsal branch identity and base `77c7b07`.
- Absorb F1/F2/F3a product-surface facts as replayed components.
- Do not carry stale branch-local verification counts forward as current-branch
  evidence.
- Keep all non-claims explicit: no merge, push, release, deployment, production
  UI, approval-execution UI, full live golden-loop UI, external release, full
  RBAC/DLP/tenant isolation, external-system exactly-once, or automatic R4/R5.

Mechanical checks after conflict resolution:

- Conflict markers: none in `README.md` / `docs/CURRENT_STATE.yaml`
- YAML parse: OK
- `git diff --check`: OK

## CI

Command:

```bash
make ci PYTHON=/Users/mima1234/Documents/AI-Agent-Projects/ai-native-business-data-agent-os/.venv/bin/python
```

Result:

- ruff check: OK
- ruff format check: OK
- primary unittest discovery: 458 tests OK, 4 skipped
- eval subset: 12 tests OK, including 10 governed-action D6 eval tests
- OpenAPI contract drift check: OK / up to date

## Browser QA

Tool path:

- Browser plugin available and used.
- Static server: `python -m http.server 8124 --bind 127.0.0.1`
- URL: `http://127.0.0.1:8124/apps/workspace/prototype/index.html`

Desktop viewport `1440x900`:

- Page title: `Data Agent OS · Intent Workspace Prototype`
- DOM nonblank with F3a boundary and `POST /runs` markers.
- Console warn/error logs: none.
- `运行可信闭环` resolved to exactly one button.
- Clicking it without an API server entered bounded network state:
  `Run request failed.`
- Screenshot evidence:
  `/tmp/workspace-f3-rerehearsal-current-desktop.png`
  `/tmp/workspace-f3-rerehearsal-current-desktop-after-click.png`

Mobile viewport `390x900`:

- F3a boundary visible.
- `POST /runs` marker visible.
- `运行可信闭环` visible.
- Console warn/error logs: none.
- `scrollWidth == clientWidth == 390`, no horizontal overflow.
- Screenshot evidence:
  `/tmp/workspace-f3-rerehearsal-current-mobile.png`

## Non-Claims

This verification does not claim:

- merge to `main`
- push to `origin`
- external release or deployment
- production UI
- React/Next.js scaffold
- full live golden-loop frontend workspace
- approval-execution UI
- automatic R4/R5 execution
- full RBAC, DLP, tenant isolation, field/row-level authorization
- external-system exactly-once or external ACK confirmation
- durable arbitrary external connector recovery
- autonomous-core research result or general autonomy evidence

## Next Gate

Founder/CTO may now decide whether to merge this combined successor branch.
Release remains a separate gate even if the merge is approved.
