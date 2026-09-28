# Agent OS Dual Workbench Slice 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fake Agent Window page with the exact VS Code Sessions Workbench baseline and show a real, read-only Agent OS Runtime task catalog through an `ISessionsProvider` adapter.

**Architecture:** Upgrade the generated Code-OSS checkout atomically from VS Code `1.106.3` to `1.136.2`, retain upstream `src/vs/sessions` as the native Agent Window, and keep Agent OS additions under `src/vs/agentos`. The renderer receives only typed task projections from a main-process Runtime bridge; the loopback bearer remains outside renderer state. This slice is read-only and does not add approval, automation, task mutation, multi-client writes, or a Rust Runtime.

**Tech Stack:** Code-OSS/Electron, TypeScript, Node test runner, Python Agent OS Runtime HTTP API, JSON Schema-compatible DTOs, tracked overlay plus reproducible upstream checkout.

**Spec:** `docs/architecture/A-AGENT-OS-DUAL-WORKBENCH-ARCHITECTURE-SPEC-V2-2026-09-09.md`

## Global Constraints

- Active upstream must become exactly VS Code tag `1.136.2`, commit `88e44fa0e00b08f7758b4f6d05632e4fd5e4df6f`; tag-only or `main` is forbidden.
- The baseline switch, replacement patch/overlay, bootstrap success, build success and anti-regression tests land atomically; never leave an active lock with an unappliable patch.
- Reuse upstream `ISessionsProvidersService`, `ISessionsManagementService`, `ISessionsService`, `ISessionsProvider`, Workbench, Parts and layout controller. Do not create a parallel sessions state machine.
- Product truth remains Task/Run/etc. in the existing Python Runtime. `ISession`/`IChat` are read-only Workbench facades in this slice.
- Renderer and webview receive no bearer token, profile credential, cookie or secret. Runtime access is owned by Electron main and returns a closed typed projection.
- Host identity terminology uses `surfaceInstanceId`, mandatory for every host: `window:<native-window-id>`, `cli:<process-start-id>`, or `test:<case-id>`. A client-supplied value is correlation only and cannot expand a server lease.
- Current interactive Runtime ends on application quit. Window/renderer reload does not stop it. Background OS-service lifecycle is out of scope.
- No approval, correction mutation, automation scheduler, multi-client mutation, schema-wide freeze, Rust migration, commit to `main`, push, merge or release.
- Keep the known anti-degradation oracle red until Task 3 replaces the fake DOM implementation; do not weaken or delete it to obtain green tests.

---

### Task 1: Activate the exact upstream baseline without carrying the rejected page patch

**Files:**
- Modify: `apps/code-oss/upstream.lock.json`
- Modify: `apps/code-oss/scripts/bootstrap.mjs`
- Modify: `apps/code-oss/scripts/verify.mjs`
- Move: `apps/code-oss/patches/010-native-agent-workbench.patch` → `apps/code-oss/retired-patches/010-native-agent-workbench-1.106.3.patch`
- Create: `apps/code-oss/tests/upstream-baseline.test.mjs`

**Interfaces:**
- Consumes: `upstream.lock.json` active `tag` and `commit`.
- Produces: reproducible `.code-oss/upstream` at `1.136.2@88e44fa0`; an empty active patch set ready for new minimal patches.

- [ ] **Step 1: Write the failing exact-baseline test**

```js
test('active Code-OSS baseline is the reviewed Sessions release', async () => {
  const lock = JSON.parse(await readFile(path.join(root, 'apps/code-oss/upstream.lock.json'), 'utf8'));
  assert.equal(lock.tag, '1.136.2');
  assert.equal(lock.commit, '88e44fa0e00b08f7758b4f6d05632e4fd5e4df6f');
  assert.equal(lock.sessionsBaseline.status, 'ACTIVE');
});
```

- [ ] **Step 2: Run the test and confirm it fails on the old active lock**

Run: `node --test apps/code-oss/tests/upstream-baseline.test.mjs`

