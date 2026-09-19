# 四份代码 PR 独立复核（2026-09-18）

- 基线：`origin/main` = `03ac66b563e689fd3c87d38eed2aae400989f6d5`
- 复核者：Kimi Code 子代理（same-model subagent review）
- 身份声明：创始人已接受本轮"同模型子代理复核"作为充分复核，**并诚实记录 `builder_id != reviewed_by` 未满足**。因此本文按"真实复核"标准写：每条发现都给出 `file:line`、复现方式与建议修法；无发现的 PR 明确写"无实质发现"；不凑数。
- 复核对象与精确 head：

| PR | 分支 | head SHA | 改动 |
| --- | --- | --- | --- |
| #73 | `codex/ops-client-ratelimit-20260918` | `122190d84f8a9882080e54a612cfc69a037d6ead` | +2627/-33, 16 文件 |
| #75 | `codex/deny-visibility-20260918` | `b57572e5e8a8d12ec510cad719f6c65fdc67519d` | +695/-6, 8 文件 |
| #76 | `codex/contract-surface-1-2-20260918` | `c7ec3a473f79146e629f36e7e859e3881f76cdb8` | +1153/-79, 18 文件 |
| #77 | `codex/surface-session-stop-20260918` | `d22048108bdb1a73e2cd1e993b451578c34b6bba` | +970/-147, 5 文件 |

结论汇总：

| PR | 结论 | 最严重问题 |
| --- | --- | --- |
| #73 | **APPROVE WITH FINDINGS** | 被本地限流"拒绝"的调用进入延迟分布，`/metrics` 报出 `p50 0.0ms`（已复现） |
| #75 | **REQUEST CHANGES** | 恢复历史会话（`noem -p --session <id>` / `/resume`）时，**历史 DENY 被算进当前回合**，干净回合被报成 exit 4 + "the action was NOT executed"（已复现） |
| #76 | **APPROVE WITH FINDINGS** | 反向偏斜（已安装的 1.1 客户端 + 新 1.2 daemon）硬失败，未写进"诚实边界"；SSE 路由不经过新投影出口 |
| #77 | **APPROVE WITH FINDINGS** | 均为文档/声明精度问题；`_durable_write` 的"零副作用"前提我逐条核对成立，无实质缺陷 |

复核过程约束遵守：全部实验在 `/tmp` 副本上进行；共享 worktree 只做只读检查与 `pytest`/`node --test`；未触碰 `~/.agent-os/`（实验前后 `stat` 显示 mtime 均为 `1789673577`）；`pgrep -f 'python -m apps\.runtime_daemon'` 为空。

---

## 1. PR #73 — 客户端限流 / 429 跨调用冷却 / 指标聚合

### 结论：APPROVE WITH FINDINGS

核心实现是真的，不是壳：限流器有真实令牌桶 + 真实信号量，429 冷却挂在进程级共享状态上，指标聚合消费**同一条**记录流（`_emit_attempt_record` 同时写日志与 ledger），路由有鉴权、参数校验与 typed 输出。测试不是 fake-pass（见本节"我实际运行验证的内容（#73）"的变异实验，去掉功能后 14 条变红）。

### 发现

1. **[中] 被本地拒绝的调用污染延迟分布，与 PR 自己声明的口径矛盾。**
   - 位置：`packages/os_core/src/agent_os_core/provider.py:723`（拒绝分支把 `time.monotonic() - reserve_started` 当作 `latency_ms` 写进记录）；`packages/os_core/src/agent_os_core/provider_metrics.py:158-162`（`latency_ms >= 0` 即 append 进 `latencies`）。
   - 为什么是问题：PR 正文写"`latency_ms` 仍然是请求耗时，本地等待单独记 `local_rate_limit_wait_ms`，避免冷却被算成 provider 变慢"。但被本地限流**拒绝**的调用根本没有发出 HTTP 请求，它的 `latency_ms` 只是 reserve 的微秒级耗时，却被当成一个合法延迟样本，把均值/中位数往下拉——与被禁止的失真同类（方向相反）。
   - 我已复现（命令见本节"我实际运行验证的内容（#73）"第 3 项）：1 次真实 HTTP 调用 + 1 次本地拒绝，得到
     `PROBE: provider HTTP hits=1 attempts=2 responses=1 failures=1 local_rejections=1 latency.samples=2 mean_ms=4.6 p50_ms=0.0 max_ms=9.2`
     ——`/metrics` 面板会显示 `latency p50 0.0ms max 9.2ms`（面板在 `samples > 0` 时才渲染，见 `apps/cli-ts/src/controller.ts` 的 `metricsPanel`）。
   - 建议修法：拒绝分支不写 `latency_ms`（或写 `None`）；在 `_Aggregate.absorb` 里对 `local_rate_limit_rejected is True` 的记录不计入 `latencies`，并补一条 `latency.samples == <真实调用数>` 的断言。

