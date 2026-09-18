# GC — 终端 surface 上的 Subagents / 多智能体（2026-09-18）

- **状态**：`DESIGN_ONLY / DOCS_ONLY / AWAITING_CTO_GATE / NO_IMPLEMENTATION_AUTHORITY`
- **上游**：`docs/product/GC-P3-MULTIAGENT-TASK-TREE-2026-09-16.md`（P3a 已实现）、`docs/product/AB-P3A-MULTIAGENT-TASK-TREE-2026-09-16.md`
- **范围**：终端 surface（`apps/cli-ts`）上"一个 agent 派生并驱动子代理"及其并发形状（fan-out）。
- **结论（先给判断）**：
  1. **A 形态（操作者/父会话逐个选择，多个独立会话各一个 in-flight）已经具备全部内核前提**，P3a 已交付只读树 + 跨会话切换；剩余是治理与可观测收尾，**零内核/零协议改动**。
  2. **B 形态（父会话派生子会话并扇出并发）引入一条新的控制路径**（模型输出 → 创建会话/驱动回合），属 C6 控制路径边界移动，**必须另立 ADR + C6/C7 保持证明 + 安全评审**；本文件只做前置设计，不授权实现。
  3. **A 形态今天有一条硬阻塞**：单会话"停掉"不可用（§2 事实 F7）。"能看见也能单独停掉子代理"这句话现在**不成立**。
- **本文件不授权任何运行时代码、契约、协议或内核改动。**

## 1. Goal Card

- **目标**：在终端定义"subagents / 多智能体"的**允许形态、并发形状、治理不变量与操作者体验**，并给出可证伪 gates，供 founder/CTO 选择形态。
- **非目标**：
  - 不追求超越主流、不追求范式级差异化；本线目标是**终端优先、模型无关、可编程治理**的通用 Agent CLI 的对等能力。
  - 不解冻"每会话一个 in-flight turn"（rev 9）；不做同会话内并发多回合/多路复用（`GC-P3:65` 的 P3b，另一件事）。
  - 不在终端新增治理/执行入口（Stage 2c/2d：治理面 API-only；`docs/CURRENT_STATE.yaml:26`）。
  - 不改变 permit/approval/C7；不允许子代理自行审批、不允许批量或自动批准。
  - 不引入新的跨仓依赖；不让 Agent Core 产生领域语义。
- **证据类别**：**产品能力**（Product Track）。不得由研究证据或工程流程证据回填。
- **退出条件**：§7 的 gates 全部有可观测证据；每项能力须有公共入口 + typed contract + 失败路径 + 集成点 + trace/evidence + 权限 + rollback + 分级声明（`AGENTS.md:57`）。

## 2. Context Pack（已核对事实；每条含位置）

