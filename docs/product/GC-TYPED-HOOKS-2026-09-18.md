# GC-B — Typed Hooks（类型化扩展接缝，2026-09-18）

- **状态**：`DESIGN_ONLY / DOCS_ONLY / AWAITING_CTO_GATE / NO_IMPLEMENTATION_AUTHORITY`
- **范围**：终端线唯一产品路径 `origin/main`（`03ac66b5`，PR #69 已合并）之上的**可扩展性**一项（founder 2026-09-18 权重 ~10%），即"typed hooks"：在类型化接缝上给操作者/仓库提供扩展点。
- **基线**：`docs/` 与 `packages/` 均以 `.worktrees/os-sandbox` HEAD（`03ac66b5`）为准；本文件所引行号即此 HEAD。
- **结论（先给判断）**：**可以做，且第一阶段应当只做"配置 + 只读 observer"**。理由是当前不存在任何 typed hook（`docs/CURRENT_STATE.yaml:52`，同日原文 "there are no subagents in the surface and no typed hooks"），所以接缝契约可以一次定对、无历史兼容负担；而只要 hook 的返回值**不是权威对象**、hook **不在 `[reserve, seal]` 效果窗内执行**，接缝在结构上就够不到权威——这两条是可以用测试证伪的，而不是承诺。
- **本文件不授权任何运行时代码 / contracts / 协议 / 配置格式改动。** 撰写 ≠ 实现；本文件与同批次的 subagent / MCP 文档一样，实现仍待 CTO gate。

## 0. 容器与编号（为什么不是 ADR）

- **容器选择**：放 `docs/product/` 的 GC，形制对齐同批次姊妹文档 `GC-P3-MULTIAGENT-TASK-TREE-2026-09-16.md`（状态字段、Goal Card / Context Pack / Architecture Brief / gates / 决策项 / 声明分级同一套）。理由：本文件是**产品能力范围卡**（做什么、不做什么、过什么门），不是已定架构决议；仓库中 `Accepted` 的 ADR 记录已决事项，未决的边界提案以 GC + `AWAITING_CTO_GATE` 表述更诚实。
- **编号**：GC 家族按 `GC-<主题>-<日期>` 命名，不占四位序号（`docs/product/` 现有 GC 均如此）。若 CTO 决定把本节接缝**升格为边界 ADR**，可取 **ADR-0061**：`docs/adr/` 已知最高号为 **ADR-0059**（`origin/main`：ADR-0055→0057→0058→0059，**ADR-0056 是空号，未被占用**），而 **0060 已被一个未合并分支上的草稿占用**——`ADR-DRAFT-0060-donor-repository-retirement-2026-09-15.md`，只存在于 `codex/spine1-donor-extraction-20260915`（提交 `901c2108`），不在 `origin/main`。选 0061 可同时避开 main 的当前最高号与那个已存在的草稿号。**本文件不占用 0061**，仅记录该预约。

## 1. Goal Card

- **目标**：给操作者（和未来的仓库级配置）一个**类型化**的扩展点：在 turn 开始/结束、工具调用前/后、审批请求、provider 调用前/后这些接缝上观察运行，并（仅第二阶段、仅收紧方向）干预；hook 的载荷与返回值都是 typed contract，不是自由文本、不是可执行字符串。
- **非目标**：
  - 不做插件市场、不做 MCP 工具执行（MCP 在 `docs/CURRENT_STATE.yaml:52` 记为 **PARK**，只有非授权信封解析器）、不做 skills 包、不做 subagent（另立 GC）。
  - 不改 `TURN_IN_PROGRESS`、不改 permit/approval/C7、不改 allowlist 与 permission mode 矩阵、不改 receipt/evidence 语义。
  - 不引入"hook 可以放行/自动批准"的任何形式。
  - 不追求超越主流、不追求范式级差异化；hook 不是 parity 证据。
- **证据类别**：**产品能力**（Product Track）。不得由研究证据或流程治理证据回填；hook 机制本身不得被引用为 market parity 或自主性证据。
- **退出条件**：见 §10 gates（每条独立可测）；每项 capability 需公共入口 + typed contract + 失败路径 + 集成点 + trace/evidence + 权限 + rollback + 分级声明。

## 2. Context Pack（当前事实，已核对）

