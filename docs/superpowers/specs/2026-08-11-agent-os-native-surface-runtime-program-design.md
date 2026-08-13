# Agent OS Native Surface and Unified Runtime Program Design

> Status: `FOUNDER_APPROVED_IN_CONVERSATION / PROGRAM_SPEC / NOT_IMPLEMENTED / NOT_RELEASED`
> Date: 2026-08-11
> Track: `Product Track`
> Primary requirement class: `P`
> Secondary requirement class: `A`
> Target repository: `autonomous-agent-core`
> Target platform: `macOS arm64` for the first packaged application
> Current design base observed during scoping: `feature/terminal-coding-agent-m1@a558c7e23bba95dc08a39445caf98e2a90a6b9e1`, with a pre-existing dirty working tree

## 1. Decision

Build one Agent OS product with one provider-neutral Agent Core Runtime and multiple Surfaces. The first packaged product is a macOS application that evolves the existing Web Surface into a Tauri-hosted React/TypeScript Workspace Canvas. The existing CLI connects to the same local Runtime daemon and resumes the same Tasks, Sessions, approvals, evidence, and recovery state.

The same product serves two initial organs:

1. `Software Engineering`: repository work from inspection through governed modification, verification, evidence, and recovery.
2. `Personal Work`: Gmail, Google Calendar, Chrome, an isolated embedded browser, local files, and governed terminal work.

The complete architecture also includes encrypted cloud task synchronization and optional headless Workers on macOS and Linux. Distributed multi-Agent orchestration and enterprise control-plane capabilities are architectural successors, not first-release completion claims.

The selected technical path is:

- Tauri for the macOS application shell and narrow native capabilities;
- React and TypeScript for the Workspace Canvas;
- the existing Python Agent Core as a supervised headless daemon;
- a versioned HTTP command/query protocol plus WebSocket event stream for every Surface;
- Python and PostgreSQL for the narrow cloud control plane;
- the same headless Runtime protocol for macOS and Linux Workers.

## 2. Goal Card

### 2.1 User need

`U-AGENT-SURFACE-DAILY-1`: A single operator can use Agent OS every day for repository development and personal work without reconstructing context when switching between the desktop application, terminal, local execution, and remote execution.

The user-perceptible result is one persistent workspace in which Tasks can be created, observed, redirected, approved, paused, recovered, and continued from either the macOS application or CLI. Gmail, Calendar, browser, file, terminal, and coding work appear as organs of the same Task and authority model, not separate assistants.

### 2.2 Product capabilities

- `P-SURFACE-PROTOCOL-1`: Desktop and CLI consume one versioned Surface Protocol backed by one local Runtime daemon.
- `P-WORKSPACE-CANVAS-1`: The macOS application provides a composable but closed-set Workspace Canvas.
- `P-SWE-ORGAN-1`: A real repository task can inspect, propose, modify, verify, explain, and recover through the governed execution spine.
- `P-PERSONAL-ORGAN-1`: A real Gmail, Calendar, Chrome, or embedded-browser task can read, propose, receive approval, produce an external effect, and reconcile the provider result.
- `P-SYNC-WORKER-1`: A Task can synchronize through the cloud and delegate a fenced work unit to a registered macOS or Linux Worker without duplicating external effects.

### 2.3 Protected invariants

- `A-SINGLE-RUNTIME-1`: Surfaces do not embed or fork independent task truth, policy, permit, approval, receipt, or recovery implementations.
- `A-SINGLE-EFFECT-OWNER-1`: An external effect has exactly one current execution owner and one stable effect identity.
- `A-C7-SURFACE-1`: Pause, cancel, revoke, and correction authority remains outside model control and is honored before the next external effect.
- `A-SECRET-CUSTODY-1`: Secret values never enter ordinary Task events, SQLite records, logs, model context, or Surface state.
- `A-UNKNOWN-EFFECT-1`: Timeout or disconnection creates `UNKNOWN`, not presumed failure; retry is prohibited until reconciliation.
- `A-HOME-RUNTIME-1`: Every Task has one sequencing `Home Runtime` in one epoch. A Worker receives only a fenced work-unit lease.

### 2.4 Kill conditions

The program should be narrowed or stopped if any of these remain true after the corresponding wave:

1. Desktop and CLI require separate task/session stores or cannot resume the same Task after restart.
2. A Surface, Chrome extension, model output, sync message, or stale Worker can bypass Policy, Permit, Approval, Capability Broker, receipt, or C7.
3. A provider timeout or Worker disconnection can cause an external effect to be resent without reconciliation.
4. The desktop application still requires the user to start or repair the Python service manually for ordinary use.
5. The Personal Work slice cannot demonstrate a real read-propose-approve-effect-receipt cycle on Gmail and Calendar.
6. Cloud synchronization requires copying a live SQLite database or uses last-write-wins to erase concurrent Task events.