2. **[低] 默认开启的并发上限是一处未被测试覆盖的行为变更，"拒绝"是终端失败。**
   - 位置：`packages/os_core/src/agent_os_core/client_rate_limit.py:50-53`（默认 20 rps / burst 40 / 并发 8 / 等待上界 30s）；`provider.py:718`（拒绝 → `LOCAL_RATE_LIMITED`, `retryable=False`）→ `packages/os_core/src/agent_os_core/agent_loop.py:882`（回合以 `provider_failure:LOCAL_RATE_LIMITED` 收束）。
   - 为什么是问题：状态按 `provider_id|base_url` 进程级共享。同一本地 daemon 上并发 9 个以上针对同一 provider 的调用时，第 9 个会先最多等 30s，然后**以不可重试失败结束整个回合**（而不是排队）。现有测试里的并发用例只覆盖"同一 gate 上第二次 reserve 被拒"（`test_the_concurrency_bound_refuses_the_extra_caller_after_the_bound`），没有 daemon 级多会话并发用例，所以这个默认值的影响面没有被任何测试记录。
   - 建议修法：至少在 PR/CURRENT_STATE 里写清"默认 8 并发、超限即拒（非排队）"的取舍；更稳的选择是超限时退化为"继续等待 + 记 `local_waits`"，把拒绝留给 `max_wait` 显式配置的场景。

3. **[低] 一条几乎无法失败的弱断言（不影响该用例整体有效性）。**
   - 位置：`tests/product/test_client_rate_limit.py:526` `assert "local" in refused.safe_message`。
   - 为什么：`"local"` 在本 PR 多条消息里都出现，这条断言单独几乎不会变红；不过同一用例另有 `refused.code is ProviderErrorCode.LOCAL_RATE_LIMITED`、`retryable is False`、`len(hits) == 1` 三条强断言，所以**整条用例仍是旁路检测器**，我只是建议收紧。
   - 建议修法：断言更具体的子串（例如 `local client rate limit refused the call`）。

### 我实际运行验证的内容（#73）

```bash
# 1) PR 自报的 42 例（23 + 19）
cd .worktrees/wt-ops-ratelimit
env HOME=/tmp/prrev/home TMPDIR=/tmp/prrev .venv/bin/python -m pytest \
  tests/product/test_client_rate_limit.py tests/product/test_provider_metrics.py -q
# → 42 passed in 4.45s   （与 PR 正文"恢复后 42 例全绿"一致）

# 2) 旁路变异（在 /tmp 副本上做，不动作者 worktree）
#    mutation: ProviderRateLimitState.reserve() 立即 return RateLimitLease()；
#              note_rate_limited() 立即 return 0.0
env HOME=/tmp/prrev/home .venv/bin/python -m pytest tests/product/test_client_rate_limit.py \
  tests/product/test_provider_metrics.py -q
# → 14 failed, 28 passed   （含全部冷却/适配器行为用例）
# 结论：PR 声称的"6 个行为用例变红"方向正确；我用更宽的模块内变异得到 14 条变红，
# 说明这些测试确实由行为驱动，不存在 fake-pass。（PR 的"6"是它自己那次更窄变异的结果，
# 分支上没有保留该实验脚本，无法逐字复现。）

# 3) 探针：本地拒绝是否进入延迟分布
env HOME=/tmp/prrev/home .venv/bin/python -m pytest tests/product/test_review_refusal_latency.py -q -s
# → PROBE: provider HTTP hits=1 attempts=2 responses=1 failures=1 local_rejections=1
#          latency.samples=2 mean_ms=4.6 p50_ms=0.0 max_ms=9.2
# 探针内容（复现用）：与 test_provider_metrics.py::test_a_locally_refused_call_is_counted_as_a_rejection
# 相同场景（rps=0.05, burst=1, max_wait=1.0），额外打印 snapshot.latency 各字段。

# 4) ruff（PR 声称 clean）
cd .worktrees/wt-ops-ratelimit && env HOME=/tmp/prrev/home uv run --offline --extra product-test ruff check \
  apps/api_server/surface_routes.py packages/contracts/src/agent_os_contracts/provider_metrics.py \
  packages/contracts/src/agent_os_contracts/provider.py packages/os_core/src/agent_os_core/client_rate_limit.py \
  packages/os_core/src/agent_os_core/provider_metrics.py packages/os_core/src/agent_os_core/provider.py \
  tests/product/test_client_rate_limit.py tests/product/test_provider_metrics.py
# → All checks passed!

# 5) TS 侧（/metrics 面板 + client 方法）
cd .worktrees/wt-ops-ratelimit/apps/cli-ts
env HOME=/tmp/prrev/home node --import tsx --test test/client.test.ts test/controller.test.ts
# → 63 tests, 63 pass, 0 fail
```

