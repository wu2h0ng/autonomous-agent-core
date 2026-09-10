# Slice 3 门禁材料独立审查报告(builder ≠ reviewer)

- **Reviewer:** kimi-reviewer-s3-gate(独立子代理,非材料作者)
- **Date:** 2026-09-11 · Branch: codex/ide-ui · Worktree: `.worktrees/ide-ui`
- **Scope:** 仅审查 `docs/product/GC-AGENT-OS-DUAL-WORKBENCH-S3-2026-09-11.md` 与 `docs/product/CP-AGENT-OS-DUAL-WORKBENCH-S3-2026-09-11.md` 两份门禁材料;未修改任何被审材料或源码;本报告为唯一产出
- **参照:** `review-s2-final-subagent.md`(同目录)、spec `docs/architecture/A-AGENT-OS-DUAL-WORKBENCH-ARCHITECTURE-SPEC-V2-2026-09-09.md`

## 一、逐条事实核验(核实 / 不符 + 证据行号)

### A. 服务端审批端点与合同(CP "Observed state" 第 2-4 条)

| CP/GC 声明 | 核验结果 | 证据 |
|---|---|---|
| 路由 `POST /v1/tasks/{task_id}/approval`(`server.py:919-926`)→ `app.py:2371 record_approval`,返回全量 task_json | **核实** | `server.py:919-926` 形状一致;`app.py:2403` 返回 `tasks.record_approval(...)`;`server.py:925` 回 200 + task_json |
| body = `{action_digest?, disposition?, reason?}`;digest 提供时不等即拒 | **核实** | `app.py:2378-2383`(`payload.get("action_digest")`,提供且不等即 raise "approval payload does not bind the pending action");`disposition` 默认 APPROVE(:2384),非法值由 `ApprovalDisposition` 枚举构造抛错 |
| reason 去空白后必填 | **核实** | `app.py:2385-2389`(注意:有服务端默认文案 "Reviewed in Agent OS Task Workspace",仅当客户端显式传空/全空白时才拒;"必填"语义=非空字符串,UI 侧"必填理由"仍需自行强制) |
| actor 服务端绑定,客户端无法自报 | **核实** | `app.py:2396-2397`(`actor_id/actor_role` 取自 `self.principal`,payload 无此入口) |
| `ApprovalDecision` 合同(`authority.py:200-218`):role∈{PRINCIPAL, TENANT_ADMIN}、`expires_at > decided_at` 强制;实现 = decided_at + 10min | **核实** | `authority.py:200-218` 逐行一致;`app.py:2401` `timedelta(minutes=10)` |
| `task.approval` 数据源(`task_aggregate.py:391-406`) | **核实** | `task_aggregate.py:402-406`:ACTION_PROPOSED 清空、APPROVAL_RECORDED 置位;`app.py:2509` `"approval"` 字段引用一致 |
| `proposed_action` 投影(`app.py:2465-2470`)= ActionContract dump + 解码 arguments + `action_digest` | **核实** | `app.py:2455-2470` 逐行一致;`app.py:2512` 入 task_json |
| 进入 `WAITING_APPROVAL` 机制(`execution.py:555`),APPROVAL_REQUESTED 事件置位 | **核实** | `execution.py:543-557`:未批准 → append APPROVAL_REQUESTED → `update_run_status(..., WAITING_APPROVAL, event_type=APPROVAL_REQUESTED)` → 释放 lease 返回;`index.html:420` 附近确有演示 `node('approve','approval')`(workflow 函数体 :417-423);`NodeKind.APPROVAL` 分支存在(`execution.py:520`)——CP 称"枚举值待实现期核实"属过度保守,证据本可在 CP 阶段闭合(见 P2-3) |
| spec §7.2 全量协议(protocolVersion 2.0 / clientOperationId / runId+attempt / expectedPolicyVersion / expectedEventSequence / REVISE / ApprovalReceipt)= SPECIFIED 未实现,现有 HTTP 端点不含这些字段 | **核实** | spec :479-496 逐项在列;`app.py:2371-2403` 确无这些字段;REVISE 在枚举中存在(`authority.py:41`)但 HTTP 路径无任何 REVISE 特判 |
| spec §12 验收③原文"审批卡 digest 与 ActionReceipt digest 一致";④依赖停止语义 | **核实** | spec :766 原文一致;`ActionReceipt.action_digest` 存在(`authority.py:267-270`),③ 的 oracle 在数据上可行 |
| HTTP 侧已有 pause/resume/cancel/correction 端点(`server.py:954-974`) | **核实** | `server.py:963-982` 四个操作 + correction/resume(:951-962) |
| Slice 2 白名单已剥离 `approval`/`proposed_action`,e2e 已断言不泄漏 | **核实** | `runtimeTaskCatalog.ts:121-190` 输出投影仅 7 键;`runtime-task-detail-contract.test.mjs:55` 禁键清单含 `approval`/`proposed_action`;`dual-workbench-slice-2.test.mjs:457` e2e 禁键清单**现已包含** `approval`/`proposed_action`(S2 评审 O-4b/O-6 已闭环);另确认 S2 P1-1 已闭环:`KNOWN_TASK_DETAIL_KEYS`(:114-130)对未知顶层键 fail-closed |

