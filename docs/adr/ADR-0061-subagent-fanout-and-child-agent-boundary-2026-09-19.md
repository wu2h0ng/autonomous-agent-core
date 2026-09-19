# ADR-0061: Subagent Fan-out 与子会话边界（Form B）

- Status: **Accepted**（founder 2026-09-19 授权 Form B；本 ADR 与实现同批落地，不阻塞实现）
- Date: 2026-09-19
- Deciders: founder（形态授权与边界移动）；架构判断由 agent 起草，评审等级见 §9（**非独立 provider 批准**）
- Track: Product Track（产品能力）；不得由研究证据或工程流程证据回填
- Baseline: `origin/main = 03ac66b5`（worktree `.worktrees/wt-adr61`，branch `docs/adr-0061-subagent-fanout-20260919`）
- Upstream: `docs/product/GC-SUBAGENTS-AND-FANOUT-2026-09-18.md`（D1/D3/D4 的设计输入，`DESIGN_ONLY/NO_IMPLEMENTATION_AUTHORITY`）、`docs/product/GC-P3-MULTIAGENT-TASK-TREE-2026-09-16.md`、`docs/product/AB-P3A-MULTIAGENT-TASK-TREE-2026-09-16.md`
- Preserves: C6、C7、SD4、`ADR-0033`/`ADR-0037`/`ADR-0054`、`ADR-0055`、`ADR-0059`、所有历史 verdict 与 migration/release gate
- 编号核查（baseline 实测）：本仓 `docs/adr/` 在 baseline 上最高已接受编号为 `ADR-0059`；`ADR-0056` 空号；`ADR-0060` 仅被未合并分支 `codex/spine1-donor-extraction-20260915` 上的 `ADR-DRAFT-0060-donor-repository-retirement-2026-09-15.md` 占用；`ADR-0039/0040/0041` 为历史重号不得复用。**0061 在 baseline 上空闲，本 ADR 占用之。**

## 1. Context

### 1.1 今天产品线处在哪

终端 surface（`apps/cli-ts` + `apps/api_server` + `apps/runtime_daemon` + `packages/os_core`）支持**多智能体工作的 A 形态**：操作者自己驱动多个互相独立的会话，每个会话一个 in-flight turn，外加一个只读的 agent/task 树与跨会话切换。A 形态**零内核改动**且不引入任何新授权。

今天**不存在**任何"一个 agent 派生并驱动另一个 agent"的能力。实测事实：

| # | 事实 | 位置 |
|---|---|---|
| F1 | 模型可见的能力是**硬编码 7 项**常量；其中无任何"创建会话/驱动回合"项 | `packages/os_core/src/agent_os_core/agent_loop.py:65-75`（该常量就是实际下发的 `allowed_capability_ids`：`agent_loop.py:1282,1931`） |
| F2 | 模型提议的动作以 `ActionContract` 构造，经 `ActionPipeline` 执行，使 `PolicyKernel.decide → permit → CapabilityBroker` 成为**唯一执行路径** | `agent_loop.py:193-200` |
| F3 | developer domain pack 的 manifest 只注册 4 个能力，内核不含任何 workspace/会话语义 | `domain_packs/developer_agent/__init__.py:46-61` |
| F4 | 每**会话**一个 in-flight turn；第二次 begin-turn 报 typed `SurfaceTurnInProgress`；无排队、无多路复用 | `packages/os_core/src/agent_os_core/surface_runtime.py:70-75,417-422` |
| F5 | surface 层**不区分主体**：每个 client 必须绑定同一个 runtime principal（principal/tenant/workspace 三者全等） | `surface_runtime.py:501-510` |
| F6 | 会话的 grant 由**组合根**构造，不来自模型：`self.grants` 按 `CHAT_CAPABILITY_IDS` 取子集并按 `CHAT_GRANT_MAX_RISK_TIERS` 校验 | `apps/api_server/app.py:2027-2039` |
| F7 | 授权按 grant 绑定 principal+tenant+workspace+capability+version+`max_risk_tier`+`budget_limit` | `packages/contracts/src/agent_os_contracts/capability.py:71-83` |
| F8 | policy 对 scope/version/风险 tier/预算/审批逐一 deny，fail-closed | `packages/os_core/src/agent_os_core/governance.py:341-389` |
| F9 | permit 绑定 action digest、lease fence 与 5 分钟过期；broker 在派发前校验 | `governance.py:479-499`；`packages/os_core/src/agent_os_core/capability.py:140-163` |
| F10 | tier≥3 必须有真人 `ApprovalDecision`，否则 `ESCALATE/APPROVAL_REQUIRED`；审批票绑 `action_digest` | `governance.py:378-385`；`packages/contracts/src/agent_os_contracts/authority.py:200-218` |
| F11 | C7 在执行侧只**读**：`CorrectionReadPort` 只暴露 `snapshot`/`halted`/`guard_unchanged`；写口 `CorrectionAdminPort` 明确"reserved for authenticated operator/admin paths" | `governance.py:62-77,141-158` |
| F12 | 权限门是冻结 allowlist × mode × tier；id 不在 `ACTION_RISK_TIERS` → `DENY_OUT_OF_ALLOWLIST`，**每个 mode 都 fail-closed 且永不可批准** | `packages/os_core/src/agent_os_core/permission_gate.py:23-31,58-65` |
| F13 | 单会话"停掉"**在 baseline 上不生效**：`RunStatus.QUEUED` 的允许迁移集不含 `PAUSED`，`pause_task` 抛 `InvalidTransitionError` | `packages/os_core/src/agent_os_core/task_service.py:2396-2410`；`apps/api_server/app.py:2487-2492,2912-2915`；`docs/CURRENT_STATE.yaml:51` 缺陷 (a) |
| F14 | 权限 DENY 不产生卡片（`DENY_BY_RULE` 不发 `ACTION_PROPOSED`），操作者看不见被拒 | `docs/CURRENT_STATE.yaml:51` 缺陷 (b) |
| F15 | 今日 durable 事件词汇表里没有 session→parent-session 关系 | `packages/contracts/src/agent_os_contracts/runtime.py:50-95` |
| F16 | 受治理产品门与 cli-ts 门都在 CI，且接线自守覆盖 | `.github/workflows/ci.yml`；`tests/product/test_ci_gate_wiring.py:1-30` |

### 1.2 为什么这一步需要 ADR 而不是一份 GC

`docs/product/GC-SUBAGENTS-AND-FANOUT-2026-09-18.md` 已判定：B 形态（父会话派生子会话并扇出）引入一条**新的控制路径**——模型输出 → 创建会话/驱动回合——因此是 C6 控制路径边界移动，需要**新 ADR + C6/C7 保持证明 + 安全评审 + canary/rollback + 独立评审身份**。该要求与宪法一致：根仓 `AGENTS.md:132` 规定"任何边界移动都需要 founder ADR、可证伪 gate、C6/C7 保持证明、独立评审身份、canary/rollback 且不得自我批准"。

**founder 2026-09-19 授权 Form B**，并指示按主流实践**一次做成**，而非"A 先行、B 以后再说"。本 ADR 是那次授权所要求的产物，并与实现同批落地。

### 1.3 本 ADR 的证据纪律

- 每一条关于本仓的事实都给出我在 baseline 上**实际读到**的 `file:line`；
- 关于他方（主流工具）的事实给出 URL + 抓取日期，并区分 `[vendor-doc]`（厂商文档，描述意图，不证明可靠性）与转引；
- 凡是我无法核实的，进入 §13 未核实清单，不写进论证。

## 2. Options Considered

