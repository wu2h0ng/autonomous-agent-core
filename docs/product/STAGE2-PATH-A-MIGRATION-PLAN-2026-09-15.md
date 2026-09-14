# Stage 2 — 路径 A 收敛到 cli-ts 并删除（方案）

- **日期**：2026-09-15
- **状态**：`DRAFT / RECOMMEND_ONLY / AWAITING_FOUNDER_SCOPE`（founder option c 的 Stage 2）
- **前置**：Stage 1 已合并 PR #35（`d371af00`）：删除 textual 路径 B、移除 Python `agent`/`agent-os` 命令、入口统一为 npm `agentos`/`agent-os`/`agent-os-ts`，daemon 为 `agent-os-runtime`。
- **Track**：Product（跨 surface 协议 + 测试迁移）
- **目标**：让 `agentos` 成为**唯一入口**（交互 + headless + 全部产品/管理子命令），随后删除 Path A（`packages/os_core/src/agent_os_core/agent_cli.py` 与 `apps/cli/__main__.py`）。

## 1. Path A 现状盘点

`apps/cli/__main__.py`（现状）子命令与其实现方式：

| 子命令 | 处理器 | 现在的实现方式 | surface 协议是否已暴露 | 迁移方式 | 工作量 | 风险 |
|---|---|---|---|---|---|---|
| `agent` / `chat`（prompt、`-p`、`--offline`、`--no-stream`） | `_agent`/`_chat` → `run_agent_cli` | **in-process** `AgentOSApplication` | ✅ 已有（begin-turn/stream/approval/mode + `agentos -p`） | 迁移相关断言到 cli-ts headless 测试；删除 Python 实现 | M | 低（行为已在 cli-ts 验证） |
| `run`（责任工作，`--max-cycles`、resume） | `_agent_work_run` | in-process | ❌ 未暴露 | 扩展 surface 协议（work run 命令/事件）→ cli-ts 子命令 | L | 中（多轮/补偿与审批绑定） |
| `agent-status/-answer/-correct/-resume` | `_agent_work_*` | in-process | 部分（status/resume/approval 有） | 复用/补齐 surface → cli-ts | M | 中 |
| `agent-admit-selfdev` | `_agent_work_admit_selfdev` | in-process | ❌ | 扩展 surface（SELFDEV 准入）→ cli-ts | L | 高（安全面，C7/permit 不变量） |
| `mandate-bootstrap/-attach/-status` | `_mandate_*` | in-process | ❌ | 扩展 surface（Mandate 命令）→ cli-ts | L | 中高 |
| `session-show/-pause/-resume/-correct` | `_session_command` | **HTTP** `SurfaceClient` | ✅（除 show） | 补齐 show → cli-ts `/resume`+命令 | S | 低 |
| `task-create/-show/-run/-commit/-compensate/-recovery/-replan/-signal` | `_task_*` | in-process | ❌ | 扩展 surface（Task 生命周期）→ cli-ts | L | 中高（补偿/恢复语义） |
| `workflow-validate` | `_workflow_*` | in-process | ❌ | 扩展 surface 或并入 CLI 校验 | M | 中 |
| `daemon-start/-status/-stop` | `_daemon_*` | subprocess/HTTP | n/a | 已由 cli-ts `agentos daemon *` 覆盖 ✅ | — | 已完成 |
| `correction-resume` | `_correction_*` | in-process | 部分 | 对齐 surface correction → cli-ts | S/M | 低 |

**共享但必须保留**（非 A 本体）：`apps/cli/surface_client.py`、`apps/cli/turn_commit.py` — 被 10+ 测试与 `product_evals/terminal_agent_eval/product_executor.py` 直接使用；删除 A 时**不动**它们（或仅在其调用方迁移后处理）。

**依赖 A 的测试/eval**（迁移对象）：`test_agent_cli_v0/_p1/_stream/_review_debt`、`test_cli_surface`、`test_responsibility_controller`、`test_public_long_horizon_negative_paths`、`test_selfdev_admission`、`tests/product_eval/test_spine_protocol`（文件清单）。

## 2. 分阶段（每阶段一个可独立评审合并的 PR）

```text
2a  headless chat 收敛：agentos -p 成为唯一 headless；迁移 agent_cli_* 测试到 cli-ts；A 的 _agent/_chat 标记 deprecated
2b  session 面：补齐 session-show；cli-ts 会话命令对齐；迁移 _session_command 测试
2c  work/run + agent-status/answer/correct/resume：扩展 surface 协议（work run 事件/审批绑定）→ cli-ts
2d  mandate 面：surface 协议加 Mandate 命令 → cli-ts（founder gate：权限/审计）
2e  task/workflow/compensation/selfdev-admission：surface 协议 + cli-ts；SELFDEV 准入单独安全评审
2f  删除 A：删 agent_cli.py + apps/cli/__main__.py；移除 agent_os_core 的 run_agent_cli 导出；迁移/删除剩余测试；更新 CURRENT_STATE/文档
```

