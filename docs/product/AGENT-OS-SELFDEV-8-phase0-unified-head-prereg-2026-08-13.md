# AGENT-OS-SELFDEV-8 — Phase 0 统一头重答 E6/E7 问题 Round Prereg(DRAFT 候选)

> Status: `DRAFT_CANDIDATE / NOT_ACCEPTED / NOT_FROZEN / NOT_RUN`
> Date: 2026-08-13. Builder: portfolio steward session(builder ≠ reviewer)。
> Authority: founder cast 2026-08-11 §3 条件⑥(SELFDEV-6 driver/任务/baseline/预算/abort classifier/统计门运行前重新预注册并冻结)+ §4.6(提交创始人单独裁决)。
> 本文件是 prereg **候选**:只有在(a)Phase 0 统一接受头 cd594117(或其后继修复头)通过条件③ 全范围独立复审,(b)本候选通过独立 prereg review,(c)创始人 cast 明确授权之后,才允许冻结与运行。三位一体,缺一不跑。
> Governing documents: ADR-0056/0058/0059;SELFDEV-2..7 prereg 与裁决;`docs/research/phase0-exact-head-acceptance-packet-2026-08-13.md`(根仓)。

## 0. 五项 ex-ante 声明(裁决者要求,逐轮更新)

1. **诚实动机**:E6 被配额风暴毁窗(83% 尝试),E7 在冻结充足性地板下 INSUFFICIENT_DATA(两臂 weather-free 均低于 12/24)——"对齐 prompt 后链臂 weather-free 解题率是否追平 baseline"这一问题**至今未被回答**。E8 是对同一问题的第三次发问,前两次的结果记录(E6 NEGATIVE-with-caveat、E7 INSUFFICIENT_DATA)各自成立,不被本轮替换或"修正"。本轮与 E6/E7 的差异:harness 已落地 Phase 0 契约修复(typed denial reason ①、admissible alternatives ②、SSE fail-closed ④、scoped verifier ⑤),运行在统一接受头上。本声明后置于 E6/E7 结果;缓解 = 本 ex-ante 冻结 + 独立 review。
2. **子集复用**:SELFDEV-4 冻结子集第五次复用(字节同一性在本轮 manifest 证明)。复用次数增加使污染上界继续上升——如实记录为 LIMITATION,不作污染无关声明。provider 臂无跨轮记忆;每任务新鲜 2 次尝试预算;备用任务不消耗。
3. **pause-on-403 账户规则(沿用 E7 冻结语义)**:仅账户配额签名(HTTP 403 / AUTHENTICATION_FAILED)触发 driver PAUSE + 探针门控恢复(5 分钟健康探针,连续 2 次健康恢复;累计暂停上限 6 小时,超限剩余尝试记 INVALID_PROVIDER)。其余 provider 失败照原样消耗尝试。全部暂停/恢复事件带时间戳记录;invoked 标记与部分记录永远保留(retention 约束)。
4. **ex-ante 充足性地板(沿用)**:任一侧 weather-free 尝试 < 12(24 次预算的一半)→ INSUFFICIENT_DATA,不升级任何方向结论。冻结于任何尝试之前,约束裁决者。
5. **driver + 门绑定**:driver8.py 与健康门(3 小探针 + 1 个可提取 diff 的中等探针;探针遇 403 即门失败)绑定进 freeze manifest。driver8 相对 driver7 的唯一授权变化见 §3.5。

## 1. 目的与 claim 边界

问题(承接,E6/E7 未答):在冻结 12 任务子集上,对齐后的受治理 diff prompt + Phase 0 契约修复,pass@2 + ABAB + 健康门下,链臂 weather-free 解题率是否追平 baseline——E5 残余(~6.5× 差距,定位于受治理 prompt/响应契约)是否被 prompt 对齐 + 契约修复闭合?

NON-CLAIMS(逐字承接):不与公开 agentic scaffold 可比;无 leaderboard 主张;无 HCW 主张;污染上界;非 release;非 `Autonomy(S,E,O,V,T)` 证据。

次级声明性分析(仅描述,不设门):E5/E6/E7/E8 逐臂对比;typed reason_code 分布分析(①② 首次提供机器可消费分类——回答 E5 的 apply-gate 类到底由哪些 typed 类构成);django-10880 context-mismatch 后续。

## 2. 先验负结果/结果地图

- E7(INSUFFICIENT_DATA):两臂 weather-free 均低于地板(baseline 9、chain 11);数值上 chain 1/12 < baseline 2/12 不升级。
- E6(NEGATIVE + 未答附注):83% 配额毁窗。
- E5(NEGATIVE):残余定位于受治理 prompt/响应契约 + apply-gate 类(denial 原因当时无日志——已由 ①② 修复)。
- 本轮 harness 修复:typed denial reason(①)、admissible alternatives(②)、SSE fail-closed(④)、scoped verifier 绑定(⑤)全部在统一头上并经独立 review。

## 3. 臂、输入、预算

- 输入:两臂相同(issue + base-commit 字节 + F2P + P2P id;均不见 test_patch/gold patch)。
- 链臂:冻结 argv `agent-os benchmark-run-provider .agent_runs/selfdev-4/selection.json <instance_id> --approve --duration-seconds 3600`。每任务 2 次尝试。
- 廉价 baseline:冻结 argv `agent-os benchmark-run-baseline .agent_runs/selfdev-4/selection.json <instance_id>`。每任务 2 次调用。
- 尝试记账:逐字承接系列规则(watchdog 1800/2400、invoked 标记、终态类、preview=consumed、冻结 argv = run 完整性、retention 约束)+ §0.3 暂停语义。
- 解题判定:只认独立 round-level verifier(§6)。
- 执行:严格串行;ABAB 逐尝试;每次尝试前恢复 workspace;不早停(白名单中止 = kill-4 事件)。
- 健康门:承接 E7 强化版。

