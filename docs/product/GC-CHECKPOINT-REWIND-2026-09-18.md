# GC — Checkpoint / Rewind 的形态与边界（2026-09-18）

- **状态**：`DESIGN_ONLY / DOCS_ONLY / AWAITING_CTO_GATE / NO_IMPLEMENTATION_AUTHORITY`
- **上游**：`docs/CURRENT_STATE.yaml:52`（founder 2026-09-18 原文：`checkpoint/rewind does not exist AT ALL yet`）；同批姊妹文档 `docs/product/GC-SUBAGENTS-AND-FANOUT-2026-09-18.md`、`docs/product/GC-TYPED-HOOKS-2026-09-18.md`、`docs/product/GC-MCP-FORM-AND-BOUNDARY-2026-09-18.md`
- **基线**：本 worktree `.worktrees/wt-checkpoint-gc`，HEAD = `03ac66b563e689fd3c87d38eed2aae400989f6d5`（`origin/main`）。**本文件所引行号全部为此 HEAD 上亲自读取所得**，未转引任何其它文档中的二手断言。
- **范围**：终端线唯一产品路径（`apps/cli-ts` + `apps/api_server` + `packages/os_core`）上的 **checkpoint / rewind**——该不该做、以什么形态做、边界在哪；以及与 `session pause`（中途优雅停机）共享的那块地基该怎么切。
- **结论（先给判断）**
  1. **checkpoint/rewind 今天在任何操作者可及路径上都不存在**：全仓代码 `rewind` 零命中；`apps/`（含 `apps/cli-ts`、`apps/api_server`）`checkpoint` 零命中；`domain_packs/` 零命中（F1）。`docs/CURRENT_STATE.yaml:52` 的 founder 记录与此一致。
  2. **但它不是一块空地。** 仓内已有三块真地基可以复用，且都有实现与测试：① **会话回合的 durable continuation checkpoint**（digest 绑定、单调前进、受保护 writer，F2/F3/F4）；② **单动作文件前像快照 + 前向补偿**（`workspace.apply_patch` 落 before 字节，`workspace.compensate_patch` 前向还原，F8/F9/F10）；③ **C7 halt + `correction_halted` 的中途优雅停止**（F13）。**结论：本线应做"追加式 checkpoint + 前向 restore"，不做"状态回滚/时间旅行 rewind"。**
  3. **"回到已知良好状态"在本仓的因果性约束下只对两个维度成立**（任务/回合游标、以及被治理写入的文件目标），对**第三个维度（外部效果）永远不成立**——效果收据、审计事件、C7 epoch 都是不可变或只增的（F5/F6/F7）。把"全部回退"卖给操作者会是一条**伪能力**；正确的操作者承诺是"**显式地告诉操作者哪些维度回去了、哪些没有**"。
  4. **与 `session pause` 共享的地基是同一句话**："一个进行中的回合能不能被安全地打断，并回到一个已知良好状态"。今天最接近的答案是 C7 correction（能停、但不能从终端解除），而**普通 `pause` 会留下一个永不提交的回合**（F14/F15/F16，读码推断，本文件未复现）——建议先切一个**回合级 P0**（只读回合 checkpoint 投影 + 有权限的优雅中止），它自身不引入任何新授权。
  5. **本文件不授权任何实现。** 不授权运行时代码、contracts、协议、内核或终端的任何改动；不授权 ADR 开写；不授权任何 checkpoint/rewind 能力的对外声明。

## 0. 容器与编号（为什么不是 ADR）

- **容器选择**：放 `docs/product/` 的 GC，形制对齐同批姊妹文档（状态行 / Goal Card / Context Pack / 候选形态 / gates / 决策项 / 声明分级同一套）。理由：本文件是**产品能力范围卡**（做什么、不做什么、过什么门），不是已定架构决议。仓库里 `Accepted` 的 ADR 记录已决事项；未决的边界提案以 GC + `AWAITING_CTO_GATE` 表述更诚实。
- **编号核查（2026-09-18 在本 worktree 实测）**：
  - `docs/adr/` 现存**最高编号为 ADR-0059**（`ADR-0059-merged-capability-execution-authority.md`）；
  - **ADR-0056 是空号**（`ls docs/adr/ | grep -c 'ADR-0056'` = 0）；
  - 目录内存在**历史重号**且**不得复用**：`ADR-0039`×2、`ADR-0040`×3、`ADR-0041`×2；
  - **0060 已被占用**：`docs/adr/ADR-DRAFT-0060-donor-repository-retirement-2026-09-15.md`（blob `0257682f43affaa6e816c5f2f6e8f7b9b37a794c`，由 `901c2108` 加入，所在分支 `origin/codex/spine1-donor-extraction-20260915`；`git merge-base --is-ancestor 901c2108 origin/main` → **NO**，即该草稿**不在 `origin/main`**，但在远端存在，不能视为可用别号）。
  - 因此：**GC 家族按 `GC-<主题>-<日期>` 命名，不占四位序号；本文件不占用任何 ADR 号。** 若 founder 决定把本线冻结为 ADR，**下一个安全号是 0061**，且**必须在开写前重新核查**（同批其它线、其它 worktree 也可能取号）。
- **本文件不改任何 ADR 文件，也不改 `docs/CURRENT_STATE.yaml`**（本轮由 coordinator 拥有）；需要它的改动以 §15 D 项与 §2 的 C 项列出。

## 1. Goal Card

- **目标**：为"checkpoint / rewind"给出**允许形态、不可回退维度的诚实边界、治理不变量、威胁模型、可证伪 gates 与操作者体验**，供 founder/CTO 决定是否立项、立项选哪个形态；并单独给出与 `session pause` 共享地基的**最小切片建议**。
- **非目标**：
  - **不追求超越主流、不追求范式级差异化**。目标是与 Claude Code / Codex CLI / Hermes / OpenClaw / Pi **对等**的终端体验，checkpoint/rewind 属于该集合中的一项体验面，不是产品身份。
  - **不做"时间旅行/任意回退"**：不把已发生的外部效果从证据、审计或 C7 状态里抹掉（§4）。
  - **不改 permit / approval / C7 语义**：不新增第二条派发路径，不让 rewind 成为绕过 `UNKNOWN_REQUIRES_REVIEW` 的旁路（§5）。
  - **不改 `TURN_IN_PROGRESS`（每会话一个 in-flight turn，rev 9）**：本线要回答的是"这一个回合能不能被安全打断"，不是"能不能并行多个回合"（后者是 P3b，另一个 GC/ADR）。
  - **不改 receipt / evidence / 补偿记录语义**：不因为 rewind 把 `ReceiptStatus` 或 `ACTION_RECEIPT_RECORDED` 重写。
  - **不引入新的跨仓依赖**，不让 Agent Core 产生领域语义。
- **证据类别**：**产品能力**（Product Track）。不得由研究证据或工程流程证据回填。
- **退出条件**：§11 的 gates 全部有可观测证据；每项能力须有公共入口 + typed contract + 失败路径 + 集成点 + Trace/Evidence/Outcome + 权限 + rollback/compensation + 分级声明（`AGENTS.md:57`）。

## 2. Context Pack（已核对事实；每条含位置）

