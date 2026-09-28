# Dual Workbench v2.1 独立架构审查

- 审查日期：2026-09-09
- 审查身份：独立只读架构审查员
- 审查边界：架构规格与 preflight；不是产品实现审查
- 精确工作树：`codex/ide-ui@b05d29b8cc1c5d7d54c0061db9dacac91c9a6f56`
- 字面 verdict：`REVISE_TO_SPEC`

## 结论

v2.1 已关闭原审查的产品拓扑、Webview 顶层、Rust 预锁定、贫化领域模型、双父进程 stdio、JSONL 真相根、Sessions 所有权以及 `ActionPermit.matches()` 职责误写等主要问题。`1.136.2@88e44fa0`、整体升级而非回移、SQLite canonical event/outbox、上游 Sessions 三服务和首切片边界都有足够证据进入下一轮架构收敛。

但两个直接属于本轮四项开发前置闭环的语义矛盾尚未关闭：Runtime 在当前交互 slice 中究竟是否随 Electron 应用退出，以及 peer credential 在握手中究竟是否“解析身份”。这两处会直接改变 supervisor/service ownership 和 channel authorization 的实施计划，不能留给实现者猜。因此当前不批准进入正式实施计划编写；完成以下最小规格修订后可重新审查，无需扩大协议、实现自动化/审批/Rust。

## Findings

### P0

无。

### P1-1 — 当前交互 Runtime 的应用退出语义自相矛盾

- `docs/architecture/A-AGENT-OS-DUAL-WORKBENCH-ARCHITECTURE-SPEC-V2-2026-09-09.md:100` 明确 Electron main “当前随应用退出”；`:556` 又明确首切片只承诺 Electron 存活期间的交互 Runtime，UI 关闭后保活属于后续 OS service slice。
- 但 `docs/architecture/A-AGENT-OS-DUAL-WORKBENCH-PREFLIGHT-SPIKE-2026-09-09.md:59-62` 同时写“UI 退出不等于 Runtime 退出；显式退出并停止后台运行才 shutdown”，且把它与“本阶段只实现交互 Runtime”并列。这会被自然解释为首切片已经具有 app 退出后的 Runtime 保活，和主 spec 的阶段边界冲突。
- 影响：无法唯一决定 Electron `before-quit/will-quit` 时 supervisor 是否终止子进程、descriptor/endpoint 如何失效、是否显示“退出并停止后台运行”。这是 lifecycle blocker，不只是措辞。
- 最小修订：区分 `renderer/window close`、`application quit`、`OS service installed/enabled` 三种事件。明确首切片中关闭窗口不停止 Runtime，但应用退出终止交互 Runtime；只有后续 service slice 才允许应用退出而 Runtime 保活，并届时提供“退出并停止后台运行”。

### P1-2 — peer credential 的身份作用在拓扑图与绑定不变量之间冲突

- `docs/architecture/A-AGENT-OS-DUAL-WORKBENCH-ARCHITECTURE-SPEC-V2-2026-09-09.md:551` 写 `SO_PEERCRED / named pipe 客户端令牌 → 服务端解析身份`。
- 同文 `:586` 及 preflight `docs/architecture/A-AGENT-OS-DUAL-WORKBENCH-PREFLIGHT-SPIKE-2026-09-09.md:66-68` 则正确规定 peer credential 只约束本地进程、不得产生业务身份；`principal_id/tenant_id` 必须来自受信 profile session，再签发绑定 window/host/scope 的短期 channel lease。
- 影响：`:551` 可被实施者落实成 UID/PID/token → principal/tenant 的业务身份推导，正好重开本轮要求关闭的 channel identity blocker。
- 最小修订：将 `:551` 改为“对端进程/OS 安全主体校验”，并显式写出两步：`peer credential -> local process admission`；`trusted profile session -> principal/tenant -> scoped channel lease`。业务主体不得从 peer credential 映射或覆盖。

### P2-1 — 握手示例未展示其文字上要求的关键 lease 字段

- 主 spec `:565-579` 的 `rpc/hello` 示例没有 `windowId/profileSession proof`，返回 lease 也没有展示 `profile_session_id/host_instance_id/window_id/principal_id/tenant_id/allowed_workspace_ids/generation`；而 `:586-589` 将这些字段列为强绑定要求。
- 这不阻塞修订架构本身，但实施计划必须把示例升级为最小规范 schema，或明确示例为非完整 wire excerpt，并给出服务端取得 `window_id` 与验证 profile session 的具体可信通道。否则测试无法判断 lease substitution/window confusion。

## 逐项验证

