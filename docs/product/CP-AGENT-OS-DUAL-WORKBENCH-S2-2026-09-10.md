# Context Pack — Agent OS Dual Workbench Slice 2

> Goal Card: `docs/product/GC-AGENT-OS-DUAL-WORKBENCH-S2-2026-09-10.md`
> Date: 2026-09-10
> Plan: `docs/superpowers/plans/2026-09-10-agent-os-dual-workbench-slice-2.md`

## Observed state(均经源码核实,2026-09-10)

- Slice 1 已批准(`APPROVE_SLICE_1`,head `e13684a2`):Sessions 窗口已通过主进程只读桥渲染真实任务列表;桥表面只有 `listTasks` 一个 IPC 命令;`fetchFrom` 逃逸口已删除。
- Runtime 已有可复用的只读路由(`apps/api_server/server.py`,全部 GET):
  - `GET /v1/tasks` —— 任务列表(Slice 1 已消费);
  - `GET /v1/tasks/{task_id}/runs/{run_id}/trajectory` —— `project_task_trajectory` 投影(`apps/api_server/app.py:1138`),产出 `EpisodeManifest`/`TrajectoryStep`(`packages/contracts/src/agent_os_contracts/trajectory.py`),step 携带 `sequence` 与 `event_id`,天然满足"按 seq 有序事件转录"的数据源;
  - `GET /v1/tasks/{task_id}/configuration-snapshots` —— 配置快照列表。
- 事件持久层 `sequence` 为 `INTEGER NOT NULL UNIQUE` 严格递增(`packages/os_core/src/agent_os_core/trajectory.py` 的 credit/事件表),seq 空洞检测有事实依据。
- Sessions 侧:Slice 1 的 `AgentOSSessionsProvider` 已为每个任务建稳定 facade(`agentos-task:/<id>`),`refresh` reconcile 语义已就绪,详情/转录是在既有 facade 上的投影深化,不需要第二个状态机。
- 生命周期:三层身份证据的 quit 终止(c4d8023f)已批准,Slice 2 不得触碰其语义。

## Decision inputs

- **优先复用 trajectory 投影**作为转录数据源,而不是新增裸事件端点:它已经是 contracts 层的封闭类型,且带 outcome/correction 引用,信息量比裸事件高。若评审认为其粒度不足,再按 contracts 变更流程新增只读 GET(进入评审范围)。
- **拉取而非推送**:本切片无 SSE/WS;转录刷新由用户操作或 provider refresh 触发。实时性留给后续切片单独评审。
- **详情来源**:`/v1/tasks` 载荷若已含 statement/status/run_status/时间戳则直接用;缺字段时首选扩展该列表端点的只读字段(contracts 变更),而非新端点。
- **IPC 最小扩张**:新增 `getTaskTrajectory(taskId, runId)`(及必要的 `getTaskDetail`)逐个 typed、逐个失败先行测试;channel 拒绝名单逻辑不变。

## Risks

- **trajectory 投影的语义粒度**:它面向 credit/episode 而非聊天转录,直接映射可能让用户看到过于内部的步骤命名——缓解:映射层做封闭的事件类型→转录项白名单,未知类型 fail-closed,并在 e2e 用真实任务验证可读性。
- **seq 空洞的合法成因**:事件存储若有合法的压缩/归档,严格连续校验会误报——缓解:Task 1 先用真实数据库样本核实"连续"是否是成立的不变量,不成立则改为"单调递增 + 明确 gap 标注",并在计划中留痕。
- **大事件流**:转录过长会拖慢渲染——缓解:桥侧保留 1 MiB 响应上限,provider 侧只做增量 reconcile,不引入分页(超上限即 typed error,分页属后续切片)。
- **Slice 1 回归面**:provider 16 个写入口拒绝集合、quit 三层身份证据、patch 010 上游面,均纳入本切片回归测试。

## 既有资产复用清单

| 资产 | 位置 | 复用方式 |
|---|---|---|
| 只读桥 + descriptor 校验 | `overlay-src/src/vs/agentos/electron-main/runtimeTaskCatalogMainService.ts` | 扩展 allowlist,不动校验链 |
| 生命周期三层身份证据 | 同目录 `interactiveRuntimeLifecycle.ts` | 不改动,回归测试看护 |
| trajectory 合同 | `packages/contracts/src/agent_os_contracts/trajectory.py` | 只读消费,不改合同 |
| facade/refresh reconcile | provider(Slice 1) | 在其上加详情/转录投影 |