| # | 事实 | 位置 |
|---|---|---|
| F1 | 冻结 rev 9：**每会话**一个 in-flight turn，无排队/多路复用；第二次 begin-turn 报 typed `SurfaceTurnInProgress` | `packages/os_core/src/agent_os_core/surface_runtime.py:70-77,417-423` |
| F2 | 会话级锁按 `session_id` 分桶（不同会话互不阻塞） | `surface_runtime.py:174-176` |
| F3 | "未提交回合"是**持久真值**读取：该会话 task 的 `SESSION_TURN_STARTED` 无对应 `SESSION_TURN_COMPLETED` | `apps/api_server/app.py:2299-2319` |
| F4 | 会话列表投影已含 `awaiting_approval: bool`，且已被 P3a 树消费（**零协议改动**） | `packages/contracts/src/agent_os_contracts/surface.py:173-186`；`apps/cli-ts/src/opentui/agent-tree-source.ts:92` |
| F5 | 会话列表**故意排除** statement / envelope / expected outcome / tokens / 凭证 | `surface.py:174-178` |
| F6 | 审批是**按会话**的单次 POST；服务端只有一个本地 bearer，无批量审批路由 | `apps/api_server/surface_routes.py:229-231,390-400`；`surface_routes.py:155-162` |
| F7 | **单会话 pause 对 surface 会话不生效**（已记录缺陷，未修）：Run 停在 `QUEUED`，而 `QUEUED` 允许集不含 `PAUSED` | `app.py:2487-2491`；`packages/os_core/src/agent_os_core/task_service.py:2396`；`docs/CURRENT_STATE.yaml:51` 缺陷 (a) |
| F8 | **权限 DENY 不产生任何卡片**（`DENY_BY_RULE` 不发 `ACTION_PROPOSED`）→ 操作者看不到被拒 | `docs/CURRENT_STATE.yaml:51` 缺陷 (b) |
| F9 | 模型只通过 typed tools 行动 | `packages/os_core/src/agent_os_core/agent_loop.py:96-103` |
| F10 | 今日能力名空间无任何"创建会话/驱动回合"能力 | `domain_packs/developer_agent/__init__.py:47-58`（`workspace.read/apply_patch/run_tests/artifact.write`） |
| F11 | 授权是**按 grant** 绑定的：principal+tenant+workspace+capability+version+`max_risk_tier`+`budget_limit` | `packages/contracts/src/agent_os_contracts/capability.py:71-83`；`governance.py:352-376` |
| F12 | permit 绑定 action digest、lease fence 与 5 分钟过期；broker 在派发前校验 | `governance.py:479-498`；`packages/os_core/src/agent_os_core/capability.py:140-160` |
| F13 | tier≥3 必须有真人 `ApprovalDecision`，否则 `ESCALATE/APPROVAL_REQUIRED`；审批票据绑定 action digest | `governance.py:378-385` |
| F14 | DENY 规则只减权，永不允许、永不自动批准 tier-3、永不越过 C7 | `packages/os_core/src/agent_os_core/permission_gate.py:94-98` |
| F15 | surface 层**不区分主体**：每个 client 必须绑定同一个 runtime principal；一个 daemon 一个 principal | `surface_runtime.py:501-510` |
| F16 | 客户端 token 计数是**活动会话**的累计值；cost 无定价源，恒为 `UNKNOWN` | `apps/cli-ts/src/controller.ts:547-556` |
| F17 | 跨会话切换有真实 e2e 证据；剩余 `session→parent-session` 关系**不存在** | `AB-P3A-MULTIAGENT-TASK-TREE-2026-09-16.md:113-135,15` |
| F18 | CI 已有受治理产品套件门 + cli-ts 门 + 接线自守，新 gate 必须接进去 | `.github/workflows/ci.yml:56,113`；`tests/product/test_ci_gate_wiring.py:1-30` |

**需要修正的既有陈述（本文件与它们冲突的部分）**

- **C1** `docs/CURRENT_STATE.yaml:29` 称 "P3 (multi-agent/task tree) NOT done: needs a surface-protocol extension + unfreezing one-turn-per-session"。**已被 P3a 证伪**（零协议改动、未解冻），同文件 `:53-54` 已记录正确结论；该 pin 的这句话应删。
- **C2** `GC-P3:49-53`（§3）与 `AB-P3A:38,95` 称"树内 pending 审批需附加字段 → 协议 `1.2`"。**部分过时**：`awaiting_approval: bool` 已在 v1.1 契约（F4）并被消费；仍缺的只是 **count 与 label**。
- **C3** `docs/CURRENT_STATE.yaml:52` 称 "there are no subagents in the surface"。按 F17，操作者今天**可以**持有多个独立会话并切换（多会话视图已实现），但**不能**派生；措辞需精确化为"无派生/无扇出"。
- **C4** `docs/CURRENT_STATE.yaml` 的 `updated: 2026-09-16` 与 `live_pins.origin_main_code_receipt: 3a70592d` 落后于 live HEAD `03ac66b5`（2026-09-18 合入 PR #69）。

**未核实**

- 尚无 ≥2 个会话**同时**产生 pending 审批的实测记录；F6 的"服务端无批量路由"是代码读取结论，未做运行期攻击复现。
- N 个并发会话/流的资源上界（内存、连接、锁表 `_locks` 增长）**未测量**；`surface_runtime.py:174-176` 的锁表无回收，未见上限。
- 是否有既有的、可复用的"父子 task 归因"投影（缺 `session→parent-session`，F17）——本文件按"不存在"处理。
- eval 侧：终端线自身的编码 eval 缺失（`CURRENT_STATE.yaml:52`），故本文件不设能力/质量类度量，只设治理与资源类 gates。

## 3. 候选形态

### 3.1 A 形态：多个独立会话，各一个 in-flight，由操作者选择

