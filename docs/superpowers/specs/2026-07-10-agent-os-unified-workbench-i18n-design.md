# Agent OS Unified Adaptive Workbench and Internationalization Design

> Date: 2026-07-10
> Track: Product
> Status: Founder-approved; P0 static prototype slice implemented and verified locally (production UX packet pending)
> Prototype verification: 2026-07-11 at 1440x900, 1024x768 German expansion and 390x844 in Browser/IAB
> Product boundary: Agent OS is the product; Data Agent and other domains are optional capability packs.

## 1. Decision

Agent OS uses one shared runtime with three first-class workspace profiles. These profiles
are context, ownership and governance boundaries rather than separate products or kernels:

```text
Account
  -> Workspace Profile (Personal / Developer / Organization)
  -> Space / Project
  -> Interaction Contract (Ask / Work)
  -> composable ScenePreset
  -> Task -> Context -> WorkflowGraph -> Run -> Outcome -> Reusable Knowledge
```

The profiles provide suitable defaults for personal work, software development and
organizational operations while preserving one identity, task model, capability ecosystem
and execution core. Scene presets reduce cold-start friction inside each profile; they are
soft, composable, inspectable and versioned. A user can switch profiles, use the generic
workspace, or modify a preset without adopting a permanent persona.

The first implementation will also add a real internationalization substrate for eight
launch locales:

- Simplified Chinese (`zh-CN`)
- Traditional Chinese (`zh-TW`)
- English (`en`)
- Japanese (`ja`)
- Korean (`ko`)
- Spanish (`es`)
- French (`fr`)
- German (`de`)

## 2. Product principles

1. **Task first, not chat first.** Conversation is one input method. The durable product
   object is a task with context, execution state and outcome.
2. **No persona lock.** A user may own personal, developer and organization spaces at the
   same time. Onboarding selects a default profile but never permanently classifies the user.
3. **Progressive disclosure.** Simple tasks stay simple. Workflow, authority, budget,
   provider, tool and trace details appear when they affect the current job.
4. **Evidence over narration.** Completion means a visible artifact, test, citation,
   observation or action receipt, not an agent saying it finished.
5. **Approval at the consequence boundary.** Review is attached to a concrete action and
   impact, not presented as a generic confirmation dialog.
6. **Persistent context without silent learning.** Reusable instructions or knowledge are
   proposed after successful tasks and applied only after approval.
7. **Language is presentation state.** Changing locale must never change workflow digests,
   policy decisions, action contracts, stored event types or provider behavior.

## 3. Competitor-derived requirements

The design borrows interaction patterns, not runtime dependencies.

| Product | Useful pattern | Agent OS response |
|---|---|---|
| OpenAI Codex | Projects, durable task threads, diff review, isolated work and skills | Keep task history, context boundary, action review and capability discovery in one workbench |
| Claude Code | Sessions across surfaces, permission modes, memory, skills, parallel agents and visual diffs | Preserve task continuity and expose authority only when relevant |
| Manus | Projects as persistent instruction/knowledge containers; task-driven automatic parallelism | Use Space as a neutral context container; suggest decomposition from task shape instead of persona presets |
| Microsoft Copilot Studio | Tools, connectors, knowledge, workflows, human input, eval and administration | Keep these as shared platform capabilities, but hide builder complexity from ordinary task execution |
| LangSmith Studio | Graph inspection, threads, traces, evaluation and time travel | Provide a progressive diagnostic view behind the primary outcome-oriented task surface |

Primary references:

- <https://openai.com/index/introducing-the-codex-app/>
- <https://code.claude.com/docs/en/overview>
- <https://manus.im/blog/manus-projects>
- <https://manus.im/docs/features/wide-research>
- <https://learn.microsoft.com/en-us/microsoft-copilot-studio/>
- <https://docs.langchain.com/langsmith/studio>

## 4. Universal object model

### 4.1 Workspace profile

Three workspace profiles are first-class product surfaces:

- **Personal:** research, files, content and daily automation; individual ownership and
  local-first defaults.
- **Developer:** repositories, branches, terminals, tests, reviews and releases; sandbox,
  worktree and CI-oriented defaults.
- **Organization:** enterprise data, approvals, operating decisions, audit and governed
  automation; tenant, RBAC, separation-of-duty and retention defaults.