| # | 事实 | 位置 |
|---|---|---|
| F1 | **checkpoint/rewind 今天不存在于任何操作者可及路径**：`rewind` 在 `apps/ packages/ domain_packs/ tests/`（`*.py`/`*.ts`/`*.tsx`）零命中；`checkpoint` 在 `apps/` 零命中、在 `domain_packs/` 零命中；`packages/os_core` 内 255 处全部属于内核/责任环内部机制（F4/F7），`packages/contracts` 内出现在 `evaluator.py:37-38`、`external_boundary.py:31,63`、`materialization.py:200,209`（评估器/外部边界/物化），均非终端会话能力 | 本 worktree 实跑 grep（见 §18 复现命令清单） |
| F2 | **会话回合的 durable continuation checkpoint 已存在**：`TaskEventType.SESSION_TURN_CONTINUATION_CHECKPOINT` 是正式事件类型；其载荷绑定 `session_id/task_id/run_id/tenant_id/workspace_id/turn_id`、`assistant_message_index/digest`、`next_proposal_index`、`steps`、`total_tokens`、`seen_action_digests`、配置快照 digest、provider profile digest、来源审批/认领 id、`checkpoint_message_index/digest/role`、`resolved_at`、`checkpointed_at` | `packages/contracts/src/agent_os_contracts/runtime.py:91`；`packages/os_core/src/agent_os_core/task_service.py:117-152`（`_continuation_checkpoint_payload`） |
| F3 | **该 checkpoint 单调前进且不可回退**：投影层校验"未前进即报错"、"循环状态回退即报错"（`continuation checkpoint did not advance` / `continuation checkpoint loop state regressed`），并逐字段比对 assistant/tool 游标 | `packages/os_core/src/agent_os_core/session_projection.py:1045`（`_project_continuation_checkpoint`）、`:1144`、`:1159-1160`、`:1163-1176` |
| F4 | **它是"受保护真值事件"**：`PROTECTED_TRUTH_EVENTS` 含 `SESSION_TURN_CONTINUATION_CHECKPOINT`、`ACTION_RECEIPT_RECORDED`、`ARTIFACT_RECORDED`、`OUTCOME_OBSERVED`、`SESSION_APPROVAL_PENDING/…_CLAIMED/…_RESOLVED`；通用 `append_event` 对这些类型直接抛 `InvalidTransitionError("protected event requires a typed writer: …")`，只有持有 `_runtime_writer_token` 的内核 typed 写者能写 | `packages/os_core/src/agent_os_core/task_service.py:78-89`、`:524-527`、`:588-595` |
| F5 | **审计事件流是 append-only 且带序列 CAS**：`SQLiteTaskEventStore` docstring 原文 "Crash-safe append-only task event store"；`task_events` 表 `PRIMARY KEY (task_id, sequence)`、`event_id … UNIQUE`；追加前校验 `expected_sequence == 实际 MAX(sequence)`，不符抛 `ConcurrentWriteError` | `packages/os_core/src/agent_os_core/persistence.py:22-23,40-50,192-203`；协议 `event_store.py:12-21` |
| F6 | **全仓没有删除/篡改任务事件的代码**：`DELETE FROM task_events` / `UPDATE task_events` / `DROP TABLE` 在 `packages/os_core/src/agent_os_core/*.py` 与 `apps/api_server/*.py` **零命中**；`prune`/`retention`/`VACUUM` 亦零命中（`agent_context.py:10` 的 "pruned" 是目录遍历剪枝，与事件无关） | 本 worktree 实跑 grep |
| F7 | **C7 用"epoch 前进"表达纠正，没有"回退"操作**：`CorrectionAuthority.correct(scope, scope_id, reason)` 只能前进 epoch 并置 `halted=True`；`resume(...)` 是**再前进一次**并把 `halted=False`；两者都只在 `CorrectionAdminPort` 上，运行时只拿 `CorrectionReadPort`（`snapshot`/`halted`/`guard_unchanged`）。C7 状态本身也只增（`correction_epochs` 表 `PRIMARY KEY (scope, scope_id)`，写路径是 `advance_correction`） | `packages/os_core/src/agent_os_core/governance.py:49-57`（两个 port）、`:99-107`（docstring）、`:139-167`（`guard_unchanged`）、`:170-187`（`correct`/`resume`）、`:217-245`（`_advance`）；`persistence.py:64-75` |
| F8 | **单一动作的文件前像快照已存在**：`workspace.apply_patch` 在写入前把目标文件的**完整 before 字节**落到 `<artifacts>/compensation/<action_key_sha256>/`，manifest 绑定 `action_key_sha256`/`relative_path`/`before_existed`/`before_sha256`/`applied_sha256`，状态机 `PREPARED → APPLIED → COMPENSATED`；artifacts 默认 `<workspace_root>/.agent-os-artifacts` | `domain_packs/developer_agent/workspace_capability.py:874-961`（`_apply_patch`）、`:1093-1121`（`_persist_snapshot`）、`:1123-1165`（`_load_snapshot`）、`:290-301`（`self.artifacts`） |
| F9 | **前向补偿已存在且被治理**：`workspace.compensate_patch` 是**内部（coordinator-only）**能力，只对 `workspace.apply_patch` 的既有快照生效，恢复前校验 `applied_sha256`/`before_sha256` 与文件当前内容；`COMPENSATED` 是终态，目标再次变化即拒绝。它在 action pipeline 与 execution 两处被显式挡在模型之外 | `domain_packs/developer_agent/workspace_capability.py:1033-1091`（`_compensate_patch`）、`:762-769`（`include_internal` 才注册）、`:416-418`、`:817-818`；`packages/os_core/src/agent_os_core/action_pipeline.py:245-247`、`:421-423`；`execution.py:1512-1514` |
| F10 | **补偿有独立的持久记录与状态**：`PatchCompensationRecord`（`original_action_id`/`compensation_action_id`/`compensation_ref`/`manifest_sha256`/`mode`/`status`/`manual_intervention_required`/`receipt_id`）+ `CompensationMode{AUTOMATIC,MANUAL}` + `CompensationStatus{STARTED,COMPENSATED,FAILED,BLOCKED}` + 事件 `COMPENSATION_STARTED/ACTION_COMPENSATED/COMPENSATION_FAILED/COMPENSATION_BLOCKED`；C7 halted 时补偿被记为 `BLOCKED` 且 `manual_intervention_required=True`；且**"补偿不能回滚已 SUCCEEDED/CANCELLED/VERIFIED 的 Run"**，"补偿需要 FAILED/NOT_MET 或既有介入上下文" | `packages/contracts/src/agent_os_contracts/runtime.py:43-47,183-201`；`execution.py:736-754`、`:845-865`、`:1081-1095`；`capability.py:218-222`（补偿收据状态 `COMPENSATED`） |
| F11 | **UNKNOWN 是终局性的，自动重发被显式禁止**：`DurableActionOutcomeRepository` docstring "Insert-only reservation/outcome codec"；有 reservation 无 outcome → `CapabilityEffectUnknown(RESERVATION_WITHOUT_OUTCOME)`，原文 "automatic resend is forbidden"；有 outcome 无 reservation / 历史无收据同样 → UNKNOWN；`seal` 是 insert-only，冲突时回读校验而不是覆盖 | `packages/os_core/src/agent_os_core/_action_outcome.py:19-39`（`CapabilityEffectUnknown`）、`:77-82`、`:124-174`、`:243-297` |
| F12 | **UNKNOWN 会在 Run 层留下"必须显式和解"的硬门**：`pause_session_for_unknown_action` 把 `unknown_action` 载荷写进 `RUN_PAUSED`；此后 `update_run_status(PAUSED→RUNNING)` 会反向扫描事件，一旦看到最近一个含 `unknown_action` 的 `RUN_PAUSED` 就抛 `InvalidTransitionError("UNKNOWN_REQUIRES_REVIEW requires explicit reconciliation")` | `packages/os_core/src/agent_os_core/task_service.py:1288-1346`、`:2381-2394` |
| F13 | **中途优雅停止今天只有 C7 一条**：`_drive` 每个 step 开头检查 `correction.halted(..., "provider")`，命中则 `stop_reason = "correction_halted"` 并 `break`（回合正常提交）；provider 调用前后另有 epoch 守卫与 `RunExecutionError`。UNKNOWN 则走 `unknown_requires_review`，Run 停 `PAUSED`、`resume` 被拒、只派发一次 | `packages/os_core/src/agent_os_core/agent_loop.py:866-868`、`:1269-1273`、`:1307-1322`；`:474-486`（UNKNOWN 下的回合提交守卫）；`:1110-1135`（`_pause_for_unknown`）；`docs/CURRENT_STATE.yaml:52`（同义记录：no seal / Run stays PAUSED / resume still refused / one dispatch only） |
| F14 | **普通 `pause` 只改 Run 状态，不中断进行中的回合**：`surface_pause_session` → `pause_task` → `update_run_status(PAUSED)`。`_drive` 的 runnable 检查 `run.status not in {QUEUED, RUNNING}` 会**抛 `InvalidTransitionError`**（不是优雅停止），而回合的 `_complete_turn` 只在 `_drive` 正常返回后才执行——异常路径下 `SESSION_TURN_COMPLETED` 永不写出 | `apps/api_server/app.py:2487-2492`、`:2912-2916`；`packages/os_core/src/agent_os_core/agent_loop.py:869-878`、`:390`（`_complete_turn` 调用点）、`:462-486` |
| F15 | **未提交回合会阻塞该会话的下一次 begin-turn**：`surface_has_uncommitted_turn` 的判据是"该会话 task 有 `SESSION_TURN_STARTED` 无对应 `SESSION_TURN_COMPLETED`"，且它是**持久真值读取**；`SurfaceRuntime.begin_turn` 在该判据为真时抛 `SurfaceTurnInProgress`（原文 "a prior turn is still uncommitted for this session"），provider 永不启动 | `apps/api_server/app.py:2299-2319`；`packages/os_core/src/agent_os_core/surface_runtime.py:417-423`、`:70-77` |
| F16 | **Run 状态机里 `QUEUED` 不允许 `PAUSED`**，且 `PAUSED` 只允许回到 `RUNNING`/`CANCELLED`：`{CREATED:{QUEUED,RUNNING,CANCELLED}, QUEUED:{RUNNING,CANCELLED}, RUNNING:{RUNNING,WAITING_APPROVAL,WAITING_EVENT,PAUSED,VERIFYING,SUCCEEDED,FAILED,CANCELLED}, WAITING_APPROVAL:{…}, WAITING_EVENT:{…}, PAUSED:{RUNNING,CANCELLED}, …}` | `packages/os_core/src/agent_os_core/task_service.py:2395-2402`；枚举 `packages/contracts/src/agent_os_contracts/runtime.py:25-35` |
| F17 | **C7 correction 可从终端发，但终端无处解除**：Esc / Ctrl-C 在 streaming/stalled 时发 `correction`；`noem session correct` 也发 `correction`。而解除 halt 的入口是 `POST /v1/tasks/{task_id}/correction/resume`，**`apps/cli-ts` 内没有任何调用点**（`client.ts` 的 action 联合类型只有 `pause`/`resume`/`correction`，且 `session-command.ts` 的 `resume` 走的是 `surface_resume_session` → `resume_task`，与 `resume_correction` 不是同一条路）。会话因此会停在 `CORRECTION_HALTED` 状态 | `apps/cli-ts/src/keys.ts:6-16`、`:30-42`；`apps/cli-ts/src/controller.ts:1544-1583`；`apps/cli-ts/src/session-command.ts:15,55-76,115-124`；`apps/cli-ts/src/client.ts:328`；`apps/api_server/server.py:987-996`；`apps/api_server/app.py:3011-3036`；`apps/api_server/surface_routes.py:241-243,427` |
| F18 | **唯一"未提交回合"的恢复机制是审批续跑**：`resolved_continuation`（审批 TOOL/决议批提交后的精确游标）是投影里除 `pending_approval` 外唯一能让既有 turn 继续的路径；已有测试钉住"未提交的审批暂停回合会挡住第二次 begin" | `packages/os_core/src/agent_os_core/session_projection.py:147-172`（`ProjectedResolvedContinuation`）、`:1045-1214`（`_project_continuation_checkpoint`：投影与单调性校验）、`:594`（`ProjectedSession.resolved_continuation`）；`tests/product/test_surface_begin_turn_integration.py:219-265` |
| F19 | **同一块地基的第二条证据：责任环的 restart checkpoint 同样是"只增 + CAS + 不可回退"**。`ResponsibilityLoopCheckpoint` 绑定 `binding_digest`/`fencing_token`/`last_event_sequence`/`next_transition`；写入时 `BEGIN IMMEDIATE` + fence 校验 + `expected_prior_digest` compare-and-swap，并且**显式拒绝回退**：`"checkpoint event sequence cannot move backwards"` | `packages/os_core/src/agent_os_core/responsibility_loop.py:127-140`、`:1026-1113`；调用方 `responsibility_controller.py:126,264-303` |
| F20 | **契约层的 checkpoint 家族也全是"候选/快照"，不是"可回退状态"**：`ExecutionCheckpointCandidate` 是 mirrored receipt 的**候选**、其 digest 必须等于 subject digest；`TaskConfigurationSnapshot` 是"one Run 的不可变 binding" | `packages/contracts/src/agent_os_contracts/external_boundary.py:31,63,84-90`；`docs/AGENT-OS-PRODUCT-BLUEPRINT.md:108`；`packages/contracts/src/agent_os_contracts/task_configuration.py:147-173`（`TaskConfigurationSnapshot`）；其 seal/读取端点见 `apps/api_server/server.py:546`、`:892` |
| F21 | **上下文压缩会消耗掉"回到更早对话"所需的原始材料**：`SESSION_CONTEXT_COMPACTED` 只在真正发生裁剪时记录 `dropped_messages`/`kept_from_index` 边界，`_compact_history` 在 USER 边界裁剪；压缩后历史里不再有被丢弃的原文 | `packages/os_core/src/agent_os_core/agent_loop.py:1682-1703`、`:1705-1712`；`packages/contracts/src/agent_os_contracts/runtime.py:92` |
| F22 | **Blueprint 已把这两件事写成产品度量，但没有给形态**：Primary measures 含 "recovery and state-equivalence after interruption"、"correction, invalidation and rollback success"、以及"unauthorized or duplicate side effects"；Runtime requirements 含 "idempotency, leases, interruption recovery and effect reconciliation"、"pause/correct/tighten/halt dominance"、"replay/audit without leaking secrets" | `docs/AGENT-OS-PRODUCT-BLUEPRINT.md:253`、`:257`、`:254`（unauthorized/duplicate side effects 行）、`:141`、`:146`、`:147`；C7 定义见 `:111`（`CorrectionChannel (C7)` = external pause/correct/tighten/halt authority，反面是 "writable or bypassable product setting"） |
| F23 | **协议与操作者面现状**：`SURFACE_PROTOCOL_VERSION = "1.1"`；`SurfaceSessionStatus ∈ {ACTIVE, WAITING_APPROVAL, PAUSED, CORRECTION_HALTED, CLOSED}`；`SurfaceSessionSnapshot` 含 `status/event_sequence/message_count/pending_approval/permission_mode/updated_at`；`SurfaceSessionSummary` 刻意排除 statement/envelope/expected-outcome/tokens/凭证 | `packages/contracts/src/agent_os_contracts/surface.py:14`、`:37-42`、`:160-170`、`:173-186` |
| F24 | **服务端状态投影已经把 C7 halt 当作一等状态**：`_surface_session_status` 先判 `correction.halted(task_id, run_id, "provider")` → `CORRECTION_HALTED`，再判 `WAITING_APPROVAL`、`PAUSED` | `apps/api_server/app.py:2630-2650` |
| F25 | **事件类型里已有 node 级失败与压缩两类"状态变更"，可作 checkpoint 事件的形状参照**：`NODE_COMPLETED`/`NODE_FAILED`/`SESSION_CONTEXT_COMPACTED`/`CORRECTION_WRITTEN`/`RUN_PAUSED`/`RUN_RESUMED`；`_record_tool_failure` 明确"拒绝发生在派发之前时没有收据、也没有 NODE_COMPLETED，因此记一条 node 级失败"——这条纪律同样适用于 checkpoint | `packages/contracts/src/agent_os_contracts/runtime.py:50-95`；`packages/os_core/src/agent_os_core/agent_loop.py:1352-1380` |