- **语义**：每个子代理 = 一个独立 session（各自 task/run/审批面/持久事件流）。操作者（或父会话的**操作者动作**）选择创建与切换；**agent 不派生 agent**。
- **今天已有的最小实现面**：`POST /v1/surface/sessions`（`app.py:2253`）、`GET /v1/surface/sessions`、`/resume` 切换（`AB-P3A §9`）、只读 `agents` 树面板（`agent-tree-source.ts:1-12`）。
- **缺口（而非新内核）**：① 单会话停止（F7）；② 被拒动作不可见（F8）；③ 非活动会话的成本/事件只靠轮询（F16、`AB-P3A §8`）；④ 无 `label`，多会话难以人读区分。
- **内核改动**：**零**。协议改动：可选（count/label，按 `CP-TERMINAL-CODING-AGENT-M2 §Version bumps` 附加字段升 minor 且保留旧解码）。
- **判断**：A 形态是**默认可做**的收尾；它把"多智能体"读作"操作者并行管理多个 agent"，不含任何新授权。

### 3.2 B 形态：父会话派生子会话 / 扇出并发

- **语义**：父会话在一个回合内请求派生 K 个子会话并让它们并发跑，父汇集结果。子会话是真实 session（沿用 F1/F2 的每会话冻结），并发发生在**会话之间**。
- **最小实现面（比 A 多出的部分）**：① `session→parent-session` 持久关系（今日不存在，F17）；② 一个**新的 typed 控制能力**（派生/驱动），因为 F9/F10 要求模型只能经 typed tool 行动；③ 扇出上界与超限 fail-closed；④ 父-子证据与成本归因投影；⑤ 子会话的 grant 派生与降权规则；⑥ 停止/取消语义（F7 是前置）。
- **关键边界性质**：这一步让**模型输出成为创建会话与驱动回合的触发器**。即使全部经 typed capability + policy + C7，它仍是一条新的控制路径（C6），且需要"子 scope ⊆ 父 scope ⊆ 任务 scope"作为**新契约**而非继承流程规则（见 §6）。**本文件不授权它。**

### 3.3 形态选择与编号说明

本文件选 **GC**（`docs/product/`）而非 ADR，理由有三，且可核查：

1. **前例**：`AB-P3A:15,72` 明确把 `agent-spawns-agent` 留给"后续 GC"（`GC-P3:65` 把同会话并发留给独立 ADR）；本文件正是那一份。
2. **本文件不移动任何权威边界**：A 形态零改动；B 形态被显式写成"需 ADR 前置"，本文件不自行授权（对比 `ADR-0055`/`ADR-0059` 那种"本 ADR 即决定"的写法）。
3. **ADR 的职责是冻结决定**，而当前缺的是先有可证伪 gates、威胁模型与操作者体验定义——GC 的本职。

**编号核查（2026-09-18 实测）**：`docs/adr/` 现存最高为 **ADR-0059**（`ADR-0059-merged-capability-execution-authority.md`）；文件里已存在重号（`ADR-0039`×2、`ADR-0040`×3、`ADR-0041`×2），因此**不得**重用这些编号；**ADR-0056 是空号**；**0060 已被 `ADR-DRAFT-0060-donor-repository-retirement-2026-09-15.md` 占用**（该草稿只存在于未合并分支 `codex/spine1-donor-extraction-20260915`，不在 `origin/main`）。因此若 founder 选 B，**必须新开 ADR-0061**（本文件不改 ADR 目录）。另：本行初稿误写为 0060，已按同日 `GC-MCP-FORM-AND-BOUNDARY-2026-09-18.md:77` 的独立核查更正为 0061；该更正属编号事实修正，不移动任何决定。

## 4. 治理约束（A/B 两形态共同不变量）