另外**读代码确认**（未运行）：`_emit_attempt_record`（`provider.py:788-796`）确实是"一次记录、两个消费者"；`_operator_log_record`（`provider.py:798-839`）字段里没有 prompt / completion / credential（只有 `request_id/provider_id/model_id/latency/outcome/code/retryable/tokens/text_chars/tool_proposals/finish_reason`），所以"密钥/内容泄漏"在本 PR 的聚合面上不成立；`LOCAL_RATE_LIMITED` 在 agent_loop 走通用 `provider_failure:{code}` 且 `retryable=False` 不会被内部重试循环放大（`agent_loop.py:1291-1297`）。

### 未能验证（#73）

- PR 声称的 pyright "156 个既有错误、无新增"我未复跑（耗时且需要 clean baseline）。
- 全量 `pytest tests/product`（220s / 2756 例）未跑，按委托要求只跑承载主张的文件；因此"默认开启限流没有打红既有产品测试"这一条我只有间接证据（我跑的两个文件 + 作者报告）。
- `PAT`/真实 provider 下的端到端节流行为未验证（无凭据、也不应发外部请求）。

---

## 2. PR #75 — 让 permission DENY 可见（卡片 + headless exit 4）

### 结论：REQUEST CHANGES（一条阻断级发现；其余部分实现真实、测试有效）

### 发现

1. **[阻断] 恢复会话时，历史 DENY 被算成"当前回合的拒绝"，干净回合被报成 exit 4 / "the action was NOT executed"。**
   - 位置（全部在当前 head）：
     - `apps/cli-ts/src/controller.ts:364` `durableCursor = 0`；`:1047 adoptSnapshot`（`/resume` 只换 `taskId`，**不重置也不播种** cursor）；
     - `:1342` `applyDurable` 把**所有** `POLICY_VERDICT_RECORDED` 交给 `applyPolicyVerdict`（对比 `:1305-1330`：`SESSION_TURN_COMPLETED` / `SESSION_APPROVAL_PENDING` 都有 `turn_id` 过滤）；
     - `:1524-1526` 把 DENY push 进 `turnDenials`；`:1153-1154` 只在 `runTurn` 开头清空；
     - `apps/cli-ts/src/headless.ts:149` 取 `policyDenials[0]` 决定 exit 4。
   - 为什么是问题：kernel 的 `POLICY_VERDICT_RECORDED` **不带 turn_id**（`packages/os_core/src/agent_os_core/agent_loop.py:1654-1671`，本 PR 只补了 `action_id/node_id/arguments_json/rule_reason`）。`noem -p --session <id>` 走 `controller.submit("/resume <id>")`，新控制器 cursor 仍是 0 → 第一次 drain 用 `after_sequence=0`，服务端 `surface_event_batch` 返回**该 task 的全部事件**（`apps/api_server/app.py` 的 `surface_event_batch`；03ac66b5 处为 `:2739-2743`，PR #77 在文件头部加 import 后整体 +1 行，无上限）。历史 DENY 因此进入本回合的 `turnDenials`，headless 据它为**没有发生拒绝的回合**报 exit 4，并打印
     `⏵ refused: <capability> · denied_by_rule:<id> — the action was NOT executed`。
     这正是本 PR 要修的"谎报"的镜像：把没发生的拒绝说成发生了。
   - 证据（见本节"我实际运行验证的内容（#75）"第 5 项）：真实 `TuiController` + 真实 `runHeadless` + 镜像 `surface_event_batch` 语义的 stub。
     `PROBE → exit 4, subtype "denied", stop_reason "denied_by_rule:rule-1"`（历史 DENY 在 seq1，本回合无任何拒绝）
     `CONTROL → exit 0, subtype "success"`（同一场景，去掉历史 DENY）
   - 建议修法（最小、不破坏回放）：
     - 在 `adoptSnapshot` 记下 `historyWatermark = snapshot.event_sequence`，或在 `runTurn` 起点记 `turnScope = max(this.durableCursor, adoptedWatermark)`；
     - `applyPolicyVerdict` 仍然为历史 DENY 生成卡片（历史回放是有意的），但**只在 `event.sequence > turnScope` 时**才 `turnDenials.push(...)`；
     - 补一条测试："resume 到有历史 DENY 的会话后，干净回合 = exit 0"。现有第三条 headless 测试（`test_a_refused_action_is_not_reported_as_success_on_a_later_clean_turn`）用**两个独立控制器**且第二个 `denials = []`，覆盖不到这条路径。