**需要修正/澄清的既有陈述（本文件与它们冲突或需要收紧的部分）**

- **C1**：`docs/CURRENT_STATE.yaml:52` 的 `checkpoint/rewind does not exist AT ALL yet` 作为**操作者能力**的判断**成立**（F1）。但若被读成"仓内没有任何 checkpoint 概念"，则**不成立**——内核已有 F2/F4/F19 三类 checkpoint 机制。措辞需精确化为"操作者可及路径上不存在"。
- **C2**：同批 `GC-SUBAGENTS-AND-FANOUT-2026-09-18.md` 把"单会话可停"记为对 surface 会话 `pause` 抛 `InvalidTransitionError`（Run 停在 `QUEUED`）。本文件**独立核实**了 `QUEUED` 的允许集不含 `PAUSED`（F16），但发现**更严重的一层**：即便 Run 处于 `RUNNING`，中途 `pause` 也会让回合走向异常路径而**永不提交**，从而**卡死该会话后续所有 begin-turn**（F14+F15）。两条缺陷应分开记账。
- **C3**：`docs/CURRENT_STATE.yaml:4`（`origin_main_code_receipt: 3a70592d…`）与 `:65`（`updated: 2026-09-16T00:00:00+08:00`）**落后于 live HEAD `03ac66b5`**（2026-09-18，PR #69 已合并，其 CI 绿）。本文件不修改该文件，交由 coordinator 处理（§15 D9）。

**未核实 / 未复现（本文件不主张）**