1. **子代理只能通过有作用域的 typed capability 行动**（F9、F11）：无 capability、无 grant、无 permit 的动作一律 `CapabilityDenied`/`DENY`，fail-closed。
2. **不得继承父的授权，不得洗白权限**：每个子代理的每个高后果动作需要**自己的** grant+decision+permit；父的 permit 不能被复用（digest/fence/5 分钟过期，F12）；`grant.max_risk_tier`/`budget_limit` 是上界，子不得超过父；"一次批准覆盖多个动作/多个子代理"必须不可能（F13 的 digest 绑定）。
3. **每个会话各自的人审与审批**：审批面在其会话内呈现，仅作用于该会话；**不得批量跨会话批准**，不得自动批准 tier-3（F13/F14）。
4. **C7 不可绕过**：C7 保持 non-writable、non-bypassable；子代理不得调用、模拟或清除 `op_*` 主权面；任何新路径必须在派发前仍经过既有 authority spine（`AGENTS.md:33-34`）。
5. **证据/审计可归因**：每个子代理的动作、审批与纠正事件必须落在**它自己 task_id 的持久事件流**里，能回答"这一步是哪个子代理做的、以谁的授权、被谁批准"。
6. **单 principal 现实**：surface 层不区分主体（F15），因此"子代理身份"只能表达为 **task/run/grant/permit 的绑定**，不能表达为独立 principal。任何"给子代理单独身份"的想法都需要新 ADR；本文件不采纳。
7. **不新增终端治理入口**：创建/派生仍 API-only（Stage 2c/2d）。

## 5. 操作者体验（必须逐项可达，否则不得声称该能力）

| 问题 | 今天的答案 | 缺口 |
|---|---|---|
| 看见子代理在做什么 | `agents` 只读树（标识/状态）；活动会话流式，其余轮询 | 无 `label`；非活动会话无流；被拒动作无卡片（F8） |
| 单独停掉一个 | `POST …/pause` 路由存在但**不生效**（F7） | 需要 `QUEUED→PAUSED` 之外的"回合优雅中止"切片；**前置阻塞** |
| 成本归属 | 仅活动会话的 token 累计；cost 恒 `UNKNOWN`（F16） | 每会话 token/预算归因数据不在列表投影里（F5 刻意排除 tokens） |
| 失败归属 | 该会话内 typed 状态 + 持久事件 | 跨会话汇总视图；DENY 不可见 |
| 批准归属 | 每会话 `y/n`，票绑 digest | 无批量（正确）；但待批准数在树上只有布尔 |

**判断**：在 A 形态下"看见 + 单独停 + 成本/失败归属"三项中，**第 2 项今天不可达**。若 founder 要求"多智能体"含"可单独停止"，则 §7 G6 是**先决 gate**，必须先做一个可运行的最小切片（真相是：`pause_task` 的失败已被改成"如实报错"，见 `CURRENT_STATE.yaml:51` 缺陷 (a)）。

## 6. 与既有边界的关系

- **与 GC-P3/AB-P3A 一致**：A 形态是 P3a 的自然延续；P3b（同会话多路复用）仍不在范围内，也不因本文件被解冻。
- **与 Stage 2c/2d 一致**：终端只读展示与切换，创建/派生 API-only。
- **与 mandate 树一致**：`StandingMission.parent_mandate_digest` 是既有派生层级；派生 mandate **不授权执行**（`GC-P3:30`）。B 形态若引入子代理，须复用这条层级而不是自建第二套。
- **与 ADR-0055/ADR-0059 一致**：LLM 仍是器官，untyped 输出不得直接成为后果性命令（`ADR-0055 §3`）；唯一派发路径是 `CapabilityBroker.invoke`（`ADR-0059`）。
- **与工程治理仓的 subagent 流程规则**：`child ≤ parent ≤ task` 的 scope 单调性在工程治理仓是**流程规则**（`GC-P3:72`）——产品要引入同等约束，必须以**新契约 + held-out 产品门**进入，**不得**由流程规则直接继承。
- **C6/C7 保持证明（本文件给出的判据，非完成证明）**：新增能力不得产生第二条派发路径；所有子代理动作仍走 `CapabilityBroker.invoke`（`capability.py:112-227`）；C7 校验仍在派发线性化之前（`capability.py:117-118` 的 `guard_unchanged`）。**B 形态必须提交完整证明**（见 §12 D3）。

## 7. Falsifiable gates

每条 gate 都写"**什么观测会证明它不成立**"。全部为 Product Track 门，须接入 CI（G12）。

- **G1 零新增授权路径（A 形态）**
  - 断言：A 形态下创建/切换会话不产生任何能力派发。
  - **不成立的观测**：给 `CapabilityBroker.invoke` 加计数探针，创建 N 个会话并切换若干次后计数 > 0；或实现 diff 中出现任何新 capability/permit/policy/approval 符号。