## 3. Context and evidence boundary

The repository already contains:

- a Python Agent Core with Task, Run, policy, permit, capability, evidence, recovery, Mandate, and provider seams;
- an API server and static Web Surface;
- a terminal coding-agent branch with a governed multi-turn provider/capability loop;
- SQLite-backed durable product state;
- bounded Product implementations for responsibility views, active perception, task configuration snapshots, and related contracts.

This design does not treat those components as a released product. The terminal candidate remains branch-scoped and not independently reviewed or merged according to the observed live state. The existing Web Surface is an information-architecture and API donor; a static HTML file is not sufficient for the selected composable desktop interaction model.

The current checkout has pre-existing unrelated modifications. Implementation must begin in an isolated worktree from a reconciled base. Exact-head review, integration, packaging, signing, push, merge, release, product validation, and any autonomy claim remain separate gates.

## 4. Product shape

### 4.1 One Surface, four work postures

The top-level product postures are projections over the same Runtime state:

- `Work`: outcome-oriented Tasks, plans, tool activity, approvals, evidence, Workers, and recovery.
- `Ask`: low-friction questions and research with sources and workspace context; it has no external effect by default and upgrades to `Work` when execution is required.
- `Automate`: time- or event-triggered Tasks with a Mandate, budget, capability ceiling, execution window, stop condition, and escalation rule.
- `Observe`: unfinished commitments, relevant environment changes, risks, Worker health, conflicts, and structured HelpRequests across Tasks.

No posture owns a separate agent loop, memory store, provider configuration, or authority path.

### 4.2 Workspace Canvas

The first release has a closed set of ten panel types:

1. Agent Thread
2. Plan and Tasks
3. Files
4. Diff
5. Terminal
6. Chrome Live
7. Embedded Web
8. Gmail
9. Calendar
10. Evidence and Approval

Panels can move, resize, focus, close, and persist in named layout templates. A panel is a typed Surface consumer. It cannot call native capabilities, Google APIs, Chrome automation, shell commands, or Worker endpoints directly.

The left rail provides Workspace, Task, and Automation navigation. The active Task header exposes organ, Task status, current Home Runtime or Worker, pause/correction controls, and outstanding approvals. The composer can redirect the Task or invoke typed commands such as approve, pause, or move, but typed commands still enter the Runtime protocol.

### 4.3 Browser responsibilities

- `Chrome Bridge` attaches to explicitly selected user tabs and can reuse the user's logged-in browser state. Every sensitive action binds browser profile, tab, origin, DOM/action digest, and approval.
- `Embedded Web` uses an isolated WebView profile for Agent-initiated research, previews, and tasks that should not inherit the user's general browser state.
- Logged-in state is never silently copied between Chrome and the embedded browser.
- Page, email, and document content is untrusted data. Instructions embedded in content cannot alter the Mandate, permission ceiling, system policy, or approval requirements.

## 5. Runtime and Surface architecture

### 5.1 Process model

The packaged macOS application contains:

1. a Tauri shell that owns windows, tray, notifications, Keychain access, folder authorization, updates, and supervised child-process lifecycle;
2. a React/TypeScript renderer that owns Canvas routes, panels, interaction state, and event rendering;
3. a supervised Python Agent Core daemon that owns all canonical product behavior and durable local state.

The CLI discovers or starts the same daemon through a local connection descriptor protected by filesystem permissions. It does not instantiate a second `AgentOSApplication` against the same database.

The Tauri IPC bridge is narrow. It can manage daemon lifecycle and native capability references, but renderer input cannot become a raw shell command, arbitrary filesystem path, Keychain query, or process invocation.

### 5.2 Versioned Surface Protocol

The protocol has three channels:

- command: create, redirect, approve, pause, resume, correct, move, and request a typed capability;
- query: Task, Session, layout, provider profile, approval, evidence, Worker, sync, and recovery projections;
- event stream: ordered Task/Session/tool/approval/evidence/Worker/sync changes with resume cursors.

Every request carries:

- protocol version;
- request and client identities;
- tenant, workspace, principal, and device ownership;
- Task and Session references when applicable;
- expected revision or event cursor for state-sensitive mutations;
- an idempotency key for commands;
- a payload digest for approval- or effect-bearing commands.

Unsupported protocol versions and stale expected revisions fail closed with typed errors. The renderer reconnects from its last acknowledged cursor rather than rebuilding state from chat text.

