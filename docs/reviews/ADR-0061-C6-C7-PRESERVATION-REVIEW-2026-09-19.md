# ADR-0061 C6/C7 保持性评审（对抗性评审）

- 评审日期：2026-09-19
- 评审基线：`origin/main` = `03ac66b5`，worktree `autonomous-agent-core/.worktrees/wt-threat`，分支 `docs/adr-0061-threat-model-20260919`
- 评审对象：**任务书冻结的 `agent.spawn` 接口描述**（Form B 多 Agent 派生），不是 ADR-0061 的论证文本
- 评审身份：**同模型 subagent reviewer**。`builder_id != reviewed_by` **不满足**，**没有** independent-provider approval。因此本文件**不构成**根 `AGENTS.md` §9/§13 或仓库 `AGENTS.md` §7 意义上可用于 promotion/gate 的"独立评审"，只构成一次**对抗性技术意见**（与 `docs/CURRENT_STATE.yaml:52,59` 已记录的同类边界口径一致）。
- 方法：docs-only + 静态代码阅读。**未**启动任何 daemon，**未**读写 `~/.agent-os/`，**未**修改 `docs/CURRENT_STATE.yaml`，**未**修改 ADR，**未**使用 `git stash`。本文所有 `file:line` 均为本次阅读所得。
- 声明等级：`specified: 本文件` / `implemented: NO` / `tested: NO` / 本评审给出的探针**一条都没有执行**。

---

## 0. 首先必须说清楚的一件事：ADR 文本不存在

在本评审基线上，**`docs/adr/ADR-0061*` 不存在**（`ls docs/adr/ | grep -i 0061` 无输出；`find . -name "*0061*"` 无结果；HEAD = `03ac66b5`）。ADR-0061 由并行作者撰写。

因此本评审的对象是**任务书里那份冻结接口描述**，不是 ADR 的论证。我对该接口的每一条声明做对抗性检验，但**我无法检验 ADR 是否诚实陈述了本文列出的残余风险**——这正是 ADR 落地后必须被复审的原因，也是我在 §5 列出的第一条局限。

---

## 1. C6 与 C7 究竟是什么（从本仓自身的文档与代码建立）

我不引用 ADR 作者的话。以下定义来自宪法、参考架构与实现权威脊。

**路径约定**：未加前缀的路径都是本仓（`autonomous-agent-core/`）相对路径。以下四个文件属于**根仓** `/Users/mima1234/Documents/AI-Agent-Projects/`，本仓中不存在：`AGENTS.md`、`docs/GOAL-BLUEPRINT.md`、`docs/mandates/META-SHADOW-MANDATE-0.md`、`docs/research/RR-0001-unified-autonomous-agent-architecture.md`；`.agents/skills/subagent-governance/SKILL.md` 同样在根仓。

### 1.1 C6 = 控制路径边界（器官不是主体）

来源：`docs/research/RR-0001-unified-autonomous-agent-architecture.md:62-66` —— C6 标题即"LLM 与世界模型皆为器官，不是主体"。

在本仓被操作化为三条可检查的约束：

1. **器官不得进入控制路径。** `docs/architecture/REF-ARCH-02-model-organ-contract.md:28-36`：器官输出必须"advisory and bounded"，"it cannot seize the loop … *the estimate stays out of the control path.*"；`docs/architecture/REF-ARCH-01-system-reference-architecture.md:34` 的架构图把这一条标注为 "← C6: organs out of control path"。
2. **任何模型/器官/插件/子代理只能通过 scoped typed capability 行动。** 根 `AGENTS.md:113`（§8.2）；`docs/mandates/META-SHADOW-MANDATE-0.md:33`（"C6 控制路径边界：LLM 是概率语言/推理器官，不持有最终执行权"）。仓库 `AGENTS.md:34` 同一表述。
3. **边界不因能力结果自动移动。** `docs/GOAL-BLUEPRINT.md:197`："C6 控制路径边界、C7 纠正边界和 founder-reserved SD4 不因能力结果自动移动。"

**对本次变更的关键推论：** C6 约束的是"**决策权**相对于**提议者**的位置"，不是"同时能有几个提议者"。多开一个 LLM 器官（哪怕它能开更多器官）在 C6 上**原则上**是允许的——前提是每一个提议者都被同一个确定性权威门拦住。所以 Form B 的 C6 问题不是"能不能有子代理"，而是"**子代理的每一次动作是否仍然走同一个门**"。这直接决定了本文 §2 的 D 组（控制路径重复）是本次边界移动的主战场。

### 1.2 C7 = 不可写、不可旁路的外部纠正权威

来源：`docs/research/RR-0001-unified-autonomous-agent-architecture.md:68-79` —— C7 是"唯一钉死的元固定点"，凌驾 C1–C6，四权各堵一类失效：**观测**（防欺骗，哈希链/只增审计）、**暂停**（堵进行时损害，开关在系统权限之外）、**回滚**（堵既成事实，外部触发 + durable 快照）、**收紧**（堵漂移，人可单方面收紧，系统不得抵抗）。

在本仓被操作化为：

| 层 | 载体 | 位置 |
|---|---|---|
| 权威对象 | `CorrectionAuthority`（外部所有，本进程只持快照视图） | `packages/os_core/src/agent_os_core/governance.py:99-138` |
| 读端口 | `CorrectionReadPort`（`snapshot`/`halted`/`guard_unchanged`） | `governance.py:49-68` |
| 写端口 | `CorrectionAdminPort`（`correct`/`resume`），仅经 `CorrectionAdminView` 交给 authenticated operator 路径 | `governance.py:71-76`、`governance.py:289-299` |
| 动作级检查 | `halted(task_id, run_id, capability_id)` + epoch 相等 | `governance.py:129-138`（halted 只看这三个键）；`governance.py:372`；`capability.py:154-163` |
| 派发线性化 | `guard_unchanged` 上下文管理器 | `capability.py:183-192` |
| 契约级收据 | `C7ClearanceReceipt` + `C7ReceiptVerifier`（digest 绑定、epoch replay、halted、scope、authority unavailable 全部 fail-closed） | `packages/os_core/src/agent_os_core/c7_receipt.py:13-25`、`:116-162`；`docs/architecture/C7-BOUNDARY-STATEMENT.md:9-15` |
| 明示的非声称 | C7 是 **pre-commit 线性化 token，不是中断**：不打断已派发的效果；不防"被攻陷的 worker 干脆不调用 verify" | `docs/architecture/C7-BOUNDARY-STATEMENT.md:19-23`、`:28-36` |

根 `AGENTS.md:115`：`C7 is non-writable and non-bypassable`。仓库 `AGENTS.md:33`：Agent 不得调用、模拟或清除 `op_*` 主权面。

**对本次变更的关键推论：** C7 的**可达范围（reach）由 `(task_id, run_id, capability_id)` 三个键决定**（`governance.py:129-138`、`c7_receipt.py:14-25`）。它没有 session 轴、没有 agent 轴、**没有父子轴**。这是本文 C2/G1 两个裁决的唯一根因。

### 1.3 与本次边界移动直接相关的三条既有硬约束

1. **唯一执行路径（no second dispatch path）。** `docs/adr/ADR-0059-merged-capability-execution-authority.md:19`："`CapabilityPort.execute` + `CapabilityBroker.invoke(...)` is the **ONLY** dispatch path"。`:17` 明确否掉"two execution paths for one spine — a bypass risk"。`:69` 列出必须保持单一路径的文件集，含 `agent_loop.py`、`action_pipeline.py`、`apps/api_server/app.py`。
   - 代码事实：全仓（`packages/`、`apps/`、`domain_packs/`）`connector.execute(action)` **只有一个调用点**：`capability.py:193`。三个生产 `invoke` 调用点：`execution.py:1236`、`action_pipeline.py:343`、`action_pipeline.py:479`——全部进入同一个 `CapabilityBroker` 类（`capability.py:112-227`）。