| 事实 | 位置 |
|---|---|
| 唯一生产执行边界是 `CapabilityBroker.invoke(action, permit, attempt, *, execution_claim)`；顺序为 digest 校验 → replay → claim/fence → permit 过期 → correction halted/epoch → args → collaboration preflight → **必须**有 durable outcome store → connector preflight → reserve → `guard_unchanged` → `execute` → seal | `packages/os_core/src/agent_os_core/capability.py:132-227` |
| 效果窗 = `with self.correction.guard_unchanged(...)` 内的一次 `connector.execute`；窗内异常一律转为 typed `CapabilityEffectUnknown`，绝不 auto-retry | `capability.py:183-213` |
| 生产调用的权威脊：`ActionPipeline.execute` → reconcile → external-exact approval assert → `PolicyKernel.decide` → `POLICY_DECIDED` event → verdict → `permit` → fence 校验 → `broker.invoke` | `packages/os_core/src/agent_os_core/action_pipeline.py:230-349` |
| `PolicyKernel` 是确定性权威门，docstring 原文 "Deterministic authority gate; provider/model output is never consulted"；`POLICY_KERNEL_V1_SPEC` 含 `model_final_authority: False` | `packages/os_core/src/agent_os_core/governance.py:30-46, 322-341` |
| `permit` 只在 `PolicyKernel.permit` 内铸造（要求 verdict=ALLOW + epoch 未变），有效期 5 分钟 | `governance.py:479-499` |
| 运行时只拿 `CorrectionReadPort`（snapshot/halted/guard_unchanged）；`CorrectionAdminPort`（correct/resume）**不在该 port 上** | `governance.py:49-76, 99-107` |
| 已存在的"外部扩展点"先例 `ExternalPolicyBackend`：OPA/Cedar 形，**明确 without policy-root authority**；异常 → `EXTERNAL_POLICY_UNAVAILABLE` DENY，形状错 → `EXTERNAL_POLICY_MALFORMED` DENY（fail-closed） | `governance.py:90-96, 442-477` |
| 已存在的"纯收紧"先例 `apply_deny_rules`：只能把任意裁决降级为 `DENY_BY_RULE`，**没有能 ALLOW 的规则**，且不重写既有拒绝的 provenance | `packages/os_core/src/agent_os_core/permission_gate.py:86-116` |
| 已存在的"in-code hook"先例：provider 传输钩子 `_request_body` / `_transport_headers` / `_parse_completion` / `_refusal_text`，是**子类覆写**的代码 seam（不是操作者安装面），契约由测试钉住 | `packages/os_core/src/agent_os_core/provider.py:489-510`；测试 `tests/product/test_provider_failure_visibility.py` |
| 操作者级"opt-in 日志"先例：`AGENT_OS_PROVIDER_LOG` 未被设置就**什么都不写**；写失败被吞掉，"never let logging break a turn" | `provider.py:192-220` |
| 交互权威桥 `ConfirmationGateway.confirm(action, preview)`：docstring 明确 "Implementations must be human-driven UI"；延迟实现 `DeferredApprovalGateway` 抛 `ApprovalRequired` | `packages/os_core/src/agent_os_core/agent_loop.py:110-126` |
| 审批路径：DENY（out-of-allowlist / by-rule）在 gate 阶段就地终止并**持久化** `POLICY_VERDICT_RECORDED`；`REQUIRE_CONFIRM` 走人工 gateway，tier≥3 才产出 `ApprovalDecision` | `agent_loop.py:1450-1522`，`_build_approval` `:1660-1673` |
| 自动放行**绝不**记成 `ApprovalDecision`（记 `POLICY_VERDICT_RECORDED`，basis=permission_mode + mode_event_id） | `agent_loop.py:1511-1522, 1613-1641`；M2 stop condition 同义 |
| 会话审批的对外路径是 surface 命令 `surface_decide_approval`（带 session lock + idempotency），非内核内联 | `packages/os_core/src/agent_os_core/surface_runtime.py:96, 282-289, 430-438` |
| turn 边界已是 durable 事件：`SESSION_TURN_STARTED` / `SESSION_TURN_COMPLETED` | `agent_loop.py:312-321, 462-499` |
| 可用的审计事件词汇（节选）：`ACTION_PROPOSED` / `POLICY_DECIDED` / `POLICY_VERDICT_RECORDED` / `APPROVAL_REQUESTED` / `APPROVAL_RECORDED` / `ACTION_RECEIPT_RECORDED` / `NODE_COMPLETED` / `NODE_FAILED` / `CORRECTION_WRITTEN` | `packages/contracts/src/agent_os_contracts/runtime.py:51-90` |
| 操作者配置的既有存放点：`~/.agent-os/provider.json`（0600，仓外，**不写 key**）、`~/.agent-os/runtime.json`、`~/.agent-os/cli-ts-state.json` | `apps/api_server/provider_settings.py:4,23`；`apps/cli-ts/src/descriptor.ts:11`；`apps/cli-ts/src/state.ts:25` |
| 操作者拒授权限规则是**durable 存储**（SQLite），在 composition 时载入为 `deny_rules` 传入 AgentLoop | `apps/api_server/app.py:382, 2055, 2180`；`permission_rules.py:81-138` |
| 任务配置快照已绑定 policy/provider/grants/expected-outcome 的 digest，不含 hook 相关摘要 | `packages/contracts/src/agent_os_contracts/task_configuration.py:147-173` |
| 今天**没有任何 typed hooks**；MCP PARK；无 subagent | `docs/CURRENT_STATE.yaml:52` |
| Core/domain-pack 结构边界已有测试守护（Core 不得含 workspace 具体实现） | `tests/product/test_capability_adapter_boundary.py` |