2. **[低] exit 4 在非 completed 回合不可达，`denied:out_of_allowlist` 分支在真实路径上不可达（只有 stub 能触发）。**
   - 位置：`apps/cli-ts/src/headless.ts:126-146`（`lastStopReason !== "completed"` 先返回 exit 3）先于 `:149-168`（拒绝分支）。
   - 为什么是问题：PR 正文说 headless 新增 `denied:out_of_allowlist`。真实 kernel 的 out-of-allowlist 先被 `agent_loop.py:942`（`capability_id not in CHAT_CAPABILITY_IDS`）预检拦下并置 `stop_reason="unauthorized_proposal"`，回合非 completed → 走 exit 3，永远到不了 exit 4。PR 自己的 Python 测试就该路径断言 `stop_reason == "unauthorized_proposal"`（`tests/product/test_permission_deny_visibility.py:249`）。另外 `_execute_proposal` 内的 `DENY_OUT_OF_ALLOWLIST` 分支当前**不可达**：`permission_gate.py:23-31 ACTION_RISK_TIERS` 与 `agent_loop.py:67-75 CHAT_CAPABILITY_IDS` 是同一组 7 个 capability，预检已经全部拦下。
     同理，`max_steps` / `loop_detected` / `unauthorized_proposal` 回合里发生的拒绝对脚本不可见（exit 3 且无拒绝信息）。
   - 影响：不是谎报（不是 success），但"exit 4 覆盖被拒绝的动作"被 overstate；out_of_allowlist 的 headless 用例只守护分支语义，不代表可达路径。
   - 建议修法：二选一并写清——(a) 让拒绝优先于 3（有 DENY 就 exit 4 + 原始 stop_reason 放别处）；或 (b) 在 PR/文档把 exit 4 限定为"回合 completed 但有拒绝"，并在测试里注明 out_of_allowlist 用例是分支守护。

3. **[低] 拒绝卡片复用了与"派发失败"相同的 `[failed]` 标记。**
   - 位置：`apps/cli-ts/src/controller.ts:1539-1561`（既有卡片分支 `:1541`、新卡片 `:1558` 的 `status: "failed"`）。
   - 我确认这不是 receipt 语义变更：拒绝路径上**没有**伪造 `ACTION_PROPOSED`、没有 pending、没有 receipt（PR 的 Python 测试也断言 `ACTION_RECEIPT_RECORDED == []`）。只是在 `/export` 里读者需要读文本才能区分"从未执行"与"执行了但失败"。
   - 建议修法：`errorText`/`resultSummary` 统一加 `not executed: ` 前缀即可，不必动状态机。

### 我实际运行验证的内容（#75）

```bash
# 1) PR 自报的 kernel 侧 3 例
cd .worktrees/wt-deny-visible
env HOME=/tmp/prrev/home TMPDIR=/tmp/prrev .venv/bin/python -m pytest tests/product/test_permission_deny_visibility.py -q
# → 3 passed in 0.50s

# 2) 权限相关回归文件（防止新增 payload 字段打红既有断言）
env HOME=/tmp/prrev/home .venv/bin/python -m pytest tests/product/test_permission_deny_rules.py \
  tests/product/test_permission_mode_matrix.py tests/product/test_permission_deny_visibility.py -q
# → 22 passed in 1.13s

# 3) 变异（在 /tmp 副本 mut75 上，用 PYTHONPATH 覆盖到副本源码）
#    3a. 从 _record_policy_verdict payload 删掉 rule_reason/action_id/node_id/arguments_json
#        → 1 failed, 2 passed（test_rule_deny_records_the_denied_action_identity 以 KeyError 变红）
#    3b. 把 model-visible tool message 还原成旧的
#        "denied: an operator permission rule forbids this capability"
#        → 1 failed, 2 passed（test_rule_deny_tells_the_model_which_rule_and_capability 变红）
#    → 该文件的断言确实是旁路检测器。

# 4) TS 侧：PR 自报"删掉投影 → 3 个 controller 用例红；删掉 headless 分支 → 3 个 headless 用例红"
cd .worktrees/wt-deny-visible/apps/cli-ts
env HOME=/tmp/prrev/home node --import tsx --test test/controller.test.ts test/headless.test.ts
# → 58 tests, 58 pass, 0 fail
# 在 /tmp 副本上删除 applyDurable 的 POLICY_VERDICT_RECORDED 分支：
#    not ok 44 / 45 / 47  → # pass 46, # fail 3   （与 PR 声称的 3 条一致）
# 在 /tmp 副本上删除 headless 的 denial 分支：
#    not ok 7 / 8 / 9     → # pass 6,  # fail 3   （与 PR 声称的 3 条一致）

# 5) 阻断发现的复现（探针文件 /tmp/prrev/ts75/test/review-replay-deny.test.ts）
env HOME=/tmp/prrev/home node --import tsx --test test/review-replay-deny.test.ts
# → # PROBE RESULT: 4 {"type":"result","subtype":"denied","session_id":"s:1","text":"all done",
#                    "stop_reason":"denied_by_rule:rule-1","total_tokens":10,"is_error":true}
#   # CONTROL RESULT: 0 {...,"subtype":"success","stop_reason":"completed"}
#   not ok 1 - PROBE ... ; # pass 1, # fail 1
#   探针要点：复用 headless.test.ts 的 StubClient 形态，但 events(after) 返回固定的历史事件列表
#   （与 apps/api_server/app.py:2739-2743 语义一致：sequence > after_sequence 的全部事件）：
#     seq1 POLICY_VERDICT_RECORDED(DENY, basis=rule, rule_id=rule-1, action_id=a:edit-old) —— 无 turn_id
#     seq2 SESSION_TURN_COMPLETED(turn_id="turn:0")   ← 被 turn_id 过滤，不参与本回合
#     seq3 SESSION_TURN_COMPLETED(turn_id="turn:1")   ← 本回合
#   调用 runHeadless(client, {prompt:"just say hello", sessionId:"s:1", outputFormat:"json"})。
#   CONTROL 只是删掉 seq1，其余不变。

# 6) ruff
env HOME=/tmp/prrev/home uv run --offline --extra product-test ruff check \
  packages/os_core/src/agent_os_core/agent_loop.py packages/os_core/src/agent_os_core/permission_gate.py \
  tests/product/test_permission_deny_visibility.py
# → All checks passed!
```

