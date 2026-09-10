# Agent OS Dual Workbench Slice 3 Implementation Plan(审批卡与审批决定写路径)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Sessions 窗口的任务详情从"只读"推进到"审批闭环":`WAITING_APPROVAL` 任务渲染完整审批卡(spec §7.3 字段逐项),用户经桥的第一批写命令提交批准/拒绝,批准路径恢复运行并执行被批动作,卡面 digest == 审批记录 digest == ActionReceipt digest(spec §12 验收③)。

**Architecture:** 沿用 Slice 1/2 拓扑——主进程独占 Runtime 桥、renderer 只消费封闭类型投影、overlay `src/vs/agentos/` 承载全部新代码、patch 010 上游面不扩大。数据源复用现有端点:审批卡 = `GET /v1/tasks/{task_id}` 的 `proposed_action` 白名单最小化投影;写路径 = `POST /v1/tasks/{id}/approval` + `POST /v1/tasks/{id}/run`(两段式,实证 `index.html:459-467`)。**Python/contracts 侧默认零变更。**

**Tech Stack:** 同 Slice 1/2(Code-OSS/Electron, TypeScript, Node test runner, Python Runtime HTTP API)。

**Spec:** `docs/architecture/A-AGENT-OS-DUAL-WORKBENCH-ARCHITECTURE-SPEC-V2-2026-09-09.md`(§7.2/§7.3;§12 验收③)

**门禁状态:** GC + CP 经两轮独立审查,Round 2 `APPROVE_GATE_MATERIALS`(报告 `.agent_runs/dual-workbench-slice-1-20260909/review-s3-gate-subagent.md`);CTO gate 已于 2026-09-11 通过(用户「过」)。Slice 3 从 Slice 2 批准 head `6cbbbe01` 继续,**不 push、不 merge**。

## Global Constraints(继承 Slice 1/2,逐条仍然有效)

- 上游基线钉死 `1.136.2 @ 88e44fa0e00b08f7758b4f6d05632e4fd5e4df6f`;零新增上游文件,新代码全在 overlay。
- bearer/凭证不出主进程;`decideTaskApproval`/`resumeTaskRun` 之外的任何写入口仍 typed-reject。
- 审批卡是唯一写控件;转录/详情其余面保持只读。
- 桥 GET-only 守卫改为**方法+路径双维白名单**:POST 仅放行 `/v1/tasks/{id}/approval` 与 `/v1/tasks/{id}/run` 两种形态,其余全拒。
- `resumeTaskRun` 载荷恒为 `{configuration_snapshot_id}` 单键(body),**永不发出** `inputs`/`recover_stale_lease`(评审 P2 N-2)。
- Runtime 生命周期不变:reload 不停 Runtime,quit 有界终止(c4d8023f,不得回归)。
- 无 always-allow/grant 流程、无 correction/stop UI(§12 ④ 属 Slice 4)、无 REVISE 入口、无服务端变更、无 release、无 autonomy 声称。
- 每个 Task 先写失败测试再实现;`builder_id != reviewed_by`,收口独立评审。
- 已登记服务端缺口(不得在本切片"顺手补"):policy 路径记录时刻无状态门、重复审批 last-write-wins、无 policyVersion/eventSequence 复核。

## 范围边界(In / Out)

**In:**
1. 审批卡投影:task_json `proposed_action` 白名单最小化(capability/version/risk_tier/arguments 摘要/action_digest/side_effect_guarantee)+ `run.policy_version` + `configuration_snapshot.snapshot_id` + `approval`(收敛用)入桥投影;decoder 封闭校验,禁止键缺席断言。
2. 桥写命令两条,逐个 typed、逐个失败先行;typed error 映射表(400/403/409/5xx → typed,未映射呈现原文+码)。
3. Sessions 详情页审批卡组件:§7.3 映射表逐项渲染,过期时间以说明文案+审批后真实值呈现;TOCTOU 同源提交;REJECT 不 resume。
4. e2e oracle(失败先行):WAITING_APPROVAL 配方 → 卡面渲染 → approve+resume → 三段 digest 一致;reject 用例;禁键不泄漏;Slice 1/2 回归。

**Out(显式排除):** §12 ④ 停止/correction UI、always-allow/CapabilityGrant、REVISE、审批超时自动 deny、多窗口竞态服务端加固、Python/contracts 变更(默认零变更;若确需升级独立 Task 6)。

## Tasks

### Task 1: e2e 审批配方探针(HTTP 直连,失败先行)

**Files:**
- Create: `apps/code-oss/tests/dual-workbench-slice-3.test.mjs`(先只含配方探针用例)
- Create: `.agent_runs/dual-workbench-slice-1-20260909/e2e-logs/slice3-recipe-probe.json`

- [ ] Step 1: 失败先行 e2e 探针——复用 Slice 2 HTTP 配方(loopback 桩 provider、`:local` scope、`:commit`、seal、run),workflow 在 tool 节点后插 `approval` 节点(`NodeKind.APPROVAL`,workflow.py:29);断言 run 停泊 `WAITING_APPROVAL` 且事件含 `APPROVAL_REQUESTED`,task_json `proposed_action` 非空含 `action_digest`
- [ ] Step 2: 探针续段——`POST /approval`(APPROVE+reason+digest)→ 断言 `APPROVAL_RECORDED`;`POST /run`(带 snapshot id)→ 断言 `RUN_RESUMED`、被批动作 `ACTION_RECEIPT_RECORDED`、三段 digest 一致(卡面 proposed_action.action_digest == approval.action_digest == receipt action digest);REJECT 用例断言不执行、保持停泊
- [ ] Step 3: 配方不通则**停止并升级**(不静默改服务端);通则把配方固化为 e2e 公共驱动,记录 probe 日志
- [ ] Step 4: 账本记账