- **G2 每会话冻结逐字节不变**
  - 断言：N 会话并跑时，会话内第二次 begin-turn 仍报 typed `TURN_IN_PROGRESS`（复用 `tests/product/test_surface_stream_runtime.py:1-10` 的四条口径）。
  - **不成立的观测**：第二次 begin-turn 成功；或会话 A 的在途回合**阻塞**了会话 B 的 begin-turn（跨会话误冻）。
- **G3 无权限洗白**
  - 断言：子代理动作需要自己的 grant+permit；父的许可不可复用。
  - **不成立的观测**：把父会话的 `permit_id`/`action_digest`/审批票据（或另一会话的）用于子代理动作而被 broker 或 policy 接受；或子代理动作以 `max_risk_tier` 超过父 grant 仍被 `ALLOW`（对应 `governance.py:352-360,368-372`）。
- **G4 每会话人审、无批量批准**
  - 断言：不存在服务端一次请求批准两个会话的路径；tier≥3 无真人 `ApprovalDecision` 必 `ESCALATE`（`governance.py:382-385`）。
  - **不成立的观测**：构造跨会话审批（会话 A 的票用于会话 B）被接受；或出现任何一次请求把多个会话的 pending 置 APPROVE；**或客户端出现循环批准/自动批准逻辑**（服务端只认证单 bearer，`surface_routes.py:155-162`，所以客户端侧必须单独断言）。
- **G5 证据可归因**
  - 断言：子代理的每次派发/审批/纠正事件可在其自身 task 事件流定位。
  - **不成立的观测**：某次子代理动作只出现在父会话 task 流中、或其自身 task 流缺该事件；或两条不同会话的动作有相同 turn 归因。
- **G6 单子代理可停（**当前 NOT_MET，先决**）**
  - 断言：能单独中止一个会话的在途 turn，且其他会话不受影响；停止后有 typed 结果与可见状态。
  - **今天的不成立观测（已复现记录）**：对 surface 会话 `pause` 抛 `InvalidTransitionError`（Run 停在 `QUEUED`，`task_service.py:2396` 允许集不含 `PAUSED`；`CURRENT_STATE.yaml:51` 缺陷 (a)）。
  - 判据：任何声称"多智能体"的完成声明，必须先在 pty 实测中观测到"SINGLE_SESSION_STOPPED: True 且 OTHER_SESSION_UNTOUCHED: True"。
- **G7 扇出有界、超限 fail-closed（仅 B）**
  - 断言：N 上限存在，N+1 次派生得到 typed 拒绝与可见结果，不静默排队或静默丢弃。
  - **不成立的观测**：第 N+1 次派生静默成功/静默排队/无 typed 错误；或 N 次派生的内存/连接/锁表（`surface_runtime.py:174-176`）无实测上界。
- **G8 模型不得直接触发派生（A 形态）/ 只能经 typed 控制能力（B 形态）**
  - 断言：A 形态下能力名空间无"创建会话/驱动回合"项（今日 `domain_packs/developer_agent/__init__.py:47-58` 成立）。
  - **不成立的观测**：工具/capability 注册表里出现任何能创建会话或驱动他会话回合的项，而对应形态尚未有 ADR。
- **G9 子代理不得写父状态**
  - 断言：子会话的一个回合不改变父会话的投影字段（`surface.py:160-186`）与父的 task 事件流。
  - **不成立的观测**：子代理 turn 后父会话 snapshot 任一字段时间戳/计数变化；或父 task 事件流新增由子代理产生的事件。
- **G10 降级不崩**
  - 断言：daemon 换代（`STREAM_GONE`）、会话 closed、树字段缺失时给 typed 结果与可见状态，不崩、不静默清空。
  - **不成立的观测**：注入上述三种条件后进程退出/异常冒泡/树变空而无提示。
- **G11 审批与运行状态可见（A 与 B）**
  - 断言：任一子代理处于 pending 审批或停滞时，其状态在操作者可见面出现（沿用 P2/P3a 的 pty 断言口径，`AB-P3A §8-§10`）。
  - **不成立的观测**：存在"pending 但操作者看不到"的状态；**已知反例类**：`DENY_BY_RULE` 不产卡片（F8）——故本 gate 当前只能对"审批与停滞"成立，对"被拒"**不成立**，必须如实标注而非绕过。
