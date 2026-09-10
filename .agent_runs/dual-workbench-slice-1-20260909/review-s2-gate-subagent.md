# 独立评审报告 — Dual Workbench Slice 2 门禁材料

> Reviewer: kimi-reviewer-s2-gate(独立子代理,builder_id != reviewed_by 成立)
> Date: 2026-09-10T14:52:34Z
> Reviewed commits: `2bc1a89c`(GC/CP 草稿)、`4fa79d15`(S2 计划草稿),worktree `.worktrees/ide-ui`,分支 `codex/ide-ui`
> 审查对象:
> - `docs/product/GC-AGENT-OS-DUAL-WORKBENCH-S2-2026-09-10.md`
> - `docs/product/CP-AGENT-OS-DUAL-WORKBENCH-S2-2026-09-10.md`
> - `docs/superpowers/plans/2026-09-10-agent-os-dual-workbench-slice-2.md`
>
> 方法:不采信 builder 叙述,全部事实性 claim 逐条回源码核实。

---

## 1. 事实核实(逐条)

### 1.1 trajectory 路由与投影 —— ✅ 存在,但两处表述不精确(P2)

- `GET /v1/tasks/{task_id}/runs/{run_id}/trajectory` 真实存在于 `apps/api_server/server.py:528-539`,位于 `do_GET` 内,且带 `not parsed.query and not parsed.fragment` 限制。
- `project_task_trajectory` 真实存在于 `apps/api_server/app.py:1138`,行号准确。
- 不精确处①:该方法返回 `TrajectoryProjection`(manifest + steps + outcome_links + correction_links + trajectory_digest),CP 称"产出 EpisodeManifest/TrajectoryStep",是把容器的组成部分当成了返回类型。
- 不精确处②:CP 称 step 携带 `event_id`,实际字段名是 `source_event_id`(`packages/contracts/src/agent_os_contracts/trajectory.py:112`)。decoder 白名单若按 `event_id` 写字段名会直接 fail-closed。

### 1.2 TrajectoryStep / EpisodeManifest —— ✅ 存在

- `TrajectoryStep` 在 `contracts/.../trajectory.py:109`,`sequence: int = Field(ge=1)`(:111)、`source_event_id`(:112)、`event_type`、`event_digest`、`occurred_at` 齐全。
- `EpisodeManifest` 在 :120,含 `source_stream_last_sequence`(:126)——此字段对后述 seq 空洞问题至关重要,CP 未提及。

### 1.3 "事件表 sequence INTEGER NOT NULL UNIQUE" —— ❌ 引用错配(P1)

- CP 第 14 行称"事件持久层 `sequence` 为 `INTEGER NOT NULL UNIQUE`(`packages/os_core/src/agent_os_core/trajectory.py` 的 credit/事件表)"。
- 核实:`trajectory.py:603` 的 `sequence INTEGER NOT NULL UNIQUE` 属于 **`credit_assignments`(credit 账本表)**,同文件 :610 是 `credit_ledger_head`——该行号附近**没有事件表**。
- 真正的事件表是 `task_events`,在 `packages/os_core/src/agent_os_core/persistence.py:40`(SQLite:`sequence INTEGER NOT NULL`,`PRIMARY KEY (task_id, sequence)`)和 `postgres.py:56`(`UNIQUE(task_id, sequence)`)。
- 逐 task 的 seq 连续性并非由 schema UNIQUE 保证,而是由写入路径保证:`persistence.py:196-202` 在 append 时校验 `expected_sequence == COALESCE(MAX(sequence),0)`,不等即 `ConcurrentWriteError`。
- 结论:CP 的核心方向(seq 有序有据可查)成立,但引用的表、行号、保证机制全部指错。一份自称"均经源码核实"的 CP 出现这种错配,必须修正。

### 1.4 CP 的只读路由清单不完整 —— ❌ 重大遗漏(P0)

CP 第 10-13 行只列了 3 条 GET 路由。实际 `do_GET` 中 `/v1/tasks/` 前缀下还存在(server.py:619-695):

- `GET /v1/tasks/{task_id}`(catch-all,server.py:689)→ `app.py:2436 task_json`,载荷含 `goal`(含 statement)、`commitment`、`workflow`、`run`(含 run_id 与状态)、`expected_outcome`、`observed_outcome`、`approval`、`proposed_action`、`provider`(含 usage)、`workspace`、`artifacts`、**完整 decoded events 列表**、`domain_pack`;
- `GET /v1/tasks/{task_id}/events`(server.py:634,一次性 text/event-stream 全量导出);
- `GET /v1/tasks/{task_id}/workflow`、`/evidence`、`/recovery`、`/artifacts/{id}`。

后果有三:

1. **"详情来源"决策前提错误**:CP 第 22 行称"`/v1/tasks` 载荷若已含 statement/status/run_status/时间戳则直接用;缺字段时首选扩展该列表端点(contracts 变更)"。核实 `app.py:688-701`:`/v1/tasks` 列表载荷只有 `task_id/status/statement/run_status/sequence`,**无时间戳、无 run_id**。但详情根本不需要扩展列表端点——`GET /v1/tasks/{task_id}` 已存在且含全部所需字段。CP 在错误的路由清单上做了架构决策。
2. **run_id 获取路径完全未讨论**:trajectory 端点必须带 run_id,而 Slice 1 消费的 `/v1/tasks` 载荷不含 run_id。run_id 只能从 `task_json.run` 获得。计划 Task 2 的 `getTaskTrajectory(taskId, runId)` 签名没有交代 runId 来源。
3. **字段最小化决策缺席**:`task_json` 载荷远超只读详情所需——含 approval、proposed_action、provider usage、全量 decoded payload。若把它作为详情数据源,renderer 侧封闭解码必须显式字段白名单;这是安全相关决策,CP/计划均未提及。

### 1.5 seq 空洞 fail-closed 与 trajectory 投影语义直接矛盾 —— ❌ 阻塞级(P0)

这是本次审查最重要的一条。

- GC Acceptance 第 36 行:"乱序、seq 空洞、未知事件类型全拒";计划 Task 1 Step 2:"事件按 seq 严格递增校验,空洞即 fail-closed";In#2:"按 taskId 拉取有序事件(seq 连续)"。
- 核实 `TrajectoryProjector._select_events`(os_core/trajectory.py:259-274):投影从**逐 task** 的事件流中**过滤**出该 run 的子集(run 启动前的 setup 事件 + `correlation_id == run_id` 的事件 + 特定类型)。step 的 `sequence` 原样继承 task 流序号(:175 `sequence=event.sequence`)。
- 因此,只要一个 task 有过多个 run、或流中存在未被选中类型的事件,**同一 trajectory 内 step 的 sequence 出现空洞是常态而非异常**。"空洞即 fail-closed"意味着真实数据上详情页大面积不渲染——验收标准按现状**注定失败**(或倒逼实现者偷偷放宽校验)。
- spec §12 验收②⑤的"seq 连续/无 seq 空洞"针对的是**原始任务事件流**的 tail attach,不是按 run 过滤后的投影;计划把两者混淆了。
- 出路二选一,必须在门禁材料中写明:(a) decoder 改为"严格单调递增 + 用 `EpisodeManifest.source_stream_last_sequence` 校验尾部完整性 + 空洞以 gap 标注渲染";或 (b) 消费原始任务事件流(如 `/events` 或新端点)而非 trajectory 投影——但这会推翻 CP"优先复用 trajectory"的决策输入,需要重新论证。
- CP Risk #2 提到了"先用真实数据库样本核实连续是否是成立的不变量",方向正确但定性错了:这不是"需要采样核实的经验问题",而是**从源码即可确定不成立**(`_select_events` 是确定性过滤)。CP 自称"均经源码核实"却没有读到投影器本体。

### 1.6 Slice 1 既有资产 —— ✅ 全部核实通过

- 桥:`ALLOWED_GET_PATHS = ['/v1/tasks']` 唯一白名单(runtimeTaskCatalogMainService.ts:52);descriptor 中途变更拒绝(:154-156 `RUNTIME_DESCRIPTOR_CHANGED`);1 MiB 响应上限(:51 `RESPONSE_CAP_BYTES = 1_048_576`);bearer 只存于主进程 descriptor 链路(:13-15, :23);`fetchFrom` 已无任何残留(grep 全 overlay 无匹配)。
- 16 个写入口 typed-reject:provider 实现为 1 个共享 sync throw + 12 处 `Promise.reject`,测试(agent-os-sessions-provider.test.mjs:187-218)枚举 **4 sync + 12 async = 16** 个写入口逐一断言 typed error。CP 的"16 个写入口"属实。
- 三层身份证据(interactiveRuntimeLifecycle.ts:128-150):ps lstart 指纹 + descriptor pid+boot_id 重读 + bearer 认证 HTTP 探活,SIGKILL 前三通道独立证明、任一不可证即 fail-closed。与 c4d8023f 提交信息及 round-3 评审记录一致。
- patch 010 上游改动面恰好 5 个文件(app.ts、nativeHostMainService.ts、window.ts、sessions.desktop.main.ts、desktop.contribution.ts),无其他 patch 文件。
- Slice 1 审批链:e13684a2 记录 APPROVE_SLICE_1(c4d8023f,round-3,P0=0/P1=0),messages.jsonl 记账完整,含 reviewer 替换决策记录。

## 2. 验收可证伪性

- 大部分条目可客观判定(decoder 拒绝矩阵、401→typed stale、16 写入口不缩小、reload 存活、quit 有界终止、verify/compile 全绿)。
- **不可通过项**:GC Acceptance 的"seq 空洞全拒"——见 §1.5,该条按真实数据源注定失败,属于"无法证伪其反面"的坏验收(它恒为假)。P0。
- 轻微:U-DW-S2-1 的"完整陈述"未定义到字段级(建议改为"goal.statement 与 Runtime 返回逐字符一致")。P2。

## 3. 范围纪律 —— ✅ 守住,一处警戒