### B. 状态门与防重放(CP 第 3-4 条、GC Acceptance 服务端兜底条)——**两处不符,构成 P0**

1. **`task_service.py:938-948` 引用错位(不符)。** 该行区间的精确状态门("APPROVE requires the exact WAITING_APPROVAL Run state" / "REJECT requires a pending WAITING_APPROVAL or PAUSED Run")位于 **`record_or_reuse_session_approval`**(:921 起),其唯一调用方是 agent loop 会话路径(`agent_loop.py:599`),**不是** HTTP 审批路径。HTTP 路径实际调用 `TaskService.record_approval`(:2206-2243),其状态门是**条件的**:仅当 `pending.approval_requirement == "external_exact"` 才要求 `WAITING_APPROVAL`(:2218-2227);而 workflow 工具节点产生的 ActionContract 走 `_build_action`(`execution.py:1601-1624`)→ `build_action` 默认 `approval_requirement="policy"`(`action_pipeline.py:68,96`)。**即:对本切片实际数据流(workflow approval 节点),"APPROVE 要求精确 WAITING_APPROVAL" 在记录时刻不是服务端强制不变式**;对 `policy` 要求的 action,PAUSED 状态下 APPROVE 也不会被该门拒绝。GC Acceptance 原样复述了这条错位引用。间接保护确实存在(状态漂移后 `pending_action` 返回 None → :2216-2217 拒绝),但与材料描述的机制不同。

2. **"重复审批拒绝"与"天然防重放"声明超出实际行为(不符)。** `pending_action`(:2245-2301)的 `APPROVAL_RECORDED` 防重放守卫**只存在于非 WAITING_APPROVAL 分支**(:2252-2264);WAITING 分支(:2265-2301)只守卫 `RUN_PLAN_REBOUND` 与"审批请求后的新 ACTION_PROPOSED"。而 `record_approval`(HTTP 路径)记录 `APPROVAL_RECORDED` 后**不改变 run 状态**(`task_aggregate.py:402-406` 仅置 approval 字段),`app.record_approval` 也无重复检查。推演结论:**第一次审批记录后、run 被恢复前,第二次 POST approval(digest 仍匹配)会再记一条 APPROVAL_RECORDED**;恢复执行时 `execution.py:527-542` 取 `aggregate.approval`(最后一条)——实际是 **last-write-wins 静默覆盖**,而非"后到者状态校验失败"(CP Risks 第 3 条的收敛机制描述不成立)。Python 现有测试无任何重复审批用例(grep 全 tests/ 仅 `test_spine0_golden_path.py:182` 一次审批)。GC Acceptance 把"重复审批拒绝"列为"不新增服务端代码、以现有行为断言"——该断言若写成失败先行测试将**持续红**,与"Python 零变更"立场直接冲突。