2. **每会话一个 in-flight turn（frozen rev 9）。** `surface_runtime.py:70-75`（`SurfaceTurnInProgress`）；判定在 `surface_runtime.py:417-422`，数据来自 durable 事件 `SESSION_TURN_STARTED − SESSION_TURN_COMPLETED`（`app.py:2299-2319`）。锁是**按 session_id** 的（`surface_runtime.py:174-176`、`:208`、`:224`）。`docs/CURRENT_STATE.yaml:53` 已记录"该不变量是 per-session，因此一 Agent 一 session 可不解除它"。
3. **E2 冻结 allowlist。** `permission_gate.py:23-31` 的 `ACTION_RISK_TIERS`（`{workspace.read,workspace.search,workspace.run_tests,session.todo_write}:1, {workspace.edit,workspace.apply_patch}:2, {workspace.shell}:3`）是**模块级常量**；不在表内的 capability 在**任何** mode 下 fail-closed（`permission_gate.py:58-65`）。loop 层另有一份重复的模块级常量 `CHAT_CAPABILITY_IDS`（`agent_loop.py:67-75`），在 `agent_loop.py:941-950` 做同样的 fail-closed 拒绝。

---

## 2. 攻击面、裁决与证据

裁决口径：
- **defended**：冻结设计或既有脊结构上挡住了，且我有代码/契约证据；
- **not defended**：有具体路径绕过，或设计要求的强制点**在代码里不存在**；
- **undetermined**：设计对该问题沉默，或需要运行实现才能判定。

| # | 攻击 | 裁决 |
|---|---|---|
| A1 | 授权派生：`child_grants ⊆ parent_grants` 无强制点 | **not defended** |
| A2 | 重启/rehydrate 恢复成全量授权 | **not defended** |
| A3 | `permission_mode` 未设父子上限 | **not defended（设计沉默）** |
| A4 | 子代 spawn 的"MINUS agent.spawn"无强制点 | **not defended** |
| A5 | explore/general 类型混淆（工具广告 ≠ 强制） | **not defended** |
| A6 | `agent.spawn` 入表即改 E2 冻结表，且未声明 risk tier | **not defended（设计沉默）** |
| B1 | 审批跨会话/跨代复用（digest 洗白） | **defended**（结构证据充分） |
| B2 | 子遇到 tier≥3 升级：状态枚举无法表达 | **not defended（契约不自洽）** |
| B3 | 子复用父的 ConfirmationGateway → 归因欺骗 | **undetermined（设计沉默）** |
| B4 | 子会话网关选择（Deferred / NonInteractive / Auto）未指定 | **not defended（设计沉默）** |
| C1 | 子写/模拟/清除 C7 面 | **defended**（端口隔离） |
| C2 | **C7 halt 不级联：停父不停子** | **not defended（最严重）** |
| C3 | spawn 自身绕过 C7 | **defended**（若 spawn 真走 broker） |
| C4 | 子触达 evaluator/promotion root | **defended**（不新增可达性），但需显式禁止 selfdev 授权下传 |
| D1 | 第二条 dispatch path | **defended（结构）**，但实现方式**undetermined** |
| D2 | 子回合是否过同一 policy/evidence | **defended（类相同）**，需事件级探针 |
| D3 | 子会话的 `CapabilityGrant` 由谁签发 | **undetermined（设计沉默）** |
| E1 | in-flight 上界在崩溃后不可重算 | **undetermined（设计沉默）** |
| E2 | 树可以超 N（N 是 per-parent-turn，不是树界） | **defended-as-specified，必须显式声明** |
| E3 | nested spawn 的"显式开启"如果靠 env 即无界 | **not defended（设计沉默）** |
| E4 | "父的剩余预算"在现有脊里没有对象 | **not defended（依赖不存在的机制）** |
| E5 | 挂死的子无限期占据父回合 | **not defended（无墙钟上界）** |
| F1 | 子无记录行动 | **defended（条件同 D2）** |
| F2 | 父 roll-up 需要新契约面，且与 digest-only 冲突 | **not defended（设计未列契约变更）** |
| F3 | digest-only：提示词/完成文本其实**已落 durable** | **not defended（作为系统属性）；作为两个事件上的窄口径可成立** |
| F4 | provider 日志泄文本 | **defended**（既有 opt-in，不涉 prompt/完成文本） |
| F5 | 父 roll-up 少报失败 | **undetermined（投影权威源未写）** |
| G1 | 子活过父的 pause/correct | **not defended（与 C2 同根）** |
| G2 | 子活过父的 close | **not defended（新级联要求无机制）** |
| G3 | `stopped` 被读成"无副作用" | **defended（C7 语义如此），必须显式声明** |
| G4 | 运行期死亡时的 in-flight 子无人收尸 | **not defended（设计沉默）** |
| G5 | 崩溃后 fan-out 配额被重置 | **not defended（同上）** |
| H1 | 子报 completed 而实际不是 | **undetermined** |
| H2 | roll-up 藏失败 | **undetermined** |
| H3 | 子的动作被 operator 误认为父的 | **not defended（界面层）** |
| H4 | 审计可区分归属 | **defended（durable 层）** |

### A 组：权限提升

**A1 — 授权派生没有强制点。裁决：not defended。**

这是本次审查中最结构性的一条。冻结设计声明 `child_grants ⊆ parent_grants ⊆ task_grants`。但在现有权威脊里**没有表达这件事的位置**：

- `ActionContract` 的字段是 `action_id/task_id/run_id/node_id/principal_id/tenant_id/workspace_id/capability_id/capability_version/...`（`packages/contracts/src/agent_os_contracts/authority.py:161-183`）——**没有任何 agent / session / spawn 维度**。
- `PolicyInput` 只有 `principal, grant, capability, approval, now`（`governance.py:313-320`）。
- `PolicyKernel.decide` 的 grant 校验是 principal 作用域的：`context.grant.principal_id != action.principal_id`（`governance.py:356-360`）。
- 而**所有会话共享同一个 principal**：`SurfaceRuntime._require_principal_scope` 要求每个会话命令的 client 三元组等于 composition-root 的 `application.principal`（`surface_runtime.py:501-510`）。父子会话因此是同一个 `principal_id`。

于是在"授权"这一层，父与子在结构上**是同一个主体**。`child_grants ⊆ parent_grants` 只能靠 loop/pipeline 层传入一个更窄的 `grants` dict 来实现（`agent_loop.py:243` → `action_pipeline.py:53` → `action_pipeline.py:256-260` 的 `self._grant[cid]`）。而 `CapabilityBroker` 本身**不做任何 allowlist 或 grant 检查**——它只查 permit/action digest 匹配、execution claim 的 fence、permit 未过期、C7 halted/epoch、collaboration preflight、然后在 outcome store 里 reserve（`capability.py:140-192`）。所以"子授权更窄"这条不变量**不是**由执行边界强制的，只由调用方传入的 dict 强制。

追加证据：GC 自己就警告过这一点。`docs/product/GC-P3-MULTIAGENT-TASK-TREE-2026-09-16.md:72`："多 Agent 委派的 scope 单调性（子 ≤ 父 ≤ 任务）在工程治理仓为**流程规则**；若产品要引入同等约束，须作为**新契约**进入 held-out 产品门，**不能由流程规则直接继承**。" 根仓的流程侧载体是 `.agents/skills/subagent-governance/SKILL.md:13`（`subagent_scope <= parent_agent_scope <= task_scope`），并且它自己就承认是 advisory：`:39-40` "it is an advisory constraint the parent/subagent must honor, not runner-enforced"。失败模式：`agent_loop.py` 的默认 risk tier 是 `ACTION_RISK_TIERS.get(capability_id, 1)`（`agent_loop.py:1430`），而 tier-1 在**任何** mode 下 auto-pass（`permission_gate.py:66-72`）。

**A2 — 重启/rehydrate 恢复成全量授权。裁决：not defended。**

创建路径构造子集：`chat_grants = {capability_id: grants[capability_id] for capability_id in CHAT_CAPABILITY_IDS}`（`app.py:2036-2039`）。