### Task 2: 审批卡投影封闭解码器(失败先行)

**Files:**
- Modify: `apps/code-oss/overlay-src/src/vs/agentos/common/runtimeTaskCatalog.ts`
- Modify: `apps/code-oss/tests/runtime-task-detail-contract.test.mjs`(或新建 slice-3 合同测试)

- [ ] Step 1: 失败测试——`decodeTaskDetail` 扩张:WAITING_APPROVAL 时投影 `approvalCard` 子对象(白名单键精确枚举:capability/version/risk_tier/action_digest/arguments 摘要/policy_version/请求者/快照 id);禁止键(`provider_usage`、原始 events、approval 内部字段超集)缺席断言;缺必需字段 fail-closed(approvalCard 缺席而非半成品)
- [ ] Step 2: 实现解码器扩张;非 WAITING_APPROVAL 时 approvalCard 恒缺席
- [ ] Step 3: 真实响应样本 fixture 回归(Task 1 探针捕获,无 secret)
- [ ] Step 4: 全量测试 + 编译 0 errors

### Task 3: 桥写命令(decideTaskApproval + resumeTaskRun,失败先行)

**Files:**
- Modify: `apps/code-oss/overlay-src/src/vs/agentos/electron-main/runtimeTaskCatalogMainService.ts`
- Modify: `apps/code-oss/overlay-src/src/vs/agentos/electron-main/runtimeTaskCatalogChannel.ts`
- Modify: `apps/code-oss/tests/runtime-task-bridge.test.mjs`

- [ ] Step 1: 失败测试——方法+路径双维白名单:两条 POST 形态放行,其余 POST/PUT/DELETE 全拒(GET-only 守卫改写后既有 GET 行为不回归);`decideTaskApproval` 载荷校验(disposition∈{APPROVE,REJECT},REVISE 拒;reason 非空;digest 格式);`resumeTaskRun` body 恒单键、禁发 `inputs`/`recover_stale_lease` 静态断言;typed error 映射表(400/403/409/5xx);descriptor 中途变更拒绝;401 → typed stale;channel 未知命令仍拒绝
- [ ] Step 2: 实现两个命令与映射表
- [ ] Step 3: Slice 1/2 桥回归全绿(拒绝集合形态改写逐个断言)

### Task 4: Sessions 审批卡 UI(失败先行)

**Files:**
- Modify: `apps/code-oss/overlay-src/src/vs/agentos/`(provider/content provider 相关文件)
- Modify: `apps/code-oss/tests/agent-os-sessions-provider.test.mjs`

- [ ] Step 1: 失败测试——WAITING_APPROVAL 详情渲染审批卡,§7.3 映射表逐项存在(过期时间为说明文案);提交载荷 digest 与投影逐字节一致(TOCTOU 同源,UI 无 digest 计算);REJECT 不触发 resumeTaskRun;提交后据刷新详情收敛;非等待状态无卡;16 写入口拒绝集合形态改写后其余仍 typed-reject
- [ ] Step 2: 实现审批卡组件与提交链路(卡面数据存投影模型,提交原样回传)
- [ ] Step 3: 结构测试更新(若触碰注册接缝)

### Task 5: e2e oracle 完整化 + 手动验证 + 独立评审

**Files:**
- Modify: `apps/code-oss/tests/dual-workbench-slice-3.test.mjs`
- Create: `.agent_runs/dual-workbench-slice-1-20260909/verification-slice-3.md` + 截图

- [ ] Step 1: e2e 全绿:真实任务 → Sessions 选中 → 卡面渲染逐项断言 → UI 发起 approve → run 推进终态 → 事件/转录/卡面收敛一致;reject 用例;页面与 IPC 载荷禁键缺席;bearer 不泄漏;reload 存活;quit 有界终止不回归;Slice 1/2 e2e 不红
- [ ] Step 2: 截图 + verification-slice-3.md;如实标注仅单测覆盖的行为
- [ ] Step 3: `git status --short` / `git diff --check`;显式路径提交(绝不 `git add apps/code-oss`);账本记账
- [ ] Step 4: 独立评审(builder ≠ reviewer),APPROVE_SLICE_3 才谈下一步

### Task 6(条件触发): Python/contracts 变更

仅当 Task 1–5 证明现有端点确实不够时启动:独立 Task、tests/product 全量、评审范围扩大。默认不启动。

## 验证总表(收口前逐项打勾)

- `node scripts/verify.mjs` 62+ 全绿(含新增用例)
- `node --test` 桥/合同/provider 聚焦套件全绿
- 三个 e2e(slice-1/2/3)全绿
- `npm run compile` 0 errors(cwd `.code-oss/upstream`)
- overlay 同步:`node scripts/apply-workbench-overlay.mjs` 已跑(cwd `apps/code-oss`)