3. **审批后 run 恢复执行路径在材料中整体缺席(遗漏,升级为 P0)。** `record_approval` 只追加事件,不触发恢复;daemon 是纯 HTTP 服务(`__main__.py:99` `serve(...)`,无后台 worker);既有黄金路径测试的范式就是**审批后显式第二次 `run_task`**(`test_spine0_golden_path.py:182-187`)。恢复入口 = 再次 `POST /v1/tasks/{id}/run`(`server.py:870-900` → `app.py:1480 run_task` → `RunCoordinator.run` 的 `resume_states` 含 `WAITING_APPROVAL`,`execution.py:301-316` → RUN_RESUMED → approval 节点复核 digest 通过才继续)。且恢复时 `run_task` 要求重传 `configuration_snapshot_id`(`app.py:1517-1527` 否则 `TaskConfigurationNotBound`)——该 id 不在现有白名单投影内。GC User result 承诺"任务运行相应继续或终止"、Acceptance 要求 e2e "approve → run 继续至终态",但声明的桥写面只有审批一条;材料全程未提恢复由谁触发。e2e 以直接 HTTP 重发 /run 作环境驱动是可行且符合 Slice 2 先例(种子数据均直接 HTTP),但**必须在材料中显式声明**,否则 User result 构成过度承诺、且与"单一 POST allowlist 条目"边界相互矛盾。

### C. 桥现状(CP "Observed state" 第 1 条与 Decision inputs)——两处小误

- **"GET allowlist 两条路径形态"不符**:实际三条(`runtimeTaskCatalogMainService.ts:59-63`:/v1/tasks、/v1/tasks/{id}、/v1/tasks/{id}/runs/{id}/trajectory)。(P2)
- **"16 个写入口拒绝集合"数目不可溯源**:现有拒绝证据为 channel default 抛错 + `cancelRun` 未知命令用例(`runtime-task-bridge.test.mjs:319`)+ e2e 5 个写控件 needle + provider typed-reject 集合,未见"16"的出处。(P2)
- GET-only 守卫(:193-196)、descriptor 双重读取防中途置换(:200-209)、401→`RUNTIME_DESCRIPTOR_STALE`(:224-226)、5s 超时、1 MiB 上限均核实存在,GC/CP 的继承声明成立。
- **未被告知的现状**:非 401 的非 2xx 一律塌缩为 `RUNTIME_UNREACHABLE`(:227-229),服务端 400 body 只有自由文本 `{"error": str}`(`server.py:268-269`,default=400;`InvalidTransitionError` 是 `RuntimeError` 子类 `errors.py:20`,落 default 400)。U-DW-S3-1 承诺"过期、状态漂移或 digest 不符都以明确错误呈现",这要求写路径新增 typed error 映射,材料未登记。(P1)

## 二、范围与边界审查

- **§12 ④ 推迟到 Slice 4:可接受。** ③(审批 digest 一致性)与 ④(停止后无 permit 漏执行)相互独立,④ 依赖 `correction.request`/停止语义这一不同的写簇(spec :511-521),切分方向与 Slice 1/2 的增量收口一致。GC 在 Boundaries 显式登记,CP 注明回收条件,符合"声明与实现状态分离"。附带提示:spec §7.4 旁路测试①(伪造 role=WORKER → 合同拒绝)已被 GC Acceptance 的 role 校验条部分覆盖,Slice 4 收口时注意去重引用。
- **第一个写命令的安全纪律:方向充分,细节有缺口。** 单一 IPC/单一 allowlist 条目/typed 载荷/失败先行/拒绝集合回归的框架正确;缺口即 P0-3(恢复路径未声明)、P1(4xx typed error 映射未登记)。
- **REVISE disposition:** GC 排除 REVISE UI 合理,但 REVISE 是服务端合法枚举(`authority.py:41`),桥/UI 不排除时伪造 REVISE 会被**正常记录**(恢复时不批准、重新请求审批,无执行风险但会污染卡面收敛逻辑)。失败先行测试集应显式处置 REVISE(桥侧白名单 disposition 或在断言中说明服务端容忍语义)。(P2)
- **审批超时自动 deny 配置化排除、always-allow/CapabilityGrant 排除:** 与 spec §7.2 范围化放行"只能经 CapabilityGrant 审批产生"的红线一致,排除声明忠实。

## 三、可证伪性审查

