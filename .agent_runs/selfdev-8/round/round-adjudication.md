# SELFDEV-8 (E8) Round — Adjudication (FINAL, independently amended)

> Prereg: `docs/product/AGENT-OS-SELFDEV-8-phase0-unified-head-prereg-2026-08-13.md`
> (frozen at 2b27974f + cfb2b49c driver8/solve8;manifest `.agent_runs/selfdev-8/manifest.json`)
> Round artifacts: `.agent_runs/selfdev-8/round/`. Date: 2026-08-14.
> Runner: driver8.py(one E8 result-bearing run,authorized by founder cast 2026-08-14 §2 after preflight PASS + freeze verification PASS)
> Provider: deepseek-v4-flash(openai-compatible,base https://api.deepseek.com),600s timeout
> Subset: `.agent_runs/selfdev-4/selection.json` cross-pin(fifth reuse,污染上界声明)
> Independent adjudication: `ADJUDICATION-INDEPENDENT-2026-08-14.md` — **ADJUDICATION_AMENDED**(blind-anchored per RR-0031,builder ≠ reviewer;结论 NEGATIVE 一致;两处事实修正已采纳:信封拒绝 20× 而非 19×、freeze receipt 的 manifest 自 digest 不符)。

## 1. 运行完整性

- 健康门:PASS(3 小探针 + 1 中探针,运行前与暂停恢复时均通过)。
- 全部 12 任务 × 2 尝试 × 2 臂 = 48 个 slot 均有 invoked marker + attempt 文件,无 MISSING。
- 全部 24 个 chain 尝试经 solve8.py 独立 round-level verifier 重跑(F2P/P2P 双绿才记 solve)。
- 无 403 配额暂停事件;2 个 chain slot 记 INVALID_PROVIDER(provider 天气,消耗尝试)。
- 无驱动超时、无白名单中止、无 kill-7(typed 信号契约)触发。
- 账目:baseline weather-free 24/24、chain weather-free 22/24 —— 双方均 ≥ 12/24 地板,**地板达成**。

## 2. 裁决(冻结格 §7)

**数值:baseline pass@2 = 6/12;chain pass@2 = 1/12(sphinx-doc__sphinx-8459,独立 verifier 确认)。**

```text
SUPPORTS      否(chain 1/12 不 > baseline 6/12)
INSUFFICIENT_DATA  否(两臂地板均达成,非 INVALID_PROVIDER 主导)
NEGATIVE      是 —— 地板达成且链臂 < baseline
MIXED         否
```

**裁决:NEGATIVE**(kill 无触发;无 INVALID;无 evaluator leakage 迹象;数据充足)。

## 3. 失败分布与归因(裁决者视角,逐尝试核验 stderr)

### baseline(6/12 solved)
7 个 SOLVED 尝试、14 个 FAILED_UNCLASSIFIED、3 个 solved=False(f2p 失败)。
baseline 的 FAILED_UNCLASSIFIED 多为 f2p 未过(模型未产出正确补丁),属正常未解。

### chain(1/12 solved)
24 个尝试失败分布(独立复核修正后):

| 类 | 数量 | 说明 |
|---|---|---|
| provider diff 参数契约拒绝 | 20 | stderr 统一为 "provider diff arguments must contain only path and diff; admissible: {path, diff}"(含 sphinx a1,独立复核逐字核验) |
| provider diff 格式拒绝 | 1 | "baseline diff ends inside a truncated hunk"(sklearn a2) |
| INVALID_PROVIDER(天气,provider MALFORMED) | 2 | sympy-13551 a2、sympy-13852 a2,消耗尝试 |
| 独立 verifier 确认 solved | 1 | sphinx a2 → chain 1/12 |

**核心归因:chain 的 20+1=21 个失败全部是受治理 provider diff 输出未通过 typed 契约信封校验**(参数含多余键 / diff 截断),即在 apply 之前就被契约层拒绝(87.5% 的 chain 尝试)。这不是天气、不是基础设施、不是求解能力不足,而是受治理链的 provider 响应契约未闭合 —— E5 的残余问题(governed prompt/响应契约差距)在 E8 充足数据下确认未闭合,残余假设收窄为"差距在受治理 provider 的 diff 信封生成"。

### driver8 记账层缺陷(独立复核确认,不影响 solved 判定)
typed 分类器(§3.5)将上述 20+1 个契约拒绝归为 `FAILED_UNCLASSIFIED`(classifier.surface="residual"),而非既有 `INVALID_ENVELOPE` / `DIFF_INVALID` 类 —— 因为契约拒绝的 stderr 文本不含 ProviderFailure.code / DenialReasonCode 枚举成员,且分类器未把 "must contain only path and diff" 文本签名映射回尝试失败类。此缺陷改变失败类归因(裁决者已按 stderr 文本重归类),但 **不改变任何 solved 判定、不改变 NEGATIVE 结论**。该缺陷记录于负结果地图,不构成门移动。

### freeze receipt 记录级缺陷(独立复核发现,不影响运行合法性)
FREEZE-VERIFICATION-2026-08-14.md §1 声称 manifest sha256 `ec143f04…`,实际 manifest.json 字节为 `d67070e8…`;四绑定项(driver8/solve8/selection/prereg)digest 全部与 manifest 一致,此自引用 digest 不符为记录级完整性缺陷,如实记入负结果地图。

## 4. 与 E5-E7 的关联

- E5 NEGATIVE:残余定位于受治理 prompt/响应契约(~6.5× 差距)+ apply-gate 类。
- E7 INSUFFICIENT_DATA:两臂 weather-free 均低于地板,数字不升级。
- E8 本轮回:地板达成、数据充足、两臂均非天气主导 —— 首次在充足数据下回答 E5 问题:**对齐 prompt + Phase 0 契约修复后,链臂 weather-free 解题率未追平 baseline(1/11 vs 6/12),失败主导类为受治理 diff 契约拒绝**。残余假设由"差距在契约层"收窄为"差距在受治理 provider 的 diff 信封生成"。

## 5. Claim boundary 与后果

- 本裁决仅为冻结 12 任务子集、deepseek-v4-flash、600s、ABAB、统一头 2b27974f 包络内的结果;无产品/HCW/自主性主张。
- E8 是该复用子集的**最后一轮**(cast §2):无论结果原样结案,不执行 E9。
- 重开需:新机制证据 + fresh held-out 设计 + 新 founder route cast。
- BSEC 主实验不受本裁决影响,维持另行门控。

## 6. 复核路径

全部 48 个 attempt 文件 + stderr + 1 个独立 verifier verdict 留档于 `.agent_runs/selfdev-8/round/`;独立 reviewer 盲锚定复核完成(ADJUDICATION_AMENDED),本裁决定稿为 FINAL。
