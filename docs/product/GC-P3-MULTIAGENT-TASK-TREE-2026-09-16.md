# GC-AB — P3 多 Agent / 任务树（2026-09-16）

- **状态**：`DESIGN_ONLY / DOCS_ONLY / AWAITING_CTO_GATE / NO_IMPLEMENTATION_AUTHORITY`
- **范围**：全屏 TUI（P1/P2 已合并 `fbdb865a`）之后的多 Agent / 任务树能力。
- **结论（先给判断）**：**该能力默认不需要解冻"一会话一回合"**。冻结的是 *每会话* 的 in-flight turn；把每个 Agent 建成各自 session 即可在保持冻结不变量的前提下得到多 Agent 视图。只有"同一会话内并发多回合/多路复用"才需要解冻——那是另一个特性，**不建议**在 P3 做。
- **本文件不授权任何运行时代码/契约/协议改动。**

## 1. Goal Card

- **目标**：在终端提供"多 Agent / 任务树"的工作视图——可见多个 Agent（会话）及其从属关系，可切换/观察，各自独立流式与审批。
- **非目标**：
  - 不在终端增加治理/管理权限（Stage 2c/2d 已定：`work/run`、mandate、task、workflow、selfdev 均 API-only）。
  - 不解冻 `TURN_IN_PROGRESS`（rev 9）。
  - 不改变 permit/approval/C7；不允许子 Agent 自行审批。
  - 不改 `Agent Core` 领域中立性；不引入新的跨仓依赖。
- **证据类别**：**产品能力**（Product Track），非研究证据；不得由研究/流程证据回填。
- **退出条件**：见 §7 gates；每项 capability 需公共入口 + typed contract + 失败路径 + 集成点 + trace/evidence + 权限 + rollback + 分级声明。

## 2. Context Pack（当前事实，均已核对）

| 事实 | 位置 |
|---|---|
| 冻结 rev 9：每会话一个 in-flight turn，无排队/多路复用，第二回合报 typed `SurfaceTurnInProgress` | `packages/os_core/src/agent_os_core/surface_runtime.py:73,405-421` |
| 订阅先于执行（frozen）：先 subscribe 拿 stream_id，再 bind begin-turn | `surface_runtime.py:229-236` |
| 会话投影只读、最小化（不含 statement/envelope/outcome/tokens/凭证） | `packages/contracts/src/agent_os_contracts/surface.py:173-186` |
| `SurfaceSessionSnapshot` 字段：session / envelope_id / expected_outcome_id / status / event_sequence / message_count / pending_approval / permission_mode / updated_at | `surface.py:160-171` |
| `SurfaceSessionSummary` 字段：session_id / **task_id** / status / permission_mode / message_count / updated_at | `surface.py:173-186` |
| 协议版本以字面量 `"1.1"` 固化在每个响应里 | `surface.py`（多处 `Literal["1.1"]`） |
| mandate 存在派生树：`StandingMission.parent_mandate_digest` | `packages/contracts/src/agent_os_contracts/mandate.py:112-127` |
| mandate 记录**不得**授权执行（`task_activation_authorized`/`capability_grant_authorized` 必须为 False） | `mandate.py:129-142` |
| `AgentInstanceRef` 显式排除 mission/permissions/env/learning | `mandate.py:102-109` |
| 终端进度：P0/P1（全屏）、P2（多面板 `transcript`+`files`+`diff`、独立滚动、sticky context-lock、`--no-panels/--no-animation`）已合并 | `docs/product/GC-TUI-FULLSCREEN-MIGRATION-2026-09-15.md` §7-§9 |
| Stage 2c/2d：治理面 API-only；surface 协议保持 v1.1 | `docs/CURRENT_STATE.yaml` `stage2_path_a_migration_2026_09_15` |

**OPEN（需实现前核实，勿在设计中当作已知）**
1. 会话与 mandate/task 的**从属关系**是否已持久化并可读？（`SurfaceSessionSummary.task_id` 存在，但 session→mandate、session→parent session 未见字段。）
2. 客户端能否同时持有 N 条 per-session stream？（当前 `TuiController` 单会话；stream registry 为 per-session。）
3. 附加可选字段是否触发协议版本策略（`Literal["1.1"]` 与兼容规则写在何处）。
4. 派生 mandate 的创建/绑定入口（`/v1/mandates:bootstrap|attach`）是否已覆盖 worker/subagent 场景。

## 3. Architecture Brief（推荐方案 P3a：只读树 + 每 Agent 一 session）

- **数据面（新增，只读）**：扩展现有会话列表投影，附加 **可选** 关系字段：
  `parent_session_id: str | None`、`mandate_id: str | None`、`label: str | None`、`pending_approval_count: int = 0`。
  - 兼容性：可选字段、只增不改；是否需版本递增按 OPEN#3 的政策决定（**先定政策再动手**）。
  - 不泄露：沿用 `SurfaceSessionSummary` 的"最小投影、绝不泄内容/凭证"原则。
