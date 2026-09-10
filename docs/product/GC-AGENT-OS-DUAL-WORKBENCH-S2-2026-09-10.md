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

`P-DW-S2-1`: Sessions Workbench 通过主进程只读桥,消费 Runtime 的任务详情与有序事件流(按 taskId,seq 严格连续),投影为上游 `ISession` 只读 facade 的详情页与转录项。双窗口共享同一 taskId 事件域的只读视图。

## First usable vertical slice

1. 从 Slice 1 批准的 Sessions 任务列表出发,选中任务打开只读详情。
2. 事件流映射为转录项,乱序/空洞/未知事件类型 fail-closed 不渲染。
3. Runtime 重启后重新拉取,选中状态与转录一致恢复(reload 存活)。
4. 全部路径保持零写控件;bearer 不出主进程;quit 有界终止不回归。

## Boundaries

- 上游改动面不扩大:仍只有 patch 010 的 5 个文件,零新增上游文件;新代码全在 overlay `src/vs/agentos/`。
- 只读:无发送/编辑/删除/审批控件;Runtime 侧只允许只读 GET 端点,新增端点走 contracts 封闭解码。
- 无实时推送(SSE/WS)、无写路径与审批卡、无 IDE 侧联动、无多 workspace、无后台保活。
- Slice 1 已批准的三层身份证据生命周期(c4d8023f)不得回归。
- 不 push、不 merge、不 release、无 autonomy 声称。
- `builder_id != reviewed_by`;收口独立评审,APPROVE 才进入集成讨论。

## Acceptance

- contracts/decoder 封闭性失败先行测试(多余字段、乱序、seq 空洞、未知类型全拒)。
- 主进程桥新 IPC 命令逐个 typed、逐个测试;descriptor 中途变更拒绝;401 → typed stale。
- provider 投影测试:选中打开详情、事件映射、fail-closed 不渲染、facade 身份稳定。
- e2e oracle 扩展全绿:详情渲染、事件顺序、bearer 不泄漏、无写控件、reload 存活、quit 有界终止。
- `node scripts/verify.mjs` 与 `npm run compile` 全绿;独立评审 P0=0/P1=0。
