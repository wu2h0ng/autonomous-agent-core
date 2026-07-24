# AGENT-OS-TERMINAL-1 — Mandate Coding Terminal

> Status: `IMPLEMENTED_LOCAL / V1_TOOLS_ZEROCONFIG_CONTINUATION / TESTS_ONLY / NO_HCW_CLAIM`
> Date: `2026-07-24`
> Branch: `codex/mandate-terminal-entry-20260723`
> Primary class: `P` (U: founder runs Agent OS from a Codex/Claude-Code-shaped terminal)
> Track: Product
> Supersedes interaction ceiling of: `MANDATE-TERMINAL-ENTRY-0` (chat-only)

## Named U

一次目标/对话输入后，founder 在标准终端里用 Agent OS 持续读改测仓库，直到任务完成、需要批准、或发出 HelpRequest——**不等同于**在 Cursor/Codex 聊天里叠一层 Mandate 协议。

Kill criterion（产品，非论文）：入口摩擦 ≤ `codex` / `claude` / `opencode`；单轮内可多工具续跑；写操作需明确批准；无 C7/权限自批。

## Parity map (Codex / Claude Code / OpenCode)

| Surface | Peer CLIs | Agent OS V0 | Later |
|---|---|---|---|
| One-command launch | `codex` / `claude` / `opencode` | `agent-os` (Mandate attach required) | zero-config bootstrap |
| Project/mission context | CLAUDE.md / AGENTS.md | Durable Mandate inject (no paste) | Mandate wake/continuation daemon |
| Multi-turn tools | read/edit/shell/test | `workspace.read` / `apply_patch` / `run_tests` | allowlisted shell, search, MCP |
| Mid-loop approval | interactive | `apply_patch` y/N before apply | digest-bound resume UX polish |
| Escalate irreducible | weak | `/help` → HelpRequest inbox | portfolio Help Surface |
| Streaming TUI | rich | plain stdin/stdout | optional TUI |
| Autonomy / HCW claim | marketing | **forbidden** until founder operates this surface for real Mandate work | — |

## V0 scope (must ship together)

1. Bare `agent-os` still boots Mandate REPL after attach.
2. Provider turns pass `allowed_capability_ids`:
   - `workspace.read`
   - `workspace.apply_patch`
   - `workspace.run_tests`
3. In-process tool loop: execute proposals via `WorkspaceSandbox` + typed `ActionContract`/`ActionPermit`, feed results back until text-only or max rounds.
4. `workspace.apply_patch` always prompts for interactive approve unless `--auto-approve-patches` (tests/CI only).
5. Sandbox root defaults to `--repo` (default: process CWD); Mandate attach workspace remains durable state root.
6. Slash commands: `/status` `/help` `/tools` `/quit`.
7. Tests prove: tools enabled on request; read executes; patch denied without approve; patch applies with approve; run_tests allowlisted.

## Out of V0

- Free shell / network / MCP
- Unified-diff editor UX (current capability is full-file write named apply_patch)
- Background continuation daemon (Mandate wake without any user turn)
- Merge to main / release / Autonomy / HCW evidence
- SELFDEV one-shot DAG replacement (reuse capability spine only)

## Usage

```bash
# once
agent-os --database ~/mandate.sqlite3 --workspace ~/mandate-ws \
  mandate-bootstrap mandate.json --relevance-context context.json
agent-os --database ~/mandate.sqlite3 --workspace ~/mandate-ws \
  mandate-attach --mandate-id ... --environment-binding-id ... \
  --principal-id ... --tenant-id ... --workspace-id ...

# daily — from the target repo (like codex)
cd /path/to/repo
agent-os --database ~/mandate.sqlite3 --workspace ~/mandate-ws \
  --repo . "fix the failing test"
agent-os --database ~/mandate.sqlite3 --workspace ~/mandate-ws --offline
agent-os ... --no-tools   # chat-only fallback
```

## Non-claims

- Not Codex/Claude Code parity
- Not Autonomy(S,E,O,V,T)
- Not HCW reduction evidence
- Not release

## Verification

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
  python3 -m pytest tests/product/test_mandate_repl.py tests/product/test_mandate_terminal.py tests/product/test_mandate_terminal_tools.py -q
```


## V1 additions (2026-07-24)

1. **Allowlisted shell + search**
   - `workspace.search` — regex content search under `--repo`
   - `workspace.shell` — argv allowlist (`git/ls/rg/python/...`), no metacharacters; interactive approval required
2. **Zero-config attach**
   - Bare `agent-os` auto bootstraps+attaches `mandate:local-terminal` when attach missing (`--no-zero-config` to require prior attach)
3. **Continuation**
   - `--continue` auto-feeds CONTINUE prompts until `DONE`/`BLOCKED` or `--max-continuation-cycles`
   - `/continue` `/stop` in REPL

```bash
cd /path/to/repo
agent-os --continue "fix failing tests and summarize"
```