恢复路径**不重建子集**：`restore_chat_session` 传 `grants=self._chat_grants()`（`app.py:2167`），而 `_chat_grants()`（`app.py:2880-2892`）返回全量 `CHAT_CAPABILITY_IDS` 的授权，并且**主动抬高** `max_risk_tier` 到 `CHAT_GRANT_MAX_RISK_TIERS` 声明的上限（`app.py:2889-2891`，注释自陈 "Elevate only the chat-scoped grant copies"）。

⇒ 如果"explore 只能 read/search"实现为 spawn 时传入一个更窄的内存 dict，那么任何一次 `restore_chat_session(child_session_id, ...)` 都会把子会话的授权恢复成父的完整集合，**并且**把 tier 上限抬到声明值。`/resume`、审批续跑（`app.py:2205/2262/2362/2469/2479` 全部走 `restore_chat_session`）都会经过这条路径。设计说"durable model（append-only）"，但没有说窄化是持久对象、也没有说 restore 必须重算。

**A3 — `permission_mode` 没有父子上限。裁决：not defended（设计沉默）。**

设计写的是 `max_risk_tier(child) <= max_risk_tier(parent)`，**没有**写 `permission_mode(child)` 与父的关系。而 `permission_mode` 恰好是 tier-2 的自动放行开关：`evaluate_permission_gate` 在 `risk_tier == 2 and mode == "ACCEPT_IN_WORKSPACE"` 时返回 `MODE_AUTO_ALLOW`（`permission_gate.py:73-79`），只记一条 `POLICY_VERDICT_RECORDED(ALLOW, basis=permission_mode)`（`agent_loop.py:1511-1522`），**没有** `ApprovalDecision`。`permission_mode` 是 per-session 的 durable 投影（`session_projection.py:191-192, 265-266`），由 operator-only 的 `set_permission_mode` 修改（`surface_runtime.py:313-335`；`app.py:2508-2533` 要求 `PRINCIPAL`/`TENANT_ADMIN`）。

⇒ 父会话 `ASK`、子会话 `ACCEPT_IN_WORKSPACE` 是当前代码允许的配置，此时子的 `workspace.edit`/`workspace.apply_patch` **无需任何人工确认**即可执行。这未必是漏洞，但 ADR 必须显式决定并说明，不能留白。

**A4 — "general MINUS agent.spawn" 没有强制点。裁决：not defended。**

"能力集合"目前在代码里**不是对象**，而是两个模块级常量：`permission_gate.ACTION_RISK_TIERS`（`permission_gate.py:23-31`）与 `agent_loop.CHAT_CAPABILITY_IDS`（`agent_loop.py:67-75`）。loop 的拒绝点写死查全局常量：`if capability_id not in CHAT_CAPABILITY_IDS`（`agent_loop.py:941-950`）。`AgentLoop` 实例没有"我这个 agent 的能力集合"这一字段（构造参数见 `agent_loop.py:202-229`，`_deny_rules`/`permission_mode` 是 per-loop，capability 集合不是）。

⇒ "general 继承父的能力集**减去** `agent.spawn`"目前**无处落地**。方向是对的（单调收缩），但强制点在设计里是隐含的。

**A5 — explore/general 类型混淆。裁决：not defended。**

`explore` 要 "workspace.read + workspace.search ONLY"。若实现方式是把模型看到的工具清单收窄（`provider.py:1261-1355` 的 `_TOOL_DESCRIPTIONS` 与工具广告是**全局**的），那不构成安全边界：被读取内容污染（prompt injection）的 explore 子代理完全可以发出 `workspace.edit` 的 tool call，而 loop 层只查全局 `CHAT_CAPABILITY_IDS`（`agent_loop.py:941`）、gate 层只查全局 `ACTION_RISK_TIERS`（`permission_gate.py:58`）——两者都**会放行** `workspace.edit`。叠加 A3（ACCEPT_IN_WORKSPACE），结果是**自动执行**。

注意 `agent_type` 本身进了 durable record（设计里 `CHILD_AGENT_SPAWNED.agent_type`），所以事后可审计——但这是 detective，不是 preventive。

**A6 — `agent.spawn` 入表本身就是对 E2 冻结表的修改。裁决：not defended（设计沉默）。**

冻结设计没有声明 `agent.spawn` 的 risk tier。事实是：它不在 `ACTION_RISK_TIERS` 里（`permission_gate.py:23-31`），因此**今天**它在任何 mode 下 fail-closed（`permission_gate.py:58-65`）；不在 `CHAT_CAPABILITY_IDS` 里（`agent_loop.py:67-75`），因此今天会记 `unauthorized_proposal` 并终止回合（`agent_loop.py:941-950`）；不在 `CHAT_GRANT_MAX_RISK_TIERS` 里（`agent_loop.py:84-90`），因此 `open_chat_session` 的断言会直接抛（`app.py:2028-2035`）。

⇒ 实现 `agent.spawn` 必须同时改这三个常量与 E2 冻结表。而"派生一个能自主行动的 Agent"在语义上**不是** sandbox edit：如果它被登记为 tier ≤ 2，那么在 `ACCEPT_IN_WORKSPACE` 下它会被**自动放行**（`permission_gate.py:73-79`）——也就是"派生新 Agent"不需要任何人工确认。ADR 必须显式声明它的 tier 以及为什么该 tier 是正确的。

### B 组：审批洗白

**B1 — 跨会话/跨代复用审批。裁决：defended。**

证据链是完整的三重绑定：
1. `ApprovalDecision.action_digest` 是 SHA-256 digest（`authority.py:200-210`），`action_digest()` 是 `ActionContract` 的整对象 `content_digest`（`authority.py:196-197`），而 `ActionContract` 含 `action_id/task_id/run_id/node_id`（`authority.py:161-183`）。子有独立的 `child_task_id`/`run_id`（设计如此），故 digest 必不同。
2. `resume_pending_approval` 校验 `approval.action_digest != pending.action.action_digest()` → 抛（`agent_loop.py:525-534`），并额外校验 tenant/workspace 与 disposition 只能是 APPROVE/REJECT。
3. `PolicyKernel.decide` 再查一次：`context.approval.action_digest != action.action_digest()` → `DENY(["APPROVAL_DIGEST_MISMATCH"])`（`governance.py:378-381`）。

所以"父批准的动作由子执行"或反之，在结构上不成立。

**但有一个必须记录的弱点（归因，不是洗白）：** `ApprovalDecision.actor_id` 只能等于 composition-root 的单一 principal（`agent_loop.py:545-551` 要求 `actor_id == self._principal.principal_id` 且 `actor_role == self._principal.role`），而所有会话共享该 principal（`surface_runtime.py:501-510`）。因此审计上**只能靠 action_digest 区分父子，actor 字段本身区分不了**。见 H3/H4。

**B2 — 子遇到 tier≥3 升级：契约不能表达。裁决：not defended（契约不自洽）。**

结构上 tier≥3 必须有人批：`PolicyKernel.decide` 在 `(action.risk_tier or spec.risk_tier) >= 3` 且无 APPROVE 时返回 `ESCALATE(["APPROVAL_REQUIRED"])`（`governance.py:382-385`）；`ActionPipeline.execute` 对非 ALLOW 直接抛 `PermissionError`（`action_pipeline.py:282-301`）。生产路径的网关是 `DeferredApprovalGateway`（`app.py:2207, 2257, 2364, 2469, 2479`；`responsibility_surface.py:608`），它的 `confirm` **直接抛** `ApprovalRequired`（`agent_loop.py:122-126`），loop 接住后写 durable pending 并返回 `TurnResult(text="approval required", stop_reason="approval_required")`（`agent_loop.py:1008-1027`），而 `_complete_turn` 对 `approval_required` **直接 return，不提交回合**（`agent_loop.py:468-469`）——即该回合停在"半开"状态，等 operator 的 `decide_approval`。

对子会话这意味着：
- 子的回合会**park**，返回一个**硬编码英文 text**（`agent_loop.py:1024`），而不是"子的最终助手文本"；
- 冻结输出契约的状态枚举是 `completed|failed|stopped|timeout|limit`——**没有 `awaiting_approval`**；
- 设计里 `agent.spawn` 是**同步**的（返回 `text/steps/tokens`）。

