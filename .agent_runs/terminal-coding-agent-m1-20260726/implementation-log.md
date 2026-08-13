# P-TERMINAL-CODING-AGENT-1 Implementation Log

> Date: 2026-07-26
> Track: Product
> Branch: `feature/awl-3-coordinator-decomposition`
> Base HEAD inspected: `27337578e15f307bec18edb5221356d5c3ed6c04`
> State: `IMPLEMENTED_LOCAL / UNCOMMITTED / NOT_REVIEWED`

## Authority packet

- Goal Card:
  `docs/product/GC-TERMINAL-CODING-AGENT-M0-M1-2026-07-26.md`
- Context Pack:
  `docs/product/CP-TERMINAL-CODING-AGENT-M0-M1-2026-07-26.md`
- Architecture Brief:
  `docs/architecture/T-P-CORE-TERMINAL-CODING-AGENT-ARCHITECTURE.md`
- Dated benchmark:
  `docs/product/TERMINAL-AGENT-CLI-BENCHMARK-2026-07-26.md`

The branch already contained a large, uncommitted multi-lane working tree and a
pre-existing terminal M1 candidate. This pass preserved unrelated changes and hardened
the terminal slice in place; it did not create a clean feature branch, commit, push or
merge.

## Implemented vertical slice

1. Added a governed multi-turn `AgentLoop` beside the static `WorkflowGraph` executor.
   Provider tool proposals become `ActionContract` values, pass through
   `PolicyKernel.decide`, exact permits and `CapabilityBroker`, and return to the
   provider as typed `TOOL` messages.
2. Added closed `SessionRef`, `TurnId` and assistant/tool-call message bindings;
   OpenAI-compatible requests now carry structured JSON schemas for the six chat
   capabilities.
3. Added a stdlib `chat` REPL plus `chat -p`. Interactive edits/shell calls require a
   confirmation surface; `-p` fails closed instead of auto-approving writes.
4. Bound every successful chat provider invocation to the sealed
   `TaskConfigurationSnapshot`, exact invocation binding, correction epochs and a
   durable `ProviderExecutionReceipt`.
5. Restricted the chat envelope and loop grants to the six declared chat capabilities
   rather than all composition-root grants.
6. Added exact-edit, search and allowlisted-shell behavior while retaining the existing
   whole-file replacement and test capabilities.
7. Hardened workspace and subprocess boundaries:
   - search and reads reject symlink paths, including inside-workspace aliases;
   - search cannot follow a symlink outside the workspace;
   - shell/test subprocesses receive an explicit minimal environment and do not inherit
     provider API keys;
   - shell remains exact-allowlist only and uses argument-vector execution, not
     `shell=True`.
8. Routed Ctrl-C through `AgentOSApplication.correct_task`, which performs authority
   checks and records `CORRECTION_WRITTEN`, instead of directly advancing the lower
   correction epoch table.
9. Extracted shared provider-receipt construction from `ProposalEngine` for use by both
   graph and chat execution forms.

## TDD / bypass evidence

Red-to-green cases created or closed in this pass:

- workspace search followed an escaping symlink;
- workspace read accepted an inside-workspace symlink alias;
- shell inherited `OPENAI_API_KEY`;
- OpenAI tool definitions exposed unstructured parameter objects;
- headless `chat -p` could reach a write-confirmation surface;
- terminal provider calls lacked sealed configuration/receipt evidence;
- Session/Turn identity was not a closed contract;
- Ctrl-C advanced correction state without the Task audit event;
- chat candidate envelope advertised unrelated composition-root grants.

The integration suite also contains a complete deterministic task:

`failing pytest fixture -> workspace.read -> workspace.edit -> workspace.run_tests ->
green result`, with three action receipts.

## Deliberate residual boundaries

- Live provider-message history is in memory. Task/Run events provide audit receipts,
  but `chat --resume`, branch/replay and reconstructable conversation history are not
  implemented.
- Provider responses are non-streaming. There is no full-screen TUI, steering or
  token/cost renderer.
- `AGENTS.md` discovery, codebase indexing and deterministic context compaction are not
  implemented.
- Shell execution has a sanitized environment and exact allowlist but no OS
  filesystem/network sandbox. This is not an arbitrary-shell coding environment.
- Successful provider calls receive durable receipts; failed provider attempts do not
  yet have a dedicated durable attempt receipt.
- Chat action node ids are per-turn and are not committed workflow nodes, so the
  workflow-bound artifact index does not cover them; action receipts still bind output
  artifact ids.
- No live-provider task, exact-diff independent review, clean-branch isolation, commit,
  push, merge or release occurred.