## 3. Hook 分类与精确接缝

命名建议 `hooks-v1`。载荷一律是**冻结的快照**（只读 dataclass/model 副本），不是内核可变对象引用。

| Hook | 触发点（行号） | 能读（快照） | 能返回 | 返回值如何被消费 | 为什么够不到权威 |
|---|---|---|---|---|---|
| `turn.started` | `run_turn` 写 `SESSION_TURN_STARTED` 之后（`agent_loop.py:312-321`） | `{task_id, session_id, turn_id, run_id, principal_id, tenant_id, workspace_id, permission_mode, user_text_len}`（**不含** credential，建议不含完整 user_text） | `None`（P1） | 忽略；只落审计 | 事件已持久化，返回值不进控制流 |
| `turn.ended` | `_complete_turn` 写 `SESSION_TURN_COMPLETED` 之后（`agent_loop.py:490-499`） | 上表 + `stop_reason` / `steps` / `total_tokens` | `None`（P1） | 忽略；只落审计 | 同上；turn 已完成，无法改写 stop_reason |
| `tool.pre` | `_execute_proposal` 内、`build_action` **之前**（`agent_loop.py:1421-1434`） | `{turn_id, step, index, capability_id, arguments_json 的**规范化副本**, risk_tier, allowlist 判定前的 gate 值}` | `None`（P1）；P2 仅 `HookDeny(reason_code, hook_id)` | P1 忽略。P2 时 `HookDeny` 等价于 `apply_deny_rules` 的降级输入（`permission_gate.py:86-116`）：只能把裁决变 DENY，**不能**变 ALLOW，也不能改 `basis` 之外的既有拒绝 provenance | 它位于 allowlist / risk tier / gate / deny-rule / policy / permit / broker 全链**上游且只收紧**；action digest 在其后由 `build_action` 计算，hook 改不动 digest 与 permit |
| `tool.post` | `_execute_proposal` 收到 sealed `CapabilityResult` 之后（`agent_loop.py:1580-1587`） | `{capability_id, action_digest, receipt_id, status, error_code, detail_ref, output 摘要}` | `None`（P1） | 忽略；只落审计 | receipt 已由 `outcomes.seal`（`capability.py:227`）封定，hook 没有 outcome store 句柄 |
| `approval.requested` | `ConfirmationGateway.confirm(...)` 调用点（`agent_loop.py:1495-1506`）与 surface pending 审批投影 | `{action_digest, capability_id, risk_tier, preview 文本, gate.basis}` | `None`（P1）；P2 仅 `HookDeny` | P1 忽略、**审批必须仍然由人 resolve**。P2 的 `HookDeny` 只能记为 `POLICY_VERDICT_RECORDED(basis=hook_rule, hook_id)`，**绝不可**写成 `ApprovalDecision`（后者断言"某个 actor 决定过"，与 `agent_loop.py:1511-1522` 的既有规则同源） | 它拿不到 gateway 的替换权（gateway 由 composition 注入，hook 只收到一次调用通知）；P1 返回值类型是 `None`，物理上不能"批准" |
| `provider.pre` | `_call_provider` 内、`complete_streaming` 之前（`agent_loop.py:1276-1290`） | `{provider_profile_id, model, request_id, message_count, allowed_capability_ids, max_tokens 等请求参数摘要}` | `None`（P1） | 忽略；只落审计 | 请求体与响应摘要参与 `build_provider_execution_receipt` 的绑定（`:1325-1346`）；**hook 不得改写请求体**——改写会破坏 digest 绑定，属禁止项 |
| `provider.post` | provider 响应/失败已落 `PROVIDER_RESPONDED` 之后（`agent_loop.py:1341-1347`） | `{request_id, code, retryable, latency_ms, usage, invocation_binding_digest}` | `None`（P1） | 忽略；只落审计 | 重试与失败分类已决定（`:1286-1299`），hook 不能制造/抑制 retry |

**P1 的返回值一律是 `None`**，这条是刻意的：它让"hook 无法改变权威"成为**类型层面的平凡事实**，而不是需要信任运行时的承诺。

