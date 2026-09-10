# Goal Card — Agent OS Dual Workbench Slice 3(审批卡与审批决定写路径,REVISED)

> Date: 2026-09-11(经 kimi-reviewer-s3-gate 独立审查 REVISE_TO_SPEC 后修订)
> Track: Product(Translational 成分:把 Runtime 已有审批权威链投影进 Sessions,并打通桥的**第一批写命令**)
> Status: DRAFT / PENDING_CTO_GATE / NOT_AUTHORIZED
> Branch: `codex/ide-ui`(从 Slice 2 批准 head `6cbbbe01` 继续)
> Spec: `docs/architecture/A-AGENT-OS-DUAL-WORKBENCH-ARCHITECTURE-SPEC-V2-2026-09-09.md`(§7.2 审批协议、§7.3 审批卡 UI 合同、§12 验收③)
> 审查报告: `.agent_runs/dual-workbench-slice-1-20260909/review-s3-gate-subagent.md`
> Plan: `docs/superpowers/plans/2026-09-11-agent-os-dual-workbench-slice-3.md`(CTO gate 通过后起草)

## User result

`U-DW-S3-1`: 用户在 Agent(Sessions)窗口打开处于等待审批状态的真实任务,即可看到一张完整审批卡:动作人读摘要、digest 前缀、capability+version、risk_tier、资源范围、policy 版本、过期说明、请求者;点「批准」或「拒绝」并填写理由后,决定经主进程桥提交 Runtime;批准路径在审批后恢复运行并执行被批动作,拒绝路径动作不执行、运行保持停泊;卡面据 Runtime 事件与刷新后的详情收敛为已批准/已拒绝;digest 不符、状态漂移或服务端拒绝都以明确错误呈现,绝不静默执行。

## Product capability

`P-DW-S3-1`: Sessions Workbench 在 Slice 2 只读详情之上,新增(1)审批卡只读投影——`WAITING_APPROVAL` 任务的 pending ActionContract 经白名单最小化进入 renderer,按 spec §7.3 渲染;(2)审批写路径——桥的第一批写命令 `decideTaskApproval`(POST `/v1/tasks/{id}/approval`)与 `resumeTaskRun`(POST `/v1/tasks/{id}/run`,批准流程的必要第二步,见 CP「恢复路径」),提交与卡面同源的 action digest,服务端权威判定(actor 服务端绑定、exact digest 复核、恢复时 approval 节点 digest 再复核),渲染端零权威。

## First usable vertical slice

1. 从 Slice 2 的只读任务详情出发,`run.status == WAITING_APPROVAL` 时渲染审批卡(spec §7.3 字段逐项映射,映射表见 CP;无数据源的字段以说明文案呈现并登记);非等待审批状态不渲染卡。
2. 「批准/拒绝」+ 必填理由,经 `decideTaskApproval` 提交;提交的 digest 与卡面所据投影同源(UI 不自算 digest,原样回传投影值),防 TOCTOU。
3. 批准路径:审批记录成功后经 `resumeTaskRun` 恢复运行(携带投影内的 `configuration_snapshot_id`),approval 节点复核 digest 匹配后放行执行,run 推进至终态;拒绝路径:不触发恢复,动作不执行,run 保持 `WAITING_APPROVAL` 停泊(终止/取消属 Slice 4 停止语义)。
4. 审批卡 digest == `APPROVAL_RECORDED` 记录 digest == 执行后 `ACTION_RECEIPT_RECORDED` 的 action digest(spec §12 验收③,e2e oracle 三段断言)。
5. 审批卡投影保持白名单最小化;桥既有写入口拒绝集合改为"仅两条审批路径形态允许、其余全拒"并逐个断言;quit 有界终止不回归。

## Boundaries