每阶段**退出条件**：
- 对应 surface 路由有 typed 契约 + 无效/越权失败路径 + 会被绕过的测试；
- cli-ts 覆盖该命令的交互与 headless；
- 相关 Python 测试已迁移到 cli-ts 或明确删除（删除需 founder 同意）；
- 不变量保持：permit/approval/C7/action_digest 不变；管理面同样经权限脊；
- 独立 exact-diff 评审 + CI 绿。

## 3. 关键设计约束

1. **管理面必须走权限脊**：mandate/task/selfdev 等若经 surface 暴露，需与现有 PolicyKernel→permit→approval 一致，不能成为旁路。
2. **不复制状态**：cli-ts 仅走 surface 协议；durable 真值仍在 Task 事件流。
3. **surface 协议版本**：新增子命令需协议版本策略（v1.1 扩展 vs v1.2），与 E1/E2/E3 冻结语义兼容。
4. **凭据/密钥**：沿用现有 provider/credential 规则（key 不落盘、keychain）。
5. **风险最高的两个面**：`agent-admit-selfdev`（准入）与 `task-compensate`（补偿）——建议各配独立 GC + 安全评审。

## 4. 非目标 / 风险

- 不做"在 cli-ts 重新实现一套 Python 逻辑"；只通过 surface 协议调用内核。
- 删除任何**用户可见产品面**属 founder-reserved（可选项：某些管理面可明确裁撤而非移植）。
- 2d/2e 的工作量大（surface 协议扩展 + 测试迁移），不应与 2a 混在一个 PR。

## 5. 需 founder 决策

1. 是否**全部移植**（本方案 2a–2f），还是**裁撤**部分管理面（mandate/task/workflow/selfdev）以加速删除 A？
2. surface 协议扩展采用**向后兼容 v1.1 追加**还是**升版 v1.2**？
3. 测试迁移策略：Python 断言**逐条重写为 cli-ts 测试**，还是删除 Python 测试并由 cli-ts 新测覆盖（后者需 founder 认可覆盖面变化）？

## 6. 建议起点

先做 **2a**（headless chat），它无产品面裁撤、无 surface 扩展、风险最低，且能立刻让"唯一 headless 入口 = `agentos -p`"成立；2b/2c 紧随；2d/2e 各自独立门。

## 7. Stage 2a — chat/headless 迁移映射（2026-09-15）

**结论**：canonical headless = `agentos -p <prompt> --output-format json|text|stream-json`。cli-ts 已有**冻结 exit-code 表**测试（`apps/cli-ts/test/headless.test.ts`：0 成功 / 1 传输错误 / 2 approval 必需 / 3 未完成），覆盖 json/stream-json/text 三种输出与 approval fail-closed。故 2a 不新增行为，只做**映射登记 + 弃用标记**。

| Python 测试（用例） | 处置 | 承接者 |
|---|---|---|
| `test_agent_cli_stream`（chunked deltas、no-tool delta） | 迁移 | cli-ts `headless.test.ts`（stream-json）+ controller 流式测试 |
| `test_agent_cli_v0`：REPL 流式 / `--no-stream` 一次打印 / REPL `/status` | 迁移 | cli-ts controller（流式、`/status`）与 headless；REPL 专属断言随 2f 删除 |
| `test_agent_cli_v0`：session save/resume、resume 拒绝（db/mandate/workspace/terminal） | 递延 | **2b/2c**（session 面） |
| `test_agent_cli_v0`：`zero_config_mandate`/`ensure_local` | 递延 | **2d**（mandate 面） |
| `test_agent_cli_p1`：trusted profile / workspace tools / unlisted shell / AGENTS.md 注入 | 非 A 专属（内核 / M1 / M2 测试已覆盖） | 2f 连同 Python 测试删除，覆盖由内核测试保持 |
| `test_agent_cli_review_debt`：`run_agent_cli` 调用形状与错误路径 | A 专属 | 2f 删除 |
| exit code / json / approval / transport | 已覆盖 | cli-ts `headless.test.ts`（冻结表） |

**2a 退出条件（已满足）**：canonical headless 文档化；`agent_cli.py` 与 `__main__._agent/_chat` 标注 DEPRECATED 指向 `agentos -p`；迁移映射登记；cli-ts headless 测试绿；无行为变更。

## 8. Stage 2b — session 面（2026-09-15，已完成）

- cli-ts 新增 headless：`agent-os session show|pause|resume|correct <session-id> [reason]`（复用既有 `client.getSession` / `client.correct`；pause/resume/correction 走既有 surface POST）。`session show` 打印 `{session_id,status,event_sequence,message_count}`，与 Python `session-show` 对齐。
- 交互侧已具备 `/resume`、`/status`、esc correction；本次仅补齐命令面。
- 测试：`apps/cli-ts/test/session-command.test.ts`（stub daemon + descriptor，3 passed）。
- 覆盖映射：`test_cli_surface` 的 session-* 用例由 cli-ts `session-command` 承接；2f 删除对应 Python 用例。
- 退出条件：命令 + 测试 + 无协议变更（复用 v1.1）；CI 绿。