⇒ 子一旦需要 tier≥3 批准，父的 `agent.spawn` 调用既无法返回一个正确的 status，也无法返回合法的 text。它只能被压成 `timeout`（语义错）或永久挂起（资源错）。**这是设计内部的第一号不自洽，且完全可以从今天的代码推定。**

**B3 — 子复用父的 ConfirmationGateway。裁决：undetermined（设计沉默）。**

`ConfirmationGateway` 是**每个 AgentLoop 一个**（`agent_loop.py:237`，构造参数 `agent_loop.py:213`），由 composition root 在 `open_chat_session`/`restore_chat_session` 时注入（`app.py:1906, 2049, 2169`）。设计没有说子会话的 loop 用哪个网关。

如果实现让子 loop 复用父的网关（composition root 只有一个网关实例，这是"自然"的写法），那么子的 tier-2 确认会**以父的界面出现**：`_action_preview(action, arguments)`（`agent_loop.py:1852-1867`）不含 session/agent/spawn 标识。operator 会看到"父在请求确认"，实际执行者却是子。这是**操作者欺骗**，而且是 C6 意义上的控制路径混淆。

**B4 — 子会话网关选择未指定，且三个候选都有明确问题。裁决：not defended（设计沉默）。**

- `DeferredApprovalGateway`：子回合 park，但**没有 surface caller 在等它**（调用者是父的 spawn connector，不是 HTTP 客户端）→ 见 B2。
- `NonInteractiveDenyGateway`（`agent_loop.py:143-147`，fail-closed 返回 False）：子的所有确认类动作被拒，语义安全但能力受限，且父需要把"子被拒"如实呈现。
- `AutoApproveGateway`（`agent_loop.py:129-140`）：自动批 ≤2，**其 docstring 自陈不得接入交互生产路径**。若子会话走它，子的 tier-2 全部无人工确认。
  - 诚实的补充：本次在 `apps/` 全目录 grep `AutoApprove` **0 命中**，生产路径今天用的是 `DeferredApprovalGateway`；该 docstring 提到的 `-p` 一次性路径在本次基线上**未被我定位**（该路径可能经 surface 协议且同样用 Deferred）。故我把"子是否可能用 Auto"记为**需要确认**，而不作为已证事实。

### C 组：C7 触达

**C1 — 子能否写/模拟/清除 C7 面。裁决：defended（端口隔离）。**

写入口是 `CorrectionAdminPort.correct/resume`（`governance.py:71-76`），只通过 `CorrectionAdminView`（`governance.py:289-299`）暴露，而它是 composition root 经 `split_correction_authority`（`governance.py:302-310`）分发给 authenticated operator 路径的（operator 校验在 `app.py:2927-2950`：必须是 `PRINCIPAL`/`TENANT_ADMIN`，且 tenant/workspace/run 状态合法）。`CapabilityBroker` 只持 `CorrectionReadPort`（`capability.py:126`），`PolicyKernel` 也只持读端口（`governance.py:325-339`）。

⇒ `agent.spawn` 作为 developer domain pack 的 capability，**类型上拿不到** admin 写端口。这是"结构上够不到控制路径"的一个真实实例。

**但条件必须写进 ADR**：这项保护的载体是 composition root 的**注入纪律**，不是类型系统的强制（`CorrectionAuthority` 的构造函数是 public，`governance.py:109`，注释自陈 "Direct construction remains available for authority unit tests and the composition root"）。ADR 必须规定 spawn connector 依赖的端口类型就是 `CorrectionReadPort`，并且有一个 bypass-detecting 测试断言 connector 的构造签名里没有 admin 端口。

**C2 — C7 halt 不级联：停父不停子。裁决：not defended。这是我认为最严重的发现。**

三条独立证据指向同一个结论：

1. **halt 的键空间没有父子轴。** `CorrectionAuthority.halted()` 只查 `("task", task_id)`、`("run", run_id)`、`("capability", capability_id)` 三项的 any（`governance.py:129-138`）。
2. **operator 的"停父"写的就是父自己的 task 键。** `surface_correct_session` → `correct_task(task_id, reason)`（`app.py:2501-2506`）→ `self.correction_admin.correct("task", task_id, ...)`（`app.py:2963`）。`surface_pause_session` → `pause_task(task_id)` → `update_run_status(task_id, PAUSED)`（`app.py:2487-2492`、`app.py:2912-2915`）——**连 C7 更正都不写**，只改父 run 的状态。
3. **每个动作只查它自己的键。** `PolicyKernel.decide`：`self.correction.halted(action.task_id, action.run_id, action.capability_id)`（`governance.py:372`）。`CapabilityBroker.invoke`：同一三元组（`capability.py:154-163`）。`C7VerificationScope` 也只绑 `tenant/workspace/task/run/capability`（`c7_receipt.py:14-25`）。

冻结设计规定子有**自己的** `child_task_id`。因此：**operator 对父 task 下达 C7 校正或暂停父会话，不会阻止子代理继续派发效果。** 那条"stopping the parent stops its in-flight children"是一条**全新的级联要求**，今天在 C7 语义里不存在，设计没有说明它由谁强制、如何证明、以及它是否属于 C7（若它只是 spawn 管理器的一条进程内约定，那么一个 bug 或一次崩溃就能绕过它——而 C7 的定义恰恰要求"开关实现于系统权限之外，系统不可触达"，`RR-0001:72`）。

**唯一的例外（重要且必须写进 ADR）：** capability 轴的 halt **是全局的**——`capability_id` 是全局名字（如 `workspace.shell`），`halted()` 的 any 包含该轴（`governance.py:131-137`）。所以 operator 有一个"关全局闸"的杠杆能触达子代。但最自然的那个杠杆（停父）有洞。

**C3 — spawn 自身绕过 C7。裁决：defended（条件成立时）。**

若 `agent.spawn` 确实是一个走 broker 的 capability（设计说它是 capability id），那么它自己也受 `capability.py:140-163` 的 permit/epoch/halt 检查和 `capability.py:183-192` 的 `guard_unchanged` 线性化。

**条件是**：spawn 必须是 connector 的 effect，而**不是** `AgentLoop` 里的分支。如果实现成 "在 `_drive` 里识别到 `agent.spawn` 就调用 spawn 管理器"，那么它就绕过了 broker 的 reserve/lease/seal/C7 线性化——同时也就构成了 D1 意义上的第二条执行路径。ADR 必须写死这一点。

**C4 — 子触达 evaluator / audit / promotion root。裁决：defended（不新增可达性），但需显式禁止。**

spawn 不新增对 `EvaluatorAuthority`/`outcome_evaluators`/materialization promotion 的路径；子能达到的只是父已经授权的能力。**但**：如果父的授权集合里包含 selfdev / promotion 类能力，那么按"general 继承父的能力集"这条规则，**子也会拿到**。ADR 必须显式禁止子代理获得 selfdev/promotion 面（即 minus 集合至少还要含 `selfdev.*`），否则这就是一条真实的授权外溢。

### D 组：控制路径重复

**D1 — 第二条 dispatch path。裁决：defended（结构），实现方式 undetermined。**

- 代码事实：`connector.execute(action)` 全仓唯一调用点 `capability.py:193`。三个生产 `invoke` 点（`execution.py:1236`、`action_pipeline.py:343`、`action_pipeline.py:479`）进入同一个 `CapabilityBroker` 类。
- 每个 `AgentLoop` 自己 new 一个 broker 实例（`agent_loop.py:240-242`），包装同一个 connector 与同一个 correction 读端口。⇒ 子会话（作为普通 session）会走同一个类、同一个 connector。
- ADR-0059:19 已把"唯一 dispatch path"写成决策；ADR-0059:69 把 `agent_loop.py` 列进必须保持单一路径的文件集。

⇒ **只要 `agent.spawn` 的实现方式是"通过 application/surface 端口创建并驱动子回合"，就不产生第二条路径。** 但设计**没有写这条约束**，所以这是 defended-conditional；ADR 必须写明并配 bypass-detecting 测试（见 P9）。