Profiles do not duplicate Runtime, Provider, WorkflowGraph, Knowledge, Evidence, Policy or
UI infrastructure. Cross-profile data movement is explicit and auditable. An organization
profile is not merely a visual preset because tenant isolation and authority are system
boundaries.

### 4.2 Space

A Space is a persistent context and authority boundary. It may contain a repository,
documents, data sources, instructions, provider profiles, tools and knowledge. It is not a
persona or domain.

The first implementation maps the attached local workspace to one `Local Space`. It must
not claim a durable multi-Space backend until a typed Space contract and persistence path
exist.

### 4.3 Interaction contract

- **Ask** is lightweight and read-only by default. It may inspect and explain available
  context without creating a durable execution run.
- **Work** creates a durable task with tools, workflow, artifacts, verification and outcomes.
- Ask can be promoted to Work while retaining question, citations and selected context.

Ask and Work share identity, history and knowledge boundaries; they are not separate data
silos or products.

### 4.4 Scene preset

A `ScenePresetManifest` references independently versioned assets rather than embedding a
monolithic configuration:

```text
workflow_template_ref + capability_pack_refs + policy_profile_ref
+ knowledge_profile_ref + ontology_seed_ref + evaluation_suite_ref
+ memory_policy_ref + ui_scene_seed_ref
```

The preset compiler produces an immutable `TaskConfigurationSnapshot`. A preset can narrow
authority or declare required grants but can never widen effective user, Space or runtime
authority. Switching a preset during a run creates a validated configuration and GraphPatch
proposal; it never silently mutates the active WorkflowGraph.

### 4.5 Task

A Task captures:

- user goal;
- selected context;
- expected output or observable outcome;
- constraints and risk boundary;
- workflow and run history;
- artifacts, evidence and reusable-learning proposals.

The first implementation continues to use the existing Goal, Commitment, WorkflowGraph,
AgentRun and Outcome contracts. UI labels may be localized; stored enums and contracts may
not be translated.

### 4.6 Context

Context is shown as inspectable sources rather than an opaque token bucket. The first
implementation exposes:

- attached workspace root;
- target resource;
- provider and model;
- verifier;
- available capability count;
- explicit absence of knowledge sources or external connectors.

### 4.7 Plan and workflow

The task composer shows a concise execution outline before commitment. Advanced users can
open the workflow representation. Natural-language workflow generation and drag/drop
editing remain later packets, but the UI reserves one stable `Plan` surface rather than a
domain-specific builder.

### 4.8 Run and outcome

The run view answers, in order:

1. What is happening now?
2. What changed or is proposed?
3. Does the user need to act?
4. What did it cost?
5. What evidence proves the outcome?
6. What can be retried, corrected, reused or exported?

### 4.9 Generative Workspace scene boundary

The stable Agent OS Shell owns identity, authority, task navigation, notifications and
canonical pause/correct/approve/reject controls. The inner workspace may adapt to the task,
but it may render only a validated `UISceneSpec` through registered components.

`UISceneSpec` is a disposable projection, never a truth source. It binds to authoritative
task/run event sequences and source digests. If it is lost or invalid, the product rebuilds
it from TaskEvent, WorkflowGraph, ActionContract, Evidence, PolicyDecision,
ApprovalDecision and ObservedOutcome.

```text
authoritative projections
  -> optional model scene proposal
  -> deterministic SceneCompiler
  -> schema / source / permission / sensitivity validation
  -> UISceneSpec
  -> Component Registry renderer
  -> InteractionIntent
  -> command, GraphPatch proposal or Action proposal
  -> existing policy / approval / runtime path
```

The first static implementation uses deterministic fixture projections only. It includes
the stable Shell, a component registry, scene fixtures and interaction-intent simulation;
it does not include model-generated scenes or runtime execution.

Scene constraints:

- no arbitrary HTML, JavaScript, CSS, SQL, shell commands, URLs or executable callbacks;
- every panel source is a typed reference such as `evidence:23`, `belief:8` or `action:17`;
- every component type and property shape is registered;
- generated scenes cannot hide, rename or override canonical authority controls;
- gestures emit typed InteractionIntent objects and never mutate WorkflowGraph directly;
- workflow edits become previewable, validated, versioned GraphPatch proposals;
- scene semantics are locale-neutral and visible strings resolve through i18n keys.

## 5. Information architecture

### 5.1 Global frame

