# Slice 1 端到端验证记录(Dual Workbench Slice 1)

| 项目 | 内容 |
|---|---|
| 日期 | 2026-09-10 |
| 执行者 | kimi-builder(Task 6) |
| 分支 / worktree | `codex/ide-ui` @ `.worktrees/ide-ui` |
| 范围 | 计划 `docs/superpowers/plans/2026-09-09-agent-os-dual-workbench-slice-1.md` Task 6 |
| 纪律 | 本文不含 bearer token / descriptor 字节;不 push、不 merge、不 release |

## 1. 环境

- Node v24.15.0,npm 11.12.1,macOS(Darwin arm64)
- Python runtime:`../../.venv/bin/python`(项目 venv,`PYTHONPATH=packages/contracts/src:packages/os_core/src`)
- Code-OSS 基线:上游 1.136.2 Sessions 发布线(见 Task 1/2 提交 `e4461dbe`/`5b132ee6`)

## 2. 自动化验证(全部本地通过)

| 项目 | 命令 | 结果 |
|---|---|---|
| 聚焦测试(含 Task 1–5 全部单元/结构测试) | `node scripts/verify.mjs` | **42/42 pass**(6 个聚焦测试文件,6781ms) |
| 端到端 oracle | `node tests/dual-workbench-slice-1.test.mjs` | **1/1 pass**(10.8s) |
| 编译 | `npm run compile` | 0 errors |
| 合计 | verify 42 + e2e 1 | **43/43 绿** |

## 3. e2e oracle 断言明细(`tests/dual-workbench-slice-1.test.mjs`)

真实环境:启动真实 Python runtime(`apps.runtime_daemon`,端口 0 自动分配,descriptor 落临时目录),POST 两个真实任务(`Design the dual workbench` / `Review the slice one gates`),经 `scripts/code.sh` + `AGENTOS_RUNTIME_DESCRIPTOR` 启动应用,Node 内置 WebSocket 驱动 CDP 断言:

1. **双窗口**:同时存在 `workbench-dev.html`(IDE)与 `sessions-dev.html`(Sessions)两个 page target;
2. **上游 Parts 保留**:IDE 窗口 Workbench Parts 为原生布局(非伪造 EditorPane);
3. **任务投影**:两个任务标题渲染进 Sessions 窗口 DOM;
4. **密钥红线**:bearer token 不出现在 DOM / storage / 全局变量 / console;
5. **只读边界**:Sessions 中不存在 send / delete / archive / approve 控件;
6. **刷新存活**:窗口 reload 后 runtime 连接恢复;
7. **生命周期**:`Browser.close` 后应用退出,且交互 runtime 在 30s 内被终止(对应 spec §557 的有界退出要求;SIGTERM → 50ms 轮询 → 5s 超时 SIGKILL,boot_id 比对防 pid 复用)。

e2e 日志:`.agent_runs/dual-workbench-slice-1-20260909/e2e-logs/`(app/runtime stdout/stderr,**不含 token**)。

## 4. 手动验证与截图

截图目录:`screenshots/`(`ide-window.png`、`sessions-window.png`,经 ReadMediaFile 目视确认)。

- `ide-window.png`:IDE 编码视图,Explorer + Welcome + 右侧 Chat 面板,上游 Workbench 布局完整。
- `sessions-window.png`:Sessions 窗口,左侧 Sessions 栏可见两个真实任务条目(`Design the dual workbench` / `Review the slice one gates`),右侧 Files 面板显示共享 workspace,中部为会话 composer。
- 已知噪声:首次启动上游 Copilot 登录弹窗与 "Make It Yours" 向导会遮挡窗口,截图前已通过 CDP 点击关闭;该弹窗为上游行为,非本切片改动。

**覆盖边界声明**:以下行为在单元测试层覆盖(Task 3–5 的 38 项聚焦测试),e2e 未逐项手动操作:空任务列表渲染、malformed 响应 fail-closed、Runtime 不可用时 typed error 呈现、descriptor 校验各拒绝分支(symlink/权限/uid/非 loopback)。

## 5. 衍生事实(如实登记)

1. 为运行 runtime,向项目 venv 安装了 `sqlglot`(api_server 的传递依赖,仓库依赖清单未声明)。属环境补齐,非代码变更。
2. 清理了 Task 2 遗留的 dev 实例进程(`Code - OSS Dev`),避免 e2e 误连旧实例。

## 6. Git 门禁

- `git status --short` / `git diff --check` 已核对:本提交仅含 Task 6 文件(lifecycle 模块、e2e 测试、patch 010 精简、verify.mjs、bridge 测试)与本验证记录;`apps/macos` Tauri 残留、根 `package-lock.json`、`apps/code-oss/extensions/`、`docs/` 未跟踪设计文档均**未纳入**。
- `docs/architecture/A-AGENT-OS-DUAL-WORKBENCH-ARCHITECTURE-SPEC-V2-2026-09-09.md` 按其文件头"Git 纪律"声明保持 **untracked,不提交**(优先于计划 Step 10 的 add 指令);spec 状态维持 `DESIGN_ONLY / SPECIFIED`,本切片状态不在 spec 内回写,避免越权改写设计文档。
- 提交后状态:**不 push、不 merge**,等待独立评审。

## 7. 独立评审(未完成,阻塞集成)

builder ≠ reviewer(`builder_id != reviewed_by`)。本记录不构成评审。Slice 1 可集成的前提是独立 reviewer 对 exact commit 重跑测试 + 编译,核验 bearer 不泄漏与 provider 只读,并出具 `APPROVE_SLICE_1`(P0=0/P1=0)。评审请求已写入 `messages.jsonl`(to: codex-primary)。

## 8. 显式非主张(保留边界)

本切片**不包含**:审批/自动化执行、多客户端写、后台常驻服务、Rust 迁移、发布物,以及任何形式的 autonomy 声称。对上游 Code-OSS 内核的改动面仍为 patch 010 的 4 个上游文件小 hunk + 1 个 sessions 入口接缝,零新增上游文件;全部新代码位于 overlay `src/vs/agentos/`。