读代码确认（未运行）：`POLICY_VERDICT_RECORDED` 在 `task_aggregate.py:443-465` 属于"不改变聚合状态的审计标记"（`:461 "Chat-turn audit markers carry no aggregate state transition."`），新增 payload 字段不会破坏 kernel 聚合；`ACTION_PROPOSED` 本身携带 `action.model_dump()`（含 `arguments_json`），所以拒绝事件新增 `arguments_json` 没有引入新的数据类别（**未发现密钥/内容泄漏**：字段来自模型自己产生的 tool 参数，且这些参数本就已耐久存在于回合记录中）。

### 未能验证（#75）

- 未用真实 daemon 复现阻断发现（作者已做过真实 daemon e2e；我的复现建立在"真实 controller/headless 代码 + 与 `surface_event_batch` 语义一致的 stub"之上，属于代码路径级复现，不是活体 daemon 复现）。
- 未跑 `pytest tests/product` 全量；PR 声称的 2756 passed / 1 skipped 我未复算。
- pyright 计数（156 既有）未复跑。

---

## 3. PR #76 — surface 协议 1.1 → 1.2（附加字段的兼容收口）

### 结论：APPROVE WITH FINDINGS

缺陷描述属实、修法方向正确：`extra="forbid"` 未放宽，投影只删除注册表里声明的附加字段，协商是有序闭集，三处等值门确实改成了协商，且 TS 镜像同步（否则 CLI 会被降级到 1.1 而静默丢掉 `awaiting_approval`）。测试非 fake-pass：`test_strict_1_1_reader_*` 用独立定义的 strict 1.1 模型（不是宽容阅读器）做断言，`test_really_is_the_published_1_1_shape` 还把该模型的字段集钉在"当前契约字段 − 已注册 1.2 增量"上。

### 发现

1. **[中] 反向版本偏斜会硬失败，但 PR 的"诚实边界"只写了 macOS renderer。**
   - 位置：`apps/runtime_daemon/descriptor.py:33`（新：`protocol_version: SurfaceProtocolVersion`），对照基线 `03ac66b5:apps/runtime_daemon/descriptor.py:31-32`（旧：`protocol_version: Literal["1.1"]`）与 `:59`（`load_runtime_descriptor` → `RuntimeDescriptor.model_validate` 失败即 `RuntimeDescriptorError("... has an invalid schema")`）。
   - 为什么是问题：daemon 现在把 `~/.agent-os/runtime.json` 写成 `1.2`。任何**已安装的**旧客户端（旧 `agent-os-runtime` / 旧 `noem` dist / `apps/cli-ts/src/descriptor.ts` 的旧版本把 `protocol_version` 钉成 `z.literal("1.1")`）在读 descriptor 时就会 `invalid schema`，**连一个请求都发不出去**。PR 的"诚实边界"里那句"macos renderer 故意保持 1.1 读取器：它发 1.1 → 收到 1.1 投影 → 继续工作"对 HTTP 响应是对的，但不覆盖 descriptor 这道门；1.1 客户端 + 1.2 daemon 这一方向被漏写了。
   - 建议修法：把该方向补进 PR 诚实边界与 `docs/CURRENT_STATE.yaml` 的协议条目（写明 `protocol_version` 偏斜语义与后果）；若要保留反向兼容，让 descriptor 固定写 floor（`1.1`）而用请求头承担协商，或让旧客户端在 descriptor 校验失败时按 floor 降级重试。

2. **[低] "**所有** surface 响应经由单一 `_respond` 出口做投影"不准确：两条 SSE 路由绕过该出口。**
   - 位置：`apps/api_server/surface_routes.py:529 (_write_frame_sse)`、`:602 (_write_sse)` 直接 `handler.wfile.write(...)`；对照 `:651 (_respond)`。相关路由：`:473 _get_stream`、`:549 _get_events`。
   - 为什么值得记：今天这两条 SSE 体里没有版本化字段（只有逐帧 `kind/payload`/事件 + `cursor`），所以**线上没有谎报**；但这句"全部响应"在"下一个 minor 新增一个流式字段"的那天会变成真的漏洞——那条路径没有注册表驱动的投影。同类问题：`SurfaceRuntime._require_protocol`（`packages/os_core/src/agent_os_core/surface_runtime.py:496-511`）只返回协商值、不投影，投影只发生在 HTTP 层，因此进程内用 1.1 命令调用 runtime 会拿到声明 1.2 的响应模型（今天没有这样的调用者，我 grep 过 `apps/ packages/` 没有 Python 侧构造 1.1 命令）。
   - 建议修法：把措辞收窄为"所有 JSON surface 响应"；或在 `_write_sse` / `_write_frame_sse` 写出前也过 `downgrade_surface_payload`。