- F14+F15 的"卡死"结论是**读码推断**，本文件**未在真实 daemon 上复现**（纪律：不得起不带显式 `--descriptor/--database/--workspace` 的 daemon，也不得触碰 `~/.agent-os/`）。它被写作 §11 的 **G1**，探针必须由实现/评审方在隔离环境跑出来。
- **整棵工作树的文件状态没有快照**：F8 只覆盖"被 `workspace.apply_patch`/`workspace.edit` 写过的那一个文件"。`workspace.shell` 与 `workspace.run_tests` 的子进程副作用（新建文件、删文件、改目录、外部网络）**没有任何 before 记录**；未测量的还有：一次回合内被改动的文件数分布、单文件 before 字节的体积分布（决定快照成本）。
- **`workspace.edit` 是否也一定经 `_apply_patch` 落快照**：`_edit` 在 `workspace_capability.py:1230-1237` 与 `:563-591` 把 edit 编译成 patch 参数，本文件读到的是"经同一 helper"，**未**逐行确认落盘路径完全一致。
- **补偿路径的端到端可运行性**：`compensate_task` 需要 `effect_custody`（`execution.py:736-746`），本文件**未核实**终端线 composition 是否注入了 `EffectCustodyPort`；若未注入，则"前向 restore"在今天可能只对 selfdev/责任环路径可达。
- **操作者体验的现状读数**：`/export`、`/task`、`/files` 的实际输出**未运行**，只读了 `surface_task_overview`（`app.py:2776-2815`）与路由匹配（`surface_routes.py:96-130,198-202`）。
- **eval 侧**：终端线自己的 coding eval 仍是缺失件（`docs/CURRENT_STATE.yaml:52` 末句），因此本文件**不设能力/质量类度量**，只设治理、可证伪性与资源类 gates。

## 3. 什么才算一个 checkpoint（本文件的核心回答）

本文件把"checkpoint"定义为**一个可被重新指向的、绑定到精确 digest 的持久状态引用**，并要求它必须回答四个问题，缺一不可：

| 维度 | 今天的载体 | 今天是否已存在 | 能否"回去" |
|---|---|---|---|
| **D-A 会话回合游标** | `SESSION_TURN_CONTINUATION_CHECKPOINT`（F2/F3），绑定 assistant/tool 消息 digest、proposal 游标、steps/tokens、seen digests、配置与 provider profile digest | **是**（内核内部，无操作者入口） | **只能向前**：投影层显式拒绝"未前进"与"循环状态回退"（F3） |
| **D-B 任务/运行状态** | append-only 事件流本身（F5）+ `RunStatus` 状态机（允许集见 F16）与 `TaskStatus` 枚举（`packages/contracts/src/agent_os_contracts/runtime.py:13-22`） | **是** | **只能追加**：没有删除/改写事件的代码（F6）；状态只能按允许集前进 |
| **D-C 工作区文件状态** | 单一 patch 的 before 字节 + manifest（F8） | **部分**（仅 `apply_patch`/`edit` 的目标文件；无整树、无 shell 副作用） | **可以前向还原**，且必须经 `workspace.compensate_patch`（coordinator-only，F9），受 C7 halt 阻断（F10） |
| **D-D 外部效果** | `ActionReceipt`（`ReceiptStatus ∈ {DISPATCHED, ACKNOWLEDGED, SUCCEEDED, FAILED, UNKNOWN, CANCELLED, COMPENSATED}`）+ insert-only reservation/outcome + 补偿记录 | **是（作为记录）** | **永远不能回退**：收据与 reservation 是 insert-only（F11）；`UNKNOWN` 是终局；补偿是**新动作**而不是抹除（F10） |

**判断 1（"什么才算"）**：一个合格的 checkpoint 必须是 "**D-A 游标 + D-B 序列号 + D-C 文件集合（可空，但必须显式枚举）+ D-D 的显式"不可回退"清单**" 四者的一个绑定包。只写"任务状态"或只写"文件"都是**伪 checkpoint**：前者无法回答操作者"我的代码回去了吗"，后者无法回答"哪些动作已经发生过"。

**判断 2（"回到已知良好状态"能不能成立）**：在本仓的因果性约束下，**只有在把 4 个维度分开声明时才成立**：

- D-A/D-B 的"回退"在本仓的正确表达不是"减回序列号"，而是**追加一条新事件，声明从这里开始走一条新的分支**（F5/F6/F7 共同决定）。
- D-C 的"回退"是**允许的**，但只对被治理写入、且已被快照的目标成立，且必须经补偿能力、受 C7 阻断（F9/F10）。
- D-D 的"回退"**不可能成立**，任何声称可以的做法都需要构造一个不可审计的真相——这与 F4/F5/F7 直接冲突。
- **因此"已知良好状态"的严格定义应是**：一个操作者可读的、`(任务序列号, Run 状态, C7 epoch, 文件集合的 digest 清单, 未解 UNKNOWN 列表)` 五元组，**且这份清单里的每一项都有明确的"回去了/没回去"标记**。缺任何一项，就不许把它叫做"回到已知良好状态"。

**判断 3（checkpoint 自身的存储纪律）**：checkpoint 不是"我保存一份当前数据库"。它必须**与事件流同源**（引用既有的 digest 与序列号，而不是复制一份状态），因为本仓的真相定义是**事件流**（F5/F6），第二份真相会立刻变成漂移源。已有的两个先例都遵守这条：F2/F3 的 continuation checkpoint 就是事件载荷；F19 的责任环 checkpoint 引用 `last_event_sequence` 并 CAS 到 `expected_prior_digest`。

## 4. rewind 与 C7 / 效果收据 / 审计不可变性的冲突在哪

**这一节是"为什么不做真 rewind"的论据。**

1. **审计日志不可变 → 不能"抹掉已发生的事"。** 任务事件表是 append-only、`PRIMARY KEY (task_id, sequence)`、序列 CAS（F5），全仓没有删除/改写代码（F6），且关键真值事件只允许持有 `_runtime_writer_token` 的 typed 写者写入（F4）。任何 rewind 若表现为"删掉序列 N 之后的事件"，就等于引入第二个真值源与一条不可审计的写路径。
2. **效果收据不可改 → 不能"把已发生的外部效果从证据里抹掉"。** `ActionReceipt` 一旦 `seal` 就是 insert-only；reservation 与 outcome 的配对关系被 `_load_outcome` 逐字段校验，不匹配即报错（F11）。`ReceiptStatus` 里唯一诚实的"不知道"是 `UNKNOWN`，而它的语义就是**不重发、等人和解**（F11/F12/F13）。rewind 若让 `UNKNOWN` 变成"没发生过"，就是把本仓最硬的一条诚实性保证拆掉。
3. **C7 没有"回退"这种操作。** 纠正权威只提供 `correct`（epoch+1, halted=True）与 `resume`（epoch+1, halted=False）（F7）。"回到纠正前的 epoch"在本仓的表示就是**再写一条纠正**。若 rewind 被实现成"把 epoch 减回去"，它会同时破坏 `guard_unchanged` 的线性化语义（`capability.py:183-193`）与 permit 上的 `correction_epochs` 绑定（`capability.py:156-163`）。
4. **已发生的外部效果在物理上不可回退。** `workspace.shell` / `workspace.run_tests` 的子进程可写任意路径、可发起网络请求；本仓对它们的记录是收据与输出，**不是 before 快照**（F8 只覆盖 patch 目标）。因此"回到良好状态"对这类效果唯一成立的形态是**前向补偿 + 显式 BLOCKED**（F10），而不是保证回退。
5. **正确的形态结论**：**rewind 在本仓只能是"前向的"。** 具体地说，"从 checkpoint 重新开始"应被实现为**一个新的、可归因的分支/新 Run**（追加事件、新的 run_id、新的 C7 epoch、新的审批），而不是让旧的 Run 假装没发生。这条与 F16（`PAUSED` 只能回 `RUNNING`）和 F10（补偿需要 FAILED/NOT_MET 或既有介入上下文）的既有纪律一致。

**给操作者的承诺必须写成一句可以验伪的话**：例如 "restore 只回退 checkpoint 内被枚举的文件集合的 digest；它不会、也不能撤销任何已 dispatch 的动作；未解 UNKNOWN 会阻止 restore"。这句话必须出现在 CLI 输出里，而不是只在文档里（见 §9 与 §11 G7）。

