# Agent OS 双 Workbench 开发前置 Spike

| 项目 | 内容 |
|---|---|
| 状态 | `CHARACTERIZED / NOT_IMPLEMENTED / NOT_RELEASED` |
| 日期 | 2026-09-09 |
| 轨道 | Product Architecture preflight |
| 当前活动 Code-OSS 基线 | VS Code `1.106.3` / `bf9252a2fb45be6893dd8870c0bf37e2e1766d61` |
| Sessions 候选基线 | VS Code `1.136.2` / `88e44fa0e00b08f7758b4f6d05632e4fd5e4df6f` |

## 1. 裁决

选择“整体升级 Code-OSS 基线到 `1.136.2`，随后在新基线上重写最小 Agent OS patch”作为实施路线。

否决把 `src/vs/sessions` 单独回移到 `1.106.3`。该目录不是可独立搬运的 UI 包，而是对同版本 `base`、`platform`、`editor` 和 `workbench` 的大面积源码依赖层。

本裁决只固定实施基线和迁移方向，不把 `apps/code-oss/upstream.lock.json` 的活动基线切换为 `1.136.2`。活动切换必须与可应用的新 patch、构建和反退化测试在同一提交完成，避免仓库进入“lock 已升级、overlay 必坏”的伪状态。

## 2. 可复核证据

从 `https://github.com/microsoft/vscode.git` 的正式 tag refs 获取：

- 最新正式标签：`1.136.2`。
- exact commit：`88e44fa0e00b08f7758b4f6d05632e4fd5e4df6f`。
- `src/vs/sessions` 存在，包含 844 个文件。
- 其中 TypeScript 文件 705 个。
- 静态解析得到 1,923 个唯一 import 目标；1,090 个目标位于 `src/vs/sessions` 外。
- import 次数按顶层依赖聚合：`sessions=3087`、`base=2871`、`platform=2600`、`workbench=1936`、`editor=217`。
- `1.106.3..1.136.2` 全仓差异：14,058 个文件，约 3,128,012 行增加、199,973 行删除。
- 与迁移直接相关的 `base/platform/editor/workbench/code/build/package.json/product.json` 差异：7,294 个文件，约 1,284,129 行增加、137,110 行删除。
- 现有 `010-native-agent-workbench.patch` 对 `1.136.2` 执行 `git apply --check` 失败；明确冲突包括 renderer bootstrap、native host、windows main、titlebar、chat contribution 和 desktop main 等核心接缝。

这些数字是依赖规模证据，不是实现工作量承诺。精确改造文件集必须从上游 Agents Window 的实际入口和 Agent OS 最小纵向切片反推。

## 3. 上游结构审计

`1.136.2/src/vs/sessions` 的稳定所有权应原样保留：

- `ISessionsProvidersService`：provider registry；
- `ISessionsManagementService`：session/chat 生命周期与 provider 路由；
- `ISessionsService`：active/visible session、focus、navigation 与恢复；
- `ISessionsProvider`：Agent OS Runtime adapter seam；
- `Workbench`、Parts、layout controller：独立 renderer 与 per-session working set。

Agent OS 不应把这三层服务压平成自造的单一 sessions service，也不应复制一套平行状态机。Product Runtime 的 `Mandate/Task/Run/...` 经 provider adapter 投影为 `ISession/IChat` facade；Task 仍是产品真相对象，Session 只是 Workbench 交互模型。

## 4. 四项开发前置闭环

### 4.1 唯一事务提交根

SQLite 是产品状态与领域事件的唯一原子提交根：状态变更、幂等记录、sequence 和 typed event/outbox 在同一 SQLite transaction 提交。

SHA-256 链式审计段、JSONL、搜索索引和快照均是可验证派生物，不是第二真相根。发布器只读取 committed outbox；崩溃后按 sequence 重投。派生审计段损坏时停止导出并告警，但不得反向改写 canonical event rows。

### 4.2 Runtime 生命周期

每个 profile 只有一个 Runtime owner，通过 profile lock + endpoint generation/fence 仲裁：

- 交互模式：Electron main 启动并拥有 Runtime；关闭或重载任一 renderer/window 不停止 Runtime，但 **application quit 会有界终止交互 Runtime**；
- 无人值守模式：后续由 OS service manager 启动并保活，macOS 对应 LaunchAgent，Linux 对应 user systemd service，Windows 对应 per-user service/task；该模式下 application quit 不停止 Runtime；
- “退出并停止后台运行”只在 OS service 已安装且启用后提供，用于停止/禁用后台 service；交互模式不展示该动作；
- 本阶段只实现交互模式。自动化与 application quit 后继续运行必须等 OS service slice 通过后才可声称。

### 4.3 身份绑定

`SO_PEERCRED`/named-pipe peer token 只作为本地进程约束，不产生业务主体。

Runtime 依据受信 profile session 建立 `principal_id/tenant_id`，再向 Electron main、具体 Agent window、IDE extension host 签发短期 channel lease。lease 绑定 `profile_session_id + host_instance_id + window_id + principal_id + tenant_id + allowed_workspace_ids + capabilities + expiry + generation`。renderer 只能通过受限 contextBridge 使用对应 channel；客户端字段不能覆盖这些绑定。

### 4.4 权威校验分层

`ActionPermit.matches()` 当前只校验 action identity、digest、principal、tenant、workspace 和 correction epochs。`lease_fence`、permit expiry、grant status/expiry、current correction snapshot 与 sandbox policy 必须由 CapabilityBroker dispatch-time guard 单独复核。测试必须分别击穿每一层，不能用 `matches()` 的通过替代完整授权。

## 5. 实施入口门

进入产品代码实施前，修订 spec 必须满足：

1. 将 `1.136.2`/exact commit 和“整体升级”登记为 D-BASE 决策；
2. Sessions 三服务和 provider seam 与上游一致；
3. SQLite canonical event/outbox 模型替代“双真相根”；
4. Runtime 交互生命周期与后台服务生命周期分阶段，不提前声称无人值守；
5. 业务身份绑定不依赖 peer credential 推导；
6. `ActionPermit.matches()` 与 dispatch-time guard 分账；
7. v2 退出门改为“架构 spec 修订完成，但尚未实现/验证”。

通过后首个产品实现切片只能覆盖：升级活动基线、独立 Sessions renderer 启动、真实 Workbench/Parts/grid、只读 Runtime provider task list。审批、自动化、多客户端写入和 Rust Runtime 均不在首切片。