## 4. 接线顺序（钉死；拒绝任何"排在 X 之前/之后都行"的模糊）

一次 tier-3 工具调用的完整顺序（`→` 表示数据流，方括号是既有代码）：

```text
[provider 响应 → tool proposals]                       agent_loop.py:880-930
→ [allowlist 成员判定 CHAT_CAPABILITY_IDS]              agent_loop.py:941
→ HOOK tool.pre（只读，P1）                             ← 新增
→ [risk tier → evaluate_permission_gate]                agent_loop.py:1430,1450
→ [apply_deny_rules（纯收紧，只入不出）]                 permission_gate.py:86
→ 若 DENY：记录 POLICY_VERDICT_RECORDED 并终止           agent_loop.py:1464-1494
→ [ConfirmationGateway.confirm（人）]                   agent_loop.py:1495-1506
→ HOOK approval.requested（只读，不得代替人作答）        ← 新增
→ [build_action → digest]                               agent_loop.py:1435-1448
→ [PolicyKernel.decide → POLICY_DECIDED]                action_pipeline.py:267-281
→ [PolicyKernel.permit（唯一铸 permit 处）]              action_pipeline.py:304；governance.py:479
→ [lease fence / execution fence / claim fence 校验]     action_pipeline.py:321-337
→ [broker.invoke：replay → claim → permit 过期 → correction halted/epoch
   → args → collaboration preflight → outcomes 必需 → connector preflight
   → reserve ┐                                          capability.py:140-181
              │  ┌── 效果窗（hook 不得进入）────────────┐
              └→ │ guard_unchanged → connector.execute  │   capability.py:183-193
                 │ → 异常 → typed UNKNOWN（不 seal）     │   capability.py:195-213
                 └→ seal + receipt ─────────────────────┘   capability.py:214-227
→ HOOK tool.post（只读，收到 sealed receipt 摘要）        ← 新增
→ [turn 结束 / SESSION_TURN_COMPLETED]                   agent_loop.py:490-499
→ HOOK turn.ended（只读）                                ← 新增
```

**C7 与 hook 的相对位置（显式）**：hook 在**所有** `CorrectionAuthority` 判定之外与之上；hook 只拿 `CorrectionReadPort`（`governance.py:49-68`），拿不到 `CorrectionAdminPort`；hook 不得执行 `correct`/`resume`，不得落在 `guard_unchanged` 窗口内；hook 运行期间发生 correction 时，`broker.invoke` 的 halted/epoch 检查（`capability.py:154-163`）与效果窗守卫（`:183-192`）仍然生效——即 effect 要么不执行，要么成为 typed UNKNOWN，**不会**因为 hook 而出现"用过期 epoch 执行"。

## 5. 信任模型

**hook 就是代码，以操作者权限运行。** 因此：

1. **安装来源（P1 只允许一个）**：`~/.agent-os/hooks.json`（0600，仓外），形制与权限沿用 `provider_settings.py:23` 的既有先例；模块经 `module_path` + 入口名引入。
2. **明确不接受的来源**：**仓库/工作区内**的任何目录（例如 `<workspace>/.agent-os/hooks/` 或 `AGENTS.md` 里声明的命令）。理由是可证伪的：workspace 内容可被 agent 通过 `workspace.edit`/`apply_patch` 写入，若该内容能选择要执行的 hook，就等价于**把模型输出变成了被执行的代码**——这正是 §6 禁止项，且与仓库铁律"模型/插件/子代理只能通过有作用域的 typed capability 行动"直接冲突（`AGENTS.md` §3.2）。
3. **摘要固定**：配置条目形状 `{hook_id, event, module_path, entry, sha256, schema_version, enabled, required, on_error}`；载入时校验 sha256，不符 → typed `HOOK_INTEGRITY_MISMATCH`，**该 hook 不载入**，并落审计。签名（谁签、本地 key 还是组织 key）**不在 P1**，见 §15 决策项。
4. **可否禁用**：`enabled: false` 与全局 `AGENT_OS_HOOKS_DISABLED=1` 两种；**hook 不得启用/禁用/改写自身的注册**（这是自改边界，参照 `ADR-0037` L4/L5 与 `AGENTS.md` §5 的当前边界），禁用动作本身落审计。
5. **失败语义（按 hook 类别定，不搞统一含糊）**：
   - **观察类**（P1 全部）：`on_error: skip_and_record` —— 抛异常/超时 → 记 `HOOK_FAILED`，turn 继续，行为与基线一致。
   - **门类**（P2 的 `tool.pre` / `approval.requested`）：`required: true` 时 **fail-closed**（失败按 DENY 处理并记录）；`required: false` 时跳过并记录，**但任何失败都绝不能被解释成 ALLOW/APPROVE**。
   - 超时上限必须有（P1 观察类建议 ≤ 200 ms 且**不得**计入 provider/broker 的窗口）。

