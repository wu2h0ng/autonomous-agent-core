# Context Pack — Agent OS Dual Workbench Slice 2(REVISED,评审修订版)

> Goal Card: `docs/product/GC-AGENT-OS-DUAL-WORKBENCH-S2-2026-09-10.md`
> Date: 2026-09-10(当日经 kimi-reviewer-s2-gate 独立审查 REVISE_TO_SPEC 后修订)
> Plan: `docs/superpowers/plans/2026-09-10-agent-os-dual-workbench-slice-2.md`
> 审查报告: `.agent_runs/dual-workbench-slice-1-20260909/review-s2-gate-subagent.md`

## Observed state(均经源码核实,2026-09-10)

- Slice 1 已批准(`APPROVE_SLICE_1`,head `e13684a2`):Sessions 窗口已通过主进程只读桥渲染真实任务列表;桥表面只有 `listTasks` 一个 IPC 命令,allowlist 仅 `/v1/tasks`;`fetchFrom` 逃逸口已删除。
- Runtime 现有只读 GET 路由(`apps/api_server/server.py`,逐条核实):
  - `GET /v1/tasks` —— 任务列表(Slice 1 已消费;载荷含 `task_id/status/statement/run_status/sequence`,**不含 run_id**,见 `app.py` `list_tasks`);
  - `GET /v1/tasks/{task_id}` —— **任务详情已存在**(catch-all → `app.py:2436 task_json`),含 goal/run(**含 run_id**)/approval/全量 decoded events/proposed_action/provider_usage——**载荷过富,字段最小化是本切片的安全决策**;
  - `GET /v1/tasks/{task_id}/evidence`、`/recovery`、`/workflow`、`/events`、`/artifacts/{id}` —— 子资源路由(server.py:634/651/664 等);
  - `GET /v1/tasks/{task_id}/runs/{run_id}/trajectory` —— trajectory 投影(server.py:524+,`app.py:1138`),产出 `EpisodeManifest`/`TrajectoryStep`(`packages/contracts/src/agent_os_contracts/trajectory.py`);
  - `GET /v1/tasks/{task_id}/configuration-snapshots` —— 配置快照。
- **事件序真相(评审纠正后的事实)**:逐 task 事件表 `task_events`(`packages/os_core/src/agent_os_core/persistence.py`,sequence 逐 task 连续,由 append 侧校验保证);但 trajectory 的 step sequence **继承自逐 task 流**、经 `_select_events`(`os_core/trajectory.py:259-274`)按 run 过滤——**同一 trajectory 内 seq 空洞是常态,不是异常**。"seq 空洞即 fail-closed"的验收不成立,已改为单调递增 + `EpisodeManifest.source_stream_last_sequence` 完整性校验 + gap 显式标注。
- Sessions 侧:Slice 1 的 `AgentOSSessionsProvider` 已为每个任务建稳定 facade(`agentos-task:/<id>`),`refresh` reconcile 语义已就绪。
- 生命周期:三层身份证据的 quit 终止(c4d8023f)已批准,Slice 2 不得触碰其语义。

## Decision inputs(修订后)

- **详情数据源 = 现有 `GET /v1/tasks/{task_id}`(task_json)**,不扩展 `/v1/tasks` 列表端点、不新增详情端点。载荷过富,桥的封闭解码器**白名单最小化**字段:goal.statement、status、run(含 run_id)、时间戳;`approval/proposed_action/provider_usage/decoded events` 一律不得穿过桥进入 renderer。
- **run_id 来源 = task_json.run**(评审 P0-3 修复):`getTaskDetail` 返回 run_id,`getTaskTrajectory(taskId, runId)` 据此调用。
- **转录数据源 = trajectory 投影**(复用现有端点与 contracts 封闭类型),事件类型→转录项白名单映射,未知类型 fail-closed。
- **拉取而非推送**:无 SSE/WS;转录刷新由用户操作或 provider refresh 触发。
- **IPC 最小扩张**:新增 `getTaskDetail(taskId)` / `getTaskTrajectory(taskId, runId)`,逐个 typed、逐个失败先行测试;channel 拒绝名单逻辑不变。
- **Python/contracts 侧默认零变更**(全部复用现有端点);若评审或实现中发现必须变更,升级为独立 Task 并跑 tests/product 全量,不在本切片顺手改。

## Risks(修订后)

- **trajectory 语义粒度**:面向 credit/episode 而非聊天转录,直接映射可能过于内部——缓解:封闭的事件类型→转录项白名单,未知类型 fail-closed,e2e 用真实任务验证可读性。
- **task_json 载荷泄漏面**:详情端点含 approval/proposed_action/provider 细节,白名单解码若写宽即泄漏——缓解:decoder 测试枚举**禁止字段缺席**;e2e 断言页面与 IPC 载荷均不含这些键。
- **gap 标注的真实性**:trajectory gap 是 run 过滤的常态,UI 必须显式标注而非静默跳过,否则会伪造"连续执行"的假象——缓解:映射层对非连续 seq 插入显式 gap 项,测试覆盖。
- **大事件流**:桥侧 1 MiB 上限不变,超上限 typed error;分页属后续切片。
- **Slice 1 回归面**:provider 16 个写入口拒绝集合、quit 三层身份证据、patch 010 上游面(5 文件、零新增),纳入本切片回归测试。

## 既有资产复用清单

| 资产 | 位置 | 复用方式 |
|---|---|---|
| 只读桥 + descriptor 校验 | `overlay-src/src/vs/agentos/electron-main/runtimeTaskCatalogMainService.ts` | 扩展 GET allowlist(`/v1/tasks/{id}`、`/trajectory`),不动校验链 |
| 生命周期三层身份证据 | 同目录 `interactiveRuntimeLifecycle.ts` | 不改动,回归测试看护 |
| 任务详情 task_json | `apps/api_server/app.py:2436` | 只读消费 + 白名单最小化 |
| trajectory 合同 | `packages/contracts/src/agent_os_contracts/trajectory.py` | 只读消费,不改合同 |
| facade/refresh reconcile | provider(Slice 1) | 在其上加详情/转录投影 |
