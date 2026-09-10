# Context Pack — Agent OS Dual Workbench Slice 3(审批卡与审批决定写路径,REVISED)

> Goal Card: `docs/product/GC-AGENT-OS-DUAL-WORKBENCH-S3-2026-09-11.md`
> Date: 2026-09-11(经 kimi-reviewer-s3-gate 独立审查 REVISE_TO_SPEC 后修订;事实核验逐项复审通过)
> 审查报告: `.agent_runs/dual-workbench-slice-1-20260909/review-s3-gate-subagent.md`
> 计划: 待 CTO gate 通过后起草 `docs/superpowers/plans/2026-09-11-agent-os-dual-workbench-slice-3.md`

## Observed state(均经源码核实,2026-09-11;修订版已吸收评审 P0-1/P0-2/P0-3/P1 纠正)

- Slice 2 已批准(`APPROVE_SLICE_2`,head `6cbbbe01`):详情(`GET /v1/tasks/{task_id}` 白名单投影)+ trajectory 只读转录已上线;桥表面 = `listTasks`/`getTaskDetail`/`getTaskTrajectory` 三个只读 IPC 命令;GET allowlist = **三条**路径形态(`runtimeTaskCatalogMainService.ts:59-63`:`/v1/tasks`、`/v1/tasks/{id}`、`/v1/tasks/{id}/runs/{runId}/trajectory`);**无任何写命令**,`request()` 有 GET-only 守卫(:193-196);`approval`/`proposed_action`/`provider_usage` 经 decoder 白名单**显式剥离**,e2e 已断言不泄漏。
- 审批决定端点已存在(`apps/api_server/server.py:919-926` → `app.py:2371 record_approval`):
  - 路由:`POST /v1/tasks/{task_id}/approval`,body = `{action_digest?, disposition?, reason?}`,返回全量 task_json;
  - app 层校验:要求 active committed task + run;pending action 必须存在;`action_digest` 提供时不等即拒;reason 去空白后必填;actor 服务端绑定(`self.principal`);
  - service 层校验(`task_service.py:2206-2243`):pending 存在(:2215-2217)、digest 绑定(:2232)、task/run 绑定(:2228-2231);**`WAITING_APPROVAL` 精确状态门仅对 `approval_requirement == "external_exact"` 的动作生效(:2218-2227)——本切片的 workflow 审批路径(`approval_requirement="policy"`)在记录时刻无 run 状态门**(评审 P0-1 纠正);
  - `ApprovalDecision` 合同(contracts `authority.py:200-218`):role∈{PRINCIPAL, TENANT_ADMIN} 强制、`expires_at > decided_at` 强制(实现 = decided_at + 10min)。
