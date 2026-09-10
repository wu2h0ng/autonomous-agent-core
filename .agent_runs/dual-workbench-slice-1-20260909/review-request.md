# Slice 1 独立评审包(Independent Review Packet)

| 项目 | 内容 |
|---|---|
| 任务 | slice-1-independent-review |
| 发起者 | kimi-builder(builder,非 reviewer) |
| 指派 reviewer | codex-primary |
| 日期 | 2026-09-10 |
| 仓库 / 分支 | `autonomous-agent-core/.worktrees/ide-ui`,分支 `codex/ide-ui` |
| 评审范围(exact commits) | `e4461dbe` → `ac3c6d94`(共 6 个提交,全部本地,未 push) |
| 裁决标准 | `APPROVE_SLICE_1` 仅当 **P0=0 且 P1=0**;否则 `REVISE_TO_SPEC` / `REJECT` |

## 1. 背景(最小上下文)

基于 Code-OSS 1.136.2(上游 Sessions 发布线)构建"IDE + Agent"双 Workbench。Slice 1 目标:**一个 Code-OSS 应用内同时打开 IDE 编码窗口与 Agent Sessions 窗口,把 Agent OS Product Runtime 的任务以只读方式投影进 Sessions 窗口**。上位约束见根 AGENTS.md(C7 不可写、bearer 不出主进程、无 autonomy 声称)与 spec V2(`docs/architecture/A-AGENT-OS-DUAL-WORKBENCH-ARCHITECTURE-SPEC-V2-2026-09-09.md`,**untracked,禁止提交**)。

## 2. 必做核验项(reviewer 必须亲自重跑,不得采信 builder 记录)

在 `.worktrees/ide-ui` 下:

1. `cd apps/code-oss && node scripts/verify.mjs` —— 期望 42/42 pass;
2. `cd apps/code-oss && node tests/dual-workbench-slice-1.test.mjs` —— 期望 1/1 pass(e2e 起真实 Python runtime + 双窗口 + CDP 断言);
3. `cd apps/code-oss && npm run compile` —— 期望 0 errors;
4. `git log --oneline e4461dbe^..ac3c6d94` 与 `git diff --stat` —— 核对改动面。

## 3. 重点审查问题(逐条给结论)

1. **密钥红线**:bearer token 是否在任何路径泄漏出主进程(渲染进程 DOM / storage / 全局变量 / console / IPC 载荷 / 日志)?descriptor 字节是否会经 IPC 到达 renderer?
2. **只读边界**:`AgentOSSessionsProvider` 的 16 个变更入口是否全部 typed reject?是否存在绕过只读 facade 直接触达 runtime 写端口的代码路径?
3. **descriptor 校验**:symlink / 权限位 / uid / 非 loopback / pid 存活的校验是否 fail-closed?每次请求后重读比对(pid/boot_id/port/bearer)是否可被竞态绕过?
4. **生命周期**:`interactiveRuntimeLifecycle.ts` 的有界终止(SIGTERM → 50ms 轮询 → 5s SIGKILL,boot_id 防 pid 复用)是否正确?`hasServedCatalog` 语义是否保证 quit 只杀本实例实际连过的 runtime?
5. **上游改动面**:patch 010 是否确实只触碰 4 个上游文件、零新增上游文件?sessions 入口接缝是否唯一(`sessions.desktop.main.ts`)?
6. **伪实现检查**:overlay `src/vs/agentos/` 13 个文件是否存在空实现 / mock 成功 / 常量返回测试?
7. **测试有效性**:e2e 断言是否会在 provider 返回常量或 bridge 被绕过时失败?

## 4. 已知边界(builder 如实声明,供 reviewer 核对)

- 空任务列表 / malformed 响应 / Runtime 不可用 typed error 仅在单元测试层覆盖,e2e 未逐项手动操作;
- 项目 venv 被补装 `sqlglot`(api_server 传递依赖,仓库未声明)——环境事实,非代码变更;
- spec V2 及其状态 ledger 未回写(遵守其文件头 Git 纪律);
- `apps/code-oss/extensions/`、`apps/macos`、根 `package-lock.json`、`docs/` 未跟踪文档均不在本切片范围,未提交。

## 5. 产出要求

将评审报告写入 `.agent_runs/dual-workbench-slice-1-20260909/review-codex-primary.md`,包含:逐项结论、发现的问题列表(P0/P1/P2 分级)、最终裁决(`APPROVE_SLICE_1` / `REVISE_TO_SPEC` / `REJECT`)、reviewer 身份与时间;并向 `.agent_runs/dual-workbench-slice-1-20260909/messages.jsonl` 追加一条 `type: review-verdict` 记录。