| 选项 | 内容 | 代价 / 与 C1–C7 的关系 | 判断 |
|---|---|---|---|
| **A. 只做 A 形态收尾** | 操作者驱动多会话；先补单会话停止、DENY 可见性、成本归因 | 零边界移动；但"agent 系统"的对等能力仍缺失，且 A 形态自身被 F13 阻塞 | 不作为本次路线（founder 已明确要 B） |
| **B. 父派生子会话 + 扇出（本 ADR）** | 新 typed capability `agent.spawn`；子会话是真实 session/task/run | 移动 C6 控制路径边界；需要本 ADR + 保持证明 + gate + canary/rollback | **选定** |
| **C. 不新增 capability，让模型直接调 surface HTTP** | 模型输出直接构造 `POST /v1/surface/sessions` 等请求 | **违反**根仓 `AGENTS.md:34`、`docs/AGENT-OS-PRODUCT-BLUEPRINT.md:308-309`："untyped model output 不得直接成为后果性命令"；且会绕过 permit/C7/admission，产生第二条派发路径 | 拒绝（这正是必须避免的形态） |
| **D. 只做"只读子代理"（explore-only，不做 general）** | 子代理只能 `workspace.read`/`workspace.search` | 风险最小，但"派生并驱动"的控制路径仍然存在，边界移动**不会因此消失**；同时放弃对等能力 | 拒绝为唯一形态；**保留为嵌套默认关闭的降级形态**（`explore` agent_type） |
| **E. PARK** | 不做 | 无边界移动 | 与 founder 授权冲突，且 GC 已判定前置缺口（F13）本身值得做 |

**最强反方论证（记录，不软化）**：`docs/architecture/REF-ARCH-03-agent-role-contract.md:28-33` 明确写 `many autonomous agents loosely coordinated ❌`，理由是"role A 说 yes、role B 执行、role C 没有证据、runtime 只记录了它，于是**没有人为结果负责**"，结论是 `One subject loop = one accountable boundary`。Form B 在字面上增加 loop 数量。本 ADR 必须回答的是：**新增的边界在哪里**、**哪一条不变量承接了"一个可问责边界"**、以及**什么观测会证明我们答错了**。见 §4.6。

## 3. Decision

### 3.1 移动的东西（精确）

批准 **B 形态**：父会话在一个回合内可以经一个 **typed capability `agent.spawn`** 派生一个**真实子会话**（child session + task + run），把子会话的一个回合**驱动到结束**，并把子会话的最终 assistant 文本作为该次 capability 调用的结果返回父会话。

被移动的边界只有一条：

> 模型输出今天只能触及"本会话能力集内的效果"；此后它还多触及**一个节点**——"创建一个会话/task/run 并驱动它的一个回合"。

### 3.2 明确**没有**移动的东西

1. **没有第二条派发路径。** 子会话的每个动作仍然只经 `CapabilityBroker.invoke`（同一个类、同一份代码、同一个组合根）。`agent.spawn` 自身也走同一条路径。
2. **C7 未被触碰。** 不新增 correction 写口；`CorrectionAdminPort` 仍只属认证 operator/admin 路径（`governance.py:71-77`）。
3. **没有新 principal。** surface 层一个 daemon 一个 principal（F5）；子会话与父会话同 principal/tenant/workspace。"子代理身份"只能表达为 task/run/grant/permit 的绑定。
4. **没有新权威根。** evaluator / promotion / audit / C7 根不变，子会话与父会话共用同一根。
5. **`ActionReceipt` / `ReceiptStatus` 语义不变**（`packages/contracts/src/agent_os_contracts/authority.py:51-58,267-281`）。
6. **每会话一个 in-flight turn 不变**（F4）。子会话是会话，因此它自己也只有一个 in-flight turn；并发发生在**会话之间**。
7. **冻结 E2 矩阵语义不变**（F12）：只是新增一个 allowlist 条目；allowlist 之外依旧每个 mode fail-closed 且不可批准。
8. **没有批量或自动批准**：tier≥3 仍需真人 `ApprovalDecision` 且绑定**该子动作**的 digest。
9. **不新增终端治理/执行入口**：创建/派生仍 API-only（沿 Stage 2c/2d 的既有处置，`docs/CURRENT_STATE.yaml:26`）。
10. **无跨仓 import/copy**（根仓 `AGENTS.md:40`）。

### 3.3 为什么"是 capability 就够"

本 ADR 的判断是：把 spawn 做成**一个 capability**，而不是做成一条特殊通道，是"边界移动可被治理"的关键。原因是这条链上**每一步都已经存在且 fail-closed**：

```
模型输出（untyped）
  -> ActionContract（typed，带 digest）
  -> PolicyKernel.decide（scope/version/tier/budget/approval 逐项 deny）      governance.py:341-389
  -> ActionPermit（绑 action_digest + lease fence + 5min + correction epochs） governance.py:479-499
  -> CapabilityBroker.invoke（permit 匹配 -> lease fence -> 过期 -> C7 halted/epoch
                             -> 确定性 preflight（deny 先于任何 reservation）
                             -> reserve -> guard_unchanged -> 物理执行 -> seal）capability.py:132-227
```

任何一步缺失 ⇒ `CapabilityDenied`。因此模型永远拿不到"创建会话"这件事本身，它只拿到"**提议**创建会话"，而提议要过与所有其他动作完全相同的门。

### 3.4 边界移动的替代读法（诚实记录）

同一事实也可以被读成"我们只是新增了一个会创建一个容器对象的 capability，就像 `artifact.write` 会创建一个文件"。本 ADR **不接受**这个读法，理由可证伪：`artifact.write` 创建的是**被治理对象内部的数据**，而 spawn 创建的是**另一个治理域实例**（带自己的 task/run/grant/permit 生命周期与自己的审批面）。后者改变了"模型输出能触达的对象类型集合"，所以按 GC 与根仓 `AGENTS.md:132` 的标准，它是边界移动。把它写成 capability 降低的是**实现风险**，不是**边界移动的事实**。

## 4. C6/C7 保持证明

本节是全文最重要的部分。§4.1/§4.2 给出 C6、C7 在本仓**实际是什么**（含 `file:line`）；§4.3–§4.5 给出**可证伪的**保持论证，并逐条标注 `[证明]`（结构性事实，读码可得）与 `[推断]`（依赖实现按本 ADR 落地后由 gate 证否）；§4.6 记录最弱点。

### 4.1 C6 在本仓是什么

**原文要点（哲学层，摘要）**：根仓 `docs/research/RR-0001-unified-autonomous-agent-architecture.md:62` —

> **C6 LLM 与世界模型皆为器官,不是主体**：LLM = 摊销推理先验；世界模型 = 业务状态空间上的预测器官；主体性在生存力核 + 主动推理回路 + 相关性场。

**工程层（可执行语义）**：`docs/architecture/REF-ARCH-02-model-organ-contract.md:28-36` 给出"器官**永不**可做"的清单：不得直接执行动作/调用会改状态的工具；不得绕过任何安全边界；不得写 policy、不得修改 Corrigibility Shell、不得设定自己的风险上限；不得决定审批或自我授权 R4/R5；不得修改安全基底（SD4）；自然语言置信度**不是**证据。该节最后一句是 C6 的准确表述：

> `This is the C6 discipline — the estimate stays out of the control path.`（`REF-ARCH-02:36`）

并且 `docs/architecture/REF-ARCH-01-system-reference-architecture.md:5-13,34` 把这一点写成参考架构的论点与图中标注：`Agent = the governed closed loop`、`← C6: organs out of control path`。

**"一个可问责边界"**：`docs/architecture/REF-ARCH-03-agent-role-contract.md:28-33` 的不可协商规则是 `multi-role reasoning INSIDE one governed loop ✅ / many autonomous agents loosely coordinated ❌`，理由与结论是 `One subject loop = one accountable boundary`。

### 4.2 C7 在本仓是什么

**原文要点（哲学层，摘要）**：根仓 `docs/research/RR-0001-unified-autonomous-agent-architecture.md:68` — C7 是"唯一钉死的元固定点（最高承诺，凌驾 C1–C6）"，四权为**观测（防欺骗）/ 暂停（防进行时损害）/ 回滚（防既成事实）/ 收紧（防漂移）**，且"罩在 Ring 0 之上，永不进入任何变异回路"。