- **重复审批行为(评审 P0-2 纠正)**:`APPROVAL_RECORDED` 不改变 run 状态;`pending_action` 的 WAITING 分支(`task_service.py:2265-2301`)只防 `RUN_PLAN_REBOUND` 与其后的新 `ACTION_PROPOSED`,**无 `APPROVAL_RECORDED` 守卫**——恢复前重复审批会成功,aggregate.approval 以最后一条记录为准(last-write-wins)。服务端幂等加固不属于本切片。
- **恢复路径(评审 P0-3 纠正,本切片的关键结构事实)**:`record_approval` **不恢复运行**;恢复 = 客户端再次 `POST /v1/tasks/{id}/run`(路由 `server.py:870-901` → `app.py run_task`;恢复时刻强制携带与已 seal 快照一致的 `configuration_snapshot_id`,`app.py:1517-1527`;启动时刻的快照核对在 `task_service.py:367-372`);执行器将 `WAITING_APPROVAL`/`PAUSED`/`FAILED` 视为可恢复态并重入(`execution.py:301-316`,事件 `RUN_RESUMED`),重入 approval 节点时复核 `aggregate.approval` 存在 + disposition==APPROVE + digest 匹配才放行(`execution.py:537-544`),否则重新停泊 `WAITING_APPROVAL`(:545-557)。**因此批准流程 = 两条写命令(`decideTaskApproval` + `resumeTaskRun`),REJECT 后 run 保持停泊、动作不执行(终止属 Slice 4)**。演示页 `index.html:459-467` 的 `reviewAction` 即此两段式配方的实证。另:`/run` 端点权力大于 `/approval`——body 可携带 `inputs`/`recover_stale_lease` 等键(评审 P2 N-2),桥的 `resumeTaskRun` 载荷测试须显式断言永不发出这两键;`run_task` 要求 provider 已配置(`app.py:1510-1513`),e2e 失败先行注意配置顺序(评审 P2 N-3)。
- 审批卡投影数据源:task_json 的 `proposed_action` 字段(`app.py:2465-2470`)= ActionContract 全量 dump + 解码 arguments + `action_digest`;`run.status` 指示 `WAITING_APPROVAL`;`configuration_snapshot.snapshot_id`(`app.py:2497-2501`)是 resume 必需载荷,须入白名单;`run.policy_version`(`task_service.py:403`)是 §7.3 policy_version 字段的真实数据源,须入白名单(评审 P1-3 纠正)。**Slice 2 白名单已剥离 proposed_action/approval,本切片以独立最小化投影重新引入——字段面扩张,decoder 测试须精确枚举允许键**。
- 进入 `WAITING_APPROVAL` 的机制已核实:workflow 节点 kind `approval`(`workflow.py:29 NodeKind.APPROVAL`,枚举值已核实,评审 P2 关闭),执行器在 approval 节点无匹配审批时以 `APPROVAL_REQUESTED` 事件停泊(`execution.py:545-555`);e2e 复用 Slice 2 配方,`:commit` workflow 中加入 approval 节点即可。
- `task.approval`(task_json `approval` 字段)= 已记录的 ApprovalDecision(`task_aggregate.py:391-406`),审批后卡面收敛的数据源;`session_projection.py:214` 显示 APPROVAL_RECORDED 载荷为 exact `{"approval"}` 单键。
- spec §7.2 全量协议(protocolVersion 2.0 / clientOperationId / runId+attempt / expectedPolicyVersion / expectedEventSequence / REVISE / ApprovalReceipt)为 **SPECIFIED 未实现**,现有 HTTP 端点不含这些字段;本切片不补服务端(见 GC Boundaries)。
- spec §12 验收④(停止后无 permit 漏执行,旁路测试 §7.4-5)依赖 `correction.request`/停止语义;HTTP 侧已有 pause/resume/cancel/correction 端点(server.py:954-974),但 UI 写路径+补偿验证属另一切片量级,GC 建议归 Slice 4。
- 桥错误映射现状(评审 P1-2):非 401 的 HTTP 错误当前塌缩为 `RUNTIME_UNREACHABLE`,服务端 400 仅自由文本——写路径必须先建 typed error 映射表(失败先行)再实现。

## Decision inputs(修订后)

- **写路径形态 = 桥新增两个 typed IPC 命令**:`decideTaskApproval({taskId, actionDigest, disposition, reason})` 与 `resumeTaskRun({taskId, configurationSnapshotId})`,载荷全 typed;POST allowlist 仅新增 `/v1/tasks/{id}/approval` 与 `/v1/tasks/{id}/run` 两条路径形态;channel 拒绝名单逻辑、descriptor 守卫、0600/symlink/loopback 校验、5s 超时、1 MiB 上限全部继承不动。
- **TOCTOU 同源 = 投影直通**:审批卡渲染所据的 action digest 存于投影模型,「批准」提交时原样回传;UI 不得自算 digest,不得从 DOM 文本反解析。
- **审批卡 §7.3 字段映射表(评审 P1-3 修订版)**:

| §7.3 字段 | 数据源 | 形态 |
|---|---|---|
| action 摘要(人读) | proposed_action:capability 名 + arguments 摘要 | 渲染 |
| digest 前缀 | proposed_action.action_digest | 渲染(截断展示,提交用全量) |
| capability+version | proposed_action:capability + capability_version | 渲染 |
| risk_tier | proposed_action:risk_tier | 渲染 |
| 资源范围 | proposed_action.arguments(白名单子集摘要) | 渲染 |
| policy_version | run.policy_version | 渲染 |
| 过期时间 | **无预渲染数据源**(服务端在审批时签发 decided_at+10min) | 说明文案「提交后 10 分钟内有效」+审批后从 approval.expires_at 呈现真实值 |
| 请求者(principal/run) | run.run_id + principal 标识(task_json 已有字段) | 渲染 |

