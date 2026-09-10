# Slice 2 独立评审报告（builder ≠ reviewer）

- **Reviewer:** 独立子代理（非 builder）
- **Date:** 2026-09-11 · Branch: codex/ide-ui · HEAD: 01d4d97e
- **Scope:** 437a6463 / 2ce7f289 / 538f37bc / 01d4d97e（`git diff e13684a2..HEAD -- apps/code-oss` 已核实变更集边界）
- **纪律:** 未改任何源码；本报告为唯一产出

## 复跑记录（reviewer 亲跑，非引用 builder 声明）

| 命令 | 结果 |
|------|------|
| `node scripts/verify.mjs`（apps/code-oss） | 绿，7 个聚焦测试文件共 62/62 pass |
| `node --test tests/runtime-task-bridge.test.mjs` | 绿，19/19 |
| `node --test tests/agent-os-sessions-provider.test.mjs` | 绿，14/14 |
| `node --test tests/runtime-task-detail-contract.test.mjs` | 绿，7/7 |
| `node --test tests/dual-workbench-slice-2.test.mjs`（真实 daemon + stub provider + 双窗口 e2e） | 绿（12.7s；ground truth: 20 steps, TASK_CREATED→RUN_FAILED） |
| `node --test tests/dual-workbench-slice-1.test.mjs`（Slice 1 回归） | 绿（11.5s） |

另做的只读核对：Python 冻结合同 `packages/contracts/src/agent_os_contracts/runtime.py:50-92` 的 42 个 TaskEventType 与 TS 白名单脚本比对 0 差异；`trajectory.py` 的 TrajectoryProjection/EpisodeManifest/TrajectoryStep 字段集与解码器三层 exact-keys 清单逐字段一致；三个真实样本 fixture 扫描无 bearer/token/URL/本地路径/私钥（`task-detail.real.json:85` 的 "provider-api-key" 仅为 domain pack 的 credential_classes 枚举标签，非密钥）。

---

## 要点 1：封闭性 — verdict: APPROVE（带 1 个 P1）

**decodeTaskDetail（runtimeTaskCatalog.ts:108-157）**：输出由新对象字面量构造，仅读取 `task_id/status/goal.statement/run.{run_id,status,created_at}/sequence` 七个白名单键；`approval/proposed_action/provider/events` 等富字段**在任何输入下都不可能出现在输出**——封闭性由构造保证，而非靠运行时检查。合同测试断言输出键集精确等于白名单且 wire 中无禁用键（runtime-task-detail-contract.test.mjs 'detail decoder projects only the whitelist'），变异推演：若解码器直通 payload，deepEqual 与禁用键断言立即红。

**decodeTaskTrajectory（runtimeTaskCatalog.ts:229-295）**：三层 exact-keys（root :234、manifest :241、step :267）+ schema_version 钉死 "1.0" + 42 事件类型白名单（:191-205，与 Python 冻结合零差异）+ 序列严格递增且 ≤ source_stream_last_sequence（:280-285）。逐项推演未发现洞：root/manifest/step 任一多余键（如 `bearer_token`）即拒；乱序、重复、越界、seq=0 均拒；gap 以 `gapBefore` 保留而非拒绝，符合计划语义。manifest 中未被消费的字段（tenant_id 等）只做键校验不做类型校验——它们不进入输出，无风险。

**P1-1（应修，非阻断）**：计划 Task 1 Step 1 字面要求"多余未知顶层字段按封闭约定拒绝"，但 decodeTaskDetail 只做投影、不拒绝未知顶层字段（对比 trajectory 解码器的 exact-keys）。安全不变式（富字段不出输出）由构造完整保证，缺失的只是**合同漂移报警**（服务端新增顶层敏感字段会被静默忽略而非 fail-closed 报警）。建议二选一关闭：给 detail 解码器补 exact-keys 顶层校验，或修订计划条文并注明理由。须在 Slice 3 门禁前关闭。

## 要点 2：桥安全 — verdict: APPROVE