## 5. rewind 与"已派发但结果未知"（UNKNOWN）的关系

1. UNKNOWN 的产生与终局性：见 F11。要点是 `RESERVATION_WITHOUT_OUTCOME` 的语义 "automatic resend is forbidden"，以及 `seal` 只能插不能改。
2. UNKNOWN 在 Run 层是一道**显式和解门**：`RUN_PAUSED` 里带 `unknown_action`，此后 `PAUSED→RUNNING` 直接抛 `InvalidTransitionError("UNKNOWN_REQUIRES_REVIEW requires explicit reconciliation")`（F12）。这正是"回到已知良好状态"的反例：**本仓已经明确地说"这个状态不是已知的，不能自动离开"**。
3. 因此本文件给出**不可协商的关系规则**：**存在未解 UNKNOWN 时，checkpoint 可以创建、可以被读取，但 restore 必须 fail-closed 为 typed 拒绝**。理由不是"实现困难"，而是 F12 已经给出的判断：未解的未知效果意味着"过去不完整"，任何一个声称"已知良好"的恢复点都可能是错的。
4. 与之配套的三件事（都属本文件的 gates，不属实现）：
   - **G3** 必须证明"restore 不能把 `unknown_action` 标记绕过"——包括"先 restore 到 UNKNOWN 之前的 checkpoint"这条最诱人的旁路；
   - **和解（reconciliation）今天没有操作者入口**：终端的 `session resume` 走的是 `resume_task`（Run 状态），与 C7 的 `resume_correction` 不是同一条路（F17），而 UNKNOWN 门所在的正是 `update_run_status`（F12）。所以"人和解一个 UNKNOWN"今天**只有内核拒绝，没有操作者动作面**；
   - 若要补齐入口，它是 **session pause / graceful stop 的同一块地基**（§6），建议与 P0 一起做，而不是让它成为 checkpoint/rewind 的内部依赖。
5. **不做的部分**：本文件**不**设计"自动和解"、"按 reason_code 分类放行"或"超时后自动推进"。任何此类机制都必须另立 gate 并给出 C6/C7 保持证明。

## 6. 与 `session pause`（中途优雅停机）共享的那块地基，建议怎么切

**共享的那句话**：*一个进行中的回合，能不能被安全地打断，并回到一个可被命名的已知状态？*

今天的三个部分答案，各自缺一块：

| 机制 | 能停吗 | 停在哪 | 有 typed 结果吗 | 能从这里继续吗 |
|---|---|---|---|---|
| C7 correction（Esc / `noem session correct`） | **能**（step 边界） | `stop_reason="correction_halted"`，回合**正常提交**（F13） | **有** | **终端无入口**：解除 halt 要 `POST /v1/tasks/{id}/correction/resume`，`apps/cli-ts` 没有调用点（F17）；会话停在 `CORRECTION_HALTED` |
| `session pause`（Run `PAUSED`） | **停不住**：`_drive` 抛 `InvalidTransitionError` 而不是优雅停止（F14） | 不写 `SESSION_TURN_COMPLETED` | **无**（异常冒到 surface worker，通常被 begin-turn 的快速返回吞掉） | **卡死**：`surface_has_uncommitted_turn` 永真 → 后续每次 begin-turn 都 `SurfaceTurnInProgress`（F15）；且从 `QUEUED` 发起时直接 `InvalidTransitionError`（F16） |
| UNKNOWN 自动停机 | **能** | `RUN_PAUSED` + `unknown_action`，`stop_reason="unknown_requires_review"`（F12/F13） | **有** | **不能**，且这是设计意图：必须显式和解 |

**建议的切法（P0，最小、且自身不引入新授权）**：

- **P0-a 回合级 checkpoint 的只读投影**：把 F2 已有的 `SESSION_TURN_CONTINUATION_CHECKPOINT` 暴露成一个**只读**的操作者可读引用（`checkpoint_ref` = 该事件的 `event_id` + `sequence` + 已存在的 digest 字段），进 `SurfaceSessionSnapshot` 或 `/files`-类只读端点。**不新增写路径、不新增能力、不改状态机**——这是"checkpoint 存在"的最小真话。
- **P0-b 优雅中止（abort）**：给"打断一个进行中的回合"一条**有权限、有 typed 结果、且一定会提交回合**的路径。它的判据是 F13 已经给出的形状：像 `correction_halted` 那样在 step 边界 **break 并提交**，而不是像 F14 那样抛异常。它必须同时给出"如何离开中止态"的入口（今天的 C7 明显缺这一半，F17）。
- **P0-c 未提交回合的解除**：为 F15 的卡死提供一个显式出口（typed 拒绝 + 操作者可见 + 不伪造成功），或证明它不可能发生。**今天只有审批续跑一条恢复路径**（F18）。
- **不建议**把 P0 扩成"通用 rewind"：P0 的价值是**把地基的语义钉死**（谁有权中止、中止后停在哪、怎么离开），而这正是 rewind 与 pause 共同需要的、且今天全都缺失的部分。

**与既有冻结项的关系**：P0 **不解冻** rev 9 的"每会话一个 in-flight turn"（`surface_runtime.py:417-423` 的 `SurfaceTurnInProgress` 一字不改），**不改** permit/approval/C7，**不新增**终端治理入口。

## 7. 候选形态与其边界代价

### 7.1 A 形态：追加式 checkpoint + 前向 restore（本文件推荐）

- **语义**：操作者（或内核在回合边界）创建一个 checkpoint 引用；操作者可以选择"从该 checkpoint 继续"，实现方式是 **restore = 前向补偿（D-C）+ 追加一条明示分支的事件（D-B）+ 明确的 D-D 不可回退清单**。`restore` 不复用旧 permit、不带旧审批、必走 C7 与 `CapabilityBroker.invoke`。
- **今天已有的最小实现面**：F2/F3/F4（游标）、F5/F6（追加）、F8/F9/F10（文件前像与前向补偿）、F11/F12/F13（UNKNOWN 与 halt 的诚实表达）。**缺口**：操作者可读的 checkpoint 引用、restore 的公共入口与 typed 契约、未解 UNKNOWN 的 fail-closed 判据、"不可回退清单"的投影。
- **边界代价**：① 必须新增一个**公共入口 + typed contract + 失败路径**（`AGENTS.md:57`），并进 `tests/product`；② 必须回答"restore 之后新旧动作的归因"（沿用既有 `run_id`/`node_id`/`action_digest` 归因，不自建第二套）；③ 快照成本与保留策略（今天只有单 patch 粒度，F8）。
- **判断**：**推荐**。它是唯一与 F4/F5/F6/F7/F11 全部相容的形态，并且**完全复用**既有能力，不新增授权面。

### 7.2 B 形态：真 rewind（回退事件流 + 回滚工作区树）

- **语义**：把时间"拨回"一个更早的状态，连同事件流与文件树。
- **为什么判为不做（四条，都可核查）**：
  1. 它与 F5/F6 的 append-only 真相定义直接冲突：要么改写事件流，要么让第二份真值存在；
  2. 它与 F11 的 insert-only 收据/outcome 直接冲突：被回退的动作必须有收据，而收据不能被删；
  3. 它与 F7 的"纠正只能前进 epoch"冲突：回退 C7 状态会破坏 `guard_unchanged` 的线性化（`capability.py:183-193`）；
  4. 它对 D-D 承诺了物理上做不到的事（F8 只覆盖 patch 目标，shell/网络副作用无 before 记录）。
- **若 founder 仍要 B**：它必须是一个**新 ADR**（建议号 0061，且开写前重新核查）并附 C6/C7 保持证明、独立安全评审、canary/rollback，以及"哪些维度仍不可回退"的显式清单。**本文件不授权它，也不为它写实现路径。**

### 7.3 C 形态：只读 checkpoint（不提供任何回退）

- **语义**：只做 §6 的 **P0-a**——把已有游标暴露成只读引用，让操作者能命名"这里"。
- **代价/收益**：**零内核与协议风险**（不改状态机、不新增写路径），但它**不是** checkpoint/rewind 能力的完成态，只能作为 A 的 P1 与 pause P0-a 的共用切片。必须**明确禁止**在只有 C 的时候声称"支持 checkpoint/rewind"。

### 7.4 形态选择与编号说明