### 5.3 Runtime ownership

The Agent Core daemon owns:

- Task, Session, Run, commitment, and recovery state;
- provider invocation and streaming;
- policy, permit, approval, and C7 enforcement;
- capability registration and execution dispatch;
- evidence, artifacts, action receipts, and outcome acceptance;
- provider profiles and non-secret resolver references;
- local event ordering and sync outbox/inbox state.

SQLite remains the local durable event and projection store for the first release. Large artifacts use a content-addressed local artifact store referenced from events.

## 6. Personal Work connectors

### 6.1 Google identity and scopes

The first Personal Work connector is Gmail plus Google Calendar using OAuth authorization-code flow with PKCE. OAuth scopes are requested incrementally. Token values are stored in macOS Keychain for the local Runtime. A remote Worker requires an independently authorized connector profile on that Worker; tokens are not synchronized as Task data.

Default authority:

- Gmail read/search and local draft generation may run automatically inside an authorized account scope.
- Creating a remote draft, sending, moving, archiving, or deleting mail requires exact approval.
- Calendar read and free/busy analysis may run automatically inside an authorized calendar scope.
- Creating, updating, inviting, cancelling, or deleting events requires exact approval.

Approvals bind the account, provider object identifiers, recipients or attendees, content or event digest, and provider precondition/version where available.

### 6.2 Workspace and terminal

Default authority:

- read and search inside explicitly authorized roots may run automatically;
- edit, delete, Git write operations, test execution, and commands require approval;
- project profiles may reduce repeated interactive approval for exact capability patterns, but cannot remove the capability scope, effect reservation, receipt, C7, or risk-tier floor;
- test execution is treated as arbitrary workspace-code execution, even when its user-facing label is verification.

### 6.3 Chrome and embedded browser

Default authority:

- reading an attached tab, taking a screenshot, and no-side-effect navigation may run automatically within the authorized origin and Task;
- form submission, purchase, publication, upload, destructive action, and executing a downloaded artifact require approval;
- the Chrome bridge validates extension origin, native host identity, tab binding, message schema, and replay identity before forwarding a proposal;
- the embedded browser requires approval before login, persistent cookies, state-changing submission, or cross-origin download.

## 7. Cloud synchronization and Workers

### 7.1 Narrow cloud control plane

The first cloud control plane uses a Python service, PostgreSQL, and WebSocket or SSE connections. It provides:

- account and device registration;
- encrypted Task-event synchronization with per-Task cursors;
- Worker registration, capability manifests, health, and revocation;
- Work Lease allocation with fence tokens and expiry;
- a durable command outbox and receipt inbox;
- effect reconciliation records;
- selective synchronization by Workspace and content classification.

It does not copy SQLite files, resolve local Keychain secrets, silently grant capabilities, or become a second Runtime policy implementation.

### 7.2 Home Runtime

Every Task has one `HomeRuntimeRef` containing a Runtime identity and monotonically increasing epoch. The Home Runtime is the sole sequencer for Task decisions and event revisions during that epoch.

A Home Runtime migration:

1. stops new effect-bearing work;
2. closes or reconciles all outstanding permits, reservations, and leases;
3. seals a checkpoint and sync cursor;
4. atomically assigns a new Runtime identity and higher epoch;
5. rejects every later write from the old epoch.

The first release supports migration only at a Task boundary or explicit checkpoint.

### 7.3 Worker contract

A Worker registers:

- device public key and Worker identity;
- platform and Runtime version;
- a versioned Capability Manifest with risk levels and sandbox or dependency requirements;
- health, load, available budget, and last acknowledged event cursor.

A `WorkAssignment` binds:

- Task, Run, Action, and stable effect identities;
- configuration snapshot and authority-envelope digests;
- capability and argument digests;
- permit, approval reference when required, lease identifier, fence token, and expiry;
- expected artifact and receipt contract.

The Worker revalidates the assignment locally before execution. It records effect start before invoking an external connector and returns a signed `ActionReceipt` plus artifact references. It cannot accept the outcome it produced.

### 7.4 Synchronization semantics

- Event identity and cursor deduplicate delivery.
- Append-only records preserve concurrent observations and decisions.
- Last-write-wins is forbidden for Task truth, authority, effects, approvals, and outcomes.
- Semantic conflicts create a typed Conflict and pause affected work until replan, merge, or HelpRequest resolution.
- A timeout or missing receipt produces `UNKNOWN`.
- `UNKNOWN` effects are reconciled against the external system or durable provider identity before retry.
- Offline local work may continue only within already valid local authority and without acquiring a new remote lease, changing Home Runtime, expanding permissions, or accepting cloud-dependent results.