**宪法层**：
- 根仓 `AGENTS.md:33`：`C7 是 non-writable、non-bypassable 的外部纠正权威；Agent 不得调用、模拟或清除 op_* 主权面`；
- 根仓 `docs/GOAL-BLUEPRINT.md:60,194,197`：权威根"不得被系统单方面写入或削弱"；`C7 是不可写、不可旁路的外部纠正权威`；`C6 控制路径边界、C7 纠正边界和 founder-reserved SD4 不因能力结果自动移动`；
- 本仓 `AGENTS.md:33`（同文）与 `AGENTS.md:38`（authority/correction/promotion core 必须自研，不可外包给 agent framework）；
- `docs/AGENT-OS-PRODUCT-BLUEPRINT.md:111`（`CorrectionChannel (C7)` = external pause/correct/tighten/halt authority，反义是 "writable or bypassable product setting"）与 `:309`（`C7 is non-writable and non-bypassable`）。

**工程层（本仓实际实现的形态）**：`docs/architecture/C7-BOUNDARY-STATEMENT.md` 明确 C7 在 contract 层的表现与**边界**：

- C7 表现为 digest 绑定的 `C7ClearanceReceipt`，由外部拥有的 `CorrectionAuthority` 签发，commit 前校验；scope 绑定（tenant/workspace/task/run/capability）是**必填参数对象**，不可省略（`C7-BOUNDARY-STATEMENT.md:9-13,31`）；
- §3 的 enforced/not-enforced 表**明确列出未强制项**：`worker/process compromise` **NOT enforced by option A**，"一个被攻陷的调用方只要从不调用 `verify`，本模块拦不住它"，因此**不作"抵抗被攻陷进程"的主张**（`:34-36`）；
- §5 明确非主张边界：`"Non-bypassable" is asserted only to the extent section 3 enforces`（`:44`）。
- 参考架构 `docs/architecture/REF-ARCH-04-runtime-governance-contract.md:20-23`：shell 可 pause/block/require approval，agent 不能覆盖；**修改纠正通道本身即 SD4，永久禁止**；C7 包裹整个 loop，且在 agent 的优化之外。

运行时代码：`packages/os_core/src/agent_os_core/c7_receipt.py:13-56`（verification scope 必填、四类 fail-closed 错误）；`governance.py:62-77,141-158`（读口 + admin 写口分离）；`capability.py:154-163,183-193`（派发前 halted/epoch 校验 + `guard_unchanged` 线性化）。

### 4.3 子代理不能放宽自己的授权 `[证明 + 推断]`

- `[证明]` 授权**不是模型产生的**：grant 由组合根构造（F6, `apps/api_server/app.py:2027-2039`），模型只能提议动作。
- `[证明]` 即使提议了越权动作，policy 逐项 deny：scope/principal 不匹配、grant 撤销、capability version 不匹配、`RISK_TIER_EXCEEDED`（`(action.risk_tier or spec.risk_tier) > grant.max_risk_tier`）、`BUDGET_EXCEEDED`（`governance.py:345-389`）。
- `[证明]` 跨会话复用父许可不可能：permit 绑 `action_digest` + `lease_fence`，broker 先查 `permit.matches(action)` 与 `execution_claim.fence == permit.lease_fence`（`capability.py:140-151`、`governance.py:486-499`）。
- `[推断]` **本 ADR 要求实现的新性质**（今天不存在，必须由 gate 证否）：`child_grants ⊆ parent_grants ⊆ task_grants`、principal/tenant/workspace 不得放宽、`max_risk_tier(child) <= max_risk_tier(parent)`、`budget_limit(child) <= parent 的剩余预算`。
  - 其中 **`parent 的剩余预算` 今天不是一个被测量的量**：grant 的 `budget_limit` 只用于**单次动作**的 fit 检查（`governance.py:376`），本仓没有跨会话总预算。因此这一条**必须**被读成"实现要新增的计算量"，或退化为安全上界 `budget_limit(child) := parent grant.budget_limit`（**不放宽**但没有真正的"剩余"语义）。**在没有跨会话预算测量之前，本 ADR 禁止声称"存在跨会话总预算"。**
- `[推断]` 子若未拿到某 capability，动作必须 `CAPABILITY_NOT_GRANTED`（`governance.py:351-352`）；这一点必须由带探针的测试证明，而不是读码。

### 4.4 子代理不能批准任何事 `[证明]`

- `[证明]` 审批票据是 typed 对象，且**只**能由 principal 或 tenant-admin 角色署名；`action_digest` 必填；过期时间必须晚于决定时间（`authority.py:200-218`）。
- `[证明]` 票据必须绑定**被批准的那个动作**的 digest，否则 `APPROVAL_DIGEST_MISMATCH`；过期则 `APPROVAL_EXPIRED`（`governance.py:378-381`）。
- `[证明]` tier≥3 若无真人 `ApprovalDecision`（或 disposition 不是 APPROVE）⇒ `ESCALATE/APPROVAL_REQUIRED`（`governance.py:382-385`）。
- `[证明]` 没有"服务端一次批准多个会话"的路径：审批是**按会话**的单次 POST，服务端只有一个本地 bearer（`docs/product/GC-SUBAGENTS-AND-FANOUT-2026-09-18.md:33` 的 F6 读码结论，引用 `apps/api_server/surface_routes.py:229-231,390-400,155-162`；**本 ADR 未独立运行期复现**）。
- `[证明]` 模型侧不可能"自己批"：approval 对象不经 tool schema 暴露；`AutoApproveGateway` 的 docstring 明确它只用于 hermetic 测试与非交互 `-p` 路径，且 tier≥3 仍 fail-closed、`must not be wired into interactive production paths`（`agent_loop.py:129-140`）。
- **因此**：子代理能做的只有**提出**审批请求；批准仍是操作者在**该子会话自己的卡片**上做的人动作。这是 §4.3 之外独立成立的第二条。

### 4.5 子代理不能写 C7，也不能动 evaluator/promotion/audit 根 `[证明]`

- `[证明]` 执行侧只持有 `CorrectionReadPort`（`snapshot`/`halted`/`guard_unchanged`），写口 `CorrectionAdminPort` 的 docstring 是 `Mutation contract reserved for authenticated operator/admin paths`（`governance.py:62-77`）。spawn 不新增任何 correction 写口。
- `[证明]` 派发被 `guard_unchanged` 线性化：在 `with` 块内若 correction 已变，`unchanged=False` ⇒ `CapabilityCorrectionBlocked`，效果不会被 seal 成成功（`capability.py:183-193`）。
- `[证明]` 能力名空间里没有任何"写 correction/halt、注册 evaluator、promote candidate、改写审计"的项：今天模型可见的 7 项全部是 workspace/session 类（F1），domain pack manifest 只有 4 项（F3）。spawn **只新增一个 id**（`agent.spawn`），不新增这些项。
- `[证明]` evaluator 根是 fail-closed 的具名校验面（`packages/os_core/src/agent_os_core/evaluator_authority.py:30-56` 的 typed 拒绝、`:89` 的 `TrustedEvaluatorRegistrationRegistry`）；promotion 根是 `materialization_promotion.py:79` 的 `DomainCandidatePromotionService`（需要完整链、grant 与第五方身份）；审计是 append-only 的 durable task 事件流（`packages/contracts/src/agent_os_contracts/runtime.py:50-95`）。**Form B 不触碰这三者的任何接口。**
- `[证明]` 协议级"不授权"先例已存在：外部信封入站的回执 `ProtocolIngressReceipt` 把三个授权位钉成 `Literal[False]`（`activation_authorized` / `capability_grant_authorized` / `external_effects_authorized`），且产出只允许 `TASK_DRAFT | HELP_REQUEST | NO_PROPOSAL`（`packages/contracts/src/agent_os_contracts/protocol_ingress.py:130-148`，字段在 `:146-148`）。这说明本仓已有"入站不携权威"的成型做法，Form B 沿用同一姿态。