- **审批卡渲染逐字段断言 + 缺字段 fail-closed:可证伪**,非伪验收(缺任一键不渲染卡的断言结构能咬住投影路径)。
- **TOCTOU 同源("UI 不存在 digest 计算"+ 逐字节一致):可证伪**,静态扫描 + 运行时断言双重咬合。
- **"过期时间"字段的验收写法内部不一致:** GC Acceptance 把"过期时间"列入逐项断言清单,CP 却已诚实登记"预渲染无数据源、以说明文案替代"。两条材料并读时可理解,但 Acceptance 单读会诱导实现者伪造一个时间字段。应改写为"过期时间位呈现说明文案;审批后呈现真实 expires_at"的可断言形式。(P1)
- **policy_version 映射缺口:** spec §7.3(:509)要求卡面含 policy_version,数据源**存在**(`proposed_action.policy_version`,`action_pipeline.py:90` 写入),但 CP Decision inputs 的白名单枚举遗漏 policy_version,却列入 spec §7.3 未要求的 `side_effect_guarantee`。GC Acceptance 的"policy 版本说明"失去 CP 侧的字段承载。须补齐映射表。(P1)
- **服务端兜底复核条整体可证伪**,但须按本报告 P0-1/P0-2 修正引用与预期行为后才可执行。

## 四、治理合规

- GC Status = `DRAFT / PENDING_CTO_GATE / NOT_AUTHORIZED`,计划明确"CTO gate 通过后起草" ✓ 符合根 AGENTS.md 中高风险流。
- `builder_id != reviewed_by` 声明在案;本审查由独立身份执行 ✓。
- 无 push/merge/release/autonomy 声称;Python/contracts 零变更为默认立场且给出升级路径 ✓。
- 无服务端暗改迹象;材料对 §7.2 协议缺口、过期时间缺口的自我登记是诚实的 ✓。
- Track 标注(Product + Translational 成分)与内容相符。

## 五、问题清单

**P0(阻断门禁,必须改):**

- **P0-1 状态门引用错位与保证过誉**:`task_service.py:938-948` 是 agent-loop 会话路径(`record_or_reuse_session_approval`)的门,不是 HTTP `record_approval`(:2206-2243)路径的门;后者对本切片数据流(`approval_requirement="policy"`)只在 `pending_action` 为 None 时间接拒绝。GC Acceptance 与 CP Observed state 须改写为真实机制,或显式把目标 action 的 `approval_requirement` 问题登记为风险。
- **P0-2 "重复审批拒绝"断言不存在的服务端行为**:HTTP 路径在 run 恢复前可重复记录审批(last-write-wins);该 Acceptance 条与"Python 零变更"冲突。二选一:删除/降级该断言并登记为已知缺口,或把服务端去重显式升级为独立 Task(变更立场需走 CP 自定的升级流程)。
- **P0-3 审批后恢复执行路径未声明**:批准不会自动恢复 run;恢复 = 再次 POST /run(且需 configuration_snapshot_id,不在现有投影内)。须显式选择:(a) e2e 环境侧直接 HTTP 恢复并相应改写 User result 措辞,或 (b) 扩大桥写面(则"单一 IPC/单一 allowlist 条目"表述需改)。当前文本下 Acceptance e2e "approve → run 继续至终态"无可执行的驱动路径。

**P1(应改):**

- **P1-1 多窗口竞态收敛机制描述不实**:CP Risks 称"后到者状态校验失败"收敛;实际 APPROVAL_RECORDED 不改状态,后到者**成功**并在恢复时静默覆盖。GC 已把多窗口竞态排除出范围,这没问题;但 CP 的机制描述必须改成"无服务端保护、已知缺口、范围外"的如实表述。
- **P1-2 写路径 typed error 映射未登记**:桥把非 401 错误塌缩为 `RUNTIME_UNREACHABLE`,服务端 400 只有自由文本;U-DW-S3-1 的分类错误呈现承诺需要新增映射设计。
- **P1-3 §7.3 字段映射表不完整**:CP 白名单遗漏 policy_version(数据源存在),多列 side_effect_guarantee;GC Acceptance 的"过期时间"断言目标需改写为说明文案+审批后真实 expires_at。

**P2(建议):**

- **P2-1** CP "GET allowlist 两条路径形态" → 实为三条(:59-63)。
- **P2-2** CP "16 个写入口拒绝集合"数目无出处,建议改为可溯源表述。
- **P2-3** "approval 节点枚举值待实现期核实"本可在 CP 阶段闭合(`execution.py:520`、`index.html:417-423`、`test_spine0_golden_path.py` 的 `approve` 节点均为现存证据)。
- **P2-4** REVISE 为服务端合法枚举,失败先行测试集应显式处置而非依赖"伪造 disposition 即报错"的笼统表述。