- **assertSafeRouteSegment（runtimeTaskCatalogMainService.ts:69-79）**：字符类 `[A-Za-z0-9:._-]` 排除 `/`、`\`、`%`、`?`、`#`、`&`、空白与控制字符；长度钉死 1-256；显式拒 `.`/`..`；非字符串拒绝。**编码绕过不可能**——`%` 本身不在允许字符集，`%2e%2e`/`%2F` 在校验阶段即拒（桥测试 'unsafe task and run ids' 含 `task%2Fadmin` 用例，且断言 server 零命中）。
- **raw segment 拼接（commit 01d4d97e）**：取消 encodeURIComponent 后**未引入新注入面**——合法字符集中不存在任何需要编码或能改变路由形状的字符；修复理由（Python 路由不 percent-decode，`:` 编为 `%3A` 导致 404）与 e2e 证据一致，代码注释如实。
- **GET allowlist 模板（:59-67）**：三条锚定正则精确对应 catalog/detail/trajectory 路由；路径只由已校验段构造，`[^/]+` 不可能吞入额外段；即便构造路径匹配 detail 模板，响应仍被 decodeTaskDetail 封闭投影兜底，无越权数据面。两条新路由继承 descriptor 身份 / 401→typed stale / 5s 超时 / 1 MiB 上限，桥测试 'detail and trajectory reads inherit the descriptor and response guards' 逐项断言（含 descriptor 中途置换拒绝）。
- **观察项 O-2**：safe-segment 允许 `:`，与 runtime 的 `:commit` 动作后缀约定共处同一字符空间；`request()` 的 GET-only 守卫（:193-195）使动作端点（均为 POST）当前不可达，故无害，但若未来放行任何非 GET 方法需重新评估此交集。

## 要点 3：只读不变式 — verdict: APPROVE

- **IPC 表面恰好 3 个读命令**（runtimeTaskCatalogChannel.ts:32-50）：`listTasks/getTaskDetail/getTaskTrajectory`，default 抛错，`listen()` 抛错；参数逐个 typed 校验（非字符串即拒），未知命令（`cancelRun`）测试拒绝。channel 只返回解码投影，descriptor 字节与 bearer 不出主进程。
- **content provider 绝无写路径**（agentOSTaskContentProvider.ts:141-186）：仅实现 `provideChatSessionContent`，**requestHandler 缺席**（provider 测试断言 `session.requestHandler === undefined`），`isReadOnly` 钉死 `constObservable(true)`（:176）；sessions provider 的写入口 typed-reject 集合在 commit 3/4 中未被触碰（`git show` 证实这两个 commit 对 agentOSSessionsProvider.ts 只有新增 reportContentError 与状态映射修改）。
- **DRAFT→InProgress 修正（agentOSSessionsProvider.ts:52-58）合理**：上游把 Untitled 视为本地未发送草稿并打开可交互 new-chat composer——对 runtime 拥有的 DRAFT 任务构成写面；映射到 InProgress 是**收紧**只读不变式，代码注释与 commit message 理由充分。Slice 1 语义未破坏：Slice 1 e2e 我复跑绿；DRAFT 任务在列表仍投影为活跃会话，仅状态标签变化。
- **观察项 O-3**：该修正改动了 Slice 1 已批准的映射且未走新门禁；属于 e2e 发现的真实缺陷修复、方向收紧、证据完整，评审接受，但建议在下一次计划修订中补记此映射的当前语义以防漂移。

## 要点 4：测试有效性 — verdict: APPROVE

变异推演（只读心算，未改码）：

| 变异 | 会变红的测试 |
|------|-------------|
| decodeTaskDetail 直通/置空 | 合同测试 deepEqual + 禁用键 wire 断言；桥测试 forbidden-key 断言 |
| assertSafeRouteSegment 被绕过 | 'unsafe task and run ids are rejected before any HTTP request'（9 个坏 id × 3 入口 + 编码斜杠 + server 零命中） |
| 转录渲染循环置空 | e2e 'transcript renders the trajectory in order'：`seqCount !== stepSequences.length` 超时变红（builder 已实证红→绿，我核对断言结构确实咬住渲染路径） |
| gap 标注被删除 | provider 测试断言 3 条响应（2 step + 1 gap）与 gap 文案 |
| 标签白名单漂移/缺键 | transcript 抛错 + 'the transcript label whitelist totals the frozen event-type contract'（42 计数） |