Expected: FAIL because active `tag` is `1.106.3` and status is `CHARACTERIZED_NOT_ACTIVE`.

- [ ] **Step 3: Retire the rejected 1.106.3 patch and activate the reviewed baseline**

Set the active lock to:

```json
{
  "repository": "https://github.com/microsoft/vscode.git",
  "tag": "1.136.2",
  "commit": "88e44fa0e00b08f7758b4f6d05632e4fd5e4df6f",
  "sessionsBaseline": {
    "tag": "1.136.2",
    "commit": "88e44fa0e00b08f7758b4f6d05632e4fd5e4df6f",
    "status": "ACTIVE"
  },
  "license": "MIT",
  "productName": "Agent OS"
}
```

Move the old patch intact into `retired-patches/`; `apply-workbench-overlay.mjs` must continue to read only `patches/*.patch`.

- [ ] **Step 4: Make bootstrap replace a checkout whose exact HEAD differs**

Change bootstrap so a mismatched generated checkout fails with a typed instruction and exits before copying/applying anything. The implementation must not mutate a dirty generated checkout. The accepted message is:

```js
throw new Error(`Code-OSS checkout mismatch: expected ${lock.commit}; remove only ${upstreamRoot} and rerun bootstrap`);
```

- [ ] **Step 5: Bootstrap a fresh generated checkout and verify upstream Sessions assets**

Run in a new temporary clone root or after moving the existing generated checkout aside recoverably:

```bash
node apps/code-oss/scripts/bootstrap.mjs
git -C .code-oss/upstream rev-parse HEAD
test -f .code-oss/upstream/src/vs/sessions/electron-browser/sessions.ts
test -f .code-oss/upstream/src/vs/sessions/browser/workbench.ts
```

Expected HEAD: `88e44fa0e00b08f7758b4f6d05632e4fd5e4df6f`.

- [ ] **Step 6: Run the baseline test and patch applicability check**

Run: `node --test apps/code-oss/tests/upstream-baseline.test.mjs && node apps/code-oss/scripts/apply-workbench-overlay.mjs`

Expected: PASS; no retired patch is applied.

- [ ] **Step 7: Commit only Task 1 files on the feature branch**

```bash
git add apps/code-oss/upstream.lock.json apps/code-oss/scripts/bootstrap.mjs apps/code-oss/scripts/verify.mjs apps/code-oss/tests/upstream-baseline.test.mjs apps/code-oss/patches apps/code-oss/retired-patches
git commit -m "build(code-oss): activate reviewed sessions baseline"
```

---

### Task 2: Preserve the upstream Sessions Workbench as the Agent Window

**Files:**
- Create: `apps/code-oss/patches/010-agent-os-sessions-window.patch`
- Create: `apps/code-oss/tests/sessions-workbench-structure.test.mjs`
- Modify: `apps/code-oss/tests/native-agent-window.test.mjs`
- Modify: `apps/code-oss/scripts/verify.mjs`

**Interfaces:**
- Consumes: upstream `isSessionsWindow`, `src/vs/sessions/electron-browser/sessions.ts`, `sessions.desktop.main.ts`, Workbench/Parts/layout controller.
- Produces: Agent OS-branded native Sessions Window with no custom DOM page or EditorPane impersonation.

- [ ] **Step 1: Replace old source-name assertions with upstream structural assertions**

```js
test('Agent Window is the upstream Sessions Workbench', async () => {
  const bootstrap = await source('src/vs/sessions/electron-browser/sessions.ts');
  const workbench = await source('src/vs/sessions/browser/workbench.ts');
  const windowContract = await source('src/vs/platform/window/common/window.ts');
  assert.match(windowContract, /isSessionsWindow\?: boolean/);
  assert.match(bootstrap, /vs\/sessions\/sessions\.desktop\.main\.js/);
  assert.match(workbench, /extends Workbench/);
  assert.doesNotMatch(workbench, /agentOSWindowEditor|createWebviewPanel|extends EditorPane/);
});
```

- [ ] **Step 2: Run structural tests and confirm failure is caused by stale Agent OS assertions**