- **本切片显式改写 Slice 2 边界「无写路径与审批卡」**:写路径仅限审批相关两条命令,POST allowlist 仅新增 `/v1/tasks/{id}/approval` 与 `/v1/tasks/{id}/run` 两条路径形态,逐个 typed、逐个失败先行测试。
- 消费**现有** HTTP 端点语义(`app.py:2371 record_approval` 经 `server.py:919-926`;`app.py:1505-1527 run_task` 经 `server.py:870-901`),Python/contracts 侧零变更。已核实并登记的服务端事实与缺口(详见 CP):
  - policy 审批路径在**记录时刻无 run 状态门**(`task_service.py:2206-2243` 的 `WAITING_APPROVAL` 门仅对 `external_exact` 生效);兜底为 digest 绑定(:2232)+ run 绑定(:2230)+ 恢复执行时 approval 节点的 digest 再复核(`execution.py:537-542`)——错时/过期审批不会导致任何动作执行;
  - 恢复前**重复审批 last-write-wins**(pending_action 的 WAITING 分支无 APPROVAL_RECORDED 守卫),多窗口竞态后到者静默覆盖——本切片以"卡面据最新 `APPROVAL_RECORDED` 收敛"缓解,服务端幂等加固显式推迟;
  - 端点无 `expectedPolicyVersion`/`expectedEventSequence`/`clientOperationId` 复核(spec §7.2 全量协议属 UDS/rpc 面,SPECIFIED 未实现),本切片不补服务端。
- UI typed 命令仅暴露 `APPROVE`/`REJECT`;`REVISE` 是服务端合法枚举但本切片不提供入口,decoder/载荷校验显式拒绝。
- 上游改动面不扩大:仍只有 patch 010 的 5 个文件,零新增上游文件;新代码全在 overlay `src/vs/agentos/`。
- 不含:always-allow / CapabilityGrant 产生流程(§7.2 范围化放行)、`correction.request`/停止/暂停 UI(§12 验收④与 §7.5,**建议归 Slice 4**)、审批超时自动 deny 配置化、服务端幂等/状态门加固。
- Slice 1/2 已批准面不回归:三层身份证据生命周期(c4d8023f)、只读桥 descriptor 守卫、转录投影封闭解码。
- 不 push、不 merge、不 release、无 autonomy 声称。
- `builder_id != reviewed_by`;收口独立评审,APPROVE 才进入集成讨论。

## Acceptance(评审修订版)

- 审批卡渲染可证伪:spec §7.3 字段逐项断言,映射表(见 CP)中标注「无源」的字段以说明文案呈现、不得渲染伪造值;缺字段 fail-closed 不渲染卡。
- 写命令失败先行测试(两条命令逐个):伪造 disposition(含 REVISE 经 UI 通道)、空 reason、错误 digest、非 `WAITING_APPROVAL` 状态提交、resume 缺/错 `configuration_snapshot_id`,全部 typed error;`resumeTaskRun` 载荷形状静态断言——仅 `taskId`+`configurationSnapshotId` 两键,永不发出 `inputs`/`recover_stale_lease`(评审 P2 N-2);服务端 4xx/5xx 自由文本错误映射为 typed error 的表先写测试后实现(评审 P1-2);IPC channel 拒绝名单逻辑不变;descriptor 中途变更拒绝;401 → typed stale。
- TOCTOU 同源断言:卡面渲染所据投影的 action digest 与提交载荷 digest 逐字节一致;UI 代码路径中不存在 digest 计算(测试断言/静态检查)。
- 服务端兜底以现有行为断言(不新增服务端代码):role 与 expires_at 合同校验(`authority.py:212-218`)、digest 不符拒绝(`task_service.py:2232`)、run 绑定不符拒绝(:2230)、恢复时 digest 不匹配则重新停泊(`execution.py:537-557`);**不再断言**"记录时刻精确状态门"与"重复审批拒绝"——二者为已登记缺口(评审 P0-1/P0-2)。
- e2e oracle 失败先行,随后全绿:驱动真实任务进入 `WAITING_APPROVAL`(workflow 含 approval 节点,`NodeKind.APPROVAL`,`execution.py:520-557`)→ 卡面渲染 → approve + resume → run 推进,事件流含 `APPROVAL_RECORDED` 与被批动作的 `ACTION_RECEIPT_RECORDED`,三段 digest 一致(spec §12③);reject 用例 → 不 resume、动作不执行、卡面收敛已拒绝、run 保持停泊;审批期间详情其余只读面不回归。
- `node scripts/verify.mjs`、`node --test` 聚焦套件、两个既有 e2e 与新 e2e、`npm run compile` 全绿;独立评审 P0=0/P1=0。