e2e 断言覆盖：seq 计数等于 ground truth、首事件类型在末事件类型之前、页面无富字段键、bearer 在 DOM/storage/console 三处缺席（双 renderer）、5 个写控件 needle 全缺席、reload 后 runtime 存活且标签复现、application quit 有界终止 runtime。

- **观察项 O-4a**：e2e 顺序断言只验"首在末前"，中间乱序不可见；由解码器严格递增校验兜底，可接受。
- **观察项 O-4b**：e2e 富字段禁用清单（dual-workbench-slice-2.test.mjs:457）缺 `approval`；该键的缺席由解码器/桥单测覆盖，但 e2e 层面的如实口径见要点 6。

## 要点 5：计划符合性 — verdict: APPROVE

- `git diff e13684a2..HEAD --stat` 核实：变更全部位于 `apps/code-oss/`（overlay-src、tests、fixtures、scripts/verify.mjs）、`docs/`（计划/GC/CP/CURRENT_STATE）、`.agent_runs/`；**无 packages/（Python/contracts）变更**；**无上游新文件**（新文件均在 overlay-src 或 tests）；patch 集合零变更，patch 面未扩大。
- In 四项全部落地（详情白名单消费、trajectory 转录+gap 标注、Sessions 交互、e2e 扩展）；Out 项（SSE/写路径/审批卡/IDE 联动/Python 变更）均未出现。
- fixture 无敏感信息（见复跑记录）；真实样本仅含 e2e 租户/工作区标识与枚举标签。

## 要点 6：诚实性 — verdict: APPROVE（1 个轻微夸大）

- verification-slice-2.md 的量化声明全部经我复跑证实：bridge 19/19 ✓、provider 14/14 ✓、verify.mjs 7 文件全绿 ✓、slice-2 e2e 绿且 ground truth（20 steps、TASK_CREATED→RUN_FAILED）一致 ✓、slice-1 e2e 回归绿 ✓。
- gap 仅单测覆盖在验证报告 §"Unit-Only Coverage" 与 e2e 文件头（:16-18）**双处如实标注** ✓；e2e 发现的两个真实缺陷及修复理由记录完整 ✓。
- **观察项 O-6**：验证报告 line 23 称 e2e 断言"页面/载荷无 approval/..."，但 e2e 禁用键清单实际不含 `approval`（见 O-4b）——属轻微夸大；approval 的桥侧不泄漏有单测实证，不影响结论，建议修订该句口径。
- 两项声明我未独立复跑：`npm run compile 0 errors`（verify.mjs 不含编译步骤；结构测试与 e2e 运行间接佐证）与 Oracle teeth 变异实证（纪律不允许 reviewer 改动产物做变异；断言结构与声明一致，采信）。

---

## 总体结论：**APPROVE_SLICE_2**

- **P0（阻断）：0 项。**
- **P1（应修，须在 Slice 3 门禁前关闭）：**
  - P1-1：decodeTaskDetail 未按计划在顶层拒绝未知多余字段（runtimeTaskCatalog.ts:108-157 vs 计划 Task 1 Step 1）；补 exact-keys 校验或修订计划条文。
- **观察项（不阻断）：**
  - O-2：safe-segment 的 `:` 与 runtime `:action` 后缀约定同字符空间，GET-only 守卫下无害，未来放行非 GET 需重估。
  - O-3：DRAFT 映射修正改了 Slice 1 已批准语义未走新门禁，建议计划修订中补记。
  - O-4a/O-4b：e2e 顺序断言仅首尾、禁用键清单缺 `approval`（均有单测兜底）。
  - O-6：验证报告 line 23 对 e2e 覆盖范围的轻微口径夸大。

四个 commit 的范围、封闭性、桥安全、只读不变式、测试咬合度与验证报告的真实性均通过独立核查与亲跑复跑；Slice 2 满足收口条件。