3. **[低] (c) 结构性门是基于"变量名"的，改名即可绕过（我已复现）。**
   - 位置：`tests/product/test_surface_protocol_1_2.py:531 (_is_version_operand)` 只承认名字里含 `protocol_version` 的 `Name`/`Attribute`；门本体在 `:597`。
   - 复现：在 `/tmp` 副本的 `apps/cli/surface_client.py` 里加入一个真实的等值门
     `if server_version != "1.2": raise ValueError(...)`，再跑该门：
     `pytest tests/product/test_surface_protocol_1_2.py -q -k equality` → **`1 passed`（仍是绿的）**（对照：未加代码时同样 `1 passed`；门对当前树报 0，符合 PR 声称）。
   - 建议修法：把"与 `^\d+\.\d+$` 字面量比较"的 `Compare` 也纳入判定（`surface_version`、`server_version` 这类局部名同样要覆盖），或至少在 docstring 里写明"只覆盖以 `protocol_version` 命名的操作数"，避免被当成全覆盖门。

4. **[低] 改写后的 E3 断言把 1.2 增量重新钉住，下一个 additive minor 必红。**
   - 位置：`tests/product/test_cost_honesty.py:240` `assert surface_protocol_unknown_fields("1.1") == ("awaiting_approval",)`。
   - 为什么：`surface_protocol_unknown_fields` 汇总的是**所有**已注册且 minor 大于协商值的字段（`packages/contracts/src/agent_os_contracts/surface.py:136-152`）。将来注册 1.3 字段时这条 E3 门会变红，必须改测试——正是本 PR 批评的"把版本 bump 变成改测试"。这不是错，只是与"1.2 只是 additive，不该再被测试钉住"的论调不自洽。
   - 建议修法：断言改为"包含 1.2 增量"（superset）或把这条搬到 `test_surface_protocol_1_2.py`，让 E3 门只守 `minor >= 1.1`。

### 我实际运行验证的内容（#76）

```bash
# 1) PR 自报的新文件 43 例 + 被改写的 cost_honesty
cd .worktrees/wt-contract-1-2
env HOME=/tmp/prrev/home TMPDIR=/tmp/prrev .venv/bin/python -m pytest \
  tests/product/test_surface_protocol_1_2.py tests/product/test_cost_honesty.py -q
# → 53 passed in 7.83s

# 2) 结构性门 + 改名绕过复现（/tmp 副本 mut76）
env HOME=/tmp/prrev/home .venv/bin/python -m pytest tests/product/test_surface_protocol_1_2.py -q -k equality
# 未加代码： 1 passed, 42 deselected in 2.40s
# 加代码后（apps/cli/surface_client.py 里 if server_version != "1.2": raise ...）：
#            1 passed, 42 deselected in 2.19s      ← 门没有报红

# 3) TS 侧
cd .worktrees/wt-contract-1-2/apps/cli-ts
env HOME=/tmp/prrev/home node --import tsx --test test/protocol-version.test.ts test/client.test.ts test/doctor.test.ts
# → 31 tests, 31 pass, 0 fail

# 4) ruff
env HOME=/tmp/prrev/home uv run --offline --extra product-test ruff check \
  apps/api_server/surface_routes.py apps/cli/surface_client.py apps/runtime_daemon/descriptor.py \
  packages/contracts/src/agent_os_contracts/surface.py packages/os_core/src/agent_os_core/surface_runtime.py \
  tests/product/test_surface_protocol_1_2.py tests/product/test_cost_honesty.py
# → All checks passed!
```

读代码确认（未运行）：`_negotiate_protocol` 把协商结果存在 handler 上（不是共享 router 上，`surface_routes.py:622-649`），无跨线程污染；header 缺席 → floor 1.1，与"无 header 的老客户端不认识新字段"的论证一致；不可协商的 header → `SurfaceProtocolError` → 422，且错误响应自身也走 `_respond`（此时 `_negotiated_protocol` 回落到 floor）。

### 未能验证（#76）

- `apps/cli-ts/scripts/install_smoke.sh`（PR 声称 8/8 PASS，跨升版真实回合）未跑：它会构建 CLI 并启动 hermetic daemon，属于"可能起进程"的操作，我按约束回避。
- `npm run test:ci`（35 文件）与 `npm test`（PR 声称 240/240）未全跑，只跑了承载主张的 3 个文件。
- macOS 侧未验证：`apps/macos/renderer/src/surface_client.ts:126` 是 `value.protocol_version !== SURFACE_PROTOCOL_VERSION`（`SURFACE_PROTOCOL_VERSION = "1.1"`）的严格读取器，与 PR 说明一致；但 `apps/macos/shell/src/daemon_supervisor.rs:40` 要求 descriptor 的 `protocol_version == "1.0"`，**在基线（写 1.1）就已不匹配**，属既有不一致、与本 PR 无关，仅记录以免被误认为本 PR 引入。