- **关系来源**：沿用既有 mandate 派生树（`parent_mandate_digest`）与会话→task 关联；**不新建**第二个层级模型。
- **控制面**：创建/派生 Agent 仍走既有治理 API（API-only）；终端**只读**展示与切换。
- **客户端**：
  - 树模型：`sessions[]` + 关系字段 → 纯函数构建树（可测，不依赖渲染器）。
  - 会话控制器：仍**每会话一个** `TuiController`；活动会话决定 composer/审批面；切换 = 重订阅该会话 stream。
  - 每会话各自保留"一回合在飞"不变量；其审批面在其会话内呈现。
  - 面板：复用 P2 右侧栏 → 新增 `agents` 面板（树），`Tab` 选中、独立滚动。
- **失败路径（必须有 typed 处理与可见结果）**：`STREAM_GONE`（daemon 换代）、`TURN_IN_PROGRESS`（该会话已有未提交回合）、会话 `closed`、未授权（无本地权限路径）、列表投影字段缺失（降级为平铺列表，不崩）。
- **权限/审批**：切换会话**不**授予任何权限；每会话审批仍为人工 `y/n`，仅作用于该会话；终端不得批量批准（**gate G5**）。
- **不变量**：SurfaceClient/TuiController 的协议语义、`TURN_IN_PROGRESS`、订阅先于执行、C7/permit 不变。

### 备选方案 P3b（**不建议**，仅记录）
同会话内并发多回合/多路复用：需改 `surface_has_uncommitted_turn` 语义、idempotency/锁模型与流绑定，属 **内核并发语义变更**，需独立 ADR + C6/C7 保持证明 + 安全评审 + canary/rollback。**非 P3 范围**。

## 4. 与既有边界的关系

- 与 Stage 2c/2d 一致：终端不新增治理入口，仅只读展示。
- 与 `MandateWorkspaceRecord` 一致：树/派生 mandate 不授权执行。
- 与 `AgentInstanceRef` 的"不泄露 mission/permission/学习历史"一致：树面板只显示标识、状态与计数，不显示 mission 文本或凭证。
- 参考（**非产品运行时**）：多 Agent 委派的 scope 单调性（子 ≤ 父 ≤ 任务）在工程治理仓为流程规则；若产品要引入同等约束，须作为**新契约**进入 held-out 产品门，不能由流程规则直接继承。

## 5. 失败/回滚

- 特性开关：`--no-agents`（等价 P2 行为）；契约字段全可选 → 旧客户端不受影响。
- 回滚：移除树面板与可选字段消费即可回到 P2；无数据迁移、无写路径。

## 6. 安全评审范围（P3a 开工前）

1. 树投影是否泄露会话内容/凭证/mission 文本（对照 `SurfaceSessionSummary` 的最小化原则）。
2. 是否存在任何"切换会话→提升权限"或"跨会话审批"路径（**必须无**）。
3. 多会话流订阅的资源上限（N 条 stream 的连接/内存上界、断开与换代处理）。
4. 附件字段是否引入跨租户/跨工作区可见性（tenant/workspace 隔离必须保持）。
5. 不涉及 C7/permit/approval 语义变更的证明（若证明不了 → 停止并升级）。

## 7. Falsifiable gates（每项须独立可测，通过才推进）

- **G1 只读**：树/关系字段的读取路径无任何写/执行调用（可测：调用图 + 失败注入）。
- **G2 不变量保持**：新增能力下 `TURN_IN_PROGRESS` 行为逐字节不变（复用 `tests/product/test_surface_stream_runtime.py` 断言）。
- **G3 无权限提升**：切换会话不改变授权；构造"通过树面板触发动作"的攻击用例必须失败。
- **G4 审批前台性**：任一会话的 pending 审批在其视图内可见且必须人工确认；跨会话批量批准不可达。
- **G5 最小投影**：新字段不含 statement/envelope/outcome/tokens/凭证（契约测试 + 快照）。
- **G6 降级**：字段缺失/会话关闭/`STREAM_GONE` 时 UI 不崩且状态可见（pty 证据）。
- **G7 兼容**：旧客户端对新服务端、新客户端对旧服务端均可运行（契约兼容测试）。

## 8. 度量（量化，替代口号）

- 多会话切换 p95 延迟；N 条 stream 时的内存/连接上界（实测数字，非估计）。
- 树渲染帧字节与空闲写入（沿用 P2 指标：空闲 0 字节）。
- 审批可见性：任一 pending 审批在 N 会话下的可见率 = 100%（pty 断言）。

## 9. 未决问题与需 Founder/CTO 决策

1. **协议版本策略**（OPEN#3）：可选字段是保持 `1.1` 还是升 `1.2`？→ 需先定政策。
2. **关系数据来源**（OPEN#1）：是否已有 session↔mandate/parent 持久化？缺失时是否允许新增只读字段（不改写路径）？
3. **范围选择**：是否确认 P3a（只读树、每 Agent 一 session）为 P3 唯一范围，P3b 另立 GC？
4. **是否允许终端只读消费治理投影**：与 Stage 2c/2d 的 API-only 决定是否一致（本设计判为一致，因不改治理面）。
5. **N 的上界**：并发会话/流的硬上限与超限行为。

## 10. 声明分级（当前）

`specified: 本文件` / `implemented: NO` / `tested: NO` / `integrated: NO` / `verified: NO` / `released: NO`。
未执行：架构评审、CTO gate、实现、测试、独立评审、发布授权。**不得**据此声称多 Agent 能力、自主性或 market parity。