- **推荐**：**C 作为 P0（与 pause 共用）→ A 作为 P1 主体；B 判为 `NO_ACTION`（不做）**，除非 founder 另立 ADR-0061 并接受 §4 的四条冲突。
- **本文件选 GC 而非 ADR**，理由与同批姊妹文档一致：本文件**不移动任何权威边界**（A 复用既有能力、B 被显式写成"需 ADR 前置"）；ADR 的职责是冻结决定，而当前缺的是威胁模型、不可回退维度定义与可证伪 gates。

## 8. 治理约束（不可协商不变量）

1. **restore 不是派发旁路**：任何由 restore 引起的物理效果仍必须经 `CapabilityBroker.invoke`（唯一路径，`capability.py:132-227`），带 permit、lease fence、未过期、C7 epoch 未变。**不允许**任何"恢复专用 dispatch"。
2. **C7 不可绕过**：checkpoint/restore 不得调用、模拟或清除 `op_*` 主权面；不得落在 `guard_unchanged` 窗口内（`capability.py:183-193`）；C7 halted 时 restore 必须 fail-closed（既有先例：补偿在 halted 时记 `BLOCKED` + `manual_intervention_required=True`，F10）。
3. **已发生的外部效果不得从证据里消失**：禁止删除/改写任务事件（F6）、禁止改写 `ActionReceipt`（F11）、禁止改写补偿记录（F10）。restore 只能**追加**。
4. **未解 UNKNOWN 时 restore 必须拒绝**（§5）；且**不存在**"restore 到 UNKNOWN 之前"的旁路。
5. **模型不得创建/恢复 checkpoint**：checkpoint 的创建与 restore 都是**操作者/内核 typed 写者**的动作（沿 F4 的 `PROTECTED_TRUTH_EVENTS` 纪律）；不得是模型可调用的 capability，除非另有 ADR 与 C6/C7 证明。
6. **checkpoint 不能成为第二份真相**：它只引用事件流中的 digest 与序列号（§3 判断 3），不得复制一份可漂移的状态。
7. **不新增终端治理入口**：沿 Stage 2c/2d，创建/恢复沿用既有 API-only 与 operation-owner 纪律，终端只做展示与显式 `--confirm` 类交互。
8. **不把"回到良好状态"当作 evals 的分数**：终端线自己的 coding eval 仍是缺失件（`docs/CURRENT_STATE.yaml:52` 末句：eval 存在于研究/mandate 侧，终端线自己的 coding eval 是缺失件），在它存在之前不得用 checkpoint 机制本身充当能力/质量证据。
9. **不引入新的外部依赖**：checkpoint 的存储复用既有 SQLite 事件库与 artifacts 目录（F5/F8），不引入新数据库/新文件格式族。

## 9. 操作者体验（必须逐项可达，否则不得声称该能力）

| 问题 | 今天的答案 | A 形态必须做到 |
|---|---|---|
| 我现在的 checkpoint 在哪 | **不存在**（F1）。内核有 F2 的游标但它们不出现在任何投影里 | 一个可读引用（id + 事件序列 + 已存在 digest 的可见形式）；**不泄露** statement/凭证（沿 F23 的排除纪律） |
| 有哪些 checkpoints | **不存在** | 有界列表（分页 + 上限），绑定 run/turn 归因，可读、不泄露内容 |
| 回到某个 checkpoint 会做什么 | **不存在** | 执行前必须打印**将被改动的文件集合 digest 清单**与**不可回退清单**（已 dispatch 的动作数、UNKNOWN 数、C7 epoch 变化） |
| 有未解 UNKNOWN 时能回吗 | **不存在** | **不能**，且必须给出 typed 原因与"先和解"的指示（§5） |
| 回退之后怎么继续 | **不存在** | 走既有路径（`RUN_RESUMED` + 新的审批/permit），**不复用**旧审批票据 |
| 失败了怎么办 | **不存在** | restore 半途失败必须留下可审计的部分结果与 `manual_intervention_required` 标记（沿 F10 的形状），绝不静默 |
| 成本 | 只有活动会话 token 累计（`docs/CURRENT_STATE.yaml:52`/既有 GC 记录）；资金成本恒 `UNKNOWN` | checkpoint 存储占用必须可量化（文件数 + 字节），金额允许继续 `UNKNOWN`，**不得伪零** |

**判断**：A 形态第一版可以让"看见 checkpoint"可达（P0-a，零风险），但**"回到某个 checkpoint"在没有 §6 的 P0-b/P0-c 之前不可达**——因为打断与恢复的语义今天是破的。**P0 是本线的前置，不是收尾。**

## 10. 威胁模型

| # | 威胁 | 现有防线 | 缺口 / 需要的观测 |
|---|---|---|---|
| T1 | **restore 成为绕过 UNKNOWN 的旁路** | `RUN_PAUSED.unknown_action` + `update_run_status` 的硬拒绝（F12） | 没有"restore 也必须过同一道门"的判据；需要"先 restore 再 resume"被拒的对抗用例（G3） |
| T2 | **restore 成为第二派发路径** | `CapabilityBroker.invoke` 唯一路径（F13 所依赖）；`workspace.compensate_patch` 已被 pipeline/execution 两处挡在模型之外（F9） | 需要计数探针 + 实现 diff 双证（G2）；历史上出现过派发路径分叉（见 §14） |
| T3 | **审计被写成"没发生过"** | append-only + 序列 CAS（F5）、零删除代码（F6）、受保护事件只允许 typed 写者（F4） | 需要"restore 前后既有事件集合逐字节相同"的断言（G5） |
| T4 | **restore 覆盖了别人的写入** | 补偿前校验 `applied_sha256`/`before_sha256` 与当前内容（F9）；`apply_patch` 的 `overwrite_guard` 披露机制 | 需要"目标在 checkpoint 之后被第三方改动 → restore 必须拒绝而不是覆盖"的用例（G6）；跨主体（多会话/多进程）未测 |
| T5 | **checkpoint 泄露工作区内容** | 会话列表投影刻意排除内容/token/凭证（F23） | checkpoint 清单若携带路径/内容摘要会引入新泄露面；需要"不出现绝对路径、不出现文件内容"的扫描断言（G10） |
| T6 | **checkpoint 自我指涉/可被模型污染** | F4 的 protected-writer 门 | 需要"模型输出无法创建/选择 checkpoint"的对抗用例（G8） |
| T7 | **"能停"其实是假的**（今天已成立） | C7 correction 能停但终端无解除入口（F17）；`pause` 会卡死（F14/F15） | 这是本线**唯一的既有硬阻塞**：任何"可中断/可恢复"的声明必须先过 G1/G4 |
| T8 | **资源无界**：每次检查点复制工作区树 | F8 的快照是单文件、按 action key 去重 | 需要实测：文件数/字节上界、单回合快照数、磁盘占用随会话增长曲线；无上限即判不通过（G11） |

## 11. Falsifiable gates

每条 gate 都写"**什么观测会证明它不成立**"。全部为 Product Track 门，须接入 CI（`tests/product` 与 cli-ts 套件；接线自守见 `tests/product/test_ci_gate_wiring.py`）。

- **G1 中途打断不卡死（当前 NOT_MET，先决）**
  - 断言：一个进行中的回合并发收到打断请求后，**要么**优雅提交（写 `SESSION_TURN_COMPLETED`，带 typed `stop_reason`），**要么**在有限时间内进入一个**可被显式离开**的 typed 状态；两种情况下该会话的**下一次 begin-turn 都返回 typed 结果而不是永久 `SurfaceTurnInProgress`**。
  - **今天的不成立观测（读码推断，需在隔离环境实测确认）**：Run `PAUSED` 时 `_drive` 抛 `InvalidTransitionError`（`agent_loop.py:869-878`），`_complete_turn` 不被调用（`:390`），`surface_has_uncommitted_turn` 永真（`app.py:2299-2319`）→ 后续 begin-turn 全部 `SurfaceTurnInProgress`（`surface_runtime.py:417-423`）。
  - 判据（可机读）：`TURN_COMMITTED_AFTER_INTERRUPT: True` 且 `NEXT_BEGIN_TURN_TYPED: True`（不是 `SurfaceTurnInProgress` 或 `SurfaceTurnInProgress` 可被显式清除）。
- **G2 零新增派发路径**
  - 断言：restore 引起的任何物理效果都经过 `CapabilityBroker.invoke`。
  - **不成立的观测**：给 `invoke` 加计数探针，做一次 restore 而计数为 0；或实现 diff 出现新的 `execute`/`dispatch` 入口（含"仅测试用"分支）。
