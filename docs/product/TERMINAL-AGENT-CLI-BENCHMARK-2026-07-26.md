# Terminal Agent CLI Benchmark — Hermes, OpenClaw and Pi

> Date: 2026-07-26
> Track: Product
> Status: **DESIGN_BASELINE / NOT_PARITY_EVIDENCE**
> Scope: terminal coding-agent execution surface for Agent OS
> Goal Card: `docs/product/GC-TERMINAL-CODING-AGENT-M0-M1-2026-07-26.md`
> Architecture Brief: `docs/architecture/T-P-CORE-TERMINAL-CODING-AGENT-ARCHITECTURE.md`

## 1. Decision

The target is not a clone of any one reference:

- use **Pi** as the core-shape constraint: a small coding-agent loop, a small default
  tool surface, multiple machine/interactive modes, and extension seams outside the
  kernel;
- use **Hermes** as the interaction-loop reference: visible multi-step tool use,
  interruptibility, context-file discovery, session continuity and later TUI
  observability;
- use **OpenClaw** as the authority/session reference: serialized work per session,
  explicit execution approvals bound to the exact command, sandbox-aware execution and
  durable session lifecycle;
- retain the Agent OS differentiator: provider output is proposal-only; every
  consequential action remains behind typed capability contracts, policy, an
  exact-action permit, correction epochs and durable receipts.

M1 is a governed vertical slice, not feature parity. Channel gateways, broad plugin
ecosystems, arbitrary shell access, sub-agents, MCP and a full-screen TUI are not part
of the first product claim.

## 2. Dated source baseline

Primary sources inspected for this decision:

- Hermes Agent repository and documentation:
  <https://github.com/NousResearch/hermes-agent>,
  <https://hermes-agent.nousresearch.com/docs/user-guide/cli>,
  <https://hermes-agent.nousresearch.com/docs/developer-guide/agent-loop/>,
  <https://hermes-agent.nousresearch.com/docs/user-guide/features/context-files>,
  <https://hermes-agent.nousresearch.com/docs/user-guide/security/>.
- OpenClaw documentation:
  <https://docs.openclaw.ai/cli>,
  <https://docs.openclaw.ai/agent-loop>,
  <https://docs.openclaw.ai/tools/exec-approvals>.
- Pi coding-agent documentation and repository:
  <https://pi.dev/docs/latest/usage>,
  <https://pi.dev/docs/latest/session-format>,
  <https://pi.dev/docs/latest/rpc>,
  <https://github.com/earendil-works/pi/blob/main/packages/coding-agent/README.md>.

These sources establish design inputs only. They do not establish security
equivalence, benchmark superiority, market parity or compatibility.

## 3. Capability comparison

| Dimension | Hermes | OpenClaw | Pi | Agent OS terminal M1 |
| --- | --- | --- | --- | --- |
| Product center | terminal agent with a broad tool/skill surface | gateway-centered agent runtime across sessions/channels | deliberately small coding-agent harness | governed terminal coding vertical slice on the existing Runtime/Kernel |
| Agent loop | iterative model/tool loop with visible tool activity | serialized agent loop with session lifecycle and tool execution | compact model/tool loop | typed provider → proposal → policy/permit → capability → TOOL feedback loop |
| Terminal modes | interactive CLI/TUI-oriented experience | broad CLI controlling gateway, sessions and tools | interactive, print, JSON and RPC modes | stdlib REPL plus `chat -p`; no JSON/RPC mode yet |
| Rendering | richer interactive rendering and interruption | event/stream-oriented runtime surfaces | streaming interactive UI and machine-readable modes | final-response rendering only; no provider streaming |
| Session durability | session/history and context-management features | durable, serialized per-session execution | append-only session tree with branching | Task/Run events and provider/action receipts; live message history remains in memory; no resume |
| Context files | repository context-file discovery, including `AGENTS.md`-style guidance | workspace/session context assembled by the runtime | project/user context files and extension hooks | fixed system prompt plus bounded live history; `AGENTS.md` auto-load is not implemented |
| Default coding tools | broad terminal/file/web/skill-oriented surface | configurable tool profiles plus exec and plugin tools | small file/edit/bash-oriented tool set | six typed capabilities: read, search, exact edit, whole-file replace, allowlisted tests and allowlisted shell |
| Shell authority | security controls and sandbox options | exact-command approvals, allowlists and sandbox modes | project-trust model; powerful shell is part of the coding harness | tier-3 approval plus sanitized environment, but only configured exact commands; no OS filesystem/network isolation |
| Provider support | multiple model/provider paths | configurable runtime/provider stack | provider/model extensibility | OpenAI-compatible HTTP plus deterministic CI provider; no Anthropic-native or streaming protocol |
| Extensions | skills, tools and MCP-oriented expansion | plugins, tools, gateways, sub-agents and integrations | extensions/packages/RPC | none in M1; future connectors must still become typed capabilities |
| Governance/audit | security-oriented controls | approvals, allowlists, sandbox and session controls | intentionally lightweight trust boundary | strongest current differentiator: policy kernel, exact permits, approval binding, correction epochs, event sourcing and provider/action receipts |