## 6. 明确禁止（每条都给出执行机制，而不是"我们会保证"）

1. **不得授予权限**：hook 不能产出 `ActionPermit` / `CapabilityGrant` / `PolicyDecision` / `ApprovalDecision`；hook 结果 union 里没有这些类型（P1 更是 `None`）。机制=类型；违反会在序列化/校验处直接失败。
2. **不得抑制或伪造审批**：`approval.requested` 的 P1 返回值是 `None`，gateway 由 composition 注入且 hook 拿不到替换权；tier≥3 仍需 digest 绑定的真人 `ApprovalDecision`（`agent_loop.py:1495-1508`，`governance.py:382-385`）。hook 造成的拒绝只能记 `basis=hook_rule`，**不得**写成 `ApprovalDecision`。
3. **不得改写证据/审计/收据**：hook 上下文不含任何写句柄（无 event store、无 outcome repository、无 artifact 记录器）；receipt 由 `_build_receipt` + `seal` 产出，hook 只收到**已封定的摘要**。
4. **不得让模型输出变成被执行的代码或命令**：hook 注册只来自操作者配置；hook 不得接收"要执行的命令字符串"这一类字段；`tool.pre` 看到的是 capability_id + 规范化 params（typed），任何 `exec/eval/subprocess` 语义都不在 hook API 上，**也没有可用的执行器对象**。模型提出 `workspace.shell` 仍必须走 gate→policy→permit→broker（`agent_loop.py:941,1450-1463` 与 `capability.py:132`）。
5. **不得改写 provider 请求体/响应体**：请求与响应摘要参与 receipt 绑定（`agent_loop.py:1325-1346`），改写会破坏绑定。
6. **不得暂停/恢复/纠正**：hook 拿不到 `CorrectionAdminPort`（`governance.py:71-76`）。
7. **不得进入效果窗 `[reserve, seal]`**（`capability.py:183-227`）：hook 只能在窗外观察，且不得延长该窗口。
8. **不得把 hook 当作领域语义入口**：hook 载荷与行为不得引入 Metric / SQL / DataProduct 等 domain 语义（`AGENTS.md` §3.3）。

## 7. C6 / C7 与权威保持证明（需 CTO 接受后才谈实现）

- **C6（器官/扩展不进控制路径；出处：`docs/architecture/REF-ARCH-01-system-reference-architecture.md:34` "C6: organs out of control path"，另见 `ADR-0034:309`、`ADR-0041:50`）**：
  1. `PolicyKernel.decide` / `permit` 的签名与逻辑**不感知 hook**（不新增 hook 参数）；
  2. hook 全关 = 基线行为**逐字节一致**（G9）；
  3. hook 可**单独消融**：只开某一个 hook 与全开两种配置下，权威面断言集合相同（G2）。
- **C7（non-writable、non-bypassable 外部纠正权威；`AGENTS.md` §3.1、`ADR-0039:46`）**：
  1. hook 无写纠正面的路径（无 admin port）；
  2. hook 执行期间发生的 correction 仍然在 dispatch 处生效（epoch/halted 检查与守卫，`capability.py:154-163, 183-192`）；
  3. hook 不得成为"让已 halt 的 run 继续"的旁路：halt 后 provider 调用与 dispatch 均被拒（`agent_loop.py:866-868, 1272-1273`；`capability.py:154-155`）。
- **产品/流程边界**：hook 是产品运行时能力，不是研究证据、不是流程治理工具；hook 的"存在"不得计入自主性主张，也不得作为 market parity 证据。工程治理仓的 subagent scope 单调性等**流程规则不自动成为产品契约**（`GC-P3-MULTIAGENT-TASK-TREE-2026-09-16.md` §4 同义）。

## 8. 可观测性

- 每个 hook 事件产生一条 **durable** 记录：`{hook_id, event, config_digest, hook_sha256, outcome ∈ {OK, DENIED, FAILED, SKIPPED}, latency_ms, correlation_id}`。
- hook 引起的 DENY 必须走既有 `POLICY_VERDICT_RECORDED` 形状并带 `basis=hook_rule` + `hook_id`（`agent_loop.py:1613-1641`），使其与 `permission_mode` / `rule_id` 的 provenance 可区分、可审计。
- 大体积观察载荷（如 preview 文本）走 opt-in 的操作者日志（先例 `AGENT_OS_PROVIDER_LOG`，`provider.py:192-220`）：默认关闭、0600、append-only、**写失败不得让 turn 失败**、不含 credential/secret。
- hook 配置摘要建议进入 `TaskConfigurationSnapshot`（新增可选字段 `hooks_digest`，`task_configuration.py:147-173`），使"这次运行挂了哪些 hook"随任务快照被封定；**是否允许动这个契约是 CTO 决策项**（§15）。