Run: `node --test apps/code-oss/tests/native-agent-window.test.mjs apps/code-oss/tests/sessions-workbench-structure.test.mjs`

Expected: FAIL where tests still require `agentOSWindowEditor.ts` or `workbench.agentOS.main`.

- [ ] **Step 3: Create the minimal branding/handoff patch**

The patch may modify only reviewed shared seams and Agent OS-owned additions. It must not copy `src/vs/sessions`. Required patch properties:

```text
src/vs/sessions/**                      upstream unchanged in Task 2
src/vs/platform/window/**               retain upstream isSessionsWindow
src/vs/agentos/**                       Agent OS additions only
src/vs/workbench/browser/parts/titlebar one destination action hook only
```

Add command IDs `agentOS.openSessionsWindow` and `agentOS.focusOrOpenIDEWindow`; route them through native window services and existing `isSessionsWindow`. Do not reintroduce `agentOSWindow?: boolean`.

- [ ] **Step 4: Add anti-regression assertions**

Assert that the generated checkout contains no `src/vs/workbench/agentOSWindow/browser/agentOSWindowEditor.ts`, no `AgentOSTaskListPart extends Disposable`, and no top-level `createWebviewPanel` Agent surface.

- [ ] **Step 5: Apply the patch and run focused structure verification**

Run: `node apps/code-oss/scripts/bootstrap.mjs && node --test apps/code-oss/tests/upstream-baseline.test.mjs apps/code-oss/tests/sessions-workbench-structure.test.mjs apps/code-oss/tests/native-agent-window.test.mjs`

Expected: all focused tests PASS, including the formerly red fake-Part oracle.

- [ ] **Step 6: Commit Task 2**

```bash
git add apps/code-oss/patches/010-agent-os-sessions-window.patch apps/code-oss/tests apps/code-oss/scripts/verify.mjs
git commit -m "feat(code-oss): adopt native sessions workbench"
```

---

### Task 3: Define the closed read-only Runtime task projection

**Files:**
- Create: `apps/code-oss/overlay-src/src/vs/agentos/common/runtimeTaskCatalog.ts`
- Create: `apps/code-oss/overlay-src/src/vs/agentos/common/runtimeTaskCatalog.test.ts`
- Modify: `apps/code-oss/scripts/apply-workbench-overlay.mjs`
- Create: `apps/code-oss/tests/runtime-task-contract.test.mjs`

**Interfaces:**
- Consumes: existing `GET /v1/tasks` response `{ tasks: [{ task_id, status, statement, run_status, sequence }] }`.
- Produces: `AgentOSTaskSummary`, `AgentOSTaskCatalogSnapshot`, strict decoder, and overlay-copy mechanism.

- [ ] **Step 1: Write decoder tests for valid, missing and extra-authority input**

```ts
const valid = decodeTaskCatalog({ tasks: [{
  task_id: 'task:1', status: 'RUNNING', statement: 'Build the workbench',
  run_status: 'RUNNING', sequence: 7
}] });
assert.strictEqual(valid.tasks[0].taskId, 'task:1');
assert.throws(() => decodeTaskCatalog({ tasks: [{ task_id: '', sequence: -1 }] }));
assert.throws(() => decodeTaskCatalog({ tasks: [], bearer_token: 'forbidden' }));
```

- [ ] **Step 2: Run the contract test and confirm the decoder is absent**

Run: `node --test apps/code-oss/tests/runtime-task-contract.test.mjs`

Expected: FAIL because `runtimeTaskCatalog.ts` is not yet copied/generated.

- [ ] **Step 3: Implement the exact DTO and decoder**

```ts
export interface AgentOSTaskSummary {
  readonly taskId: string;
  readonly status: string | null;
  readonly statement: string;
  readonly runStatus: string | null;
  readonly sequence: number;
}

export interface AgentOSTaskCatalogSnapshot {
  readonly tasks: readonly AgentOSTaskSummary[];
  readonly fetchedAt: number;
}
```