---

## 4. PR #77 — 单会话停止（QUEUED→PAUSED + 中途优雅停机）

### 结论：APPROVE WITH FINDINGS

我独立确认的关键主张：

- **`QUEUED → PAUSED` 确实开放，且只开放这一条边**：`packages/os_core/src/agent_os_core/task_service.py:2415`（QUEUED 集合加入 PAUSED），`:2419 PAUSED: {RUNNING, CANCELLED}` 未放宽，终态仍为 `set()`；测试 `test_run_transition_table_allows_queued_to_paused_only` 同时断言了 PAUSED→PAUSED、PAUSED→QUEUED、CANCELLED→PAUSED 都必须抛错。
- **停止点是真实安全点**：`agent_loop.py:933-938`（每次 provider 调用前）与 `:1012`（每次能力派发前，循环头）两处检查，且 `:1128-1136` 把 `stopped_by_operator` 加进"为未回答的 tool_call 补 `not executed`"的分支，transcript 合法性有代码依据。
- **`_durable_write` 的"失败那次什么都没写"前提成立**（我逐条读了被包裹的写路径）：`update_run_status`(task_service.py:2425-2437)、`_record_action_receipt`(:1509-1563 只读校验 + 单次 `_append_event`)、`record_or_reuse_session_approval`(:961-1130 每条路径单次 `_append_batch`，且有 reuse 分支使重放幂等)、`resolve_session_approval`(:1153-1283 校验后单次 `_append_batch`)。乐观 append 是"抛错即未写"，因此重试不会重复施加效果。这是对 PR 最关键不朽性主张的独立确认，**不是缺陷**。
- **入口守卫充分**：`resume_turn` 两个分支分别要求 QUEUED/RUNNING（`agent_loop.py:410-425`）与 RUNNING（`:427-435`），因此"PAUSED 的 Run 进入 `_drive`"今天只可能是**回合进行中**的操作者暂停（见发现 2）。

### 发现

1. **[低] `_pause_task_with_conflict_retry` 的 docstring 与状态机不一致，不只是措辞问题。**
   - 位置：`apps/api_server/app.py:2495-2512`（docstring "a retry only re-applies the same idempotent target state" + 5 次重试），对照 `task_service.py:2419`（`PAUSED: {RUNNING, CANCELLED}`）。
   - 为什么：重试之所以安全，是因为**冲突的那次零写入**，而不是因为目标状态幂等；如果另一个写入者（另一个客户端）先完成了 pause，重试会抛 `InvalidTransitionError` → 操作者连按两次停止、或两个客户端同时停止，第二次拿到 409 而不是成功。这不是本 PR 新引入的行为（基线同样拒绝 PAUSED→PAUSED），但 docstring 与 PR 正文的说法会误导下一个读者。
   - 建议修法：把"安全性来自失败写入无副作用"写清楚；若要真幂等，可在 `surface_pause_session` 里把"Run 已是 PAUSED"按 no-op 成功返回当前快照（并说明与 C7/审计的关系）。

2. **[低] `_drive` 把"Run 处于 PAUSED"一律解释为操作者停止，抹平了暂停来源。**
   - 位置：`agent_loop.py:933-938`（原为"PAUSED 即抛 `InvalidTransitionError`"），对照 `task_service.py:2397-2409`（重启用 `RUN_PAUSED` payload 里是否有 `unknown_action` 来判定 `UNKNOWN_REQUIRES_REVIEW`）。
   - 为什么：`RUN_PAUSED` 事件本身携带来源信息（`update_run_status` 写 `{"run": ...}`；`pause_session_for_unknown_action` 写带 `unknown_action` 的 payload）。现在任何 PAUSED 都产出 `stopped_by_operator`，审计上"操作者停止"与"其他原因暂停"的区分只存在于事件里、不再体现在 stop_reason。今天我确认它不可达（本节"入口守卫充分"那一条的两处守卫），属潜在风险。
   - 建议修法：`_operator_stopped` 只认"最近一次 `RUN_PAUSED` 不带 `unknown_action`"的那种（或把来源带进 text/stop reason），这样语义与入口守卫解耦。

3. **[低] `_STOPPED_BY_OPERATOR_TEXT` 与 `PAUSED` 的绑定只在 stop 时刻成立。**
   - 位置：`agent_loop.py:1867-1871`（文案写死"the session is paused and must be resumed"）。
   - 为什么：文案是对**那一刻**状态的断言。竞态窗口（作者已在"边界与未做"里承认）是 pause 落盘与派发开始同瞬——此时回合仍会走完这次派发，但文案/`stop_reason` 一致（都是 stopped_by_operator），所以没有说谎；只是文案在"pause 之后又被立刻 resume"的场景下会被读成过期陈述。
   - 建议修法：文案改为不依赖即时状态的表述（例如"stopped by the operator before the next step"），或在回合收束时按当前 Run 状态选择文案。