## 总体结论:**REVISE_TO_SPEC**

材料整体形态、边界意识与自我登记纪律(§7.2 协议缺口、过期时间缺口、字段面扩张风险)是好的;事实核验中 A 组(端点/合同/投影/spec 引用/Slice 2 剥离)全部准确。但 B 组三项(P0-1/2/3)触及本切片的核心安全叙事:**状态门与防重放的保证被归错了方法、重复审批拒绝是未实现的断言、审批到继续执行的事件链没有声明驱动者**。这些是门禁材料必须如实修正的事实层错误,而非实现期再发现的问题。修正 P0 三项与 P1 三项后可复审;治理合规与范围切分(④→Slice 4)本身无需推翻。


---

# 复审 Round 2(2026-09-11,builder 修订后)

- **Reviewer:** kimi-reviewer-s3-gate(同一独立身份,非 builder)
- **对象:** 同路径重写的 GC/CP(REVISED 版);逐项回到源码复核,未修改被审材料

## 修订落地核验(对照 Round 1 问题清单)

| Round 1 问题 | 修订核验结果 | 证据 |
|---|---|---|
| P0-1 状态门引用错位 | **已纠正,准确** | CP :14 现为 `task_service.py:2206-2243` 真实语义:pending 存在(:2215-2217)、task/run 绑定(:2228-2231)、digest 绑定(:2232)、`external_exact`-only 状态门(:2218-2227)——逐条与源码一致;GC :31/:46 同步改写,Acceptance 明确"不再断言记录时刻精确状态门" |
| P0-2 重复审批断言 | **已纠正,准确** | GC :46 显式删除"重复审批拒绝";CP :16 对 last-write-wins 的描述与 `pending_action` WAITING 分支(:2265-2301,无 APPROVAL_RECORDED 守卫)+ `task_aggregate.py:402-406` 完全一致 |
| P0-3 恢复路径缺席 | **实质已修复;新增引用有定位错误(见 N-1)** | 两条写命令结构、`index.html:459-467` `reviewAction` 两段式配方(POST /approval → APPROVE 时 `runTask()`)、恢复时 approval 节点复核(`execution.py:537-544` 放行 / :545-557 重新停泊)、REJECT 不 resume 保持停泊——全部经源码证实为真 |
| P1-1 竞态收敛描述 | **已纠正** | CP :16/:42/:49 现为 last-write-wins 如实描述 + 卡面跟随最新记录;GC :32 登记服务端加固推迟 |
| P1-2 typed error 映射 | **已落实为验收条** | GC :44 失败先行写映射表;CP :23/:53 登记塌缩现状,且"400/409"表述与实际状态码分布一致(ValueError→400 `server.py:268-269`;`TaskConfigurationNotBound`→409 `server.py:241`) |
| P1-3 §7.3 字段映射表 | **已纠正,数据源真实** | `run.policy_version` 确为真实字段(`runtime.py:311` AgentRun 模型字段,`task_service.py:403` 构造时自 workflow 写入,task_json 经 model_dump 带出);过期时间改说明文案 + 审批后真实 expires_at,与端点语义(`app.py:2401`)一致 |
| P2-1 allowlist 条数 | **已纠正** | CP :10 三条,与 :59-63 一致 |
| P2-2 "16 写入口" | **已纠正** | CP :47 改为 Slice 1 plan 口径、数量以 provider 测试实际枚举为准 |
| P2-3 approval 枚举值 | **已闭合,准确** | `workflow.py:29` `APPROVAL = "approval"` 属实 |
| P2-4 REVISE 处置 | **已落实** | GC :34/:44 显式拒绝 REVISE 经 UI 通道,与"REVISE 为服务端合法枚举(`authority.py:41`)"的事实陈述一致 |
| (附带)CP :20 `session_projection.py:214` APPROVAL_RECORDED 载荷 exact 单键 | **核实** | :213-214 `if set(payload) != {"approval"}` 逐字一致 |

## 复审新发现问题

**P0:0 项。**

**P1(应改,须在材料定稿/计划起草前修正,均为定位错误而非行为虚假):**