## 8. Security and failure model

### 8.1 Unified execution pipeline

Every effect path is:

```text
untrusted input
-> typed capability proposal
-> policy decision
-> durable permit
-> exact approval when required
-> pre-dispatch reservation
-> Capability Broker or fenced Worker
-> action receipt and evidence
-> independent outcome acceptance
```

C7 correction, pause, cancellation, expiry, and revocation are checked before the next effect and at cancellable execution boundaries.

### 8.2 Secret custody

- macOS provider keys, OAuth tokens, and device private keys live in Keychain.
- Linux Worker secrets use a separately configured Worker-side secret store or deployment injection.
- cloud synchronization carries resolver references and encrypted Task data, never ordinary secret values.
- Surface logs and evidence include redacted configuration identifiers and digests rather than credentials.
- enterprise KMS or secret-manager integration is a successor that implements the same resolver contract.

### 8.3 Required typed failure states

- provider unavailable: preserve the working set and expose retry timing; never treat empty output as success;
- Runtime crash: supervisor restarts the daemon and recovery resumes from the last closed event; unresolved permits enter reconciliation;
- Worker disconnected: lease expiry does not prove effect failure; possible effects become `UNKNOWN`;
- OAuth expired or revoked: pause only affected connector work and emit a minimal HelpRequest;
- sync conflict: preserve both histories, freeze affected effects, and require typed resolution;
- prompt injection: external instructions remain untrusted content and cannot alter authority;
- stale fence, epoch, revision, permit, approval, or configuration digest: reject without execution;
- Surface protocol mismatch: block state-changing commands and present an upgrade-required state.

## 9. Enterprise and distributed evolution

Every first-release Task, Session, Permit, Approval, Receipt, Worker, and Sync Envelope includes tenant, workspace, principal, and device ownership. The first release implements one personal tenant; presence of ownership fields is not multi-tenant evidence.

Successor distributed Agent work can add goal/program/task dependency planning, organ allocation, multiple Workers, fenced work-unit scheduling, cross-node conflict handling, and result aggregation. It must reuse Home Runtime epochs, leases, stable effect identities, reservations, receipts, and correction priority.

Successor enterprise work can add organization tenancy, SSO, SCIM, RBAC/ABAC, policy packages, audit export, deployment management, retention, compliance controls, and service-level operations. It cannot change these permanent semantics:

- model output does not hold final authority;
- proposer and outcome acceptor remain separated for consequential work;
- no self-approval or permission expansion;
- C7 remains non-writable and non-bypassable;
- uncertain external effects fail closed pending reconciliation;
- task, authority, evidence, process, product, and commercial claims remain separate.

## 10. Delivery decomposition

This program is too large for one implementation plan. It is divided into four independently testable waves. Wave 1 is the first implementation-plan target after this program spec is accepted. Waves 2 through 4 require their own bounded child spec and plan before implementation.

### Wave 1: Unified local Runtime and development loop

Deliver:

- supervised Agent Core daemon;
- versioned Surface command/query/event protocol;
- CLI connection to the same daemon;
- durable Session history and reconnect cursors;
- shared Task, approval, evidence, correction, and recovery state;
- a real local Software Engineering loop.

Exit gate: Desktop protocol client and CLI can create, inspect, continue, pause, approve, and recover the same Task across process restart; all existing execution authority checks remain non-bypassable. Wave 1 may use a protocol test client before the Tauri UI exists.

### Wave 2: macOS application and Workspace Canvas

Deliver:

- Tauri macOS shell;
- React/TypeScript Workspace Canvas and the ten closed panel types;
- task/workspace navigation and layout templates;
- daemon installation and supervision;
- Keychain, folder authorization, notifications, tray, and isolated embedded WebView;
- an arm64 `.app` development artifact.

Exit gate: a clean arm64 Mac installation launches, configures, exits, restarts, and recovers without manually starting Python. Packaging does not imply signing, notarization, release, or daily usability.

### Wave 3: Personal Work and browsers

Deliver:

- Google OAuth and Keychain custody;
- Gmail read, draft, approved effect, and reconciliation paths;
- Calendar read, proposal, approved effect, and reconciliation paths;
- Chrome extension and native bridge;
- isolated embedded browser behavior;
- Ask-to-Work upgrade.

Exit gate: real authorized accounts complete read-propose-approve-effect-receipt cycles without token leakage or duplicate effect. Live-account evidence is stored as redacted receipts, not customer content or credentials.

### Wave 4: cloud sync and macOS/Linux Workers

Deliver:

- PostgreSQL cloud control plane;
- device enrollment and event-cursor synchronization;
- Home Runtime epochs and checkpoint migration;
- Worker registration, manifests, health, leases, fences, and revocation;
- durable command outbox, receipt inbox, and effect reconciliation;
- one macOS and one Linux Worker path.

Exit gate: the same Task delegates a work unit to both Worker classes in separate runs; injected disconnect, timeout, duplicate message, out-of-order event, and stale fence cases do not duplicate an external effect or erase Task truth.

## 11. First daily-use acceptance suite

The first internal daily-use candidate requires all of these:

1. A clean arm64 Mac can install and launch the application, configure a provider, and start the supervised Runtime without manual service commands.
2. A coding Task created in the desktop app can be continued and paused from the CLI, then recovered in the app after restart with the same history, approvals, evidence, and Task identity.
3. A real isolated-worktree repository task completes failing-test observation, minimal governed modification, verification, result explanation, and recovery behavior.
4. A real Gmail and Calendar account completes read, local proposal, exact approval, one provider effect, provider-identity reconciliation, and receipt inspection.
5. Chrome completes one controlled logged-in submission and the embedded browser completes one isolated research or preview task without profile leakage.
6. One macOS and one Linux Worker register, declare capabilities, receive a fenced lease, and return a signed receipt.
7. Fault injection covers Runtime crash, Worker disconnect, OAuth expiry, duplicate delivery, event reordering, stale epoch/fence, sync conflict, and effect timeout.
8. Bypass tests prove that renderer IPC, Chrome messages, model output, sync messages, old permits, and stale Workers cannot skip Policy, Permit, Approval, receipt, or C7.

After engineering and live-integration gates pass, the founder runs a seven-day personal dogfood period. Only observed daily use, intervention burden, recovery cost, and result-interpretation burden can support a `daily-usable` judgment.

## 12. Baselines and product validation

The product comparison uses three baselines:

- Codex app interaction baseline: multiple supervised Tasks, long-running work, skills/automations, native application lifecycle, and secure permission UX;
- Hermes Desktop interaction baseline: Desktop, CLI, and remote surfaces sharing agent sessions, skills, memory, and configuration;
- strong cheap baseline: founder-driven frontier model plus tools in the same repository, account, authority, and budget envelope.

The design does not claim feature parity. Agent OS must additionally show recoverable cross-domain Task continuity, typed authority, effect reconciliation, and lower operator hidden cognitive work. Product metrics include:

- end-to-end valid Task outcome rate;
- operator intervention count and HCW minutes;
- context-restoration and result-interpretation burden;
- restart and interruption recovery success;
- unsafe or duplicate external-effect rate;
- bypass/regression rate;
- cost and latency by Task type.

## 13. Out of scope for the first release

- production multi-tenant enterprise SLA;
- SSO, SCIM, organization administration, or a complete RBAC/ABAC console;
- arbitrary-topology distributed Agent scheduling;
- cross-node linearizability claims;
- general plugin renderer or arbitrary frontend code execution;
- unconstrained shell, filesystem, browser, email, or calendar authority;
- model self-approval, permission expansion, or final outcome authority;
- released, enterprise-ready, autonomous, self-improving, AGI, or customer-validated claims.

## 14. External prerequisites and release separation

These prerequisites do not block local protocol and Canvas development, but their related gates cannot close without them:

- a Google OAuth client authorized for the selected Gmail and Calendar scopes;
- a cloud deployment target and PostgreSQL instance for Wave 4 integration;
- a reachable macOS Worker and Linux Worker for live Worker verification;
- Apple Developer signing and notarization credentials for any externally distributed macOS build.

Implementation, tests, integration, live connector verification, package creation, signing, notarization, push, merge, release, enterprise readiness, and daily usability remain separate statuses.

## 15. Confirmed founder choices

The founder confirmed during the 2026-08-11 design session:

- both repository development and general personal-Agent use are required;
- the existing Web Surface is the UI donor and must evolve into a native macOS application;
- macOS is the only first application platform;
- Personal Work includes Gmail, Google Calendar, Chrome, and an embedded browser;
- the product should benchmark Codex app and Hermes app without copying their claim boundaries;
- the main UI is a composable Workspace Canvas;
- both macOS and Linux remote Workers are architectural and first-release targets;
- local state plus cloud Task synchronization are required;
- distributed Agent and enterprise-Agent support belong to the complete architecture;
- the first running release implements the local/native and sync/Worker layers, while distributed and enterprise completion remains successor scope;
- Tauri + React/TypeScript + Python headless Runtime is the approved technical path;
- the architecture, interaction model, sync/Worker model, security model, and delivery gates in this document were each confirmed.