- **G12 gate 必须接进 CI 且不可被静默移除**
  - 断言：新 gate 进入 `tests/product`（受治理套件）或 cli-ts 套件，且接线自守覆盖它。
  - **不成立的观测**：删除/中和该 CI 步骤（`|| true`、`--if-present`、改名脚本为 no-op）后其余检查仍全绿。

## 8. 威胁模型

| # | 威胁 | 现有防线 | 缺口 / 需要的观测 |
|---|---|---|---|
| T1 | **失控扇出**（放大循环、denial-of-wallet） | 每会话一个 in-flight（F1）；grant `budget_limit`（F11）；`BUDGET_EXCEEDED`（`governance.py:377`） | 无跨会话总预算、无扇出上限、无速率限制（`CURRENT_STATE.yaml:52` 明确"没有客户端侧限流"） |
| T2 | **权限洗白** | grant 绑 principal/tenant/workspace/capability/version（F11/F12）；审批票绑 digest（F13）；DENY 规则只减权（F14） | 无"子 ≤ 父"契约；surface 层不区分主体（F15），父子只能靠 task/grant 归因 |
| T3 | **证据混淆** | 每 task 独立持久事件流；turn 归因按会话（F3） | 跨会话无父子投影；成本只有活动会话 token（F16） |
| T4 | **子写父状态 / 视图夺走审批面** | `/resume` 守卫是回合状态谓词 `canStartTurn()`（`AB-P3A §9`） | 该类缺陷**已真实发生过一次**（旧守卫用 `busy`，审批挂起时 `busy` 已清零 → 切换会把审批面移出视野）。任何新切换/派生路径必须用**驱动真实回合到 `awaiting_approval`** 的测试来证否，不能只看状态字段 |
| T5 | **批量/自动批准** | 无批量路由（F6）；无 ALLOW 型规则（F14） | 客户端可循环；历史上有过 `AutoApproveGateway` 类 review debt（`CURRENT_STATE.yaml:572`） |
| T6 | **观测面泄露** | 列表投影刻意不含内容/凭证（F5） | label 等新字段可能引入内容；跨租户/跨工作区隔离必须保持 |
| T7 | **"停不下来"** | — | F7：单会话停止今天不生效，等于"能启动不能中止"，对本能力是**硬阻塞** |

## 9. 负面清单（明确不做）

1. 不做同会话内并发多回合/多路复用（GC-P3 的 P3b）。
2. 不做自动批准、批量批准、任何形式的 tier-3 自动放行（F13/F14）。
3. 不给模型"创建会话/驱动回合"的 capability，直到 B 形态的 ADR 通过。
4. 不让子代理继承父的 grant/permit；不做"父一次批准覆盖全部子代理"。
5. 不在终端新增治理/执行入口（Stage 2c/2d）。
6. 不把工程治理仓的 subagent scope 流程规则直接当产品契约（`GC-P3:72`）。
7. 不跨租户/跨工作区展示；不在树里渲染 mission/statement 文本或凭证。
8. 不给子代理独立 principal（需新 ADR）。
9. 不设"自主/多智能体能力/超越主流"类主张；不写 `Autonomy(S,E,O,V,T)`。

## 10. 失败与回滚

- 特性开关（沿 P2/P3a 先例）：`--no-agents` 关闭树面板即回 P2 行为；B 形态另需 `--no-fanout`，默认关。
- 契约策略：只增可选字段 + 保留旧解码（`CP-TERMINAL-CODING-AGENT-M2 §Version bumps`）。
- 回滚：移除新面板/新能力注册即可；A 形态无数据迁移、无写路径；B 形态需说明派生关系数据的回滚方式（**未设计**，B 未授权故不细写）。

## 11. 负面地图与先例（写 gates 时已吸收的教训）