Decoder requirements: root keys exactly `tasks`; task keys exactly the five server fields; non-empty `task_id`; integer `sequence >= 0`; nullable status fields; no credential/authority fields accepted.

- [ ] **Step 4: Copy tracked Agent OS overlay sources deterministically**

Extend `apply-workbench-overlay.mjs` to recursively copy `overlay-src/src/vs/agentos` to `.code-oss/upstream/src/vs/agentos` before applying patches. Reject symlinks and paths escaping the target root.

- [ ] **Step 5: Run decoder and overlay tests**

Run: `node --test apps/code-oss/tests/runtime-task-contract.test.mjs && node apps/code-oss/scripts/apply-workbench-overlay.mjs`

Expected: PASS and generated `src/vs/agentos/common/runtimeTaskCatalog.ts` exists.

- [ ] **Step 6: Commit Task 3**

```bash
git add apps/code-oss/overlay-src apps/code-oss/scripts/apply-workbench-overlay.mjs apps/code-oss/tests/runtime-task-contract.test.mjs
git commit -m "feat(agentos): define read-only task catalog contract"
```

---

### Task 4: Add the main-process Runtime task bridge without leaking credentials

**Files:**
- Create: `apps/code-oss/overlay-src/src/vs/agentos/common/runtimeTaskCatalogService.ts`
- Create: `apps/code-oss/overlay-src/src/vs/agentos/electron-main/runtimeTaskCatalogMainService.ts`
- Create: `apps/code-oss/overlay-src/src/vs/agentos/electron-main/runtimeTaskCatalogChannel.ts`
- Create: `apps/code-oss/overlay-src/src/vs/agentos/electron-browser/runtimeTaskCatalogService.ts`
- Create: `apps/code-oss/tests/runtime-task-bridge.test.mjs`
- Modify: `apps/code-oss/patches/010-agent-os-sessions-window.patch`

**Interfaces:**
- Consumes: private descriptor fields `protocol_version`, `pid`, `boot_id`, `host`, `port`, `bearer_token`, `database_path`, `workspace_path`, `created_at` in Electron main only and `GET /v1/tasks`.
- Produces: `IRuntimeTaskCatalogService.listTasks(): Promise<AgentOSTaskCatalogSnapshot>` across a read-only IPC channel.

- [ ] **Step 1: Write bypass-detecting bridge tests**

Test a local fake loopback server and assert:

```js
assert.deepEqual(await service.listTasks(), expectedSnapshot);
assert.equal(rendererPayload.includes('bearer'), false);
await assert.rejects(() => service.request('POST', '/v1/tasks'), /read-only/);
await assert.rejects(() => service.fetchFrom('http://example.com'), /loopback/);
```

- [ ] **Step 2: Run the bridge test and confirm RED**

Run: `node --test apps/code-oss/tests/runtime-task-bridge.test.mjs`

Expected: FAIL because the service/channel do not exist.

- [ ] **Step 3: Implement the renderer-facing service contract**

```ts
export const IRuntimeTaskCatalogService = createDecorator<IRuntimeTaskCatalogService>('runtimeTaskCatalogService');
export interface IRuntimeTaskCatalogService {
  readonly _serviceBrand: undefined;
  listTasks(): Promise<AgentOSTaskCatalogSnapshot>;
}
```

The IPC channel exposes exactly one command, `listTasks`; any other command throws `Unknown runtime task catalog command`.

- [ ] **Step 4: Implement main-process descriptor and HTTP validation**

Required checks before request: descriptor is a regular non-symlink file; on POSIX its owner equals the current uid and mode has no group/other bits; host equals `127.0.0.1`; PID is alive. After the response, reload the descriptor and reject the result if `pid`, `boot_id`, `port` or `bearer_token` changed during the request. Send `Authorization: Bearer <token>` only from Electron main. Apply a 5-second timeout and 1 MiB response cap. Decode with `decodeTaskCatalog` before IPC return.

- [ ] **Step 5: Register the main channel and renderer proxy only for Sessions Window**