- Product identity: Agent OS
- Workspace profile and current Space switcher/status
- Ask / Work interaction switch
- current soft scene preset, recommendation source and version
- New task command
- Recent and filtered tasks
- Integrations/settings
- Locale selector

Personal, Developer and Organization appear only in the workspace switcher. They do not
become three separate global navigation trees or three products.

### 5.2 Task composer

The first viewport contains:

- universal goal input;
- context bar showing Space, target and provider;
- target resource field where the active capability requires one;
- expected outcome/verifier;
- compact plan preview;
- primary `Create task` / `Run` command;
- setup blockers shown inline with direct recovery actions.

Optional examples are action patterns such as `Analyze`, `Create`, `Transform`, `Automate`
and `Investigate`. They are not modes, personas or permanent presets.

### 5.3 Active run

- compact status header with elapsed state, model, token usage and current node;
- stable stage rail that does not resize as nodes change state;
- approval panel with target, current/proposed content, action risk and exact effect;
- activity stream with human-readable policy, tool and recovery events;
- outcome summary with evidence links and next actions.

### 5.4 Task details

Tabs remain available but are reordered around user value:

1. Outcome
2. Activity
3. Evidence
4. Plan

Raw contract JSON is available only inside an advanced disclosure.

## 6. Internationalization architecture

### 6.1 Locale resolution

Resolution order:

1. explicit user choice stored under `agent-os.locale`;
2. best match from `navigator.languages`;
3. English fallback.

The language menu displays every language in its native name. Changing language updates
the current screen immediately, persists across reloads and updates the document `lang`
attribute. The architecture must permit future RTL locales even though no launch locale is
RTL.

### 6.2 Translation catalog

Frontend text uses stable semantic keys, for example:

```text
nav.newTask
task.goal.label
run.status.waitingApproval
approval.effect.fileReplacement
error.provider.unavailable
evidence.openReport
```

Catalog requirements:

- one complete English source catalog;
- eight complete locale catalogs with identical key sets;
- fallback to English for a missing runtime key;
- development-time missing-key reporting;
- no translated strings embedded in business logic;
- interpolate only escaped values;
- use `Intl.NumberFormat`, `Intl.DateTimeFormat` and `Intl.RelativeTimeFormat` for dynamic
  values;
- preserve user content, paths, model IDs, event IDs and contract enums verbatim.

### 6.3 Backend error mapping

The API continues to return stable typed error names and safe messages. The UI maps known
error types/codes to localized summaries and recovery actions. Unknown errors display the
safe backend message and a localized generic heading. The client must never infer policy
success from translated prose.

### 6.4 Accessibility

- language selector has a programmatic label;
- focus remains on the selector after locale changes;
- status is not conveyed by color alone;
- all controls keep visible focus styles;
- translated text may wrap without changing fixed control dimensions;
- layouts are tested using German expansion and narrow mobile widths;
- dynamic status changes use a polite live region where appropriate.

## 7. First implementation scope

### P0: multilingual product shell

- split the current monolithic HTML into static HTML, CSS, application JS and locale
  catalogs served by the existing stdlib HTTP server;
- implement eight locales, browser detection, persistence and live switching;
- localize every visible label, status, empty state, error, action, tab and accessibility
  name in the existing Task Workspace;
- add catalog parity and fallback tests.

### P0: unified workbench refinement

- remove remaining developer-only framing from top-level labels;
- present the current attached workspace as `Local Space` without adding a fake Space API;
- replace the raw setup disclosure with a focused integration panel and clear readiness
  states;
- improve new-task empty state, context bar, plan preview and commitment summary;
- make approval explain the concrete effect and policy decision;
- make terminal outcomes surface evidence, next action and retry/correction availability;
- keep current provider-driven patch golden path fully functional.

### P0 prototype: stable Shell plus deterministic scene renderer (implemented 2026-07-11)

- create an isolated Chinese static prototype without replacing the PM-accepted runtime
  UI;
- render one cross-domain task list inside a stable Agent OS Shell;
- render a deterministic investigation scene containing metric delta, causal relationship,
  evidence, agent topology, approval and activity components;
- demonstrate panel focus, evidence selection, canonical pause/correct controls and a
  bottom command surface through local interaction state;
- keep scene data in a structured fixture separate from component rendering;
- expose the prototype through a standalone static server for browser review;
- make no runtime, provider, policy, workflow or capability claim from the prototype.

