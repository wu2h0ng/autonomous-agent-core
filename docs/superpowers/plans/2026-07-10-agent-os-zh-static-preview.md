# Agent OS Chinese Static Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a polished Chinese static preview of the unified Agent OS workbench without changing the existing live workspace behavior.

**Architecture:** Add a self-contained `preview-zh.html` surface served at `/preview-zh`. The page uses local sample state and browser-only interactions to demonstrate the approved product model while the existing `/` page and `/v1` API remain untouched.

**Tech Stack:** Python stdlib HTTP server, semantic HTML, CSS, vanilla JavaScript, pytest, Browser/IAB visual verification.

## 2026-07-11 Scene-Driven Redesign Amendment (Executed)

This amendment supersedes the original Task 2/Task 3 plan-first tab surface while
preserving the route and static-fixture boundary. The implemented preview now contains:

- a stable Agent OS Shell with Personal, Developer and Organization workspace profiles;
- Ask-to-Work context continuity and replaceable soft ScenePreset selection;
- deterministic fixture `UISceneSpec` validation and a registered component renderer for
  metrics, relation hypotheses, evidence, Agent topology, environment, timeline and
  concrete-action approval;
- canonical pause, correct, approve and reject controls that emit browser-local typed
  interaction records rather than mutating a real workflow;
- eight browser-local locale catalogs with live switching and persistence;
- responsive acceptance at 1440x900, 1024x768 German expansion and 390x844.

The redesigned structure test was observed RED against the old page and GREEN after the
implementation. Final verification: `96 passed, 1 skipped`; Ruff clean; Pyright zero
errors; Browser/IAB console clean. It remains a static product prototype with no `/v1`
request path, production tenancy, preset compiler or runtime scene generation.

## Global Constraints

- Product identity is `Agent OS`; `Agent Core` is not the top-level product name.
- The primary model is `Space -> Task -> Context -> Plan/Workflow -> Run -> Artifact/Outcome -> Reusable Knowledge`.
- Present Personal, Developer and Organization as workspace profiles, not separate products,
  permanent personas or runtime forks.
- Keep Ask / Work as interaction contracts inside every workspace profile.
- Scene presets must remain soft, composable, versioned and replaceable by a generic Work state.
- Chinese is the default preview locale. Eight browser-local demonstration catalogs are
  included; production catalog parity and backend locale negotiation remain outside this slice.
- Preserve the existing `/` workbench and all `/v1` API behavior.
- Static preview data must be visibly presented as sample state and must not imply a production Space backend.
- Keep the UI operational and compact: no marketing hero, nested cards, gradients, decorative blobs, or domain-specific dashboard framing.
- The preview must remain usable at 1440x900 and 390x844 without clipped text, overlapping controls, or horizontal page overflow.

---

### Task 1: Preview HTTP Contract

**Files:**
- Modify: `tests/product/test_api_surface.py`
- Modify: `apps/api_server/server.py`
- Create: `apps/api_server/preview-zh.html`

**Interfaces:**
- Consumes: `Handler.do_GET()` and the existing Python stdlib server.
- Produces: `GET /preview-zh -> text/html; charset=utf-8` containing the Chinese Agent OS preview.

- [x] **Step 1: Write the failing route test**

Add this assertion block after the existing `/` page assertion in `test_http_api_and_workspace_use_application_path`:

```python
        with urllib.request.urlopen(base + "/preview-zh") as response:
            preview = response.read().decode()
            assert response.headers["Content-Type"] == "text/html; charset=utf-8"
        assert '<html lang="zh-CN">' in preview
        assert "Agent OS" in preview
        assert "空间" in preview
        assert "任务" in preview
        assert "上下文" in preview
        assert "计划" in preview
        assert "运行" in preview
        assert "成果" in preview
        assert "知识" in preview
        assert "个人空间" in preview
        assert "开发空间" in preview
        assert "组织空间" in preview
        assert "Ask" in preview
        assert "Work" in preview
        assert "场景预设" in preview
```

- [x] **Step 2: Run the route test and verify RED**

Run:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. uv run --extra product-test pytest tests/product/test_api_surface.py::test_http_api_and_workspace_use_application_path -q
```

Expected: FAIL with HTTP 404 for `/preview-zh`.

- [x] **Step 3: Add the static preview route**

Define the preview bytes next to `INDEX` and serve them before the API routes:

```python
PREVIEW_ZH = Path(__file__).with_name("preview-zh.html").read_bytes()

if parsed.path == "/preview-zh":
    self.send_response(HTTPStatus.OK)
    self.send_header("Content-Type", "text/html; charset=utf-8")
    self.send_header("Content-Length", str(len(PREVIEW_ZH)))
    self.end_headers()
    self.wfile.write(PREVIEW_ZH)
    return