1. **`AB-P3A §9`**：切换会话的守卫缺陷只能用"驱动真实回合到 `awaiting_approval`"的探针暴露。→ 本文件的 G9/G11 不接受静态状态断言。
2. **`AB-P3A §10`**：pty 证据必须先证明 daemon 身份，否则 fixture bug 会被误读为产品缺陷（曾产生一个假的 NOT_MET 结论）。→ 任何扇出 e2e 必须先打印 daemon 身份与稳定性。
3. **`CURRENT_STATE.yaml:29`**：P2 曾因 Tab 抢焦点造成输入丢失 HIGH 回归。→ 视图层变更必须带 `TYPABLE_*` 类断言。
4. **`CURRENT_STATE.yaml:51`**：`pause` 不生效与 DENY 不可见，两条都是"实现看着像做完了、真值是假的"。→ G6/G11 设为**先决**而非收尾。
5. **`CURRENT_STATE.yaml:52`**：founder 2026-09-18 判定同模型 subagent 评审足够，但 `builder_id != reviewed_by` **未满足**、无独立 provider 批准。→ 本文件自身也受同一评审等级约束，须如实声明。
6. **`GC-P3:65`**：把并发/内核语义变更留给独立 ADR 的先例。→ B 形态按同一标准处理。
7. **`CURRENT_STATE.yaml:53-54`**：P3a 设计包中"需协议扩展/需解冻"的早期判断被实现结果证伪。→ 本文件对 A 形态的"零改动"判断同样**可被证伪**（G1/G2），不等同于已验证。

## 12. 需 founder/CTO 决策

- **D1 形态选择**：A（操作者驱动、多次独立会话）还是 B（父派生子会话/扇出）还是"A 先行、B 另立 ADR"（本文件推荐）。影响：B 需要 ADR-0061 + C6/C7 保持证明 + 安全评审 + canary/rollback，A 只需收尾。
- **D2 先决范围**：是否批准先做 **G6（单会话可停）+ F8（DENY 可见）** 这两个缺口的最小切片——不做则"多智能体"不得声称"可单独停止/可看见被拒"。这是本文件**唯一建议立即开工**的部分，且它本身不引入新授权。
- **D3 若选 B：ADR-0061 前置内容**是否接受如下清单（派生关系的持久模型、子 grant 派生与 `child ≤ parent ≤ task` 契约、扇出上界与超限行为、父子证据/成本归因投影、停止与取消语义、C6/C7 保持证明、canary/rollback、独立评审身份）。
- **D4 扇出上界与资源预算**：N 上限、超限行为（typed 拒绝）、以及是否要求**跨会话总预算**（今日不存在，T1）。
- **D5 协议策略**：是否批准"为多会话可读性补齐 `label` 等附加可选字段并按 minor 升版保留旧解码"（C2 要求先定政策）。
- **D6 成本可见性**：是否接受"成本归因只到 token、金额恒 `UNKNOWN`"（F16），或要求引入定价源（本文件判为**不引入**）。
- **D7 陈述修正**：是否授权修正 `docs/CURRENT_STATE.yaml:29`（C1）与 `:52`（C3）两处过时陈述；以及 `:updated`/`live_pins` 落后 live HEAD（C4）是否由本批文档一并更新。

## 13. 度量（量化，替代口号）

- 单会话停止的实测：`SINGLE_SESSION_STOPPED`、`OTHER_SESSION_UNTOUCHED`、停止到可见状态的延迟。
- N 并发会话的资源上界：进程内存、连接数、`_locks` 表条目数（实测数字，非估计）。
- 审批可见率：任一会话处于 pending 时在其视图内可见的比例 = 100%（pty 断言）。
- 树面板刷新：轮询周期与空闲写入字节（沿 P2 指标：空闲 0 字节）。
- 扇出（若 B）：N 上限、超限 typed 拒绝率 100%、跨会话事件归因错误数 = 0。

## 14. 声明分级（当前）

`specified: 本文件` / `implemented: NO` / `tested: NO` / `integrated: NO` / `verified: NO` / `released: NO`。

未被授权的动作：架构评审通过与 CTO gate、任何运行时/契约/协议/内核改动、B 形态的 ADR-0061、G6/D2 之外的下游实现、发布与合并。

**本文件是 `specified only`**：所列 A 形态的"已存在"事实来自代码与既有文档的读取（§2，含行号），**未**新增任何实现、未运行任何新测试、未做运行期攻击复现；F7/F8 是**已知未修缺陷**的自述转引，本文件未独立复现。不得据此声称"支持 subagents / 多智能体 / fan-out"或任何 parity 主张。