Static-prototype evidence is deliberately narrower than the production P0 sections above:

- `/preview-zh` renders validated deterministic fixture `UISceneSpec` objects through a
  frozen component registry; it does not accept model-produced markup or callbacks;
- the stable Shell retains workspace, Ask/Work, pause, correct and concrete-action
  approval controls while Personal, Developer and Organization reuse the same components;
- eight browser-local catalogs support live locale switching and persistence; automated
  structure checks cover every locale option, while Browser/IAB exercised Chinese,
  English and German directly;
- Ask-to-Work promotion, evidence inspection, pause/resume, correction and approval were
  exercised in Browser/IAB with no relevant console errors;
- 1440x900, 1024x768 German expansion and 390x844 passed without horizontal page
  overflow; the approval controls remain visible and do not overlap the command dock;
- Product Track regression is `96 passed, 1 skipped`; Ruff and Pyright are clean.

This evidence does not satisfy the production-shell requirements for modular assets,
backend locale negotiation, catalog-parity tooling or the live SPINE-0 Task Workspace.

### P1: product-quality details included in this slice

- task search/filter by goal and status on the client;
- human-readable relative timestamps;
- responsive desktop/mobile layout;
- reduced-motion support;
- loading and in-flight button states;
- prevention of accidental duplicate submissions;
- direct recovery links for missing workspace/provider/target;
- task list status labels localized independently from stored status enums.

## 8. Non-goals

This implementation does not add:

- persona onboarding or domain presets;
- a production Space backend;
- visual workflow editing or natural-language workflow compilation;
- multi-file patch generation;
- arbitrary shell/browser execution;
- persistent encrypted credential storage;
- plugin marketplace, knowledge ingestion or RAG;
- subagent/swarm execution;
- Data Agent migration;
- Codex, Claude, Manus or enterprise-platform parity claims.
- model-generated UISceneSpec, SceneCompiler authorization or real scene-driven execution.

These remain separate product packets and must not be represented by disabled decorative
controls that imply delivery.

## 9. Error and recovery behavior

- API calls show operation-specific progress and disable only the initiating action.
- A failed request retains user input and current task context.
- Retry reuses the same task/run only where the runtime explicitly supports it.
- Approval rejection remains a durable decision and is not silently converted into retry.
- Locale loading failure falls back to the bundled English catalog without blocking work.
- Local storage failure keeps the selected locale for the current session and reports no
  false persistence.

## 10. Verification

### Automated

- catalog key parity across eight locales;
- locale resolution, fallback and persistence;
- no untranslated keys rendered in the default journey;
- existing API/product tests remain green;
- task creation, provider proposal, approval, retry and evidence links use the same API
  paths after frontend modularization;
- static assets reject path traversal and return correct content types.

### Browser

Run the same journey in English, Simplified Chinese and German at minimum:

```text
load -> change locale -> attach/check integrations -> create task -> run -> review action
-> approve -> verify outcome -> open evidence -> reload -> locale and task persist
```

Required viewports:

- 1440x900 desktop;
- 1024x768 compact desktop/tablet;
- 390x844 mobile.

Check no overlap, clipping, layout shift, untranslated labels, console errors or broken
focus order. German is the expansion stress locale; Chinese and Japanese verify non-Latin
rendering.

## 11. Acceptance criteria

1. A user can switch among all eight locales without reload and the choice survives reload.
2. Every first-party visible string in the core journey is catalog-backed.
3. Stored contracts, event types, digests and provider prompts are unchanged by locale.
4. No onboarding step asks for persona, industry or a fixed task category.
5. The empty state explains current readiness and offers one clear path to start a task.
6. The approval panel states the proposed effect, target and policy disposition before any
   file write.
7. A successful run ends with a localized, evidence-backed outcome and sensible next
   actions.
8. A failed run retains input and exposes a valid recovery action.
9. Existing SPINE-0 security, persistence and provider-driven golden-path tests remain
   green.
10. Desktop, compact and mobile browser verification passes with no relevant console
    errors.

## 12. Claim boundary

Passing this packet establishes only that the current SPINE-0 Task Workspace has a
multilingual, unified and more usable product surface. It does not establish complete
Agent OS, general task execution, enterprise readiness, autonomy, market parity or product
superiority.