### 我实际运行验证的内容（#77）

```bash
cd .worktrees/wt-session-stop
env HOME=/tmp/prrev/home TMPDIR=/tmp/prrev .venv/bin/python -m pytest tests/product/test_surface_session_stop.py -q
# → 9 passed in 5.81s      （文件内确有 9 个 test 函数，与 PR 声称一致）

env HOME=/tmp/prrev/home uv run --offline --extra product-test ruff check \
  apps/api_server/app.py packages/os_core/src/agent_os_core/agent_loop.py \
  packages/os_core/src/agent_os_core/task_service.py packages/contracts/src/agent_os_contracts/surface.py \
  tests/product/test_surface_session_stop.py
# → All checks passed!
```

关于"stop 是否把会话搞坏/锁死"这一问：本 PR 的测试里有真实覆盖——`test_pause_during_a_provider_call_stops_before_any_dispatch` 在停止后依次做了 resume → set_permission_mode → 第二个回合完成（fixture 文件真正被改写），并断言 `surface_has_uncommitted_turn(...) is False`。按委托要求，我**不重复**对 stop 语义做全套复现（另有 agent 负责），只在此记录我看到的覆盖范围。

### 未能验证（#77）

- 真实 daemon + 真实 `noem session pause` CLI 的端到端（作者报告了 before/after 表；我未复跑，因为需要起 daemon）。
- 全量 `pytest tests/product`（作者报告 2762 passed / 1 skipped）未复算；我只跑了承载主张的单文件。
- pyright / cli-ts 套件（本 PR 未改 TS）未跑。
- `CANCELLED` 中途停机仍然抛错（PR 明确列为"未做"）——我未验证其在 loop 内的具体表现。
- pause 的 `reason` 未耐久记录（PR 明确列为"未做"）——见发现 2，二者相关。

---

## 5. 跨 PR / 合并次序事项（给协调者）

我用 `git merge-tree --write-tree <headA> <headB>`（只读，不写工作区）检查了两两合并：

| 组合 | 结果 |
| --- | --- |
| #73 × #77 / #73 × #75 / #73 × #76 / #75 × #76 | 无冲突 |
| **#76 × #77** | **冲突：`packages/contracts/src/agent_os_contracts/surface.py`** |
| **#75 × #77** | **冲突：`packages/os_core/src/agent_os_core/agent_loop.py`** |

- `#75 × #77` 的冲突在 `_record_policy_verdict`（#75 往 payload dict 里加 `rule_reason/action_id/node_id/arguments_json`，#77 把同一段 `append_event` 包进 `_durable_write`）。合并时两处都要保留：包裹 + 新字段。
- `#76 × #77` 的冲突在 `surface.py`（#76 重写所有 `protocol_version: Literal["1.1"]` → `SurfaceProtocolVersion`，#77 给 `SurfaceTurnResponse` 加 docstring）。
- 语义（不冲突但需人守）：#73 新增的 `GET /v1/surface/observability/metrics` 用 `handler._json(200, ...)`（`surface_routes.py:314`），而 #76 把路由层的出口统一成 `_respond`。metrics 载荷里没有版本化字段，所以今天即使绕过投影也无害；但两者合到一起后应把该路由改走 `_respond`，以免下一个 additive 字段从这条新路由漏出去。

## 6. 汇总：我未能验证的内容

1. 四份 PR 的**全量** `pytest tests/product`（#75/#76/#77 各作者自报 2756 / 2796 / 2762 例；#73 未报全量数字）——按委托要求只跑承载主张的文件，未复算总数与 exit code。
2. 四份 PR 的 **pyright** 计数（均自报"156 个既有错误、改动文件 0 新增"）——未复跑，未建立 clean baseline。
3. `apps/cli-ts` 的 `npm test`（全 34/35 文件）与 `npm run typecheck`；我只跑了与本轮主张相关的文件子集，并全部通过。
4. `apps/cli-ts/scripts/install_smoke.sh`（#76 自报 8/8）与任何需要**启动 daemon/构建 CLI** 的 e2e（#75、#77 的 daemon 级证据）——按硬约束回避起进程；#75 的阻断发现只做到"真实 controller/headless 代码 + 与 `surface_event_batch` 语义一致的 stub"级别的复现。
5. #77 的 stop 语义全套复现（由另一 agent 负责，我不重复）；`CANCELLED` 中途停机的实际表现。
6. macOS（renderer/shell）相关行为：不在 CI，我未运行，只做了静态阅读（见第 3 节（#76）"未能验证"最后一条）。
7. 外部真实 provider 下的限流/冷却行为（无凭据，也不应发外部请求）；#73 的节流是用本地 loopback stub + 注入假时钟验证的。