- **卡面收敛 = 事件+刷新**:提交成功后重取详情,`approval` 字段非空且 digest 匹配则呈现已批准/已拒绝;不据本地乐观态;多窗口/重复提交场景后到者覆盖,卡面始终跟随最新记录(已知缺口,见 Risks)。
- **Python/contracts 侧零变更**为默认立场;若实现期发现必须变更,升级为独立 Task 并跑 tests/product 全量。

## Risks(修订后)

- **第一批写命令是桥的信任边界扩张**:此前全部守卫建立在"只读"假设上,且 GET-only 守卫(:193-196)本身要为这两条命令开口——缓解:开口按方法+路径双维白名单(仅这两条 POST 形态),两个命令逐个 typed、逐个失败先行;Slice 1 的 provider 写入口 typed-reject 集合(Slice 1 plan 口径,数量以 provider 测试实际枚举为准)与桥既有拒绝断言改写为"仅两条审批路径允许、其余全拒"并逐个断言。
- **审批卡投影重新引入富字段**:`proposed_action` 含 arguments 全量(可能含路径/内容),白名单写宽即泄漏——缓解:decoder 测试枚举**禁止键缺席**(原始 events、provider_usage、approval 内部字段等),e2e 断言页面与 IPC 载荷不含禁键。
- **服务端审批语义缺口被误当已合规**(评审 P0-1/P0-2 的登记):记录时刻无状态门、重复审批 last-write-wins——缓解:真实兜底是恢复时 approval 节点的 digest 再复核(`execution.py:537-542`),错时审批不会执行任何动作;UI 只从 `WAITING_APPROVAL` 卡面发起提交;缺口写入 GC Boundaries,服务端加固显式推迟。
- **§7.2 协议缺口**:端点无 policy version/乐观并发复核——GC Boundaries 显式声明,卡面文案不暗示强一致;UDS/rpc 面落地时回收。
- **过期时间预渲染无数据源**:渲染伪造过期时间违反"卡面不渲染无源数据"——缓解:说明文案 + 审批后真实 expires_at,评审逐项核对映射表。
- **e2e 两段式配方未实证**:approval 节点停泊 → decide → resume 的确切事件序列与 resume 幂等性未验证——缓解:实施 Task 1 即以失败先行 e2e 探针固定配方,配方不通则升级,不静默改服务端。
- **桥错误映射塌缩**(评审 P1-2):写路径可用性依赖把 400/409 自由文本映射为 typed error——缓解:映射表失败先行测试,未映射错误一律呈现原文+码,不猜测语义。
- **Slice 1/2 回归面**:provider 写入口拒绝集合形态改写、GET-only 守卫开口、quit 三层身份证据、转录投影、DRAFT→InProgress 语义全部纳入回归。

## 既有资产复用清单

| 资产 | 位置 | 复用方式 |
|---|---|---|
| 只读桥 + descriptor 校验 | `overlay-src/src/vs/agentos/electron-main/runtimeTaskCatalogMainService.ts` | 新增两个写命令,校验链/descriptor 守卫不动,GET-only 守卫改为方法+路径双维白名单 |
| 封闭 decoder 白名单机制 | overlay 桥解码器(Slice 2) | 审批卡投影复用同一封闭解码模式,独立白名单 |
| 审批决定端点 | `apps/api_server/server.py:919-926`、`app.py:2371` | 只读消费语义,不改服务端 |
| 恢复端点 | `apps/api_server/server.py:870-901`、`app.py:1505-1527`(`run_task`) | 只读消费语义,不改服务端 |
| ApprovalDecision 合同 | `packages/contracts/src/agent_os_contracts/authority.py:200-218` | 只读依赖其校验兜底 |
| 恢复时 digest 再复核 | `packages/os_core/src/agent_os_core/execution.py:537-557` | 只读依赖,错时审批的执行面兜底 |
| e2e 驱动配方 | Slice 2 `tests/dual-workbench-slice-2.test.mjs` | 扩展:workflow 加 approval 节点 → WAITING_APPROVAL → decide → resume |
| 两段式审批配方实证 | `apps/api_server/index.html:459-467`(`reviewAction`) | e2e oracle 的对照实现 |
| 转录/详情投影 | Slice 2 provider 与 facade | 审批卡作为详情页的条件下沉组件,不新开窗 |