```

Create an initial semantic HTML file containing the required product-stage labels and `<html lang="zh-CN">`.

- [x] **Step 4: Run the route test and verify GREEN**

Run the same targeted pytest command.

Expected: `1 passed`.

### Task 2: Unified Chinese Workbench Surface

**Files:**
- Modify: `apps/api_server/preview-zh.html`

**Interfaces:**
- Consumes: no backend data; all seed state is declared in browser-local JavaScript.
- Produces: responsive app shell with navigation rail, task list, context header, task composer, plan/run surface, artifacts, outcome, and knowledge continuation.

- [x] **Step 1: Add static-structure assertions and verify RED**

Extend the preview assertions with:

```python
        assert 'data-testid="task-search"' in preview
        assert 'data-testid="context-bar"' in preview
        assert 'data-testid="plan-step"' in preview
        assert 'data-testid="run-activity"' in preview
        assert 'data-testid="artifact-row"' in preview
        assert 'data-testid="knowledge-action"' in preview
        assert 'aria-label="主导航"' in preview
        assert 'aria-live="polite"' in preview
```

Run the targeted test and confirm it fails on the first missing selector.

- [x] **Step 2: Implement the desktop information architecture**

Build these regions in order:

```text
App shell
  left rail: Agent OS, workspace profile switcher, Ask/Work, create, search, recent tasks
  top context bar: current Space boundary, connected sources, provider, run status
  preset bar: current ScenePreset, version, recommendation and replace action
  task header: editable task title, status, more actions
  main workspace: task input, context sources, commitment summary
  plan band: five ordered plan steps with status and approval boundary
  run activity: current action, evidence trail, recovery action
  result area: artifacts, verified outcome, reusable knowledge action
```

Use a restrained neutral palette with green for verified state, amber for approval boundaries, and blue only for active selection/focus. Keep radii at `6px` or below and use borders/spacing rather than stacked cards.

- [x] **Step 3: Implement responsive behavior**

At `max-width: 900px`, collapse the left rail into a top mobile bar and keep the task content single-column. At `max-width: 560px`, stack action rows, allow context labels to wrap, keep all tap targets at least `40px`, and prevent horizontal page overflow.

- [x] **Step 4: Run the targeted test and verify GREEN**

Run the targeted pytest command and expect `1 passed`.

### Task 3: Local Preview Interactions

**Files:**
- Modify: `apps/api_server/preview-zh.html`

**Interfaces:**
- Consumes: click/input events and static `sampleTasks` state.
- Produces: task filtering, task selection, tab switching, plan approval state, run state progression, compact mobile navigation, and accessible live announcements.

- [x] **Step 1: Add interaction-hook assertions and verify RED**

Add:

```python
        assert 'data-action="create-task"' in preview
        assert 'data-action="approve-plan"' in preview
        assert 'data-action="start-run"' in preview
        assert 'data-action="save-knowledge"' in preview
        assert 'data-tab="plan"' in preview
        assert 'data-tab="activity"' in preview
        assert 'data-tab="outcome"' in preview
```

Run the targeted test and confirm RED.

- [x] **Step 2: Implement browser-local interactions**

Implement event delegation with these exact transitions:

```text
task search input -> filter recent task rows by title
task row click -> selected row and task title update
workspace profile -> update boundary, recommended preset, task examples and Ask context
Ask / Work -> switch interaction contract without losing the current Space
scene preset -> replace the Work seed without widening authority
plan/activity/outcome tab click -> one visible panel and active tab
approve plan -> approval boundary becomes approved and start button enables
start run -> run status becomes running, one pending step becomes active, live region announces start
save knowledge -> button becomes saved/disabled, live region announces persistence preview
create task -> composer clears and receives focus
mobile menu -> left rail opens/closes with aria-expanded synchronized
```

No control may issue a `/v1` request.

- [x] **Step 3: Run product checks**

Run:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. uv run --extra product-test pytest tests/product/test_api_surface.py -q
uv run --extra product-test ruff check apps/api_server/server.py tests/product/test_api_surface.py
```

Expected: all selected tests pass and Ruff reports `All checks passed!`.

### Task 4: Browser Acceptance

**Files:**
- Modify if required by findings: `apps/api_server/preview-zh.html`

**Interfaces:**
- Consumes: running local server at an available localhost port.
- Produces: screenshot-backed desktop/mobile acceptance evidence and a clean interaction path.

- [x] **Step 1: Start or restart the local server**

Run the API server on `127.0.0.1:8787`; if occupied by a stale process, stop that process or use the next available port.

- [x] **Step 2: Verify desktop in Browser/IAB**

Open `/preview-zh` at 1440x900. Confirm the Shell/scene hierarchy, Chinese copy, no
clipping/overlap or horizontal overflow, visible approval controls, and working locale,
workspace, Ask/Work, evidence, pause/correct and approve/reject interactions.

- [x] **Step 3: Verify mobile in Browser/IAB**

Resize to 390x844. Confirm the mobile navigation, wrapped context bar, readable task title, stacked controls, accessible tap targets, and no horizontal page overflow.

- [x] **Step 4: Inspect the latest screenshots**

Capture desktop and mobile screenshots and inspect both with `view_image`. Fix every material issue before repeating the screenshots.

- [x] **Step 5: Run final regression and Git status**

Run the targeted pytest and Ruff commands again, then `git status --short`. Report only files changed for this preview and distinguish them from pre-existing working-tree changes.
