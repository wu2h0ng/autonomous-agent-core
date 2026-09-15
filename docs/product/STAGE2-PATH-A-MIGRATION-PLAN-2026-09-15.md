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

**2b 行为差异登记（非逐位等价，F3）**：cli-ts 的 `session correct` 的 reason 可省略（缺省 `operator correction`），pause/resume 额外接受自定义 reason；Python `session-correct` 的 reason 为 argparse 必填，`session-pause/-resume` 只接受 session-id。属有意扩展；2f 删除 Python 时按此登记，不视为 parity 缺口。

## 9. Stage 2c — work/run 与 agent-status/-answer/-correct/-resume（2026-09-15，处置：API-only）

**Founder 决策（选项 B）**：治理/管理操作**不进终端**；终端只保留 **agent 循环（交互 + headless）** 与 **配置/会话命令**（对齐主流 Claude Code / Codex / opencode / Gemini CLI）。因此 2c **不新增 cli-ts 命令**，surface 协议 **v1.1 不变**。

**实现位置**：这些操作在内核 `agent_os_core/responsibility_surface.py`（`run_responsibility_work` / `responsibility_status_payload` / `answer_responsibility_help` / `correct_responsibility_work`）；`apps/cli/__main__.py` 只是 in-process 包装，删除 A 不会移除能力。

**既有 HTTP 管理覆盖（apps/api_server/server.py）**：
| 操作 | HTTP 端点 | 状态 |
|---|---|---|
| status（责任视图） | `GET /v1/mandates/{id}/responsibility-view` | ✅ |
| answer（答复 help request） | `GET/POST /v1/mandates/{id}/outcome-portfolio/help-requests[:respond]` | ✅ |
| run（受监督工作循环，`--max-cycles`） | — | ❌ 无 HTTP 端点 |
| correct（operator 纠正） | — | ❌ 无 HTTP 端点 |

**结论 / pre-2f 门**：2f 删除 A 前，`run` / `correct` 必须在 HTTP 管理 API 上有端点（或明确 **park 为 daemon-only**），否则它们在产品上只剩进程内可达。→ **需 founder 决策**：补管理端点 vs park。

**测试迁移**：A 的 CLI 测试（`agent-run/-status/-answer/-correct`）覆盖改由 **HTTP API 层测试**保持（非 cli-ts，因终端不实现管理面）。

## 10. Stage 2d/2e — mandate / task / workflow / selfdev（2026-09-15，处置：API-only）

**处置同 2c（founder 选项 B）**：这些治理/管理命令**不进终端**；终端只保留 agent 循环 + 配置/会话。

**既有 HTTP 管理覆盖（在 `apps/api_server/server.py` 核实）**：
`/v1/tasks`（创建/列表/详情）、`tasks/{id}:commit`、`/signals`、`/replan`、`/compensate`、`tasks/{id}/runs/{id}/trajectory`、`configuration-snapshots`、`domain-candidates` evaluations/promotions、`/v1/mandates`（列表）、mandate `task-links`、`outcome-portfolio`（commitments/settlements）、`responsibility-view`、`help-requests` + `:respond`、`/v1/workflows/validate`、`/v1/workspace`、`/v1/provider`、data-agent `query:run`、`environment-bindings:authorize`。

**尚未见 HTTP 端点（pre-2f 需逐条核对后 补端点 / park / 裁撤）**：
- `mandate-bootstrap`、`mandate-attach`
- `work run`（受监督工作循环）、`work correct`（2c 已记）
- `task-run`
- `agent-admit-selfdev`（SELFDEV 准入，安全面）

**结论**：管理面 HTTP 覆盖已相当完整；删除 A（2f）前，需对上述 6 项做一个**合并决策**（补 HTTP 管理端点 vs park 为 daemon-only vs 明确裁撤）。任一裁撤属 founder-reserved。

**测试迁移**：A 的 mandate/task/workflow/selfdev CLI 测试覆盖改由 **HTTP API 层测试**保持（终端不实现该面）。

## 11. 2f-prep 进展与"权威模型"门（2026-09-15）

| 操作 | 状态 |
|---|---|
| mandate-bootstrap / mandate-attach | ✅ 已加 admin HTTP 端点（PR #40，`e5391751`） |
| task-run | ✅ 既有 `POST /v1/tasks/{id}/run` 已覆盖（无需新增） |
| work run / work correct | ⛔ 未完成——不是"加路由"问题 |
| agent-admit-selfdev | ⛔ 未完成——同上，且属安全面 |

