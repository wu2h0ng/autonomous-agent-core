# 独立评审报告(round 2)— Dual Workbench Slice 2 门禁材料复审

> Reviewer: kimi-reviewer-s2-gate(builder_id != reviewed_by 保持)
> Date: 2026-09-10T15:20:00Z
> Reviewed commit: `e213389c`(docs(agentos): revise slice two gate materials after independent review)
> 复审范围:round-1 报告(review-s2-gate-subagent.md)的 3 个 P0 + 3 个 P1 是否真正关闭。方法不变:不采信 builder 自述,逐条回源码与修订后文档核实。

---

## P0 逐项复核

### P0-1:seq 空洞 fail-closed 与 trajectory 投影语义矛盾 —— ✅ 关闭

- GC Acceptance(:36)已改为:"乱序/非单调 sequence、`source_stream_last_sequence` 与事件流不一致、未知事件类型全拒;**seq gap 不是错误,必须显式标注**",并注明"trajectory 按 run 过滤,gap 是常态"。
- 计划 Task 1 Step 1(:46)、In#2(:31)、GC First slice(:21)、CP :17 全部一致改写;原文档中"空洞即 fail-closed"的表述已无残留。
- 与源码核对一致:`_select_events`(os_core/trajectory.py:259-274)按 run 过滤、step 继承逐 task 序号(:175),gap 为常态;`EpisodeManifest.source_stream_last_sequence`(contracts trajectory.py:126)确为投影自带的完整性锚点,修订方案用的是真实存在的字段。

### P0-2:路由清单不完整 / 详情决策前提错误 / 字段最小化缺席 —— ✅ 关闭

- CP :12-16 补全了 catch-all `GET /v1/tasks/{task_id}`(→ `app.py:2436 task_json`)与 evidence/recovery/workflow/artifacts 子路由;详情决策(:23)改为复用现有 task_json、不扩展列表端点、不新增端点。与源码核对:task_json 确含 goal/run/approval/provider/全量 decoded events(app.py:2482-2524),"载荷过富、字段最小化是安全决策"的定性准确。
- 字段最小化已升级为可证伪验收:GC :37 要求 decoder 测试枚举 `approval`/`proposed_action`/`provider_usage`/原始事件载荷**缺席**,e2e 断言页面 innerText 与 IPC 载荷均不含这些键。可客观判定通过/失败。✅
- 残留(P2-2,见下):清单仍漏 `/v1/tasks/{task_id}/events`。

### P0-3:run_id 来源无着落 —— ✅ 关闭

- CP :24 与 GC :38 明确 run_id 来自 `task_json.run`,`getTaskTrajectory(taskId, runId)` 据此调用。
- 源码核实成立:`AgentRun`(contracts/runtime.py:298)含 `run_id: NonEmptyStr`(:299)与 `created_at: UtcDateTime`(:309),`task_json` 返回 `run` 的完整 model_dump(app.py:2493)——run_id 与时间戳均有真实来源,白名单中的"时间戳"字段也有着落。

## P1 逐项复核

### P1-4:credit 表引用错配 —— ✅ 关闭

- CP :17 已改为:逐 task 事件表 `task_events`(persistence.py),sequence 逐 task 连续"由 append 侧校验保证"。与源码一致(persistence.py:40 表定义;:196-202 `expected_sequence == COALESCE(MAX(sequence),0)` 校验)。trajectory.py 的 credit 表引用已删除。

### P1-5:Python/contracts 工作量零覆盖 —— ✅ 关闭

- CP :28 声明默认零变更,若确需则"升级为独立 Task 并跑 tests/product 全量,不在本切片顺手改";计划新增 Task 5(:83-85,条件触发、默认不启动),Out 清单(:35)同步显式排除。条件分支有了归属。✅

### P1-6:e2e 无 RED 步骤 —— ✅ 关闭(附 P2 观察)

- 计划 Task 4 改为新建 `dual-workbench-slice-2.test.mjs`(不动 slice-1 oracle),Step 1 明确"**先写失败 e2e**"再实现至转绿;GC :41 同步写入"e2e oracle 失败先行,随后全绿"。门禁材料层面的纪律已闭合。
- P2 观察:Task 4 仍排在 Task 1-3 实现之后,若 1-3 已把全链路接通,e2e 可能写绿。收口评审时应要求 verification.md 记录 red-run 证据;若 e2e 首次运行即绿,需以变异验证(临时移除投影)补足 fail-first 证明。

## 本轮新发现问题(均为非阻塞)

| # | 级别 | 问题 |
|---|---|---|
| R2-1 | P2 | 计划 Task 1 Step 1 的"多余字段拒绝"措辞有歧义:task_json 的 `approval`/`provider`/`workspace` 等键**恒存在**(值为 null 或对象,app.py:2509-2514),若按 Slice 1 的"对输入 fail-closed 拒额外字段"语义实现,将拒绝一切真实响应。GC :37 的表述(枚举投影输出中这些键缺席)是正确的;建议把 Task 1 Step 1 改为"对原始响应做白名单**投影**,对投影输出做封闭校验"。Task 1 Step 3 的真实 fixture 测试可在同 Task 内兜底,故不定 P1 |
| R2-2 | P2 | CP 路由清单仍漏 `GET /v1/tasks/{task_id}/events`(server.py:634,text/event-stream 全量导出)。不影响本轮决策(转录选 trajectory、详情选 task_json),但"逐条核实"的完整性声明应当名至实归 |
| R2-3 | P2 | "`source_stream_last_sequence` 与事件流不一致即拒"未定义"一致"的精确语义(等值于 max(step.sequence) 还是 ≥)。当前 `TaskAggregate.run` 为单槽、详情展示的是当前 run,等值检查实践中大概率成立;但建议在 Task 1 把校验规则写死,避免重蹈 P0-1 式语义陷阱 |
| R2-4 | P2 | CP :14 引用 "server.py:651/664 等" 与实际行号有偏差(evidence ≈:683、recovery ≈:688、catch-all :689),虽已用"等"容错,建议修准 |

## 章程与纪律复核(维持 round-1 结论)

- §5/§13 流程位置正确(Goal Card + Context Pack + 计划,DRAFT/PENDING_CTO_GATE,未自称已授权);§7 只读/封闭解码/字段最小化方向正确;`builder_id != reviewed_by` 与不 push/merge 声明保持;无 autonomy 误用(RR-0024)。
- 修订提交 e213389c 仅含三份被审文档与 round-1 评审报告,未夹带代码改动,范围干净。

## 最终裁决

**APPROVE_S2_GATE_MATERIALS**

round-1 的 3 个 P0 与 3 个 P1 全部真正关闭,且每处修订均与源码事实相符(非叙事性修补)。遗留 4 个 P2 均为非阻塞的精确性问题,可在 CTO gate 或 Task 1 细化时顺手修正。门禁材料可提交 CTO 审批。