**D2 — 子回合是否过同一 policy/evidence 路径。裁决：defended（类相同），需事件级探针。**

父回合的路径是 `_drive → _execute_proposal → ActionPipeline.execute → PolicyKernel.decide → permit → broker.invoke`（`agent_loop.py:1412-1587`；`action_pipeline.py:236-320`；`capability.py:132-227`）。`AgentLoop` 与 session 的绑定校验只有 `session != self._session`（`agent_loop.py:841-843`）——它对会话身份没有特殊化。所以同类型的子 loop 走完全相同的路径。

证据强度是"类相同"，不是"实例相同"。需要有探针证明**子的 task 流上**确实出现 `POLICY_DECIDED` 与 `ACTION_RECEIPT_RECORDED`（`packages/contracts/src/agent_os_contracts/runtime.py:62-63`；写入点 `action_pipeline.py:276-281`）。

**D3 — 子会话的 `CapabilityGrant` 由谁签发。裁决：undetermined（设计沉默）。**

`agent.spawn` 事实上**创建新的 task/run**（设计里有 `child_task_id`），而 `PolicyKernel` 的每一次判定都需要一个 `grant`（`governance.py:351-352`：`capability is None or grant is None → DENY(["CAPABILITY_NOT_GRANTED"])`）。`CapabilityGrant` 的粒度是 `(principal, tenant, workspace, capability_id, capability_version)`（`packages/contracts/src/agent_os_contracts/capability.py:71-83`），`granted_by` 是一个字段（`:81`）。

⇒ 子会话的 grant 从哪来、由谁 `granted_by`、是否记为一次可审计的授权动作？设计完全没说。这也是 A1 的另一面：`child_grants ⊆ parent_grants` 需要一个**载体对象**，而现有脊里没有"agent 的授权集合"这个东西。附带的小工程问题：`action_pipeline.py:256-260` 的 `self._grant[cid]` 在 capability 缺失时是 **`KeyError`**（未经类型化的拒绝），会被 `agent_loop.py:1572-1577` 的 `except Exception` 捕获并记成工具失败——**不是** `POLICY_VERDICT_RECORDED(DENY, ...)`。这会让"窄化生效"的测试很难写成 fail-closed 的形态，也让 operator 看不到一条策略拒绝。

### E 组：资源与扇出

**E1 — in-flight 上界在崩溃后不可重算。裁决：undetermined（设计沉默）。**

设计写 "at most N children **in flight** per parent turn"。durable 模型只有 `CHILD_AGENT_SPAWNED` 与 `CHILD_AGENT_FINISHED`。崩溃后：一个"spawned 无 finished"的子算不算 in-flight？如果上界是内存计数器，重启后归零；如果实现从 durable 事件重算，那么崩溃后的残留子会**永久占用配额**（反过来把父回合锁死）。设计没说，两种实现都有明确的风险面。**这是 G5 的同一条。**

**E2 — 树可以超 N。裁决：defended-as-specified，但必须显式声明。**

N 的量词是 "per parent turn"，而子有自己的 `parent_turn_id` ⇒ 深度 d、每层扇出 N 的树总量是 N^d，**任何一层都不违反 N**。这不是漏洞，是设计所声明的语义；问题在于它对 operator 是反直觉的。ADR 必须显式写：**N 只界住每个父回合的并发子数，不界住树的总数、总 token、总成本或总时长。**

同源的还有 step 与 turn 预算：`AgentLoopConfig.max_steps_per_turn`（`agent_loop.py:152`，循环约束在 `agent_loop.py:864`）与 `max_turn_tokens`（`agent_loop.py:154`）都是 **per-loop / per-turn** 的，子的消耗不走父的计数器。设计说"父的 totals INCLUDE children"——那是**投影层的加法**，不是**预算强制**。

**E3 — nested spawn 的"显式开启"。裁决：not defended（设计沉默）。**

设计写："general … MINUS `agent.spawn` unless nested spawns are explicitly enabled (default OFF)"。**谁可以开启？** 设计没说。它与 `AGENT_OS_MAX_CHILD_AGENTS` 并列出现在同一段，暗示可能是 env。若真是 env，那么"进程环境即权力"——任何能设置环境变量的路径就解除了无界 spawn 的限制，而 C7 的定义要求关键开关"实现于系统权限之外"（`RR-0001:72`）且系统"不可触达"——env 恰好是系统进程自己读的东西，方向是反的。ADR 必须把"开启 nested spawn"定义为一次受授权的动作（operator 决定 + durable record + 可收紧），而不是一个环境变量。

**E4 — "父的剩余预算"在现有脊里没有对象。裁决：not defended（依赖不存在的机制）。**

设计写 `budget_limit(child) <= parent's remaining budget`。但：

- `CapabilityGrant.budget_limit` 是**静态上限**（`capability.py:79`），`ResourceBudget.fits_within` 只做**静态**逐字段比较（`packages/contracts/src/agent_os_contracts/resource.py:14-25`）——没有消耗账本。
- `ActionContract.estimated_budget` 是**单个动作的估计**（`authority.py:174`），而 `ActionPipeline.build_action` 的默认值是 `max_cost_usd=0, max_duration_seconds=120, max_provider_tokens=0, max_tool_calls=1`（`action_pipeline.py:83-89`）——即"一次调用"的估计，不是会话累计。
- `PolicyKernel` 唯一的预算判定是 `not action.estimated_budget.fits_within(context.grant.budget_limit)`（`governance.py:376-377`）。

⇒ **"父的剩余预算"这个量今天不可计算。** `srl_budget_ledger.py` 是 SRL 的 wake/query/help 预算账本（`srl_budget_ledger.py:34-96`），不是 capability 成本账本，且只服务 SRL 绑定。所以这条不变量在当前脊上是**悬空的**：ADR 要么先定义并实现一个 token/成本账本，要么把这条降级为"静态上限的单调收缩"并说明它不是运行期剩余量。

**E5 — 挂死的子无限期占据父回合。裁决：not defended（无墙钟上界）。**

同步 spawn（由设计的同步返回值决定）意味着**父回合的墙钟时间被子的墙钟时间占据**。而本仓明确没有给 loop 加墙钟上界：`AgentLoopConfig`（`agent_loop.py:151-158`）只有 steps/retries/tokens/context/loop-detection，没有 wall-clock；`docs/architecture/REF-ARCH-04-runtime-governance-contract.md:36` 记录过真实故障"a kimi call hung 1h22m"，并写明 "every organ call has a hard wall-clock cap" 是**要求**；`:53` 承认"Hard wall-clock caps on remote-LLM-organ calls still to be enforced at the `LLMBackend` boundary"（🟡 未完成）。Provider 层有 retry 上限（`CURRENT_STATE.yaml:52` 的 (a)），但没有回合级墙钟。

**并且有一个具体的交互需要 ADR 回答：** 父的 `agent.spawn` 动作在派发时持有父 run 的 execution lease（`agent_loop.py:1541-1543` → `_action_outcome.py:87-116`），而该 lease 的默认 TTL 是 **5 分钟**（`_action_outcome.py:92`）。子回合轻易可以超过 5 分钟。`seal` 不再校验 fence 或过期（`_action_outcome.py:243-297`）。我**没有**读完 `persistence.py:286-323` 之下的 `_acquire_lease_in_transaction`，所以我不下结论——把它列为探针 P13，并明确记为"未确定"。

### F 组：证据完整性

**F1 — 子无记录行动。裁决：defended（条件同 D2）。**

子若作为普通 session，其动作写在自己的 task 流上：`POLICY_DECIDED`（`action_pipeline.py:276-281`）、receipt（`capability.py:214-227`）。需探针确认（P9）。

**F2 — 父 roll-up 需要新契约面，且与 digest-only 冲突。裁决：not defended。**