## 9. 版本与兼容策略

- `schema_version: "hooks-v1"`；事件词汇在 v1 内**只增不改**；新增事件 = v1 的附加项，旧 hook 不受影响。
- **未知 event 键在载入时拒绝整份配置**（typed `HOOK_CONFIG_UNKNOWN_EVENT`），不静默忽略：忽略等于悄悄丢弃操作者以为生效的约束。代价是旧 daemon + 新配置会拒绝——这被选定为诚实失败（与 `provider.py:497-506` 对 `_refusal_text` 的处理同源：不留"静默走错形状"的余地）。
- 无 hook 配置 = 现状（opt-in，默认关闭）；`hooks.json` 缺失不报错、不创建文件。

## 10. Falsifiable gates（每条附"什么观测会证明它不成立"）

- **G1 返回值不含权威对象**：hook 结果 union 里不存在 `ActionPermit`/`PolicyDecision`/`ApprovalDecision`/`CapabilityGrant`/`CapabilityResult`/`ActionReceipt`。
  **证伪**：任一用例中 hook 返回构造的 permit/approval 后被接受，或该次调用产生 dispatch（`connector.execute` 计数 > 0）。
- **G2 不可授信**：对 out-of-allowlist 与 `DENY_BY_RULE` 两类，hook 全关与全开两种配置下 `execute()` 调用次数**都等于 0**。
  **证伪**：任一配置下 `execute()` > 0，或该拒绝的 provenance 被改写成非 `rule`/非 `out_of_allowlist`。
- **G3 审批不可抑制/伪造**：tier-3 动作在 hook 存在时仍产出 pending 审批且必须人工 resolve；hook 返回"批准"不产生任何 `ApprovalDecision`；hook 造成的拒绝记录中 **actor 不是人**（走 policy verdict 而非 approval）。
  **证伪**：出现非人 actor 的 APPROVE 记录，或 tier-3 在无人工 resolve 情况下执行。
- **G4 证据不可改写**：同一输入的 sealed receipt 与审计事件集合，在 hook 全关/全开下**逐字段相等**（新增的 hook 事件除外）。
  **证伪**：任一既有 receipt/event 字段取值不同，或 hook 通过任何签名/上下文取得写句柄（用无写句柄断言 + 结构测试）。
- **G5 无 模型→代码 路径**：一个"返回 shell 文本"的敌对 hook + 一个输出 `exec(...)` 文本的模型输出，都不能产生执行。
  **证伪**：任一用例产生子进程或一次 capability dispatch。
- **G6 位置正确**：hook 的 span 与 `[reserve, seal]` 事件**不重叠**；hook 执行期间写入 correction 后，该 action **不执行**（要么 DENY，要么 typed UNKNOWN）。
  **证伪**：hook span 覆盖 reserve..seal；或 correction 后仍发生 `connector.execute`。
- **G7 失败语义**：门类 hook 失败 → DENY 且记录 `HOOK_FAILED`；观察类 hook 失败 → turn 照常完成且 `stop_reason` 与基线一致。
  **证伪**：门类失败时仍 dispatch；或观察类失败导致 turn 失败/挂起/`stop_reason` 变化。
- **G8 完整性与来源**：改动 hook 模块一个字节 → 载入被拒（`HOOK_INTEGRITY_MISMATCH`）+ 审计；**workspace 内**放置的 `hooks.json`/hook 目录不生效。
  **证伪**：摘要不符仍载入；或 workspace 内配置生效（哪怕一次）。
- **G9 消融=基线**：`AGENT_OS_HOOKS_DISABLED=1` 或空配置时，行为与当前 HEAD 基线逐字节一致（同一会话脚本的事件序列与断言集合相同）。
  **证伪**：任一基线断言在 hooks off 时变红，或事件序列出现差异。
- **G10 无 secret 入参**：hook 载荷/审计记录中不出现 provider key 或其材料（对载荷做字符串扫描，沿用 `test_provider_failure_visibility.py` 的脱敏断言风格）。
  **证伪**：任一 hook 事件载荷中出现 key/凭证材料。
- **G11 可审计**：任何由 hook 造成的行为变化，在 durable 审计中都有一条对应记录（hook_id + event + outcome）。
  **证伪**：构造一次 hook 导致的行为差异，而审计中无对应记录。

## 11. 威胁模型（先列，评审时逐条给对策与测试）