### 4.6 最弱点：C6 的"一个主体 loop"

**必须诚实写明**：`REF-ARCH-03:28-33` 的规则在字面上被 Form B 打破——此后一次操作者会话可能同时存在多个 loop。

本 ADR 主张的保持方式是**逐层替换**，而不是宣称原句仍然逐字成立：

| 原句要求 | Form B 下的承接物 | 状态 |
|---|---|---|
| 一个**可问责**边界 | 一个 principal、一个 operator、一个 C7 根、一份 broker 实现、一条 evidence/audit spine | `[证明]` 结构性（F5、F11、`capability.py` 单实现） |
| 没有"A 说 yes、B 执行、C 无证据"的松散协调 | 每个子会话的动作都要**自己**的 grant + decision + permit + receipt；父的许可不可复用；子无法批准 | `[推断]` 依赖 G2/G3/G4 |
| 没有不受治理的 loop | 子会话与父会话走完全相同的门、评估与审计 | `[推断]` 依赖 G1/G5/G9/G11 |
| 结果归属清晰 | 归因投影：父回合的 `children[]`，每子 status/steps/tokens；父的合计**包含**子并明示 | `[推断]` 依赖 G7/G8 |

**会证否本 ADR 的观测**（若出现任一，则 §4.6 的替换不成立，本 ADR 的保持证明失败）：
1. 子会话获得父没有的 grant，或换到另一个 principal/tenant/workspace；
2. 子动作复用父的 permit/审批票被接受；
3. 子能在没有真人决策的情况下让 tier≥3 动作 sealed SUCCEEDED；
4. 子动作不落在子自己的 task 事件流里，或与父的动作共享同一 turn 归因；
5. `agent.spawn` 之外的任何 capability 也能创建会话或驱动他会话回合；
6. 存在第二处 `connector.execute` 调用点（即第二条派发路径）。

### 4.7 C6/C7 保持证明的总结（哪些是证明、哪些是推断）

- **`[证明]`（结构性，读码可得，不依赖新代码）**：授权由组合根产生（F6）；policy 逐项 deny（F8）；permit 绑 digest+fence+过期（F9）；tier≥3 需真人票据并绑 digest（F10）；执行侧只有 C7 读口（F11）；allowlist 之外每个 mode fail-closed（F12）；每会话一个 in-flight turn（F4）；单 principal（F5）；三类根（evaluator/promotion/audit）接口不被触碰。**spawn 自身也是 capability**：它必须有 `CapabilitySpec`（`packages/contracts/src/agent_os_contracts/capability.py:26-43` 的全部必填字段：`side_effect_guarantee`/`idempotency_supported`/`credential_class`/`data_boundary`/`risk_tier`/`timeout_seconds`/`cancellation_supported`/`compensation_supported`/`audit_policy`）、必须被注册（未注册能力 fail-closed：`domain_packs/developer_agent/workspace_capability.py:427,834` 抛 `CapabilityDenied("capability is not registered: …")`）、必须持有 grant（无 grant ⇒ `CAPABILITY_NOT_GRANTED`）并留下 `ActionReceipt` 与持久事件——因此它与所有其他动作受同一套 grants/policy/risk tier/evidence 约束，**没有"因为它是 spawn 所以例外"的通道**。
- **`[推断]`（依赖实现落地后由 §7 的 gate 证否）**：`child ⊆ parent ⊆ task` 的 grant 单调性；子未授权动作得到 typed 拒绝；父 permit/票据不可复用；扇出上界与超限 typed 拒绝；stop 语义；只含 digest 的 durable 记录；归因投影；子不写父状态。
- **`[NOT_MET]`（baseline 上已知不成立，不得声称）**：单会话停止（F13）；DENY 可见（F14）。**在这两项落地前，"可以停掉子代理"与"操作者能看见被拒"都不得作为本能力的一部分声称。**
- **明确不作的主张**：不主张 C7 能抵抗被攻陷的 worker/进程（`C7-BOUNDARY-STATEMENT.md:34-36` 已把该情形列为**未强制**）。Form B 不改变这一点，但也不得借 Form B 把它说成已解决。

## 5. 冻结接口

以下接口在并行实现批次中**已经冻结**，本 ADR 逐字采用、不改形状。

### 5.1 capability

- **id**：`agent.spawn`，注册在 **developer domain pack**；内核保持 domain-free（`AGENTS.md:35`）。
- **输入**：`prompt: str`；`description: str`（≤80 字符，操作者可见标签）；`agent_type: "general" | "explore"`（默认 `general`）；`max_steps: int | None`。
- **输出**：`child_session_id`；`child_task_id`；`status: completed|failed|stopped|timeout|limit`；`text: str`（子会话最终 assistant 文本，有界，**永不**回显 prompt）；`steps: int`；`tokens: int`；`stop_reason: str | None`。

### 5.2 agent_type 与权限收窄

- `general`：继承父的能力集**减去 `agent.spawn`**，除非显式启用嵌套派生（默认 **OFF**）。
- `explore`：只读子集（`workspace.read`、`workspace.search` 两项）——**没有** edit、apply_patch、run_tests、shell、todo_write、artifact.write。

### 5.3 grant 不变量（必须实现且必须测）

- `child_grants ⊆ parent_grants ⊆ task_grants`；
- principal / tenant / workspace **不可放宽**；
- `max_risk_tier(child) <= max_risk_tier(parent)`；
- `budget_limit(child) <= parent 的剩余预算`（"剩余预算"是一个**必须新增的计算量**，见 §4.3；无测量时退化为 `<= parent grant.budget_limit` 且不得声称存在跨会话总预算）；
- tier≥3 仍需要**真人** `ApprovalDecision`，且绑定**子动作**的 action digest。

### 5.4 扇出上界

- 每个父回合**在途**子代理最多 N 个（配置，默认 **4**，env `AGENT_OS_MAX_CHILD_AGENTS`）。
- 超限是 **typed 拒绝**（`ChildAgentLimitExceeded`），**永不**静默排队、永不静默丢弃。

### 5.5 durable 模型（append-only、additive、只含 digest）

- `CHILD_AGENT_SPAWNED {spawn_id, parent_session_id, parent_turn_id, child_session_id, child_task_id, agent_type, description, prompt_digest}`
- `CHILD_AGENT_FINISHED {spawn_id, status, steps, tokens, stop_reason, summary_digest}`
- 子会话事件携带 `parent_session_id` + `parent_turn_id` + `spawn_id`；
- 归因投影暴露某父回合的 `children[]`（每子 status/steps/tokens），且父的**合计包含子并明示这一点**；
- **不携带任何 prompt 或 completion 文本——只有 digest。**

### 5.6 stop 语义

- 停父会话 ⇒ 其**在途**子代理被停，每个都 durable 地以 `stop_reason=stopped_by_operator` 结束；
- 子代理也可经**既有单会话停止路径**单独停掉；
- 子代理**永不**比其父会话的关闭活得更久。

### 5.7 不得改变的不变量

- 每**会话**一个 in-flight turn（子代理是会话）；
- C7 non-writable 且 non-bypassable；
- 没有第二条派发路径；
- `ActionReceipt`/`ReceiptStatus` 语义不变。

### 5.8 本 ADR 明确留下的、冻结接口未覆盖的一项

`agent.spawn` 在**冻结 E2 权限矩阵**（`permission_gate.py:23-31`）中的风险 tier **不在**上述冻结形状之内，因此本 ADR 不擅自把它写死，只写约束与默认行为：