Patch the exact `1.136.2` composition seams so `isSessionsWindow` receives the proxy. IDE workbench registration is allowed only if lazy and inert; renderer code must never receive descriptor bytes or bearer.

- [ ] **Step 6: Run bridge tests**

Run: `node --test apps/code-oss/tests/runtime-task-bridge.test.mjs apps/code-oss/tests/runtime-task-contract.test.mjs`

Expected: PASS for valid list, fail-closed descriptor cases, non-loopback URI, oversized body, unknown IPC command and bearer non-disclosure.

- [ ] **Step 7: Commit Task 4**

```bash
git add apps/code-oss/overlay-src/src/vs/agentos apps/code-oss/patches/010-agent-os-sessions-window.patch apps/code-oss/tests/runtime-task-bridge.test.mjs
git commit -m "feat(agentos): bridge read-only runtime task catalog"
```

---

### Task 5: Implement and register the Agent OS Sessions provider

**Files:**
- Create: `apps/code-oss/overlay-src/src/vs/agentos/browser/agentOSSessionsProvider.ts`
- Create: `apps/code-oss/overlay-src/src/vs/agentos/browser/agentOSSessionsProvider.contribution.ts`
- Create: `apps/code-oss/overlay-src/src/vs/agentos/browser/agentOSSessionsProvider.test.ts`
- Modify: `apps/code-oss/patches/010-agent-os-sessions-window.patch`
- Create: `apps/code-oss/tests/agent-os-sessions-provider.test.mjs`

**Interfaces:**
- Consumes: `IRuntimeTaskCatalogService`, upstream `ISessionsProvider`, `ISession`, `IChat`, `ISessionsProvidersService`.
- Produces: provider id `agent-os-runtime`, task resource `agentos-task:/<encoded-task-id>`, one read-only main chat per task, provider change events after refresh.

- [ ] **Step 1: Write provider projection tests**

```ts
assert.strictEqual(provider.id, 'agent-os-runtime');
assert.strictEqual(provider.getSessions()[0].resource.scheme, 'agentos-task');
assert.strictEqual(provider.getSessions()[0].label.get(), 'Build the workbench');
assert.strictEqual(provider.getSessions()[0].mainChat.origin, 'readOnly');
assert.deepStrictEqual(provider.browseActions, []);
```

Also assert malformed/duplicate task IDs fail closed, refresh removal emits `removed`, and statement/status updates preserve the stable session facade/resource.

- [ ] **Step 2: Run provider tests and confirm RED**

Run: `node --test apps/code-oss/tests/agent-os-sessions-provider.test.mjs`

Expected: FAIL because provider source/registration is absent.

- [ ] **Step 3: Implement the read-only facade**

Implement the full exact `1.136.2` `ISessionsProvider` contract with:

```ts
readonly id = 'agent-os-runtime';
readonly supportsQuickChats = false;
readonly browseActions = [];
readonly automations = undefined;
getSessions(): ISession[];
resolveWorkspace(): undefined;
```

All mutation methods required by the upstream interface must reject with typed `Agent OS Slice 1 is read-only`; capability flags must hide composer/send/delete/archive/fork controls. Do not silently no-op.

- [ ] **Step 4: Register through the upstream provider registry**

Instantiate the provider in a Workbench contribution and call:

```ts
this._register(sessionsProvidersService.registerProvider(provider));
```

Import the contribution from the Sessions desktop entry via the Agent OS patch. Do not import provider code from shared `src/vs/sessions/browser` or `services` modules.

- [ ] **Step 5: Run provider and layer-boundary tests**

Run: `node --test apps/code-oss/tests/agent-os-sessions-provider.test.mjs apps/code-oss/tests/sessions-workbench-structure.test.mjs`

Expected: PASS; no `src/vs/sessions` shared module imports `src/vs/agentos` except the reviewed desktop registration seam.

- [ ] **Step 6: Commit Task 5**

```bash
git add apps/code-oss/overlay-src/src/vs/agentos/browser apps/code-oss/patches/010-agent-os-sessions-window.patch apps/code-oss/tests/agent-os-sessions-provider.test.mjs
git commit -m "feat(agentos): project runtime tasks into sessions"
```