- **G3 UNKNOWN 不可绕过**
  - 断言：存在未解 `unknown_action` 时，restore 一律 typed 拒绝，且**不存在**"restore 到 UNKNOWN 之前的 checkpoint"这条旁路。
  - **不成立的观测**：构造一次 `RESERVATION_WITHOUT_OUTCOME` 后，restore 成功、或 restore 后再 `resume` 成功（对应 `task_service.py:2381-2394` 的拒绝）；或 `unknown_action` 标记在 restore 后被移除。
- **G4 打断/恢复的权限与 typed 结果**
  - 断言：打断与 restore 都需要 principal/tenant/workspace 绑定与 operation owner；无权限者得到 typed 拒绝，不产生任何状态变化与事件。
  - **不成立的观测**：跨 tenant/workspace 的 restore 被接受；或拒绝后事件流序列增长（应零增长）。
- **G5 证据不可改写**
  - 断言：restore 前后，checkpoint 之前已存在的任务事件集合**逐字节相同**（`event_id`/`sequence`/`event_type`/`payload_json` 全等）；`ACTION_RECEIPT_RECORDED` 与补偿记录逐字段不变。
  - **不成立的观测**：任一既有事件的 `payload_json` 或序列发生变化；或出现 `sequence` 空洞/重排。
- **G6 不覆盖 checkpoint 之后的第三方改动**
  - 断言：若目标文件在 checkpoint 之后被非本 Run 的写入改动，restore 以 typed 拒绝结束且**不写文件**。
  - **不成立的观测**：对 checkpoint 之后被外部改写的文件执行 restore 后，文件内容变成了 checkpoint 的内容（sentinel 校验：mtime/内容 sha256 变化）。
- **G7 不可回退清单必须出现在操作者可见面**
  - 断言：restore 的确认面与结果面都明确列出"已 dispatch 动作数、未解 UNKNOWN 数、C7 epoch 变化"，且不出现"已全部回退"这类无条件的表述。
  - **不成立的观测**：一次成功的 restore 输出中缺失不可回退清单；或输出断言"fully restored/rollback complete"。
- **G8 模型不得创建/选择/触发 checkpoint 或 restore**
  - 断言：`CHAT_CAPABILITY_IDS`（`agent_loop.py:65-75`）与能力注册表中不出现 checkpoint/restore 项；模型输出无法使其出现。
  - **不成立的观测**：对抗用例（模型输出要求"回到 30 秒前"）产生一次 restore 调用或一次 checkpoint 创建。
- **G9 C7 保持**
  - 断言：C7 面不可写（实现 diff 不触碰 `governance.py` 的 C7 符号）；restore 不得落在 `[reserve, seal]` 窗内；C7 halted 时 restore fail-closed。
  - **不成立的观测**：hook 式地让 restore 在 `guard_unchanged` 窗内运行；或 `correction.halted(...)` 为真时仍发生一次 `connector.execute`。
- **G10 不泄露内容与秘密**
  - 断言：checkpoint 投影与列表中不出现工作区文件内容、`~/.agent-os` 内路径、凭证材料或 host 绝对路径。
  - **不成立的观测**：对载荷做 sentinel 扫描（沿既有脱敏断言风格，如 `agent_loop.py:1768` 的 `_ABSOLUTE_PATH_RE` 与 `:1790-1798` 的 `_model_visible_unknown_detail` host-path 脱敏）时任何一项命中。
- **G11 资源有界**
  - 断言：存在单一 checkpoint 的文件数/字节上界与保留上限；超限给出 typed 拒绝，不静默丢弃、不静默截断。
  - **不成立的观测**：单回合内快照字节随被改文件数**无上界**增长；或达到上限后静默丢弃快照（此时 restore 会错误地声称"回去了"）。
- **G12 消融=基线**
  - 断言：checkpoint/restore 功能全关时，行为与当前 HEAD 基线**逐字节一致**（同一会话脚本的事件序列与断言集合相同）。
  - **不成立的观测**：任一基线断言在关闭时变红，或事件序列出现差异。
- **G13 gate 必须接进 CI 且不可被静默移除**
  - 断言：新 gate 进入受治理的 `tests/product` 或 cli-ts 套件，且接线自守覆盖它。
  - **不成立的观测**：删除/中和该 CI 步骤（`|| true`、`--if-present`、改名脚本为 no-op）后其余检查仍全绿。

## 12. 负面清单（明确不做）

1. 不做真 rewind / 时间旅行（§7.2 的四条冲突）；不删除、不改写、不重排任务事件。
2. 不改 `ActionReceipt` / `ReceiptStatus` / reservation-outcome 语义；不把 `UNKNOWN` 变成"没发生过"。
3. 不让 restore 绕过 `UNKNOWN_REQUIRES_REVIEW` 的显式和和解门；不设计自动和解、不按 `reason_code` 自动放行、不超时自动推进。
4. 不把 epoch 减回去、不重写 C7 状态；不新增 `op_*` 主权面调用。
5. 不新增第二条派发路径；不让 restore 复用旧 permit 或旧审批票据。
6. 不给模型创建/选择/触发 checkpoint 或 restore 的能力。
7. 不复制第二份状态真相（不保存"当前数据库副本"当 checkpoint）。
8. 不做整棵工作区树的隐式快照（`git stash`/整树 tar 类）；也不宣称能回退 shell/网络副作用。
9. 不把 checkpoint/restore 当作能力、质量、parity 或自主性证据；不写 `Autonomy(S,E,O,V,T)`。
10. 不在没有 §6 的 P0（打断/恢复语义）之前声称"支持 checkpoint/rewind"。

## 13. 失败与回滚（本线自身的回滚）

- **特性开关**：沿既有先例（`--no-agents` 等），checkpoint 展示与 restore 各有一个**默认关**的开关；全关即回到当前 HEAD 行为（G12）。
- **契约策略**：只增可选字段 + 保留旧解码（沿 `CP-TERMINAL-CODING-AGENT-M2 §Version bumps` 的既有纪律）；`SURFACE_PROTOCOL_VERSION` 当前为 `"1.1"`（F23），任何附加字段的版本策略是 CTO 决策项（§15 D5）。
- **数据**：A 形态不新增数据族，复用事件流与 artifacts 目录（F5/F8），因此回滚 = 移除入口与开关，无数据迁移。
- **Stop conditions（遇到即 `REVISE_TO_SPEC`）**：
  - 需要改写或删除既有任务事件 / 收据 / 补偿记录；
  - 需要让 restore 绕过 broker、permit、approval 或 C7；
  - 需要引入 `unknown_action` 的自动和解或绕行；
  - 需要新增非既有的存储依赖（新数据库、新文件格式族）；
  - 需要触碰 `TURN_IN_PROGRESS`（rev 9）或同会话并发；
  - 需要把 checkpoint/restore 暴露为模型可调用的 capability。

## 14. 负面地图与先例（写 gates 时已吸收的教训）

1. **`docs/CURRENT_STATE.yaml:52`（round-2 失败路径修复）**：UNKNOWN 回合曾**挂死 150 秒无完成**，修复后 0 秒并以真实 stop reason 结束；且修复明确保持"no seal / Run stays PAUSED / resume still refused / one dispatch only"。→ G1/G3 不接受"大概会结束"的断言，只接受可机读判据。
2. **`docs/CURRENT_STATE.yaml:51`（round-3）**：`noem session correct|pause|resume` **此前完全不能用**（fresh 进程把 `expected_event_sequence` 从 0 发出，9/9 全部 409）；TUI 的 correction 刷新与 POST **不原子**（6 次 Esc 有 3 次 409）。→ 任何新的操作者控制路径必须带"读-改-写"竞态与重试语义，且必须能区分"没送达"与"没生效"（G1/G4）。
3. **`docs/CURRENT_STATE.yaml:49`（tool-failure 审计）**：曾把 `ReceiptStatus` 当成"目标是否达成"来用，被 11 个测试证伪并回退——收据见证的是 **dispatch 是否执行、效果是否已知**，目标判定另算。→ 本文件 §3 的 D-D 与 §4 第 2 条沿用同一条纪律，**不使用 receipt 表达"回去了"**。
4. **`docs/CURRENT_STATE.yaml:51`（同一条）**：读码推断与实测被混淆过一次（`_truncate_json` 的"证据"被上游 `canonical_output` 排序打败）。→ 本文件把 F14/F15 明确标为读码推断并列 G1，不写成已复现缺陷。
5. **派发路径分叉的历史**：`GC-REALTIME-COLLAB-NATIVE-SURFACE-2026-08-14` 中第二条 pre-write 权威入口被 ADR-0059 判定为不可接受。→ G2 不接受"路径不同但都能执行"的解释。
6. **`workspace.compensate_patch` 的形状**：它是本仓已有的、"回退一个外部效果"的**正确答案**——被治理、coordinator-only、有独立记录、有 BLOCKED 终态、并且**明确拒绝回滚已 SUCCEEDED 的 Run**（F9/F10）。→ A 形态应复用它而不是新发明；B 形态必须解释它为何不够。
7. **`responsibility_loop.write_checkpoint` 的形状**：CAS + fence + **显式拒绝序列回退**（F19）。→ §3 判断 3 与 G11/G12 直接沿用。
8. **`SESSION_CONTEXT_COMPACTED` 的代价**：压缩后原始消息不再在历史里（F21），因此"回到更早的对话"在没有独立快照时不可能诚实承诺。→ §12 第 8 条。
9. **同批姊妹文档的评审边界**：`docs/CURRENT_STATE.yaml:52` 记录 founder 2026-09-18 判定同模型 subagent 评审足够，但 `builder_id != reviewed_by` **未满足**、无独立 provider 批准。→ **本文件自身受同一评审等级约束**，须在 §17 如实声明。

