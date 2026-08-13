# SELFDEV-8 (E8) Freeze Verification Receipt

> Status: `FREEZE_VERIFICATION / VERIFIED / RUN_NOT_STARTED`
> Date: 2026-08-14
> Verifier: portfolio steward session(mechanical byte/behavior verification;independent prereg review already PASS per RR-bsec-merged-rereview-2026-08-13;runner = driver8 执行会话)
> Authority: founder cast 2026-08-14 §2(preflight PASS 后 driver8/solve8 落地 + 冻结 + receipt 全绿 → 授权一次 E8)

## 1. 字节与 manifest 核验

| 项 | 结果 |
|---|---|
| manifest 文件 | `.agent_runs/selfdev-8/manifest.json`(schema selfdev-8-e8-prereg-manifest.v1) |
| manifest sha256 | `ec143f04a27c6a14c217515cb11e66f93d275115e76c629a4d2528531321f87e` |
| prereg digest | `9873525f…de6bd`(docs/product/AGENT-OS-SELFDEV-8-…-prereg-2026-08-13.md) |
| driver8 digest | `8be4595f…4f702` |
| solve8 digest | `4c02623d…3c6db` |
| selection cross-pin | `735b2643…ca7e5`(与 SELFDEV-4/5/6/7 manifest pin 逐字节一致) |

## 2. 语义差异核验(cast §2.2 — driver8 相对 driver7 仅 §3.5 三项)

以 `diff <(sed 's/selfdev-8/selfdev-7/g' driver8.py) driver7.py` 逐字节复核:

1. **abort classifier typed 三面**:`classify_attempt()` 按 14 个样例(ProviderFailure.code 4 类 / DenialReasonCode 3 类 / genuine-infra 5 类 / 残余 1 类 / 403 1 类)全部正确归类;E7 白名单成员集合(10 项)与 driver7 `GENUINE_INFRA_MARKERS` 逐字节一致(`whitelist_byte_identical_to_e7: true`)。✓
2. **SSE fail-closed**:`MALFORMED` 列入 `PROVIDER_FAILURE_CODES` → 消耗侧 INVALID_PROVIDER(消耗尝试,不中止/暂停),记账语义与 driver7 一致。✓
3. **scoped verifier 绑定(⑤)**:`SCOPED_VERIFIER_ENABLED = False`(默认不启用,沿用 §6 独立 round-level verifier)。✓

除以上三项与路径 selfdev-7→selfdev-8 外,`driver8.py` 与 `driver7.py` **逐字节相同**;`solve8.py` 与 `solve7.py` **逐字节相同**(仅路径)。

## 3. 统一接受头核验

- 运行头:`2b27974f898daba5ec5760c75916cf3e178ba3dd`(codex/canonical-convergence-20260715)
- 头性质:cd594117 统一头(Phase 0 条件 1/2/4/5 闭合)+ SELFDEV-8 prereg review 闭合提交;条件③ APPROVE_WITH_P2(f501cfc0)
- manifest 绑定头 commit,运行将以其 exact head 执行;运行前重验 docker/workspace/镜像/solver sanity(prereg §5)。

## 4. 健康门核验

- `health_gate()`:3 小探针 + 1 中探针(可提取 diff),遇 403 即门失败(prereg §0.5)。
- 静态核验:函数结构与 driver7 逐字节一致(在 §3.5 三项之外),`from agent_os_core import extract_unified_diff` 导入面存在(Agent OS 侧 2b27974f 已含 Phase 0 契约修复)。
- 动态运行需 provider 凭证;运行前由 runner 执行,失败则 ROUND NOT STARTED。

## 5. 结论

**FREEZE_VERIFICATION PASS(全绿)** — 字节、映射、选择集、统一头、健康门结构一致。按 cast §2,冻结 receipt 全绿授权**一次 E8 result-bearing run**(每任务 2 次尝试、ABAB、地板 12/24、pause-on-403、typed kill-7、retention、provider-unavailable 不记通过)。E8 为该复用子集终轮,任何结果原样结案,不执行 E9。