`SurfaceSessionSnapshot`（`surface.py:160-170`）有 `message_count`/`pending_approval`，**没有** children 字段；`SurfaceSessionSummary`（`surface.py:173-186`）同样没有；协议版本是硬编码字面量 `Literal["1.1"]`（`surface.py:161, 190, 196` 等）。设计的"父回合暴露 children[] 与含子的 totals"因此需要**契约变更**——`docs/product/AB-P3A-MULTIAGENT-TASK-TREE-2026-09-16.md:18-21` 的先例是"additional-only → 升 minor 且保留旧解码"。

**并且它和 digest-only 冲突（见 F3）：** 若父回合把子的 `text` 作为 tool result 回填，那段文本会进入父的 `SESSION_MESSAGE_RECORDED`（`action_pipeline` → loop → `task_service.record_session_message`，`task_service.py:673-683`）。设计明确说 `text` 是"child's final assistant text"——所以**子的完成文本会被 durable 保存到父的流里**。

**F3 — digest-only 作为系统属性不成立。裁决：not defended（作为系统属性）；作为两个事件上的窄口径成立。**

子代理说到底就是**一个普通会话**。它的第一条 user 消息就是 spawn prompt，由 `record_session_message` 写进 `SESSION_MESSAGE_RECORDED`，payload 里带 `"message": message.model_dump(mode="json")`（`task_service.py:671-681`）——**全文在库里**。同理子的助手文本也会落库。

所以设计里那句 "Durable model (append-only; **NO prompt or completion TEXT** - digests only)" 只在**它自己那两个事件**（`CHILD_AGENT_SPAWNED`/`CHILD_AGENT_FINISHED`）上成立。如果 ADR 把它写成"派生不落提示词文本"这种系统级隐私属性，那就是**不成立的声称**。ADR 必须把口径写窄到事件级。

（附带确认：本条与"投影层不泄露内容"是两件事——`SurfaceSessionSummary` 的最小化是**读路径**的性质，`surface.py:173-178`；写路径照样落全文。）

**F4 — provider 日志泄文本。裁决：defended。**

`AGENT_OS_PROVIDER_LOG` 是 opt-in JSONL，每条记录只有 latency/tokens/outcome/failure code/retry_after，**明确不含 prompt 或完成文本**（`docs/CURRENT_STATE.yaml:52` 的 (d)）。这是既有性质，spawn 不改变它。

**F5 — 父 roll-up 少报失败。裁决：undetermined（投影权威源未写）。**

设计说父的 totals INCLUDE children、每个子有 status。但**投影的权威源**没写：从 durable 事件算（则崩溃后仍可重建），还是从 spawn 管理器的内存状态算（则崩溃后丢失）？这决定了"一个 timed-out 或 crashed 的子会不会从 roll-up 里消失"。见 P6。

### G 组：Stop 与 liveness

**G1 — 子活过父的 pause/correct。裁决：not defended（与 C2 同根）。**

见 C2：`pause_task`/`correct_task` 都只作用于父自己的 task/run 键（`app.py:2487-2492`、`:2912-2915`、`:2951-2976`、`:2963`），而子的动作查自己的键（`governance.py:372`、`capability.py:154-163`）。C2 的后果是"子仍能执行效果"，G1 的后果是"父看起来停了但子还在跑"。两者是同一个根因的两种读法。

**G2 — 子活过父的 close。裁决：not defended。**

`SESSION_CLOSED` 是 per-session 的事件（`runtime.py:95`；`task_service.py:1470`；`agent_loop`/`task_service` 用它阻止 closed 会话再写消息，`task_service.py:665-666`）。设计的 "a child never outlives its parent session's closure" 同样是**新的级联要求**：谁在父 close 时去 close 子？没有现有机制。而且注意方向：父关闭**不会**阻止子的流继续写（子流没关）。

**G3 — `stopped` 被读成"无副作用"。裁决：defended（C7 语义如此），必须显式声明。**

`docs/architecture/C7-BOUNDARY-STATEMENT.md:19-23` 写得很清楚：收据是 **pre-commit 线性化 token，不是中断**；"It does **not** interrupt an effect that was already dispatched before the correction"。所以"停掉了子，但仍有一个已派发的效果事后落地"是**既有 C7 语义**，不是 spawn 引入的洞。但设计的状态名 `stopped` + "each ends durably with `stop_reason=stopped_by_operator`" 很容易被读成"没有副作用会发生"。ADR 必须写明：`stopped` = 不再派发新效果 + 已派发效果走既有 custody/compensation 路径（`docs/architecture/C7-BOUNDARY-STATEMENT.md:22`）。

**G4 — 运行期死亡时的 in-flight 子无人收尸。裁决：not defended（设计沉默）。这一条尤其重要，因为本仓刚为单会话修过同一类缺陷。**

**本仓对单会话的修法**（我实际读到的，与 `docs/CURRENT_STATE.yaml:53` 的位置提示略有出入——该 pin 引 `surface_runtime.py:73,405-421`，本基线实际是 `:70-75` 与 `:417-422`）：

- 测试：`tests/product/test_surface_stream_lifecycle.py:519` `test_daemon_crash_recovers_from_durable_boundary_only`。它 kill 掉 daemon（`:558` `first.crash()`），启第二个 daemon（`:562-567`），然后断言四件事：(a) 会话从**最后一个 durable 边界**恢复（`:566-568`）；(b) 旧世代的 stream 报 typed `SurfaceStreamStaleError`（`:570-576`）；(c) in-flight turn 显示为**未完成**，`started_ids` 与 `completed_ids` **不相交**（`:583-591`）；(d) 新订阅**不伪造**死回合的帧（`:593+`）。
- 机制：`_begin_turn_once` 用 `surface_has_uncommitted_turn`（`surface_runtime.py:417-422`），后者从 durable 事件算 `SESSION_TURN_STARTED − SESSION_TURN_COMPLETED`（`app.py:2299-2319`）。

⇒ 单会话的修法是"**不伪造 + 从 durable 边界恢复 + 客户端进入 stalled 状态**"，**不是**自动续跑。

**这个修法对子代理不可直接照抄：**
- 崩溃后，父的 `agent.spawn` 动作处于 "已 reserve、未 seal" 状态。恢复时 `reconcile_before_policy` → `DurableActionOutcomeRepository.replay` 会把它判成 `RESERVATION_WITHOUT_OUTCOME → UNKNOWN`（`_action_outcome.py:142-145`），并被 `agent_loop` 判为非成功、不自动重发（`docs/adr/ADR-0059-...:36-42`、`agent_loop.py:344-370`）。**这是好的**（fail-closed，父不会自动重放 spawn）。
- 但**子会话没有任何人驱动**：它是进程内对象，崩溃后不存在。它会停在 "`SESSION_TURN_STARTED` 无 `SESSION_TURN_COMPLETED`" 的形态——与单会话同形，**但没有父回合在等它**（父回合已变成 unknown/暂停）。所以：
  - 谁写 `CHILD_AGENT_FINISHED{status=failed, stop_reason=runtime_died}`？设计只说了 `stopped_by_operator`。
  - 谁把子会话 close？
  - 父的 roll-up 会不会**永远**显示一个未终结的子（叠加 F5）？
- ⇒ **需要一个进程外的对账/收尸路径**（operator 可见、durable、幂等），设计完全没有。

**G5 — 崩溃后 fan-out 配额被重置。裁决：not defended。** 见 E1。

### H 组：操作者真相

**H1 — 子报 completed 而实际不是。裁决：undetermined。**

设计的 status 枚举存在，但 **status 的来源**没写：由父的 spawn connector（同进程调用方）判定，还是由子的自报判定？另外 `text` 明确"never an echo of the prompt"，但没说它必须是子的**最后一个 assistant 消息**——今天的代码里存在返回**合成文本**的先例：`approval_required` 返回硬编码 `"approval required"`（`agent_loop.py:1024`），`unknown_requires_review` 返回 `"capability effect requires external reconciliation"`（`agent_loop.py:366, 580`）。若子走到这两条路径，就没有"子的最终助手文本"可取。ADR 必须定义 status/text 的权威源。

**H2 — roll-up 藏失败。裁决：undetermined。** 见 F5。