| # | 威胁 | 现状依据 | 对策（本设计） |
|---|---|---|---|
| T1 | 通过 workspace 内容注入"可执行 hook" | workspace 对 agent 可写（`workspace.edit`/`apply_patch` 是 CHAT_CAPABILITY_IDS 成员） | P1 只允许 `~/.agent-os/hooks.json`；G8 |
| T2 | hook 被用作绕过 permit/epoch 的后门 | permit 只在 `governance.py:479` 铸造 | hook 结果 union 无 permit；G1/G6 |
| T3 | hook 静默"批准"以提升吞吐 | 存在 `AutoApproveGateway`（`agent_loop.py:129-140`），仅测试/`-p` 路径 | hook 不接 gateway；hook 拒绝记 policy verdict 而非 approval；G3 |
| T4 | hook 改写 evidence 掩盖失败 | receipt 由 `seal` 产出 | hook 无写句柄；G4 |
| T5 | 恶意/崩溃 hook 拖垮 turn | 观察类日志先例：写失败被吞（`provider.py:204-220`） | 超时 + `skip_and_record`；G7 |
| T6 | hook 配置漂移导致"这次运行到底挂了什么"不可复现 | 快照已绑定 policy/provider/grants digest | 建议 `hooks_digest` 进快照 + 每条事件带 `config_digest` |
| T7 | hook 成为第二权威面（长期与 `ExternalPolicyBackend` 冲突） | 已有 `ExternalPolicyBackend`（`governance.py:90-96`） | 明确分层：hook = 接缝观察 + 纯收紧；策略后端仍走既有 backend；两者不得互相委托 |

## 12. 负面地图与先例

- **已有先例（可直接复用其形态，不必新发明）**：
  - `ExternalPolicyBackend`：外部扩展参与但**无 policy-root authority**，出错 fail-closed（`governance.py:90-96, 442-477`）。
  - `apply_deny_rules`：**纯收紧**、不能 ALLOW、不重写 provenance（`permission_gate.py:86-116`）。
  - provider 传输钩子：**in-code**（子类）hook，契约由测试钉住（`provider.py:489-510`）。
  - `AGENT_OS_PROVIDER_LOG`：opt-in、默认无写入、失败不破坏 turn（`provider.py:192-220`）。
- **负面（明确不做/不承认）**：
  - 不做 hook 授权、hook 审批、hook 放行；
  - 不做仓库内/工作区内可执行 hook 来源；
  - 不做 MCP 工具执行（PARK）、不做 skills 包、不做 subagent（另立）；
  - 不做 `AGENTS.md` 自动加载（M2 非目标，`GC-TERMINAL-CODING-AGENT-M2-2026-09-11.md`）；
  - 不做 checkpoint/rewind（今天完全不存在，`docs/CURRENT_STATE.yaml:52`）；
  - 不把 hook 当 parity 或质量证据（`TERMINAL-AGENT-CLI-BENCHMARK-2026-07-26.md:128` 同义："plugins/MCP/sub-agents 不是 agent 质量证明"）。
- **历史负例提示**：本仓对"静默走错形状"的扩展点已有代价记录（`_refusal_text` 不覆写 → 拒绝被报成 MALFORMED，`provider.py:497-506`）——hook 契约必须**显式**而非可选静默降级。

## 13. 轻量第一阶段（P1）与回滚

- **P1 = 配置 + 只读 observer**：`hooks.json` 载入（0600、sha256 校验、全局开关）、7 个事件的只读快照、durable 审计记录、opt-in 大载荷日志。**返回值一律 `None`**。
- **P2（需单独 gate）**：`tool.pre` / `approval.requested` 的纯收紧 `HookDeny`（含 `basis=hook_rule` 记录、fail-closed 语义、G2/G3/G7 全套测试）。
- **不做**（本 GC 内不授权）：改写类 hook（provider 请求体、action 参数、history/prompt 组装）、hook 链式调用其它 hook、hook 触发 capability。
- **回滚**：`AGENT_OS_HOOKS_DISABLED=1` 或删除 `hooks.json`；无数据迁移、无写路径、无契约删除。
- **Stop conditions（遇到即 `REVISE_TO_SPEC`）**：
  - 需要 hook 参与 allowlist / risk tier / gate / policy / permit / approval 的**判定或产出**；
  - 需要 hook 在 `[reserve, seal]` 窗内运行；
  - 需要 repo-local / workspace-local 的 hook 安装源；
  - 需要 hook 拿到写 evidence / 写纠正 / 替换 gateway 的能力；
  - 需要改动 `CHAT_CAPABILITY_IDS`、permission mode 矩阵或 `apply_deny_rules` 语义才能实现；
  - 需要新增非 `textual`/既有栈之外的运行时依赖（M2 stop condition 同义）。