1. 它**必须**被登记进 `ACTION_RISK_TIERS`，否则 `evaluate_permission_gate` 对任何 mode 都返回 `DENY_OUT_OF_ALLOWLIST`（fail-closed、永不可批准）——即**忘记登记不会导致不受治理，只会导致不可用**（`permission_gate.py:58-65`）`[证明]`；
2. 组合根必须持有与所选 tier 匹配 `max_risk_tier` 的 `agent.spawn` grant，否则 `CAPABILITY_NOT_GRANTED`（F6/F8）；
3. **建议**（recommendation，非冻结形状）：取 tier 2——派生一个会话是有后果但可逆的动作，且必须对操作者可见；tier 3 会把每一次派生都变成一次人工审批，与"一次做成"的授权意图冲突。最终取值由实现批次 pin 住，并由 §7 G12 的 gate 证据记录，安全评审可按该值反驳。

## 6. 与主流对位

founder 的指示是"按主流做法做"。本节给出来源与差异，并**明确写出我们有意不同的地方及其代价**。

### 6.1 Claude Code（主要参考）

来源：`[vendor-doc]` [Create custom subagents — Claude Code Docs](https://code.claude.com/docs/en/sub-agents)，本文作者于 2026-09-19 抓取。

| 维度 | Claude Code | 本 ADR |
|---|---|---|
| 形态 | 主会话经 `Agent` 工具把工作交给 subagent；subagent 在**自己的 context window** 里跑并只回一份 summary | 同形态：父会话经 `agent.spawn` 派生真实子会话，只把最终文本回给父 |
| 权限 | subagent **继承父会话的权限**，由 `tools` / `disallowedTools` / `permissionMode` 收窄；内建 `Explore` 为 read-only（Write/Edit denied），`Plan` 为 research agent | 同方向、更硬：`child_grants ⊆ parent_grants` 是**契约 + 测试**，不是定义文件里的一个字段；`explore` 只给 `workspace.read`/`workspace.search` |
| 步数上限 | `maxTurns`：到上限停止并把输出标为 **partial**，父可 resume 继续 | `max_steps: int \| None`；到上限输出 `status=limit`（**不**提供 partial+resume） |
| 嵌套 | **默认允许**：subagent 可自行派生，最多三层（`CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH`，设 1 即关闭）；到深度上限时**除 fork 外**所有 subagent 的 `Agent` 工具被收走 | **默认 OFF**：除非显式启用，`general` 子的能力集减掉 `agent.spawn` |
| 并发上限 | 默认 **20**（`CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`）；超限时 `Agent` 调用失败并给出 `Concurrent subagent limit reached`，且**告诉模型不要重试**；会话内**总量不限** | 默认 **4**（`AGENT_OS_MAX_CHILD_AGENTS`）；超限是 typed `ChildAgentLimitExceeded`，**不静默排队** |
| 审批 | 由 subagent 继承的 permission mode 决定 | 每次 tier≥3 都是真人 `ApprovalDecision`，且绑定**该子动作**的 digest |
| 记录 | subagent 面板按树展示，行上标 `(+N)` 后代计数 | durable 事件只记 digest；归因投影给 `children[]` 与父的含子合计 |

### 6.2 明确**不做** subagent 的对标物

- **Pi**：`[vendor-doc]` [Pi Coding Agent — usage](https://pi.dev/docs/latest/usage)，本文作者于 2026-09-19 抓取，原文：*"It intentionally does not include built-in MCP, sub-agents, permission popups, plan mode, to-dos, or background bash. You can build or install those workflows as extensions or packages…"*。Pi 把 sub-agent 留作扩展而非内建。
- **Codex CLI**：仅记录到 `/subagents` 等命令**存在**——该结论来自 `docs/product/TERMINAL-PARITY-MAP-2026-09-18.md` 在固定 commit（`7498521d`，2026-09-18）上的 `[source]` 读码，**本文未独立复核其语义**，故不对 Codex 的 subagent 行为作任何断言。
- **Hermes / OpenClaw**：本文**不作**断言（未取得可引用的 subagent 语义来源）。
- 共同背景：扩展性（MCP / skills / typed hooks / subagents）在 founder 的权重表里合计约 10%（`docs/CURRENT_STATE.yaml:52`），且 `docs/product/TERMINAL-AGENT-CLI-BENCHMARK-2026-07-26.md:128-129` 明确 "Do not treat plugins, MCP or sub-agents as proof of agent quality"。**因此"主流有"不是本决定的理由；理由是 founder 授权的对等能力目标。**

### 6.3 我们有意不同的地方，以及它对操作者的代价

1. **嵌套默认 OFF**（主流默认 ON）。代价：父无法默认递归分解；默认情况下失去"一个 reviewer 为每条 finding 派一个 verifier"的形态，需操作者显式开启。
2. **扇出默认 4**（主流 20）。代价：宽扇出的墙上时间更长。
3. **每个子代理都有 governor**：grant 单调收窄被契约化并测试；tier≥3 一律真人审批并绑子动作 digest；spawn 自身是受 permit/policy/evidence 约束的 capability。主流是"继承权限 + 模式收窄"，不把审批绑到跨父子边界的单个动作 digest 上。**代价（诚实记录）**：**我们的交互更啰嗦、能做成的动作更少**，一个主流会直接跑下去的子代理在我们这里可能停下来等操作者。这与 `TERMINAL-AGENT-CLI-BENCHMARK-2026-07-26.md:18-21` 记录的"唯一差异化"一致，是**有意的**。
4. **durable 记录只含 digest**。代价：仅凭 durable store 无法重建子代理当时被问的是什么；排障需要操作者的 transcript。
5. **成本只到 token、金额恒 `UNKNOWN`**（不引入定价源，沿 GC D6）。代价：扇出后的花费在金额维度不可读。
6. **先决条件由我们承担**：`stop` 语义必须真实可用（F13），主流已有。**在它落地前，我们不能声称"可以停掉子代理"。**

### 6.4 被丢弃的、无来源的主张

- 不主张任何"parity / 超越 / 领先"；
- 不对 Codex CLI / Hermes / OpenClaw 的 subagent 语义作断言；
- 不把厂商文档读成"该功能可靠或已达生产"（`[vendor-doc]` 只描述意图）；
- 未做第三方交叉验证：本次他方事实全部来自官方文档，没有独立复核来源；
- 不声称我们的 fan-out 与某个具体产品的上限"等价"——N=4 与 N=20 是不同的数，不是同一个性质。

## 7. 可证伪 gates

每条 gate 都写"**什么观测会证明它不成立**"。全部为 Product Track 门，且必须接入 CI（G12）。claim 等级按 §5.7 与 §4.7 逐项声明：`specified / implemented / tested / integrated / verified`。

- **G1 唯一派发路径不变**
  - 断言：`agent.spawn` 自身、以及每个子会话动作，都经 `CapabilityBroker.invoke`。
  - **证伪观测**：给 broker 加计数探针后，一次 spawn 的子会话动作出现 broker 计数为 0；或实现 diff 里出现第二处 `connector.execute` 调用点、或一个绕过 broker 的 spawn 专用 dispatch 符号。
- **G2 grant 单调性（本 ADR 的核心新性质）**
  - 断言：`child_grants ⊆ parent_grants ⊆ task_grants`；principal/tenant/workspace 不放宽；`max_risk_tier(child) <= max_risk_tier(parent)`；`budget_limit(child) <= parent`。
  - **证伪观测**：构造一条路径使子拿到父没有的 capability 而仍 `ALLOW`；或父 grant `max_risk_tier=2` 而子动作 tier 3 被允许；或子的 `budget_limit` 大于父的。
  - **探针要求**：必须**驱动真实 spawn** 并读子会话的实际 grant 集合，不接受静态断言。
- **G3 许可与票据不可复用**
  - 断言：父的 permit / `action_digest` / 审批票用于子动作必被拒。
  - **证伪观测**：把父（或另一会话）的 `permit_id`、approval ticket 用于子动作而被 broker 或 policy 接受；或复用父的 lease fence 得到 `ALLOW`。
- **G4 子不能批准；tier≥3 仍要真人；无批量批准**
  - 断言：子动作 tier≥3 在无真人 `ApprovalDecision` 时 `ESCALATE/APPROVAL_REQUIRED`；不存在一次请求批准多个会话/多个子的路径。
  - **证伪观测**：子在无票下让 tier≥3 sealed SUCCEEDED；或一条请求把多个子的 pending 置 APPROVE；或客户端出现循环/自动批准逻辑（服务端只认证单 bearer，所以客户端侧必须单独断言）。
- **G5 C7 不可写不可旁路**
  - 断言：模型侧 capability 集合内没有任何 correction/halt 写口；spawn 期间发生的 correction 使子动作不能在派发后仍 seal 为成功。
  - **证伪观测**：出现任何新增 correction 写入口；或在 spawn 在途时触发 correction 后子动作仍得到 `SUCCEEDED` receipt 而无 `CapabilityCorrectionBlocked`/UNKNOWN 语义。
- **G6 扇出有界且超限 fail-closed**
  - 断言：默认 N=4 时第 5 个在途子得到 typed `ChildAgentLimitExceeded` 与可见结果；`AGENT_OS_MAX_CHILD_AGENTS=0` 时 `agent.spawn` **不可用**（typed 拒绝），不是静默成功。
  - **证伪观测**：第 N+1 次 spawn 静默成功、静默排队或静默丢弃；或 N=0 时仍能 spawn。
  - 另需记录 N 并发下的资源实测上界（内存、连接、锁表条目数），因为 `surface_runtime.py:171-176` 的锁表无回收。
- **G7 durable 记录只含 digest**
  - 断言：`CHILD_AGENT_SPAWNED` / `CHILD_AGENT_FINISHED` 落在 durable 事件流，且**不出现** prompt 或 completion 文本。
  - **证伪观测**：在 durable store、事件流或 `/export` 输出里能 grep 到 prompt 片段或 completion 片段。
- **G8 归因可读且合计诚实**
  - 断言：父回合的 `children[]` 覆盖该回合派生的每个子，每子的 status/steps/tokens 与子自身事件一致；父的合计**包含**子并**明示**这一点。
  - **证伪观测**：`children[]` 缺项；或 step/token 数与子自身记录不一致；或父的合计不含子却未标注。
- **G9 每会话冻结逐字节不变**
  - 断言：子会话内第二次 begin-turn 仍报 typed `SurfaceTurnInProgress`（`surface_runtime.py:417-422`）；子的在途回合不阻塞父或兄弟的 begin-turn。
  - **证伪观测**：子会话第二次 begin-turn 成功；或父/兄弟的 begin-turn 被子误冻；或出现同会话并发多回合。
- **G10 stop 语义（先决，baseline `NOT_MET`）**
  - **【2026-09-19 重裁：仍为 `NOT_MET`，但已收窄到一个具名剩余切片；逐句证据与结论见 §15】**
  - 断言：停父 ⇒ 其在途子各以 `stop_reason=stopped_by_operator` durable 结束；单独停一个子走既有单会话停止路径且其余不受影响；子不比父活得更久。
  - **今天的反例（已记录、未修）**：surface 会话 `pause` 抛 `InvalidTransitionError`——`RunStatus.QUEUED` 的允许集不含 `PAUSED`（`task_service.py:2396-2410`；`app.py:2487-2492`；`docs/CURRENT_STATE.yaml:51` 缺陷 (a)）。
  - **证伪观测**：stop 后其子仍继续产生派发或事件；或 stop 后没有 durable 终止记录；或停一个子导致其它子/父被误停。
  - **判据**：任何"可以停掉子代理"的完成声明，必须先在 pty 或等价 e2e 里观测到 `PARENT_STOPPED_CHILDREN_DURABLY` 与 `SINGLE_CHILD_STOPPED_OTHERS_UNTOUCHED` 同时为真。**未满足前，本 gate 记 `NOT_MET`。**
- **G11 子不写父状态、不夺审批面**
  - 断言：子的一个回合不改变父会话投影字段，也不在父 task 事件流新增由子产生的事件（除 §5.5 冻结的 spawn/归因记录）。
  - **证伪观测**：子回合后父 snapshot 任一字段变化；或两条不同会话的动作有相同 turn 归因。
  - **探针要求（沿 `AB-P3A §9` 的教训）**：必须**驱动真实回合到 `awaiting_approval`** 再断言父的投影与父的事件流，不接受静态状态字段断言。
- **G12 gate 接进 CI 且不可静默移除**
  - 断言：新 gate 进 `tests/product`（受治理套件）或 cli-ts 套件，且 `test_ci_gate_wiring.py` 的接线自守覆盖它。
  - **证伪观测**：删除/中和该 CI 步骤（`|| true`、`continue-on-error`、`--if-present`、把脚本改成 no-op）后其余检查仍全绿。
- **G13 冻结契约语义不变**
  - 断言：`ActionReceipt` / `ReceiptStatus`（`authority.py:51-58,267-281`）逐字节未变；surface 协议只增可选字段并保留旧解码（`SURFACE_PROTOCOL_VERSION = "1.1"`，`packages/contracts/src/agent_os_contracts/surface.py:14`）。
  - **证伪观测**：`ReceiptStatus` 枚举值或 `ActionReceipt` 字段被改；或旧协议客户端解码失败。

## 8. Canary / rollback

### 8.1 全局关闭开关（必须存在）

三条**互相独立**的关断路径，全部 fail-closed，且都不需要数据迁移：

1. `AGENT_OS_MAX_CHILD_AGENTS=0` ⇒ `agent.spawn` 不可用，得到 typed 拒绝（不是静默忽略）；
2. 组合根**撤回** `agent.spawn` 的 grant ⇒ `CAPABILITY_NOT_GRANTED`（`governance.py:351-352`）；
3. 从 E2 allowlist（`permission_gate.py:23-31`）**移除** `agent.spawn` ⇒ 每个 mode `DENY_OUT_OF_ALLOWLIST`、**永不可批准**（`permission_gate.py:58-65`）。

另有一条**更窄**的开关属于冻结接口本身：嵌套派生默认 OFF，因此"关掉再派生"的形态默认就已经关闭（开关 1–3 未生效时依然成立）。

视图层沿既有先例（`--no-agents`，`apps/cli-ts/src/opentui/panels.ts:21,29`）可以再加一个 `--no-*` 面板开关；其命名属实现批次的自由，不是本 ADR 的冻结形状。

### 8.2 回滚长什么样

- **回滚动作 = 关断 + 发布一个不再注册该 capability 的版本。** 没有 destructive migration，没有需要回填的 schema（只新增可选字段与 additive 事件类型）。
- **必须保留的**：已经写下的 `CHILD_AGENT_SPAWNED` / `CHILD_AGENT_FINISHED` 与子会话/task/run 是 **append-only 历史**，不得删除或改写；关断后它们仍必须可读，子会话仍可经既有 session 端点查看/关闭。理由是可纠正性要求**不可抹除的观测**（根仓 `docs/GOAL-BLUEPRINT.md:60`；`REF-ARCH-04:20-23`）。
- **回滚不能做的事（必须如实说）**：它**不能**取消已经存在的子会话/task，也**不能**撤销子代理已经 dispatch 的效果。已 dispatch 的效果只受既有 receipt/compensation 语义约束，且 `UNKNOWN` 是终局（`docs/architecture/C7-BOUNDARY-STATEMENT.md:19-23`；parity map §5.7 记录的"receipt/reservation 是 insert-only"）。任何"回滚会把扇出撤销"的说法都是假的。
- **canary 形状**：先在单机、单 workspace、操作者显式开启下验证 G1–G13；N 的默认值在 canary 期可以低于 4，但 `AGENT_OS_MAX_CHILD_AGENTS` 的语义（含 0 = 关）不得改变。

## 9. 评审身份与评审等级（诚实记录）

- **founder 2026-09-18 的既有裁定**：本线"同模型 subagent 评审足够"，且**明确接受**因此带来的边界——`builder_id != reviewed_by` **不满足**，**没有**独立 provider 批准（`docs/CURRENT_STATE.yaml:52`，原文与 SRL M1 merge 使用同一措辞）。
- **本 ADR 因此不是独立批准的。** 本文件由实现同批的 agent 起草；与它并行的"对抗性 C6/C7 保持评审"同样是**同模型 subagent 评审**，因此它也**不**满足 `builder_id != reviewed_by`，也不是独立 provider 批准。两份文件互为**同模型交叉检查**，不构成宪法意义上的独立评审。
- 根仓 `AGENTS.md:132`（边界移动的完整条件）、`:174`（`builder_id != reviewed_by`）、`:190`（评审身份是合同的一部分，静默 provider 回退不算独立评审）与仓库 `AGENTS.md:111`（runtime/契约/安全类变更默认走 feature branch + 独立 review）要求边界移动需要"独立评审身份"；本节记录的是：**该条件在本线上被 founder 显式豁免，而不是被满足。** 这是本 ADR 最重要的诚实边界之一。
- 同样地，§7 的任何 gate 通过，只证明"在该 head 上可观测通过"，**不**等于安全评审通过、不等于 release 授权。

## 10. 本 ADR 不授权

1. **不授权 release / 发布 / 打包分发 / 付费**——这些都在 founder 保留决定清单里（仓库 `AGENTS.md:99`）。
2. **不授权 MCP**（继续 `PARK`，其前置门在 `docs/product/GC-MCP-FORM-AND-BOUNDARY-2026-09-18.md`）。
3. **不授权 typed hooks**（另一份 GC；其 §5 明确排除仓库内/工作区内 hook 来源）。
4. **不授权 checkpoint / rewind**（今天在任何操作者可及路径上都不存在）。
5. **不授权新 principal、批量审批、自动批准、任何形式的 tier-3 自动放行。**
6. **不授权新增终端治理/执行入口**（Stage 2c/2d：创建/派生保持 API-only）。
7. **不授权跨仓 import/copy**，也不授权 ADR-0054/SPINE-1 的任何移动。
8. **不授权修改 C7、权限上界、审计不可抹除性、评估/promotion 根或 SD4 的任何边界。**
9. **不授权任何 parity / 超越 / 产品就绪 / 自主主张**（不使用 `Autonomy(S,E,O,V,T)`；G10 类研究结果不是自主证据）。
10. **不授权解除 F13/F14 的缺陷状态**：本 ADR 记录它们是**先决阻塞**，不是可以把它们变成"已知可接受"的理由。

## 11. Consequences

- **代价**：一次操作者会话现在可能同时存在多个 loop，操作者需要理解"父/子"关系、成本归属与停止语义；交互摩擦上升（§6.3.3）。子会话数量增加会放大资源占用，而 `surface_runtime.py:171-176` 的锁表**无回收**、无上限——这构成一条新增的资源风险，必须由 G6 的实测上界承接。
- **被搁置/未开工的路径**：会话 fork/branch、`/compact`、并发多回合（P3b）、跨会话总预算、子代理的独立 principal——全部仍然不做，且不因本 ADR 而解冻。
- **对 `docs/CURRENT_STATE.yaml` 的更新需求（不由本 ADR 执行，该文件归协调者）**：见 §12。
- **对 PROJECT_PLAN/任务卡的影响**：本能力在 `implemented` 之前不得进入任何"已具备"清单；"多智能体 / subagents"在文档中必须精确表述为"有只读树与跨会话切换（多会话视图），**派生/扇出**由 ADR-0061 起才被授权"。

## 12. 建议给协调者的 CURRENT_STATE pin（不由本 ADR 修改该文件）

建议（逐字可用的候选文本，需协调者决定是否采纳）：

```yaml
  adr_0061_subagent_fanout_2026_09_19: "ADR-0061 ACCEPTED (founder authorized Form B 2026-09-19): a new typed capability agent.spawn creates a real child session/task/run and drives its turn from inside the parent turn. This is a deliberate C6 control-path boundary move; the ADR carries the C6/C7 preservation proof with [证明]/[推断]/[NOT_MET] labelling. The kernel stays domain-free; the capability is registered in the developer domain pack; every child action still goes through the single CapabilityBroker.invoke path; C7 is untouched (no new correction write port) and ActionReceipt/ReceiptStatus semantics are unchanged. Frozen interface: agent.spawn (prompt/description<=80/agent_type general|explore/max_steps) -> child_session_id, child_task_id, status completed|failed|stopped|timeout|limit, text, steps, tokens, stop_reason; general = parent set MINUS agent.spawn unless nested spawns are explicitly enabled (default OFF); explore = workspace.read + workspace.search only; child_grants subset parent_grants subset task_grants, max_risk_tier(child) <= parent, budget_limit(child) <= parent (the parent remaining-budget quantity DOES NOT EXIST today and must either be implemented or replaced by the non-widening parent grant limit - no cross-session total budget may be claimed); fan-out <= N in flight per parent turn (default 4, AGENT_OS_MAX_CHILD_AGENTS, 0 = OFF) with a typed ChildAgentLimitExceeded and never a silent queue; durable records are append-only and digest-only (CHILD_AGENT_SPAWNED / CHILD_AGENT_FINISHED), child events carry parent_session_id/parent_turn_id/spawn_id, and the attribution projection exposes children[] with the parent totals INCLUDING children and saying so. NO NEW AUTHORIZATION: no release/publish, no MCP, no typed hooks, no checkpoint/rewind, no new principal, no batch or auto approval, no second dispatch path, one in-flight turn per session (a child is a session), governance creation stays API-only. BLOCKING PREREQUISITES RECORDED, NOT CLEARED: single-session pause does not work on this baseline (task_service.py:2396-2410 QUEUED has no PAUSED; CURRENT_STATE.yaml:51 defect (a)) and DENY is invisible (defect (b)); until the stop slice lands, no 'you can stop a subagent' claim is permitted (gate G10 = NOT_MET). REVIEW LEVEL: every review on this line is SUBAGENT/SAME-MODEL, so builder_id != reviewed_by is NOT satisfied and there is NO independent-provider approval; the founder accepted that explicitly (CURRENT_STATE.yaml:52) - this is an exemption, not a satisfied condition. Specified: ADR-0061; implemented/tested/integrated/verified/released: NO."
```

## 13. 未核实清单（诚实列出）

**本仓侧**

1. **founder 2026-09-19 的 Form B 授权没有对应的 durable 文件**：我在本仓 baseline 与根仓 `docs/CURRENT_STATE.yaml`（`updated: 2026-09-15`）中都**没有找到**一份 2026-09-19 的 founder decision 记录。本 ADR 依据的是任务包转述的该授权。**若该授权存在正式文件，应把它加入本 ADR 的 Upstream，并按它核对 §3 的范围。**
2. **`AGENT_OS_MAX_CHILD_AGENTS` 与 `ChildAgentLimitExceeded` 是冻结接口给的形状，不是我在代码里读到的既有实现**：baseline 上不存在这个 env 名（`AGENT_OS_*` 实测清单里没有它）也不存在这个错误类型。
3. **`agent.spawn` 的风险 tier 未定**（§5.8）：建议 tier 2，但未由本 ADR 冻结。
4. **"父的剩余预算"不是一个已测量的量**（§4.3/§5.3）：本仓没有跨会话预算聚合，我未找到任何跨会话预算的度量或端点。
5. **N 并发子会话的资源上界未测量**：`surface_runtime.py:171-176` 的锁表无回收；GC §2 也把它列为未核实项。我没有做任何运行期测量（本任务 docs-only）。
6. **F13/F14 是既有记录的自述转引**：我读到了 `task_service.py:2396-2410` 的迁移集与 `docs/CURRENT_STATE.yaml:51` 的缺陷记录，但**没有**在运行期复现 `pause` 失败或 DENY 不可见（本任务禁止起 daemon）。
7. **并行实现批次的对应关系未核实**：本 ADR 与一批并行实现工作共享同一冻结接口，但我没有读过那批工作树的实际文件，因此 §5 的正确性以冻结接口文本为准，§7 的 gate 是**要求**而非**现状**。
8. **`app.py` 中 `agent.spawn` 的具体接线点还不存在**：F6/§5.3 描述的是 grant 应当从组合根派生这一既有模式，不是已经接好的 spawn 路径。

**他方侧**

9. **Codex CLI / Hermes / OpenClaw 的 subagent 语义未核实**：Codex 只引到 `/subagents` 命令的存在（转引自 parity map 在 `7498521d` 的 `[source]` 读码）；Hermes/OpenClaw 本文不作断言。
10. **厂商文档只描述意图**：Claude Code 与 Pi 的引用均标 `[vendor-doc]`，不得读成"该功能可靠或已达生产"。
11. **未做第三方交叉验证**：全部他方事实来自官方文档，没有独立复核来源（这一限制与 `docs/product/TERMINAL-PARITY-MAP-2026-09-18.md` §1.2 记录的工具限制同源）。
12. **未取得 Claude Code 的并发/嵌套上限的具体版本行为演进细节**：文档给出默认值与 env 名，但跨版本的默认变化（例如 v2.1.198 的模型继承变更）我未逐版核对。

## 14. Status / claim grading（本文件自身）

`specified: 本文件` / `implemented: NO` / `tested: NO` / `integrated: NO` / `verified: NO` / `released: NO`。

本文件**未**新增任何运行时代码、契约或协议改动，**未**运行任何测试、**未**起任何 daemon、**未**读 `~/.agent-os/`、**未**修改 `docs/CURRENT_STATE.yaml`。§4 的 `[证明]` 是对 baseline 代码的结构性读码结论；§4 的 `[推断]` 与 §7 的 gate 是**要求**，其通过与否则由实现批次的证据决定。**不得据本文件声称 C6/C7 保持已被证明成立、不得声称 parity、不得声称产品就绪或任何自主主张。**


## 15. G10 重裁记录（2026-09-19，基于实现批次证据）

本节是对 §7 G10 的一次**正式重裁**，只依据在真实 head 上跑到的证据，不凭实现或提交信息。G10 的判据是合取的：必须在 pty 或等价 e2e 中**同时**观测到 `PARENT_STOPPED_CHILDREN_DURABLY` 与 `SINGLE_CHILD_STOPPED_OTHERS_UNTOUCHED`，否则记 `NOT_MET`。下面逐句对账。

### 15.1 句 B：`SINGLE_CHILD_STOPPED_OTHERS_UNTOUCHED` —— 基本成立（一处加强项缺口）

"单独停一个子，走既有单会话停止路径，且其余不受影响"：

- **在飞子、经真实操作者路径可停（durable）**：`tests/product/test_agent_spawn_daemon_e2e.py::test_daemon_operator_can_stop_one_in_flight_child_over_surface`（真实 daemon + HTTP surface + 短延迟 provider，约 22 s，PASS）。子回合进行中 `POST /v1/surface/sessions/{parent}/children/stop` 立即返回；子事件流以 `RUN_PAUSED` 结尾，随后经正常 spawn 收尾写 `CHILD_AGENT_FINISHED(stop_reason=stopped_by_operator)`；GET children 显示 stopped；用新幂等键再停不产生第二条 finish（幂等）；对**父自身** session id 调 stop 返回 **422 "not a child"**。
- 内核在飞/停泊两支：`AgentOSApplication.stop_child_agent` 对"父回合 worker 线程 inline 驱动"的子走非阻塞 `RUN_PAUSED`（#77 的持久停止，不碰被父 spawn effect 全程持有的 correction 锁，避免自死锁）；对 parked/orphan/effect 间隙走同步 C7 correction + 终态记录。
- parked 子的单子停止 + 父不受影响：`tests/product/test_agent_spawn_kernel.py::test_child_is_individually_stoppable_through_the_existing_path`（status=stopped、`stopped_by_operator`、父 run 不被置 PAUSED，PASS）。
- TUI：agents 面板高亮在飞子按纯 `x` 即停（`opentui/agents.ts`/`viewkeys.ts`/`app.tsx`），Ctrl-X 全局"停本 run"不被劫持。
- **加强项缺口（不改变本句主体，但需补）**：尚无用**两个并发在飞子**的 e2e 正面证明"停一个时兄弟继续派发、父仍 ACTIVE"。现有证据是父不被误停（kernel 断言 + 对父 id 的 422），但没有"兄弟继续跑"的正面观测。

### 15.2 句 A：`PARENT_STOPPED_CHILDREN_DURABLY` —— 未成立（操作者路径未接线）

"停父 ⇒ 其**在途**子各以 `stop_reason=stopped_by_operator` durable 结束"：

- 内核**有**助手 `AgentOSApplication.close_session_and_stop_children`，但它**没有接到任何操作者可达的 surface 命令/路由**：全仓生产代码无调用方，仅 `tests/product/test_agent_spawn_kernel.py::test_parent_closure_stops_in_flight_children` 直接调用它，且该用例用的是 **parked** 子、终态原因是 **`parent_session_closed`**（不是 G10 具名的 `stopped_by_operator`）。
- 操作者实际的"停"（Ctrl-X → `surface_pause_session`；correction → `surface_correct_session`）**只作用于父任务本身**，不遍历停在飞子。
- 读侧祖先级联 `ChildAgentHaltCascade` 会在父被 halt 后**拒绝子的下一次派发**（C7 不旁路），但"拒绝后续派发"不等于"为每个在飞子补一条 durable `CHILD_AGENT_FINISHED(stopped_by_operator)`"；目前没有 pty/e2e 观测到停父时每个在飞子都 durable 终止。
- "子不比父活得更久"只在**运行时死亡/重启**这一支成立：P6 启动 orphan scan 在 SIGKILL+重启后回收每个在飞子，终态 `failed / unknown_requires_review`（探针 P6 PASS）——它覆盖崩溃恢复，**不**覆盖操作者主动停父，且原因不是 `stopped_by_operator`。

### 15.3 重裁结论

- **G10 整体仍记 `NOT_MET`**：句 B 基本成立，句 A 在操作者路径上未成立，合取不满足。**不得**据本节或据"单子可停已实现"对外声称"可以停掉子代理（含停父级联）"。
- 剩余切片（很小，且含一个需 founder/设计拍板的语义点，不允许实现侧自行猜测）：
  1. **语义决策**：哪个操作者动作级联停在飞子——可 resume 的 Ctrl-X/pause，还是一个独立的"关闭会话"动作；以及终态原因取 G10 具名的 `stopped_by_operator` 还是助手现用的 `parent_session_closed`。
  2. 把该操作者路径接线到遍历 `in_flight_children` 并复用现有非阻塞 `stop_child_agent`（在飞走 `RUN_PAUSED` 由子循环自收尾，parked/orphan 同步终态），为每个在飞子写 durable 终态。
  3. 用**至少两个并发在飞子**的 pty/等价 e2e，按具名观测落地：停父→两个子都 `CHILD_AGENT_FINISHED(stopped_by_operator)`（`PARENT_STOPPED_CHILDREN_DURABLY`）；停一个→被停子终止、**兄弟继续派发、父保持 ACTIVE**（`SINGLE_CHILD_STOPPED_OTHERS_UNTOUCHED`，同时补上 15.1 的加强项）。
- 不变的既有保留项：Form B 默认**关**、三条 fail-closed 关断开关仍在；本线所有评审仍是**同模型 subagent** 工作，`builder_id != reviewed_by` **不满足**、无独立 provider 批准——这是 founder 接受过的**豁免**，不是满足；本节不构成 release/publish 授权。
