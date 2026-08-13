# 独立 Exact-Head Review — Phase 0 条件①(typed denial reason code)

> Archived verbatim from the independent reviewer's returned report.
> Reviewer: standing independent reviewer, blind-anchored per RR-0031, no builder history.
> Exact head: `991f42a5157dc3f1d4fd20b75b089adbfe28b5df`(主 diff `e53d972a`;`991f42a5` 经 `--name-only` 确认为单文件 docs-only,零代码影响)。

## 总体裁决:APPROVE_WITH_P2

无 P0/P1。条件① 的实现语义正确、旁路测试真实有效、回归面干净、范围纪律为纯附加。两条 P2 记录见下(不阻塞接受)。

## 独立复现的验证结果(全部 reviewer 重跑,非采信 builder 声明)

| 项 | 声明 | 复现 |
|---|---|---|
| test_provider_diff_mode + 4 定向套件 | 27 + 45 passed | **72 passed**(6.10s)✓ 精确一致 |
| ruff(4 个改动文件) | clean | **All checks passed** ✓ |
| pyright(capability/execution) | 0 errors | **0 errors, 0 warnings** ✓ |
| 全量 tests/product | 1617 passed + 36 既有 fixed-NOW 失败 | **1617 passed / 36 failed / 1 skipped** ✓;失败组成:mandate 19 + package_metadata 1 + trajectory_binding 16 ✓ 精确一致 |

失败原因抽查(2 项):`test_unbound_provider_fails_before_invocation` → "Task commitment expired before sealing";`test_patch_applies_when_approved` → "ratified mandate is not active at evaluation time"——均为时钟/fixed-NOW 类既有失败,与本 diff 的 denial 面无任何交集 ✓。

## 逐项核验

**① 枚举值与拒绝语义一一对应(无错配/漏配)。** execution.py 实际 10 个提案拒绝点全部 typed:2× `PROPOSAL_AMBIGUOUS_OR_UNAUTHORIZED`(多提案/无提案+提取失败)、3× `PROPOSAL_ENVELOPE_KEYS`(非对象/diff 多键/content 多键)、2× `PROPOSAL_CONTENT_MISSING`、1× `DIFF_VALIDATION_FAILED`、2× `PROPOSAL_PATH_MISMATCH`(header 内不一致/与目标不符)。capability.py:`_safe_path` 4 点、workspace-changed 2 点(含 content 分支 admissible 对齐——条件②一致性,符合声明的唯一非纯附加点)、diff parse/apply 8 点、shell 族 4 点、test allowlist、参数形状 5 点。**边界纪律核验:** permit/stale-epoch/idempotency/compensation/snapshot 各拒绝点未被触碰,与枚举 docstring 声明的"内部完整性 denial 保持无码"一致 ✓。

**② 旁路检测有效性(审逻辑,不只跑)。** 参数化提案矩阵对 6 个拒绝点逐一断言 `reason_code is <expected enum>`;两个全程 apply-denial 测试(`DIFF_CONTEXT_MISMATCH`、`WORKSPACE_CHANGED_SINCE_PROPOSAL`)断言枚举同一性 + 消息中 `[CODE]` + admissible hint + 字节不变;enum-wire 端到端测试断言 reason_code 为枚举实例、值入消息、值唯一。任一产出点丢码(reason_code=None → 无 `[CODE]` 片段 → 属性 None)或退回自由文本,上述断言即红 ✓ 真实有效。

**③ 行为回归面。** `[CODE]` 注入位置在 `tool failed: {error_code}` 之后、error_detail 之前——既有 substring 断言与 SELFDEV driver 的分类器模式("unified diff context mismatch"、"patch does not apply" 等)全部仍然命中 ✓;content 分支新消息以旧子串开头 ✓;`receipt.error_code` 语义不变(仍为异常类型名),output dict 的 `reason_code` 为纯附加键 ✓;idempotency/compensation 路径零改动 ✓;两个异常构造均为 kwargs-only(`reason_code` 仅关键字),既有全部位置调用安全,`WorkerInterrupted` 继承兼容 ✓;`__init__.py` 导出正确(import + `__all__`)✓。

**④ 范围纪律。** 纯附加:枚举 + reason_code 管线 + 一处 content 分支 admissible 对齐(声明内)+ 测试 + 导出,无夹带 ✓。

## P2 记录(不阻塞接受)

- **P2-1(覆盖):** shell/glob/search/test-allowlist 等次要 typed 产出点无逐点测试连线;provider-facing 关键族(提案、apply、workspace 漂移、diff 应用)已全覆盖。最小修法:后续包为次要族补参数化断言,或将其标记为测试豁免并记录理由。
- **P2-2(健壮性):** tool-failed wrap 的 `DenialReasonCode(code_value)`(execution.py:1406 附近)对非枚举成员字符串会抛 `ValueError`;当前内部 wire 上不可达(值仅由枚举成员写入)。最小修法:`try/except ValueError` 回落为 `reason_code=None`,防御未来外部产出方。

## 对 cast §3 条件①/③ 的结论

条件①(denial reason 使用 typed reason code,不再仅依赖自由文本异常细节)在 provider-facing denial 族上**已满足**:机器可消费分类存在(枚举)、下游 wire(output dict → wrap → 属性)贯通、自由文本与 admissible hint 保留为补充证据。本审查给出 **exact head 991f42a5 上 ①② 范围无 P0/P1 的接受结论(APPROVE_WITH_P2)**。条件① 闭合尚需 founder 按 cast §3 汇总各范围审查(④⑤ 在 oracle 分支,不在本审查范围)后统一记闭合。