**H3 — 子的动作被 operator 误认为父的。裁决：not defended（界面层）。**

两个叠加因素：(1) 生产路径只有单一 gateway 实例可选，而 `ConfirmationGateway.confirm` 的签名只有 `(action, preview)`（`agent_loop.py:113`）——**没有 session/agent 标识**；(2) `_action_preview`（`agent_loop.py:1852-1867`）也不含 session/agent 标识。前端侧的呈现本次未读（见 §5），但仅从内核侧的确认载荷看，operator 无法区分"父在请求确认"与"子代在请求确认"。

**H4 — 审计可区分归属。裁决：defended（durable 层）。**

子的动作写在自己的 task 流上，`ActionContract` 带 `task_id/run_id`（`authority.py:163-164`），`POLICY_DECIDED` 落 `decision` 全文（`action_pipeline.py:276-281`）；设计还要求 child session events 携带 `parent_session_id + parent_turn_id + spawn_id`。所以**事后**归因是可行的——这也是为什么 H3 是"界面层"问题而不是审计层问题。

---

## 3. 残余风险：ADR 必须显式写出，而不是留白

按严重度排序。前三条是我认为**不写就不能过 C6/C7 保持性门**的。

1. **C7 不级联（C2/G1）。** ADR 必须二选一并给出证明：
   - (a) 新增一条级联轴（例如子动作的检查同时查祖先 task 键），并证明它**属于** C7（不可被 agent 写、不可被绕过、可被外部收紧、有 canary/rollback）；或
   - (b) 明确承认 C7 的"停父"不达子，operator 只能靠 capability 轴全局关闸或逐会话停子，并把这一限制写进 operator 可见文档与 UI。
   无论哪条，都要说清"stopping the parent stops its in-flight children"到底由**谁**强制、是否可被进程内 bug 绕过、崩溃时是否仍成立。
2. **崩溃后 in-flight 子的归属与收尸（G4/G5/E1）。** ADR 必须规定：崩溃后谁写终结记录（建议 `CHILD_AGENT_FINISHED{status=failed, stop_reason=runtime_died}`）、谁关子会话、父 roll-up 如何呈现未终结的子、以及 per-turn 配额在重启后**如何从 durable 事件重算**（而不是归零）。
3. **"子授权更窄"的载体与强制点（A1/A4/A5/A6/D3）。** ADR 必须点名一个**执行点**（不是工具广告层），说明它在重启后如何重建（A2），并说明 `agent.spawn` 自己的 risk tier、以及它进入 E2 冻结表（`permission_gate.py:23-31`）、`CHAT_CAPABILITY_IDS`（`agent_loop.py:67-75`）、`CHAT_GRANT_MAX_RISK_TIERS`（`agent_loop.py:84-90`）的方式。
4. **子会话的 `ConfirmationGateway`（B2/B3/B4）。** 必须指定；`DeferredApprovalGateway` 在嵌套调用里没有 operator 可 park，`AutoApproveGateway` 明令不得进生产路径。
5. **输出契约的状态枚举必须能表达"子停在待审批"（B2）。** 建议加 `awaiting_approval` 并定义 `text` 在该状态下的语义；否则 `timeout` 会被误用。
6. **`text` 的权威源（H1）。** 必须排除合成文本（今天有先例，`agent_loop.py:366, 580, 1024`）。
7. **digest-only 的口径要写窄（F3）。** 明确"仅指这两个事件"，并承认 spawn prompt 与子的完成文本会进 `SESSION_MESSAGE_RECORDED`（`task_service.py:671-681`）。
8. **N 的量词语义（E2）。** 写清 N 界住什么、**不**界住什么；写清树的总量/总时长/总成本没有任何界。
9. **E4：`budget_limit(child) <= parent's remaining budget` 的"剩余"目前不存在。** 要么实现账本，要么降级为静态上限单调收缩。
10. **E5：同步 spawn 的墙钟后果。** 父回合被子的时间占据，而 `AgentLoopConfig` 没有墙钟项（`agent_loop.py:151-158`），`REF-ARCH-04:53` 自陈 organ 侧墙钟未完成。必须给出 timeout 语义，并回答"子的时长与父 run 的 5 分钟 execution lease（`_action_outcome.py:92`）"的关系。
11. **E3：nested spawn 的开启方式**不能是 env 只读开关；必须是受权动作。
12. **G3：`stopped` ≠ 无副作用。** 引 `C7-BOUNDARY-STATEMENT.md:19-23` 明确写入 operator 可见文档。
13. **A3：`permission_mode` 的父子关系**必须显式决定（继承？上限？）。
14. **C4：minus 集合必须含 selfdev/promotion 面。**
15. **F2：父 roll-up 是契约变更**（`surface.py:161,190,196` 的 `Literal["1.1"]`），要按 `AB-P3A:18-21` 先例定版本策略；并写清投影的权威源（durable 事件 vs 内存）以支撑 F5/H2。
16. **D3：子会话的 grant 签发者与事件类型**必须定义；`action_pipeline.py:256-260` 的 `KeyError` 应改成类型化拒绝，否则"窄化生效"的测试写不成 fail-closed 形态。
17. **A6 的小不一致：** "超过 N 报 typed `ChildAgentLimitExceeded`"（异常）与输出里有 `status: limit`（返回值）不能是同一次发生。二选一。

---

## 4. 可证伪探针（供后续 reviewer 执行）

全部**未执行**（docs-only）。每条都写成"可运行 + 可失败"。