1. **D-BASE**：通过。远端 `refs/tags/1.136.2` 独立解析为 `88e44fa0e00b08f7758b4f6d05632e4fd5e4df6f`；`apps/code-oss/upstream.lock.json:3-8` 正确保留活动基线 `1.106.3@bf9252...`，并把 Sessions 基线标为 `CHARACTERIZED_NOT_ACTIVE`。主 spec `:637-649` 未把 characterization 冒充活动升级。
2. **whole-upgrade**：通过，作为实施路线判断而非工作量承诺。preflight `:25-33` 给出 844/705 文件、跨目录 import 与 7,294 个相关变化文件，并证明旧 patch 在新基线上冲突；主 spec `:641-645` 因依赖闭包拒绝回移，逻辑成立。独立 shallow checkout 复核 `src/vs/sessions` 为 844 文件、705 个 TS 文件。
3. **SQLite canonical event/outbox**：通过。主 spec `:362-381` 将状态、幂等、sequence 和 typed event/outbox 放入同一 SQLite transaction；审计段/JSONL/索引/快照是派生物。此前“双真相根”矛盾已关闭。
4. **Runtime lifecycle**：未完全通过，见 P1-1。主 spec 自身分阶段诚实，但 preflight 的 app/UI exit 句重开歧义。
5. **channel identity**：未完全通过，见 P1-2。绑定模型正确，但拓扑图仍写“peer -> 解析身份”。
6. **Sessions 三服务**：通过。`ISessionsProvidersService`、`ISessionsManagementService`、`ISessionsService` 和 `ISessionsProvider` 在 `1.136.2` exact checkout 均存在；主 spec `:195-207`、`:651-663` 的 registry / orchestration / visible-active state / provider seam 分权与上游结构一致。
7. **ActionPermit / dispatch guard**：通过，且状态纪律诚实。源码 `packages/contracts/src/agent_os_contracts/authority.py:236-264` 证明 `matches()` 仅比较 action id/digest、principal、tenant、workspace、correction epochs；`packages/os_core/src/agent_os_core/capability.py:132-177` 当前 broker 另查 execution fence、permit expiry、halt/current epochs 和 preflight。主 spec `:462-475` 明确把 grant status/expiry 与 sandbox 的完整复核列为尚待实现要求，没有冒充当前能力。
8. **状态纪律**：通过。目标 spec `:6-12`、`:40-45`、`:824-847` 与 spike `:3-17` 均维持 `DESIGN_ONLY / SPECIFIED / CHARACTERIZED / NOT_IMPLEMENTED / NOT_RELEASED`。四个目标架构文件和 lock 均为 untracked；工作树另有大量既存修改，本审查未更改它们。`git diff --check` 通过；未 commit/push/merge。

## 复审入口

只需修订 P1-1、P1-2，并把 P2-1 纳入实施计划前的 schema checklist。无需在本轮冻结更广协议，也无需实现审批、自动化、多客户端写入或 Rust Runtime。修订后若无新矛盾，预期 verdict 可提升为 `APPROVE_FOR_IMPLEMENTATION_PLANNING`；该批准仍只授权编写实施计划，不授权产品实现、commit、push、merge 或 release。

---

## 最小修订复审（2026-09-09）

- 复审范围：仅前次 P1-1、P1-2、P2-1 对应最小修订及其与 source/lock 的一致性。
- 字面 verdict：`APPROVE_FOR_IMPLEMENTATION_PLANNING`
- Findings：`P0=0 / P1=0 / P2=1（非阻塞计划备注）`

### 复审结论

前次两个 P1 已关闭，前次 P2 的规范字段缺口也已实质关闭。v2.1 + preflight 现在可以进入**实施计划编写**；这不等于产品实现授权，不改变 `DESIGN_ONLY / SPECIFIED / CHARACTERIZED_NOT_ACTIVE`，也不授权冻结更广协议、实现审批/自动化/多客户端写入/Rust Runtime、commit、push、merge 或 release。

### 已关闭项

1. **P1-1 Runtime lifecycle：关闭。** Preflight `docs/architecture/A-AGENT-OS-DUAL-WORKBENCH-PREFLIGHT-SPIKE-2026-09-09.md:55-62` 已明确三态：renderer/window close 或 reload 不停 Runtime；当前 `application quit` 有界终止交互 Runtime；只有后续 OS service slice 才允许 application quit 后保活，并且“退出并停止后台运行”仅在 service 已安装/启用后出现。主 spec `docs/architecture/A-AGENT-OS-DUAL-WORKBENCH-ARCHITECTURE-SPEC-V2-2026-09-09.md:557` 同步该语义，与 `:100` 的当前阶段边界一致。
2. **P1-2 peer/process admission 与 business identity：关闭。** 主 spec `:551-552` 已将流程改为两步：peer credential 只做本地进程准入；trusted profile session 才产生 principal/tenant 并签发 scoped channel lease。`:592-596` 再次约束一次性 bootstrap、peer 不产生业务身份、客户端自报字段无效。不存在 UID/PID/named-pipe token 直接映射业务主体的剩余声明。
3. **P2-1 rpc/hello/channel lease schema：关闭。** 主 spec `:562-596` 已增加 `windowId`、一次性 `channelBootstrapRef`、响应 `generation`，并在 lease 中回显/bind `profileSessionId + hostInstanceId + windowId + principalId + tenantId + allowedWorkspaceIds + generation + capabilities + expiry`；同时说明 bootstrap ref 立即消费、renderer 不接触 profile credential/长期 token。该字段集足以让实施计划定义 substitution、replay、window confusion、generation drift 和 scope expansion 的失败测试。

### 剩余 P2（不阻塞实施计划编写）

#### P2-R1 — 非窗口 host 的 `windowId` 取值需在计划中显式化

- `rpc/hello` 的 `hostType` 包含 `cli|test`（主 spec `:565`），而示例把 `windowId` 写成无条件字段（`:567`），lease 也无条件绑定 `windowId`（`:581-583`）。CLI/test 通常没有真实窗口。
- 实施计划应选择并测试一种闭合语义：按 host type 令 `windowId` 可选且 CLI/test 必须为空，或把字段改名为可覆盖非窗口宿主的 `channelEndpointId/surfaceInstanceId`。不得允许客户端用伪造 window ID 获得另一窗口 lease。
- 这是 wire schema 精化项，不改变两步身份边界，不阻止计划编写。

### 状态与 Git 纪律复核

- `apps/code-oss/upstream.lock.json:3-8` 仍保持活动基线 `1.106.3@bf9252...`、Sessions 候选 `1.136.2@88e44fa0...`、`CHARACTERIZED_NOT_ACTIVE`。
- 目标 spec、preflight、lock 与本 review 均仍为 untracked；未发现它们被提交或伪装为已实现状态。
- `git diff --check` 通过。
- 本复审除更新本文件外未修改任何 spec、source、lock 或 `CURRENT_STATE`；未 commit、push、merge。