**根因**：`work run` / `work correct` / `agent-admit-selfdev` 都经 `_work_applications()` 构造 **execution_app + authority_app**：它依赖 **本地 mandate attach session** 与 **`AGENT_OS_AUTHORITY_BEARER`** 解析 execution/authority principal 角色（`resolve_agent_work_authority`）。也就是说这是**本地终端权威模型**，不是普通管理 API 调用。

**删除 A（2f）前需 founder 决策"权威 bearer 如何在网络上定义"**：
- **(a)** 在 admin API 上定义并暴露该权威模型（bearer/角色/审计/越权失败路径）→ 必配安全评审；
- **(b)** park：这三项保持**本地权威/进程内**，不暴露 HTTP；
- **(c)** 为 work/selfdev 保留一个**精简本地权威 CLI**（即不删除 A 的该子集），只删除已覆盖的部分。

在 (a)/(b)/(c) 决定前，2f 无法安全删除 A 的这部分；mandate/task 等已覆盖部分可先行。

## 12. Stage 2f-c 执行边界（2026-09-15，founder 选项 c）

**原则**：删除 A 中"已被 cli-ts / HTTP 管理 API 覆盖"的部分；**保留一个精简的本地权威 CLI** 承载 `work run/correct` + `agent-admit-selfdev`（这些依赖本地 attach session + `AGENT_OS_AUTHORITY_BEARER`）。避免把本地权威模型搬上网络。

### 12.1 keep / delete 边界（`apps/cli/__main__.py`）

| 命令 | 处置 | 承接 |
|---|---|---|
| `agent` / `chat`（+ `run_agent_cli` / `agent_cli.py`） | **删除** | `agentos -p`（headless canonical） |
| `session-show/-pause/-resume/-correct` | **删除** | `agentos session ...`（2b） |
| `mandate-bootstrap/-attach/-status` | **删除** | admin API（PR #40；status 已有 responsibility-view） |
| `task-create/-show/-run/-commit/-compensate/-recovery/-replan/-signal` | **删除** | admin API（`/v1/tasks*`） |
| `workflow-validate` | **删除** | `/v1/workflows/validate` |
| `daemon-start/-status/-stop` | **删除** | `agentos daemon ...` |
| `agent-run/-resume/-status/-answer/-correct` | **保留** | 本地权威 CLI（本项） |
| `agent-admit-selfdev` | **保留** | 本地权威 CLI（安全面，另配评审） |
| `correction-resume` | 待定 | 视其依赖（surface correction 已被 cli-ts esc/correct 覆盖则删） |

**共享保留**：`load_attach_session` / `_work_applications` / `resolve_agent_work_authority`（仅本地权威 CLI 用）。

### 12.2 新入口
- 精简本地权威 CLI 作为**独立 console script**：`agent-os-work`（`apps/cli/__main__.py:main` 精简后）。
- 主入口仍是 npm `agentos`/`agent-os`（agent 循环 + 配置/会话）；`agent-os-runtime` 为 daemon。
- `pyproject [project.scripts]` 仅保留 `agent-os-runtime` + 新增 `agent-os-work`。

### 12.3 测试处置
- 删除：`test_agent_cli_v0/_p1/_stream/_review_debt`（chat/headless，覆盖由 cli-ts headless + 内核测试承接）；`test_cli_surface` 中 chat/session 用例；mandate/task CLI 用例（改由 admin API 测试承接，`test_mandate_bootstrap_attach_api` 等）。
- 保留并改指 `agent-os-work`：work/selfdev 的 CLI 测试（`test_responsibility_controller`、`test_selfdev_admission`、`test_public_long_horizon_negative_paths` 中对应部分）。
- `test_product_entrypoint`：断言 `agent-os-runtime` + `agent-os-work`。

### 12.4 执行切片
```text
2f1  删除 chat/headless：agent/chat 命令 + agent_cli.py + run_agent_cli 导出 + 其测试
2f2  删除 session/mandate/task/workflow/daemon 命令 + 对应测试（保留 admin API 覆盖）
2f3  精简 __main__ 为本地权威 CLI，新增 console script agent-os-work，更新 entrypoint 测试
2f4  最终删除扫描（引用、文档、CURRENT_STATE），确认 A(chat 部分) 已移除
```
每片独立评审 + CI 绿；work/selfdev 保留面不得削弱 C7/permit/审批。