- 无写路径/审批卡/SSE/WS/多 workspace/后台保活/autonomy 声称;patch 010 上游面不扩大;bearer 不出主进程;builder ≠ reviewer;不 push/merge/release。均符合。
- 警戒项(非越界,但需显式):若详情数据源切到 `GET /v1/tasks/{task_id}`,其载荷含 approval/proposed_action/全量 payload——"只读"不等于"可投影",封闭解码白名单必须把这类字段排除在外,这在当前材料中没有位置。并入 §1.4 的 P0。

## 4. 计划可执行性

- **Python 侧工作量零覆盖**(P1,与 §1.4 联动):计划 4 个 Task 的 Files 全部是 TypeScript/测试文件。若 CP 的"扩展列表端点(contracts 变更)"分支被触发,没有任何 Task 覆盖 Python 合同变更、Python 测试与合同评审。鉴于 §1.4 证明已有现成详情端点,最可能的修法是显式关闭该分支;无论选哪条路,计划必须写明,不能留一个无归属的条件分支。
- **e2e 无 RED 步骤**(P1):Task 4 Step 1 在 Task 1-3 实现全部完成后才扩展 e2e 断言,这些断言从未红过,无法证明其 fail-first 有效。需在 Task 1 之前先写 e2e 断言骨架(对未实现行为红),或在 Task 4 增加变异验证(临时移除投影证明断言变红)。
- **run_id 来源未计划**(P1):见 §1.4(2)。
- 风险列表质量:4 条均为真风险(语义粒度、seq 空洞、大事件流、Slice 1 回归),非套话;但 Risk #2 的定性需按 §1.5 重写。
- 空态未计划(P2):空事件流时 `project` 抛 `EventStreamError("trajectory requires a non-empty task stream")`(trajectory.py:87-88),renderer 需要 typed 空态而非 fail-closed 不渲染,计划未覆盖。

## 5. 章程符合性(根 AGENTS.md)

- §5 Track 选择:声明 Product(Translational 成分),与"把 Runtime 已有真相投影进产品表面"的实际相符;Goal Card + Context Pack + CTO gate 三件套齐备。✅
- §7 硬边界:无伪实现迹象(均复用真实端点与 Slice 1 真实桥);失败先行原则已声明;只读/合同封闭解码方向正确。✅(但 §1.5 说明"失败先行"的断言内容本身写错了对象。)
- §13 流程:Goal Card → Context Pack → Plan → CTO gate → 独立评审的顺序正确;Slice 1 增量续用声明明确。✅
- §12 多agent纪律:builder_id != reviewed_by 在 GC Boundaries 中显式声明。✅
- RR-0024:全文无 autonomy 误用。✅

---

## 问题清单

| # | 级别 | 问题 |
|---|---|---|
| 1 | **P0** | "seq 空洞即 fail-closed"与 trajectory 投影真实语义矛盾(`_select_events` 按 run 过滤,空洞是常态),验收注定失败;须改为单调递增+`source_stream_last_sequence` 完整性校验+gap 标注,或改换数据源并重新论证 |
| 2 | **P0** | CP 只读路由清单不完整:漏 `GET /v1/tasks/{task_id}`(task_json)、`/events`、`/workflow`、`/evidence`、`/recovery`、`/artifacts`;"扩展列表端点"的详情决策建立在错误前提上;task_json 富载荷的字段最小化(approval/proposed_action/provider usage/decoded payload 不进 renderer)决策缺席 |
| 3 | **P0** | run_id 获取路径未说明:`/v1/tasks` 载荷无 run_id,trajectory 端点必须带 run_id,`getTaskTrajectory(taskId, runId)` 的 runId 来源无着落(应从 task_json.run 获取并纳入计划) |
| 4 | P1 | 事件表引用错配:`trajectory.py:603` 的 UNIQUE sequence 是 credit_assignments 表;真正事件表在 persistence.py:40/postgres.py:56,逐 task 连续由 append 的 expected_sequence 校验保证——CP 须修正引用与机制描述 |
| 5 | P1 | Python/contracts 工作量零覆盖:若保留 contracts 变更分支须新增对应 Task(合同+Python 测试+评审);若改用现有 task_json 须显式关闭该分支 |
| 6 | P1 | e2e 扩展无 RED 步骤:断言在实现之后编写,无法证明 fail-first;须前置断言骨架或加变异验证 |
| 7 | P2 | 字段名/类型不精确:TrajectoryStep 是 `source_event_id` 非 `event_id`;`project_task_trajectory` 返回 `TrajectoryProjection` 非直接 EpisodeManifest |
| 8 | P2 | 空事件流 EventStreamError 的 typed 空态处理未计划;"完整陈述"未定义到字段级 |

## 最终裁决

**REVISE_TO_SPEC**

理由:三份材料的流程位置、范围纪律、Slice 1 事实基础均扎实,但存在 3 个 P0——验收标准与真实数据源语义直接矛盾(§1.5)、架构决策建立在不完整的路由清单上(§1.4)、关键参数来源无着落(§1.4(2))——任何一个都会让开工后的实现者被迫在"通过验收"与"忠于数据"之间二选一。修订量不大(主要集中在 CP 路由清单重写 + GC/计划 seq 验收改写 + 详情数据源决策),修订后需复审。