## 15. 需 founder / CTO 决策

- **D1 形态选择**：C（只读 checkpoint，P0）/ A（追加式 checkpoint + 前向 restore，P1）/ B（真 rewind，需 ADR-0061 + C6/C7 证明 + 安全评审 + canary/rollback）。**本文件推荐 C→A，B 判 `NO_ACTION`。**
- **D2 先决范围**：是否批准先做 §6 的 **P0-a 只读回合 checkpoint + P0-b 优雅中止 + P0-c 未提交回合的解除**。不做 P0 则"可中断/可恢复"不得被声称（G1/G4 是前置）。这与 `GC-SUBAGENTS-AND-FANOUT-2026-09-18.md` 的 D2 是**同一块地基**，建议两条线合并成**一个**切片，避免各做一半。
- **D3 "已知良好状态"的定义**：是否接受 §3 判断 2 的五元组定义（任务序列号 / Run 状态 / C7 epoch / 文件集合 digest 清单 / 未解 UNKNOWN 列表）与随之而来的"必须显式声明不可回退"要求（G7）。
- **D4 UNKNOWN 与 restore 的关系**：是否确认"存在未解 UNKNOWN 时 restore fail-closed"（§5），以及**和解入口是否与 P0 同批交付**（今天没有操作者入口）。
- **D5 协议策略**：是否批准为 checkpoint 引用添加**可选附加字段**并按 minor 升版保留旧解码（`SURFACE_PROTOCOL_VERSION` 当前 `"1.1"`，F23）；或要求复用既有只读投影（如 `/files` 形状）以**零协议改动**落地 P0-a。
- **D6 存储与保留**：是否接受"复用事件流 + `.agent-os-artifacts/compensation/`，不引入新存储"；以及快照的保留上限与超限行为（typed 拒绝 vs 显式老化），金额/字节度量口径（G11）。
- **D7 restore 的授权等级**：谁可以 restore？是否要求**独立于触发人的确认**（沿 C7 的"外部纠正权威"精神）；是否需要与 `--confirm`/二次确认绑定。
- **D8 副本范围**：是否接受 A 形态第一版**只覆盖被治理写入的文件**（F8 的粒度），并**在操作者面显式声明**"shell/网络等副作用不可回退"；还是要求先做整树快照（成本与风险都上一个量级，本文件不推荐）。
- **D9 陈述修正**：`docs/CURRENT_STATE.yaml:4`（`origin_main_code_receipt`）与 `:65`（`updated`）落后 live HEAD `03ac66b5`（C3）是否由 coordinator 一并更新；以及是否需要把 C1 的措辞收紧为"操作者可及路径上不存在"（本文件不改该文件）。
- **D10 若升格 ADR**：确认下一个安全号为 **0061**（§0），且**开写前必须重新核查**；同时确认是否把 P0（打断/恢复地基）单独作为一个更小的 ADR 处理。

## 16. 度量（量化，替代口号）

- **打断成功率**：一次打断请求到"回合被提交 / 进入可离开的 typed 状态"的延迟分布（p50/p95）；`NEXT_BEGIN_TURN_TYPED` 比例 = 100%，`SurfaceTurnInProgress` 永久残留 = 0。
- **restore 诚实性**：restore 输出中"不可回退清单"存在率 = 100%；宣称"fully restored"出现次数 = 0。
- **不可变性**：restore 前后既有事件集合逐字节相同的会话数 / 总数 = 100%；被改写事件数 = 0。
- **旁路**：UNKNOWN 存在时的 restore 拒绝率 = 100%；`CapabilityBroker.invoke` 计数探针下 restore 触发的派发数 = **0**（restore 本身不派发，只有其引发的补偿动作经 broker，且计数一致）。
- **资源**：单 checkpoint 的文件数与字节上界（实测数字）、单回合快照字节、磁盘占用随会话数/回合数的增长曲线；超限 typed 拒绝率 = 100%。
- **泄漏**：绝对路径/文件内容/凭证 sentinel 在 checkpoint 投影中的命中数 = 0。

## 17. 声明分级（当前）

`specified: 本文件` / `implemented: NO` / `tested: NO` / `integrated: NO` / `verified: NO` / `released: NO`。

**未被授权的动作**：架构评审通过与 CTO gate、任何运行时/契约/协议/内核/终端改动、P0 的任何实现、B 形态的 ADR-0061 开写、restore 能力的对外声明、发布与合并。

**本文件是 `specified only`**：§2 的事实全部来自**本 worktree `03ac66b5` 上的代码/契约/文档读取**（含行号），以及少量只读 git 查询（`git merge-base --is-ancestor`、`git log --all`）；**未**新增任何实现、**未**运行任何产品测试、**未**起任何 daemon、**未**触碰 `~/.agent-os/`、**未**做运行期复现。F14/F15/F21 的"卡死/不可回到更早对话"是**读码推断**，**未在本机实测**。§11 的 13 条 gates 的探针**一个都不存在**。不得据此声称"支持 checkpoint / rewind / 可中断可恢复"或任何 parity 主张。

**评审边界**：`builder_id != reviewed_by` **未满足**，无独立 provider 批准（沿 `docs/CURRENT_STATE.yaml:52` 记录的同日晚间 founder 判定）。

## 18. 复现命令清单（本文件事实的可核查来源）

以下命令于 2026-09-18 在本 worktree `.worktrees/wt-checkpoint-gc`（HEAD `03ac66b5`）实跑：

```bash
# F1：rewind 全仓零命中；checkpoint 在 apps/ 与 domain_packs/ 零命中
grep -rni 'rewind' apps packages domain_packs tests --include='*.py' --include='*.ts' --include='*.tsx'
grep -rn 'checkpoint' apps/ --include='*.py' --include='*.ts' --include='*.tsx'
grep -rn 'checkpoint' domain_packs/ | wc -l
grep -rn 'checkpoint' packages/os_core/src/agent_os_core/*.py | wc -l   # 255（全部内核内部）

# F6：没有删除/改写事件的代码
grep -n 'DELETE FROM task_events\|UPDATE task_events\|DROP TABLE' \
  packages/os_core/src/agent_os_core/*.py apps/api_server/*.py          # 无输出，退出码 1

# F7/F17：C7 只有 correct/resume；解除入口在 server.py，cli-ts 无调用点
grep -rn 'resume_correction\|correction/resume' apps packages --include='*.py' --include='*.ts'

# F16：Run 状态机允许集
sed -n '2395,2402p' packages/os_core/src/agent_os_core/task_service.py

# §0：ADR 编号实测
ls docs/adr/ | grep -o '^ADR-[0-9]*' | sort | uniq -c | awk '$1>1'   # 0039×2 / 0040×3 / 0041×2
ls docs/adr/ | grep -c 'ADR-0056'                                     # 0
git merge-base --is-ancestor 901c2108 origin/main || echo NOT_IN_MAIN  # NOT_IN_MAIN
```

未运行的检查（诚实标注）：任何 pytest / ruff / pyright / cli-ts 套件、任何 daemon 启动、任何 pty 检查。本文件不依赖任何绿灯测试作为论据。