## 14. 与既有边界的关系（一致性核对）

- `AGENTS.md` §3.2（模型/插件只能经有作用域 typed capability 行动）：hook 载荷 typed、来源仅操作者、不产生 capability 调用 → 一致。
- `AGENTS.md` §3.5（外部 Skill 不是内核对象）：hook **也不是**内核对象，是运行时接缝上的代码，不进入 capability registry（`CapabilityPort.specs()` 不变）。这一点需在实现时用结构测试钉住。
- `ADR-0059`（单一 dispatch 路径）：hook 不产生第二条 dispatch 路径 → 一致；`tests/product/test_capability_adapter_boundary.py` 一类的结构测试必须继续通过。
- Stage 2c/2d（治理面 API-only，终端不新增治理入口）：hook 配置是**操作者本地文件**，不新增终端治理路由 → 不冲突（若 CTO 要求 hook 必须改为经 API 下发，则与本条和 §15 决策 3 一并重定）。

## 15. 需 Founder / CTO 决策项

1. **容器**：本 GC 是否足够，还是必须升格为 **ADR-0061**（新增边界面；0060 已被未合并草稿占用，理由见 §0）。
2. **P1 范围**：是否确认"只读 observer"为 P1 唯一范围、`HookDeny` 纯收紧留到 P2？（本文件建议：是。）
3. **安装来源**：是否确认 P1 **只**允许 `~/.agent-os/hooks.json`，明确排除仓库内/工作区内来源？若 CTO 要允许仓库级 hook，需要独立安全评审与"仓库内容可被 agent 改写"这一事实的显式接受。
4. **完整性强度**：sha256 固定是否足够，还是必须签名（谁签、本地 key 还是组织 key、轮换策略）？
5. **失败语义默认值**：门类默认 `required`（fail-closed）还是默认可选（skip_and_record）？本文件建议门类默认 fail-closed。
6. **执行形态**：hook 与 daemon 同进程（同权限、**无沙箱**）是否可接受？本文件诚实标注：P1 同进程 = operator-trusted code，**不提供**隔离；若需要隔离须另立 GC（子进程/容器/能力降级）。
7. **可观测性落点**：门类 hook 用既有 durable task event、观察类大载荷用 opt-in 文件日志，是否确认？
8. **快照绑定**：是否允许给 `TaskConfigurationSnapshot` 增加可选 `hooks_digest`（契约改动；兼容策略=只增不改）？
9. **版本策略**：未知 event / 未知字段时"拒绝整份配置"是否可接受（本文件建议拒绝，理由见 §9）？
10. **与 MCP / skills / subagent 的边界**：hook 是否被允许作为 MCP/skills 的**载体**（本文件建议禁止：工具类扩展仍必须编译为 typed capability，`AGENTS.md` §3.5）。
11. **是否进入 CTO gate**：确认后需要 Goal Card → Context Pack → 独立评审 → 实现 → 测试 → 独立 review 的完整流程；本文件目前**未**进入任何一项。

## 16. 声明分级（当前）

`specified: 本文件` / `implemented: NO` / `tested: NO` / `integrated: NO` / `verified: NO` / `released: NO`。
未执行：CTO gate、架构/安全评审、实现、测试、独立评审、发布授权。**不得**据此声称可扩展性能力、market parity、自主性或"hooks 已可用"。

## 17. 未核实 / 存疑

- **未核实**：`hooks.json` 这一路径前缀与既有 `~/.agent-os/*` 的**权限/创建**约定在实现中是否有统一 helper（仅核到 `provider_settings.py:23` 的 `DEFAULT_CONFIG_PATH` 与 `cli-ts/src/descriptor.ts:11` 的 descriptor 路径）。
- **未核实**：`approval.requested` 的"完整触发面"——本文件按 `agent_loop.py:1495-1506` 与 surface `decide_approval`（`surface_runtime.py:282-289, 430-438`）描述；是否还有其它审批产生点（例如 mandate/responsibility 路径）未逐一枚举。
- **未核实**：`turn.started` 是否应携带完整 `user_text`。现状该字段已进 durable 事件（`agent_loop.py:312-321`），但把同一文本再发一份给 hook 会扩大暴露面；P1 建议只给长度，需 CTO 追认。
- **存疑**：hook 超时上限（建议 ≤200 ms）与 provider 重试/超时参数的关系未实测；`AGENT_OS_PROVIDER_*` 已有多个 env 开关，hook 开关的命名与文档位置需与 operator docs 对齐。
- **存疑**：G4 的"逐字段相等"在 P2 引入 `HookDeny` 后如何表述——拒绝会**有意**改变控制流，届时 gate 需改为"拒绝只增加记录、不改变既有事件字段语义"。