---

### Task 6: Prove the real vertical slice and preserve the red boundaries

**Files:**
- Modify: `apps/code-oss/scripts/verify.mjs`
- Create: `apps/code-oss/tests/dual-workbench-slice-1.test.mjs`
- Create: `.agent_runs/dual-workbench-slice-1-20260909/verification.md`
- Modify after verification: `docs/architecture/A-AGENT-OS-DUAL-WORKBENCH-ARCHITECTURE-SPEC-V2-2026-09-09.md` status ledger only

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces: exact evidence that one Code-OSS application opens IDE and Sessions renderers and the Sessions sidebar shows Runtime-backed tasks without mutation authority.

- [ ] **Step 1: Write the end-to-end failure oracle**

The test must start a temporary Agent OS Runtime with two persisted tasks, launch the Sessions renderer, and assert:

```text
two native windows use different renderer entrypoints
Sessions window has upstream Workbench/Parts/layout
task labels and statuses equal GET /v1/tasks
no bearer appears in renderer globals, logs or IPC payload capture
send/create/archive/delete/approval/automation controls are absent
closing/reloading Sessions renderer does not terminate Runtime
application quit terminates the interactive Runtime within the configured deadline
```

- [ ] **Step 2: Run the end-to-end test before final wiring**

Run: `node --test apps/code-oss/tests/dual-workbench-slice-1.test.mjs`

Expected: FAIL until all composition imports and lifecycle hooks are connected.

- [ ] **Step 3: Complete only the missing composition wiring**

Limit changes to `010-agent-os-sessions-window.patch`, tracked `overlay-src/src/vs/agentos`, and verification scripts. Do not add mutations to make the demo interactive.

- [ ] **Step 4: Run focused verification**

```bash
node apps/code-oss/scripts/bootstrap.mjs
node apps/code-oss/scripts/verify.mjs
node --test apps/code-oss/tests/*.test.mjs
```

Expected: all Code-OSS overlay tests PASS; the previous `Agent Window owns native Workbench parts` oracle is green because upstream real Parts replaced the fake `Disposable` DOM page.

- [ ] **Step 5: Run Code-OSS compile/build verification**

```bash
cd .code-oss/upstream
npm install
npm run compile
```

Expected: exit 0. Record exact Node/npm versions and command output summary in `verification.md`.

- [ ] **Step 6: Perform manual native-window verification**

Launch the generated application against a temporary Runtime. Verify IDE → Agent destination action, Agent → IDE return action, Sessions task rendering, renderer reload, Runtime-unavailable typed error, empty task list and malformed response. Capture screenshots and log paths in `verification.md`; do not include bearer tokens or customer data.

- [ ] **Step 7: Run repository gates and inspect scope**

```bash
git status --short
git diff --check
git diff --stat
```

Expected: no whitespace errors; only Task 1–6 files plus the pre-existing dirty files already recorded before this plan.

- [ ] **Step 8: Update status without inflating the claim**

Record only `SLICE_1_IMPLEMENTED_AND_LOCALLY_VERIFIED` if every automated and manual gate passed. Preserve: no approval, automation, multi-client mutation, background service, Rust migration, release or autonomy claim.

- [ ] **Step 9: Request independent exact-head review before integration**

Reviewer must inspect the exact commit, rerun focused tests and compile, verify bearer non-disclosure and confirm the provider is read-only. Required verdict: `APPROVE_SLICE_1` with P0=0/P1=0 before any integration decision.

- [ ] **Step 10: Commit verification/status artifacts on the feature branch**

```bash
git add apps/code-oss docs/architecture/A-AGENT-OS-DUAL-WORKBENCH-ARCHITECTURE-SPEC-V2-2026-09-09.md .agent_runs/dual-workbench-slice-1-20260909/verification.md
git commit -m "test(agentos): verify dual workbench slice one"
```

Do not push, merge or release without a separate Founder/CTO authorization.