### 3.5 driver8 相对 driver7 的授权变化(仅以下三项)

1. **abort classifier 改用 typed 信号**:分类器按三面精确命名——
   (a) 消耗侧 INVALID_PROVIDER 分类:provider 失败一律以 typed `ProviderFailure.code`
       (RATE_LIMITED/TIMEOUT/MALFORMED/REFUSED/UNAVAILABLE/AUTHENTICATION_FAILED)归类;
       其中仅 AUTHENTICATION_FAILED(403 配额族)触发 §0.3 暂停;
   (b) 尝试失败类(DIFF_INVALID/APPLY_FAILED 等):以 `DenialReasonCode`(①)归类;
   (c) genuine-infra 中止白名单:以 `BenchmarkContainerError` 的 typed code 常量族
       (BENCHMARK_CONTAINER_UNAVAILABLE/BUILD_FAILED/RUN_FAILED/VERIFIER_TIMEOUT)、
       `SelfDevelopmentValidationError` 的 RUN_DENIED + workspace 明细串、
       `TaskConfigurationDrift` 异常类型(errors.py)为 typed 判定面;
       docker daemon stderr 签名无 typed 信号,保留自由文本匹配并显式声明为残余。
   白名单成员集合逐字承接 E7 冻结值,仅判定机制升级为上述 typed 面;
   分类器输入/判定的完整映射表在 freeze manifest 中逐字绑定。
2. **SSE fail-closed 传输**:malformed non-empty SSE delta 现在产生 typed `MALFORMED` ProviderFailure 而非静默丢弃——该终态进入既有 provider-infra 尝试类(消耗尝试,不触发中止/暂停),记账语义不变。
3. **scoped verifier 绑定(⑤)**:链臂尝试的验证可使用 b32f2cb 的 mirror 验证通道;是否启用在本轮 manifest 中冻结(默认:不启用,沿用 §6 独立 round-level verifier,保持与 E2-E7 的判定连续性)。

除上述三项外,driver8 与 driver7 逐字节相同;任何额外变化 = 新 prereg。

## 4. 冻结子集(复用,哈希钉定)

`.agent_runs/selfdev-4/selection.json` at 5fa6f69(字节同一性在本轮 manifest 证明)。12 个 MAIN 任务。

## 5. 环境冻结(承接)

Provider `openai-compatible` / `kimi-k2-0711-preview`,revision unpinned(LIMITATION),timeout 600s,commitment 3600s,provider-default sampling(LIMITATION)。容器 per ADR-0056 D5。运行前重验:docker 起、12 个 workspace 在钉定 head 干净、镜像在、solver sanity、workspace 对象自含。Repo head:统一接受头(条件③ 通过后的 exact head,freeze 时逐字绑定)。

## 6. Verifier 流程(承接)

checkout base → apply candidate → apply hidden test patch → F2P → curated P2P → 双绿才记 solve → 恢复(总是)。solve 只认独立 round-level verifier 重跑。

## 7. 裁决与 kill 条件

- SUPPORTS 窄主张 iff 链臂 pass@2 solve 数 > baseline pass@2 solve 数(严格不等),无任务级完整性失败,且 §0.4 地板达成。SUPPORTS 只读作"该冻结 12 任务子集上、对齐 prompt + Phase 0 契约修复 envelope 下、窗口充足时观察到差异"——仅此而已。
- INSUFFICIENT_DATA iff 任一臂低于地板(且无 kill 触发)。NEGATIVE iff kill 触发或(地板达成且)链臂 < baseline。MIXED 其他。
- Kill 条件(逐字承接 E7,含 E6 裁决的 403-quota 归类裁定与 §0.3 暂停语义)。
- 新增第 7 条 kill:**typed 信号契约破坏(限于 typed 族)**——任一 provider-facing denial(① 枚举族)缺 reason_code,或任一 provider failure 缺 typed code(④)⇒ INVALID(运行环境与已接受的 Phase 0 头不一致)。typed 族外事件——内部完整性 denial(permit/stale-epoch/compensation/idempotency/snapshot,按① 声明边界保持无码)与白名单残余类 FAILED_UNCLASSIFIED——维持既有分类,不触发本条。

## 8. 冻结机制

1. 独立 reviewer(reviewed_by != builder_id,RR-0031 盲锚定);逐字裁决;改动重开 review。
2. Freeze commit:本 prereg、driver8.py、solve8.py、exact-content manifest(绑定以上 + 复用 selection 的 cross-pin + 统一头 digest)。
3. 轮次顺序:健康门 → ABAB(§0.3 暂停语义)→ 跑完。
4. 裁决:receipts、§7 裁决(含地板)、E5-E8 描述性对比、负结果地图、paradigm learning、状态同步、独立裁决。

## 9. 边界(承接)

C7/approval/verifier 语义不变;不可信代码容器化、无网络无凭证;非 typed 模型输出不成为后果性命令;轮中不改 envelope;任何进一步变化 = 新 prereg。本轮不主张任何产品能力、HCW 或自主性。