- **N-1 恢复路径三处引用定位错误(同一新声明内):**
  - GC :30「`app.py:345 start_run` 经 `server.py:905-926`」——`app.py:345` 是构造器区域代码(`start_run` 在 `app.py:1338`;恢复入口 `run_task` 在 `app.py:1480`);`server.py:905-926` 是 `/start`+`/approval` 路由段,`/run` 路由实际在 `server.py:870-901`;
  - CP :17「`server.py:905-918` … `task_service.py:367-372`」——`:905-918` 是 `/start` 路由;`task_service.py:367-372` 是 `start_run` 的**启动时刻**快照核对;恢复时刻的 snapshot 强制在 `app.py:1517-1527`(`TaskConfigurationNotBound`,409);
  - CP 资产表 :63「恢复端点 `server.py:905-918`、`task_service.py:345-433`」——同样指向 start 路径;恢复执行重入点在 `execution.py:301-316`(resume_states 含 WAITING_APPROVAL → RUN_RESUMED)。
  - 说明:行为声明本身全部属实(我已由 `app.py:1517-1527`、`execution.py:301-316`、`index.html:459-467` 独立证实),错的是行号落点;但本门禁的纪律就是"每条声称有源码出处",计划将从这些指针起草,必须改正。

**P2(建议/观察项,不阻断):**

- **N-2** `POST /run` 比 `/approval` 权力更大:服务端会从 body pop `recover_stale_lease` 并把其余 body 作为 workflow `inputs` 传入执行上下文(`server.py:871-899` → `app.py:1480`)。`resumeTaskRun({taskId, configurationSnapshotId})` 的 typed 载荷正确地排除了二者,但材料未显式声明该排除;建议 decoder/载荷测试断言 `inputs`/`recover_stale_lease` 永不由桥发出。
- **N-3** resume 路径要求 provider 已配置(`app.py:1510-1513`),e2e 须先配置 stub provider(Slice 2 配方已满足);实现期注意失败先行的顺序。
- **N-4** CP :10 GET-only 守卫标 `:193-195`,实际语句跨 `:193-196`;无伤大雅,顺手改。

## 可证伪性与一致性复核(两条写命令)

- `decideTaskApproval` 失败先行集(伪造 disposition 含 REVISE/空 reason/错 digest/非 WAITING_APPROVAL)每条都有明确服务端或 UI 侧拒绝点,可变红 ✓;`resumeTaskRun` 的"缺/错 configuration_snapshot_id → typed error"有真实服务端行为支撑(409)✓;两条命令各自独立可证伪,无纠缠断言。
- "GET-only 守卫开口为方法+路径双维白名单"与 `runtimeTaskCatalogMainService.ts:193-198` 现状(先方法检查后路径检查)结构一致,表述忠实 ✓。
- 三段 digest 一致 oracle(卡面 == APPROVAL_RECORDED == ACTION_RECEIPT_RECORDED)数据链完整:`proposed_action.action_digest`(`app.py:2469`)→ `ApprovalDecision.action_digest`(`app.py:2395`)→ `ActionReceipt.action_digest`(`authority.py:270`)✓。
- REJECT 语义与代码一致:disposition≠APPROVE → 恢复时重新停泊(:545-557),不 resume 则永远停泊 ✓;GC 把"终止/取消"正确归入 Slice 4,无过度承诺。
- User result 措辞已随两条命令改写("批准路径在审批后恢复运行"),与产品面能力一致,Round 1 的过度承诺已消除 ✓。

## Round 2 裁决:**APPROVE_GATE_MATERIALS**(带 1 个 P1 前置条件)

Round 1 的 P0-1/P0-2/P0-3 在**实质**上全部修复且修复声明经我逐项源码复核为真;P1/P2 全部闭环;两条写命令的验收各自可证伪;治理合规维持(Status=DRAFT/PENDING_CTO_GATE、builder≠reviewer、无 push/release/autonomy 声称)。唯一遗留 N-1 是修订新增段落的行号定位错误——行为声明真实、不改设计,但出处纪律要求改正。

**前置条件:N-1 的三处行号必须在材料中改正(GC :30、CP :17、CP 资产表 :63)后方可提交 CTO gate;此为文档内订正,不需要新一轮完整复审,builder 改完在同一文件标注即可。**