## 4. What M1 actually establishes

The local M1 candidate establishes:

1. a real multi-turn provider/tool loop in which tool results are returned as typed
   `TOOL` messages;
2. typed `SessionRef`, `TurnId`, provider tool calls and closed JSON tool schemas;
3. a stdlib `chat` REPL and fail-closed `chat -p` mode;
4. read/search/edit/whole-file replacement/test/allowlisted-shell capabilities through
   the existing policy/permit/broker/correction path;
5. exact provider configuration binding and `ProviderExecutionReceipt` persistence;
6. interactive confirmation for edits and shell actions, with shell also requiring a
   digest-bound kernel approval;
7. path confinement, symlink rejection, subprocess secret-environment minimization,
   action compensation and Ctrl-C correction audit.

The local targeted suite currently proves these paths hermetically with a deterministic
provider and a local OpenAI-compatible HTTP stub. It does not prove a real-provider
coding outcome, production sandboxing or long-session reliability.

## 5. Gap classification after M1

### P0 before calling the terminal a usable coding-agent alpha

- one real-provider coding task with a frozen fixture, expected patch and test oracle;
- full provider/message/tool-result replay sufficient for `chat --resume`;
- truthful run/session close semantics rather than an orphaned live Run;
- project trust and a useful structured command profile (`git status/diff`, targeted
  tests, lint/build) without introducing `shell=True`;
- command execution isolation beyond environment scrubbing, or an explicit
  trusted-workspace-only product boundary;
- exact-diff independent technical/security review.

### P1 after the first alpha task succeeds

- hierarchical `AGENTS.md` context discovery with change digests;
- deterministic context compaction recorded as an event;
- provider streaming, user steering and clean turn cancellation;
- session list/resume/branch plus JSON event and RPC modes;
- git status/diff/patch review as typed, read-first capabilities;
- coding-task eval set measuring task completion, unsafe-action rate, hidden operator
  work and token/tool cost.

### P2 only after task evidence shows a bottleneck

- MCP connector, skill/package system and provider-native adapters;
- bounded sub-agents with scope no greater than the parent and single-writer ownership;
- background work and richer TUI;
- gateway/channel expansion.

## 6. Explicit non-copy decisions

- Do not copy OpenClaw's channel/gateway breadth before the terminal coding task is
  reliable; it expands product surface without closing the core user outcome.
- Do not expose Pi-style powerful shell semantics until project trust, command binding
  and process isolation are explicit. Policy approval alone is not an OS sandbox.
- Do not make Hermes-style TUI polish an M1 gate; streaming and steering come after the
  governed loop has real-provider task evidence.
- Do not treat plugins, MCP or sub-agents as proof of agent quality. They are expansion
  surfaces and must be justified by measured task bottlenecks.
- Do not replace the self-developed authority/evidence/correction spine with an agent
  framework. External libraries may later serve UI, protocol and ordinary
  infrastructure roles only.

## 7. Claim ceiling

Allowed after local M1 tests:

`IMPLEMENTED_LOCAL / TARGETED_TESTED / STUB_PROVIDER_E2E / NOT_REVIEWED`

Not allowed until separate evidence exists:

`LIVE_PROVIDER_VERIFIED`, `USABLE_ALPHA`, `PRODUCTION_SANDBOXED`, `PARITY`,
`RELEASED`, any market claim, or any `Autonomy(S,E,O,V,T)` claim.
