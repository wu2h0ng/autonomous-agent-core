# Goal Card — Agent OS Dual Workbench Slice 2(任务详情与事件流只读转录)

> Date: 2026-09-10
> Track: Product(Translational 成分:把 Runtime 已有事件真相投影进 Sessions)
> Status: DRAFT / PENDING_CTO_GATE / NOT_AUTHORIZED
> Branch: `codex/ide-ui`(从 Slice 1 批准 head `e13684a2` 继续)
> Spec: `docs/architecture/A-AGENT-OS-DUAL-WORKBENCH-ARCHITECTURE-SPEC-V2-2026-09-09.md`(§12 验收②⑤的只读半边)
> Plan: `docs/superpowers/plans/2026-09-10-agent-os-dual-workbench-slice-2.md`

## User result

`U-DW-S2-1`: 用户在 Agent(Sessions)窗口的任务列表中点击任一真实任务,即可在原生会话视图中只读查看该任务的完整陈述、当前状态、运行状态与按序事件转录;任务进展刷新后视图一致更新,不丢失选中上下文。

## Product capability

`P-DW-S2-1`: Sessions Workbench 通过主进程只读桥,消费 Runtime 的任务详情(白名单最小化)与 trajectory 投影(sequence 单调递增 + 完整性校验,gap 显式标注),投影为上游 `ISession` 只读 facade 的详情页与转录项。双窗口共享同一 taskId 事件域的只读视图。

## First usable vertical slice

1. 从 Slice 1 批准的 Sessions 任务列表出发,选中任务打开只读详情(数据源:现有 `GET /v1/tasks/{task_id}`,白名单最小化字段)。
2. trajectory 事件映射为转录项:乱序/非单调/`source_stream_last_sequence` 不一致 fail-closed 不渲染;run 过滤产生的 seq gap 显式标注,不静默跳过。
3. Runtime 重启后重新拉取,选中状态与转录一致恢复(reload 存活)。
4. 全部路径保持零写控件;bearer 与 `approval`/`proposed_action`/`provider_usage` 等富字段不出主进程;quit 有界终止不回归。

## Boundaries

- 上游改动面不扩大:仍只有 patch 010 的 5 个文件,零新增上游文件;新代码全在 overlay `src/vs/agentos/`。
- 只读:无发送/编辑/删除/审批控件;Runtime 侧只允许只读 GET 端点,新增端点走 contracts 封闭解码。
- 无实时推送(SSE/WS)、无写路径与审批卡、无 IDE 侧联动、无多 workspace、无后台保活。
- Slice 1 已批准的三层身份证据生命周期(c4d8023f)不得回归。
- 不 push、不 merge、不 release、无 autonomy 声称。
- `builder_id != reviewed_by`;收口独立评审,APPROVE 才进入集成讨论。

## Acceptance(评审修订版)

- contracts/decoder 封闭性失败先行测试:多余字段、乱序/非单调 sequence、`source_stream_last_sequence` 与事件流不一致、未知事件类型全拒;**seq gap 不是错误,必须显式标注**(trajectory 按 run 过滤,gap 是常态——评审 P0-1 纠正)。
- 字段最小化可证伪:decoder 测试枚举 `approval`/`proposed_action`/`provider_usage`/原始事件载荷**缺席**;e2e 断言页面 innerText 与 IPC 载荷均不含这些键(评审 P0-2)。
- run_id 链路可证伪:`getTaskDetail` 返回的 run_id 必须来自 `task_json.run`,`getTaskTrajectory` 用它调用(评审 P0-3)。
- 主进程桥新 IPC 命令逐个 typed、逐个失败先行测试;descriptor 中途变更拒绝;401 → typed stale;1 MiB 上限。
- provider 投影测试:选中打开详情、trajectory 映射为转录项(含 gap 标注)、fail-closed 不渲染、facade 身份稳定。
- e2e oracle 失败先行,随后全绿:详情渲染、事件顺序与 gap 标注、bearer 与富字段不泄漏、无写控件、reload 存活、quit 有界终止不回归。
- `node scripts/verify.mjs` 与 `npm run compile` 全绿;独立评审 P0=0/P1=0。