- **P1（A2 重启提权）**：spawn 一个 `explore` 子；记录 `child_session_id`；重启 daemon；对该会话走一次 `restore_chat_session`（或 `/resume`），在 restore 处打印 `grants` 的 key 集合；随后投递一个 `workspace.edit` tool call。期望（安全）：grant key 集合与 spawn 时**逐字相同**，且投递得到类型化拒绝。当前代码路径（`app.py:2167` → `:2880-2892`）预期会让它**通过**并给出全量授权 + 提升后的 tier ⇒ 复现即证明 A2。
- **P2（C2 C7 不级联，可直接复现）**：(a) 建父会话与一个子会话；(b) `POST /v1/surface/correct` 父会话（触发 `app.py:2963` 的 `correct("task", parent_task_id)`）；(c) 让子会话发起 `workspace.shell`（tier 3，`permission_gate.py:30`）并经 operator 审批；(d) 断言子的 `PolicyKernel.decide` 是否 ALLOW（`governance.py:372`）。期望（安全）：DENY。当前脊预期 ALLOW ⇒ C2 之外的**第二个可复现缺陷**（P1 是 A2，P2 是 C2），且比 P1 更严重。
- **P3（A5 强制点）**：在 `ACCEPT_IN_WORKSPACE` 的 explore 子会话里**绕过工具广告**，直接用 stub provider 投递 `workspace.apply_patch`（可复用 `tests/product/test_permission_mode_matrix.py` 的驱动方式）。期望：类型化拒绝。当前 `evaluate_permission_gate` 只查全局表（`permission_gate.py:58-79`）⇒ 预期 `MODE_AUTO_ALLOW`。
- **P4（E2 树的界）**：depth-2 树、每层 N=4，断言同层并发 ≤ N **且**总量可以是 16。期望：通过。这条探针的作用是**把设计的真实语义钉死**（N 不是树的界），而不是找 bug。
- **P5（E4 预算是否含子）**：spawn 一个会大量消耗 token 的子，断言父回合的 `max_turn_tokens`（`agent_loop.py:154`）是否因子的消耗而更早触发。期望（若 ADR 声称预算含子）：触发。当前父的计数来自父自己的 provider usage ⇒ 预期不触发。
- **P6（G4 崩溃收尸）**：在子回合中途 SIGKILL daemon（复用 `tests/product/test_surface_stream_lifecycle.py:519-600` 的 harness 模式），重启后断言：(a) 子会话有 `SESSION_TURN_STARTED` 无 `SESSION_TURN_COMPLETED`；(b) 存在一条终结记录（期望：ADR 规定必须有）；(c) 父 roll-up 不再显示 in-flight 子；(d) 没有任何组件会再驱动子会话。当前设计下 (b)(c) 预期失败。
- **P7（F3 digest-only）**：spawn 一个子，然后在 SQLite 中检索 spawn prompt 的明文是否出现在 `SESSION_MESSAGE_RECORDED` 的 payload 中。期望：**能检索到** ⇒ 证明 digest-only 不能作为"提示词不落库"的系统级宣称。
- **P8（B1 正面证据）**：用父会话的 pending `ApprovalDecision`（含其 `action_digest`）调用 `resume_pending_approval(child_session, approval)`。期望：`InvalidTransitionError`（`agent_loop.py:525-534`）。这条预期**通过**，是 B1 的正面证据。
- **P9（D1/D2 第二条路径）**：(a) grep/调用图断言 `connector.execute` 全仓只有一个调用点（`capability.py:193`）；(b) 断言子在**子的** task 流上为每个动作产生 `POLICY_DECIDED` + `ACTION_RECEIPT_RECORDED`（`runtime.py:62-63`）。若子的动作没有 `POLICY_DECIDED`，则存在第二条路径。
- **P10（E3 nested spawn 开关）**：只改环境变量（`AGENT_OS_MAX_CHILD_AGENTS` 或同类开关），断言 general 子**不能**获得 `agent.spawn`。期望：失败/需 operator 授权记录。若只改 env 就能开启，则 E3 成立。
- **P11（B2/H3 审批等待与归因）**：让子触发 tier-2 确认，断言：(a) 确认载荷含 `spawn_id`/`child_session_id`；(b) operator 拒绝子的确认**不影响**父的 pending；(c) 子进入 waiting 时 `agent.spawn` 返回一个**可区分**的状态而不是 `timeout`。当前 `ConfirmationGateway.confirm(action, preview)` 的签名（`agent_loop.py:113`）与 `_action_preview`（`:1852-1867`）都不含这些标识 ⇒ (a) 预期失败。
- **P12（G3 stopped ≠ 无副作用）**：让一个子的动作进入 `UNKNOWN`，然后 stop 子，断言 receipt 语义：`UNKNOWN` 未被改写为 `FAILED`/`CANCELLED`（`ReceiptStatus` 定义见 `authority.py:51-58`），且不自动重发、不自动补偿（ADR-0059:52-56）。期望：通过（这是既有语义的确认，不是找 bug）。
- **P13（E5 lease TTL）**：让一个子回合超过 5 分钟（`_action_outcome.py:92` 的默认 TTL），断言父 run 的 `agent.spawn` 动作在 seal 时是否仍被接受（`_action_outcome.py:243-297` 不重查 fence/过期），以及在此期间是否有第二个 owner 能拿到更大的 fence。**这条我无法从 docs-only 判定**（未读 `persistence.py` 的 `_acquire_lease_in_transaction` 与过期回收逻辑），因此它是"未确定"的探针。
- **P14（C1/C3 端口最小化）**：静态断言 `agent.spawn` connector 的构造签名不含 `CorrectionAdminPort`/`CorrectionAdminView`；以及断言仓库中不存在"在 `AgentLoop._drive` 内直接调用 spawn 管理器"的分支（即 spawn 必须是 connector effect）。

---

## 5. 我自己的局限（必须被读进去）

1. **本评审评审的是设计，不是代码。** 在基线上 **ADR-0061 与 `agent.spawn` 的实现都不存在**（§0 已证）。所有"not defended"的裁决都是"**按声明的设计 + 现有脊**，强制点不存在或设计沉默"，**不是**"生产代码已被攻破"。任何一条都可能在实现落地时被正确关闭。**实现落地后必须有一次代码级复审**，且那次复审必须重跑 P1–P14。
2. **探针一条都没跑。** docs-only + 硬约束禁止启动 daemon / 触碰 `~/.agent-os/`。P1–P14 全部是**待执行**。
3. **未核实的点，明确列出**：
   - (a) SQLite execution lease 的到期与回收语义（只读了 `persistence.py:286-323` 的入口与 `BEGIN IMMEDIATE` 注释，未读 `_acquire_lease_in_transaction`）⇒ P13 结论未定；
   - (b) headless `-p` 路径是否真会用到 `AutoApproveGateway`（`apps/` 全目录 grep `AutoApprove` 为 0 命中，但该 docstring 自陈曾经接过）⇒ B4 的这一分支未定；
   - (c) 终端/TUI 侧的审批呈现（`apps/cli-ts/src/controller.ts` 等未读）⇒ H3 的界面结论只基于内核侧确认载荷缺 session 标识这一处代码事实，不是 UI 实测；
   - (d) `SurfaceSessionStatus` 的完整取值与 `stalled` 判定（只读了 `surface.py` 的一部分与 `surface_runtime.py`）；
   - (e) 我没有验证"父会话 close 时若子仍在飞，子流能否继续写"（G2）——这一条是从 `SESSION_CLOSED` 的 per-session 性质推的，未构造场景。
4. **身份诚实。** 我是**同模型 subagent reviewer**。`builder_id != reviewed_by` **不满足**，**没有** independent-provider approval。因此：
   - 本评审**不能**被引用为根 `AGENTS.md:132` 所要求的 "C6/C7 preservation proof + independent reviewer identity" 中的独立评审；
   - 也不能替代 CTO gate（仓库 `AGENTS.md:99` 把 C1–C7/SD4 移动列为 founder 保留事项）；
   - 借用 `docs/CURRENT_STATE.yaml:52,59` 已经用过的口径：这只是"**子代理/同模型**"级别的技术意见。
5. **我尝试过但没能证伪的**（应当被记录为"设计里最强的那部分"）：B1（审批 digest 绑定）、C1（C7 写端口隔离）、D1（唯一 dispatch path 在代码里确实只有一个 `connector.execute` 调用点）、P8/P12 所对应的既有语义。这些是我尽力攻击之后**活下来**的部分，它们不是我"没找"的地方。
6. **我没有做的事**：未修改 `docs/CURRENT_STATE.yaml`（coordinator-owned）；未修改 ADR（parallel author）；未动 `~/.agent-os/`；未启动 daemon；未使用 `git stash`。

---

## 6. 结论

**冻结设计的骨架是对的**：一 Agent 一 session 从而不解除"每会话一回合"、子动作仍经 `CapabilityBroker.invoke`、审批 digest 绑定、C7 写端口在类型上不可达、durable 记录 append-only——这五条在代码证据上站得住，我尽力攻击后没有推翻它们。

**但有三处不写清楚就不能认为边界已移动：**

1. **C7 不级联**（C2/G1，`governance.py:129-138` + `app.py:2963` + `governance.py:372`）。这是最严重的一条：它是"operator 最自然的停父杠杆对子无效"，而且**今天就能用 P2 复现**。
2. **崩溃后 in-flight 子的收尸与配额重算**（G4/G5/E1）。本仓刚为单会话修过同一类缺陷（`tests/product/test_surface_stream_lifecycle.py:519-600`），但这个修法**不自动 compose 到子代理**——因为子没有父在等它。
3. **"子授权更窄"缺少载体与强制点**（A1/A2/A4/A5/A6/D3）。现有脊是 principal 作用域的（`governance.py:356-360`、`surface_runtime.py:501-510`），没有 agent/session 维度；`restore` 路径会把窄化抹平（`app.py:2167` → `:2880-2892`）；GC 自己也说过这条单调性在流程侧是 advisory（`.agents/skills/subagent-governance/SKILL.md:39-40`）且"不能由流程规则直接继承"（`GC-P3:72`）。

其余 14 条残余风险（§3 的 4–17）属于"必须显式声明/补契约"级别，其中 B2（输出状态枚举无法表达子停在待审批）是我认为最容易被实现者踩到的契约不自洽。

**建议的下一道门**：ADR-0061 作者按 §3 逐条回应 → 落地实现 → 用一个**不同 provider** 的 reviewer 执行 P1–P14 并出具代码级复审。本次评审不足以作为 C6/C7 边界移动的独立依据。
