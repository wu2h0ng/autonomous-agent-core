# SELFDEV-8 (E8) Independent Adjudication — ADJUDICATION_AMENDED

> Reviewer: 独立 adjudicator 会话(selfdev-8-e8-adjudicator),blind-anchored per RR-0031,无 builder 历史与 round 预读(builder ≠ reviewer;reviewer 未触碰任何 attempt 文件或 round-adjudication.md,one writer per file)。
> 复核对象:`.agent_runs/selfdev-8/round/round-adjudication.md`(draft,待复核定稿)+ 全部 48 个 attempt 文件 + 24 个 chain/baseline stderr + `e8-summary.json` + `progress.json` + `round-console.log` + 唯一独立 verifier verdict(`sphinx-doc__sphinx-8459/chain-attempt-2-verdict.json`)。
> 基线:prereg `AGENT-OS-SELFDEV-8-phase0-unified-head-prereg-2026-08-13.md`(冻结头 2b27974f,manifest `.agent_runs/selfdev-8/manifest.json`)§0.4 地板 12/24、§7 裁决格与 kill 条件、§3.5 三项授权变化、§6 verifier 流程;founder cast `docs/research/founder-decision-2026-08-14-bsec-first-round-freeze-cast.md` §2(E8 终轮,原样结案,无 E9);负结果地图:E4 NEGATIVE、E5 NEGATIVE(~6.5× weather-free gap)、E6 NEGATIVE-with-caveat(83% 配额)、E7 INSUFFICIENT_DATA(两臂 weather-free 9/24、11/24 < 12/24)。
> 复核日期:2026-08-14。盲锚定先于任何 round 产物阅读。

## 0. 盲锚定声明

按 RR-0031,先读根仓 AGENTS.md(§11 研究纪律、§14 工程现实核查)、prereg 全文、founder cast 全文、E4/E5/E6/E7 裁决全文(E7 含 round-adjudication.md),再读任何运行产物。判定基线:裁决只能由冻结格产出;数字必须逐文件复算;不得以任何新叙事覆盖原始 verdict。

## 1. 独立复算结果

### 1.1 pass@2(prereg §7:chain 只认独立 round-level verifier 重跑;无 verdict 的 chain 尝试一律不算 solved)

| 臂 | 我的复算 | draft |
|---|---|---|
| baseline pass@2 | **6/12**(7 个 solved 尝试,6 任务:django-10880 a1、django-11066 a2、pylint-7277 a1、pytest-5631 a1、sympy-12419 a2、sklearn-13328 a1+a2) | 6/12 ✓ |
| chain pass@2 | **1/12**(唯一 solved = sphinx-8459 chain a2,`chain-attempt-2-verdict.json` solved=true、f2p/p2p 双绿、independent_verifier=true) | 1/12 ✓ |

证据路径:全部 24 个 baseline attempt json(`solved`/`f2p_passed`/`p2p_passed` 三字段逐一读取)+ 唯一 verdict.json。baseline solved 尝试与 e8-summary.json `baseline.*.solved` 数组一致。

**裁决格结论:chain 1/12 不严格 > baseline 6/12 ⇒ SUPPORTS 否;地板达成且无 kill ⇒ INSUFFICIENT_DATA 否;地板达成且 chain < baseline ⇒ NEGATIVE。与 draft 一致。**

### 1.2 充足性地板(§0.4:weather-free = 24 − INVALID_PROVIDER,每臂 ≥ 12)

| 臂 | INVALID_PROVIDER 计数 | weather-free | 地板 |
|---|---|---|---|
| baseline | 0(全部 24 个 stderr 无 ProviderFailure.code 命中) | 24/24 | 达成 ✓ |
| chain | 2(sympy-13551 a2、sympy-13852 a2,stderr 均为 `provider MALFORMED: provider response malformed: ValidationError`) | 22/24 | 达成 ✓ |

**地板达成,数据充足。与 draft 一致。**

### 1.3 失败类分布(chain,24 个尝试,逐条读 stderr + attempt json)

| 类 | 我的复算 | draft | 差异 |
|---|---|---|---|
| 参数信封拒绝("must contain only path and diff",execution.py:1395) | **20** | 19 | **draft 少计 1** |
| diff 截断("BASELINE_DIFF_INVALID: baseline diff ends inside a truncated hunk",sklearn-13328 a2) | 1 | 1 | ✓ |
| INVALID_PROVIDER(provider MALFORMED) | 2 | 2 | ✓ |
| 独立 verifier 确认 solved | 1(sphinx-8459 a2) | 1 | ✓ |
| BENCHMARK_PROVIDER_RUN_COMPLETED(未解) | **0** | 1(sphinx a1) | **draft 错标** |

**draft 的两处事实错误:**
1. draft §3 表格称 `sphinx-doc__sphinx-8459 chain a1` 为 "BENCHMARK_PROVIDER_RUN_COMPLETED(未解)…完整运行但未产出可验证候选"。逐字节核验 `sphinx-doc__sphinx-8459/chain-attempt-1.json`:attempt_class=FAILED_UNCLASSIFIED、classifier.surface="residual"、stderr_tail = "provider diff arguments must contain only path and diff; admissible…no other keys";`chain-attempt-1-stderr.log` 同文。**sphinx a1 是第 20 个参数信封拒绝,不是完整运行。**
2. 因此 draft "19+1=20 个契约拒绝" 应为 **20+1=21 个**(信封 20 + 截断 1)。归因方向("受治理 diff 契约拒绝为主导类")不变,占比 21/24 = 87.5%(draft 的 20/24 = 83.3%)。

### 1.4 kill 检查(§7 kill 条件 + §0.3 + kill-7)

| 检查项 | 结果 | 证据 |
|---|---|---|
| 403 配额暂停滥用 | 无暂停;无 403/AUTHENTICATION_FAILED | 全部 48 stderr grep 零命中;console log 无 pause 事件 |
| 白名单中止误触发 | 无 GENUINE_INFRA 分类(0 次),无容器/workspace 白名单命中 | 全部 attempt json classifier.class 均为 INVALID_PROVIDER 或 FAILED_UNCLASSIFIED |
| typed kill-7 契约破坏 | **未触发** | 信封拒绝在 execution.py:1399 带 `reason_code=DenialReasonCode.PROPOSAL_ENVELOPE_KEYS`(① 枚举族内,带码);MALFORMED 为 `ProviderFailure.code` ④ 族(execution.py:1347,带码);截断为 `BenchmarkTaskValidationError` BASELINE_DIFF_INVALID(typed,非① 族缺码面)。均无缺码事件 |
| envelope 漂移 | 无 | 运行头 2b27974f;cfb2b49c 仅新增 `.agent_runs/selfdev-8/`(driver8/solve8/manifest/verification),9a495f30 仅新增 round 产物;无 runtime 代码改动 |
| ABAB 顺序 | 成立 | round-console.log 每任务 B1→C1→B2→C2 交错,12 任务顺序与 manifest subset.main 逐字一致 |

### 1.5 冻结完整性

| 项 | 结果 |
|---|---|
| driver8 digest | 8be4595f…4f702 = manifest 绑定 ✓(独立 shasum) |
| solve8 digest | 4c02623d…3c6db = manifest 绑定 ✓ |
| selection cross-pin | 735b2643…ca7e5 = selfdev-4 manifest `/files` 值 ✓(第五次复用,字节同一) |
| prereg digest | 9873525f…de6bd = manifest 绑定 ✓ |
| 统一头 | manifest 绑定 2b27974f;运行代码树为该头(见 1.4)✓ |
| **manifest 自身 sha** | **FREEZE-VERIFICATION-2026-08-14.md §1 声称 `ec143f04a27c6a14c217515cb11e66f93d275115e76c629a4d2528531321f87e`,但实际 `manifest.json` 字节 sha256 = `d67070e8544f6a6c4e962c0aca7be058ffa2a7042b6850316cbc4c9c67c16313`(提交 cfb2b49c 内即如此)。冻结 receipt 的 manifest 自引用 digest 与实际字节不一致(记录级缺陷,不影响 driver8/solve8/selection 四绑定项一致性)** |

### 1.6 driver8 记账缺陷(草稿已如实记录,独立确认)

- 21 个契约拒绝(20 信封 + 1 截断)全部被 driver8 `classify_attempt()` 归为 **FAILED_UNCLASSIFIED(surface="residual")**,而非 INVALID_ENVELOPE/DIFF_INVALID 类。根因:stderr 文本不含 `DenialReasonCode` 枚举成员字符串("PROPOSAL_ENVELOPE_KEYS" 等未出现在异常消息文本中,execution.py:1394 消息不带 reason_code 字面值),分类器按文本子串匹配(§3.5 映射表),故落入残余类。
- **对 solved 判定的影响:零**。chain solved 只认独立 round-level verifier verdict(solve8.py 输出),verdict.json 唯一且权威;该缺陷只改变失败类归因统计,不改变任何 solved 判定、地板计数(INVALID_PROVIDER 计数不受影响)与 NEGATIVE 结论。确认 draft 的处置正确。
- 附注:e8-summary.json 的 `chain.*.solved` 数组全空(未合并 verdict 结果),`sphinx` chain classes 显示 "?";与 verdict.json 的 1 solved 不一致——summary 层记账缺陷,verdict.json 为权威,chain 1/12 成立。

## 2. 独立裁决:ADJUDICATION_AMENDED

冻结格数值(§7)与最终结论 **NEGATIVE** 与 draft 一致、可独立复现,但 draft 的事实陈述有两处精确差异,按宪法 §11.5("记录 NOT_MET/INVALID/nulls 而不作叙事救援")与裁决义务,判定为 AMENDED 而非 ACCEPTED:

1. **失败分布计数错标**:draft §3 称 "19× 参数信封拒绝 + 1× diff 截断" 且将 sphinx a1 单列 "BENCHMARK_PROVIDER_RUN_COMPLETED(未解)"。实际为 **20× 参数信封拒绝 + 1× diff 截断(共 21 个契约拒绝)**;sphinx a1 的 stderr/json 逐字显示其为信封拒绝。证据:`.agent_runs/selfdev-8/round/sphinx-doc__sphinx-8459/chain-attempt-1.json` 与 `chain-attempt-1-stderr.log`。
2. **冻结 receipt 的 manifest 自 digest 不符**:FREEZE-VERIFICATION-2026-08-14.md 声称 manifest sha256 `ec143f04…`;实际字节 `d67070e8…`。四绑定项(driver8/solve8/selection/prereg)digest 全部一致,此不符不构成运行无效,但必须如实记录于负结果地图。

其余全部核验项(地板、kill、ABAB、冻结四绑定、记账缺陷不影响 solved)与 draft 一致。

## 3. 结论

- **裁决:NEGATIVE**(冻结格原样):该冻结 12 任务子集、deepseek-v4-flash、600s、ABAB、健康门、统一头 2b27974f 包络内,链臂 pass@2 1/12 < baseline 6/12;地板达成;无 kill;数据充足。
- 修正后归因:chain weather-free 失败 21/22 为受治理 provider diff 输出未通过 typed 契约信封校验(20 信封 + 1 截断)——E5 残余(受治理 prompt/响应契约差距)在 E8 充足数据下确认**未闭合**,残余假设由"差距在契约层"收窄为"差距在受治理 provider 的 diff 信封生成"。
- E8 为该复用子集**终轮**(founder cast 2026-08-14 §2):无论结果原样结案,不执行 E9;重开需新机制证据 + fresh held-out 设计 + 新 founder route cast。
- 本裁决不构成任何产品能力、HCW、自治或 `Autonomy(S,E,O,V,T)` 证据(prereg NON-CLAIMS 逐字承接)。

## 4. 对负结果地图的独立注记(E8 后残余假设的准确表述)

1. **"prompt 对齐 + Phase 0 契约修复闭合 E5 残余差距" 假设被证伪**(于该包络):充足数据下链臂 weather-free 1/11 vs baseline 6/12;差距主导类为受治理 diff 信封生成(模型产出的 apply_patch 参数含额外键 / diff 截断,契约层按设计拒绝)。
2. **残余假设精确表述**:差距可能位于 (a) 受治理 diff 信封生成的模型侧技能、(b) 链臂 prompt/响应契约的消息构造、(c) 该包络内治理 prompt 对 deepseek-v4-flash 的适用性——三者在本轮数据下不可区分(21 个契约拒绝均为同一信封面);不可表述为"治理层缺陷"或"模型能力不足"之外的任何升级主张。
3. **django-10880 context-mismatch 后续**:本轮 chain 两尝试均为信封拒绝,APPLY_FAILED(context-mismatch)未再出现;该残余项本轮无新证据,维持 E7 状态,不新增结论。
4. **记账层教训**:driver8 typed 分类器以 stderr 文本子串匹配 reason_code,而异常消息不含 reason_code 字面值 → 21 个 typed 拒绝落入 FAILED_UNCLASSIFIED。未来 harness 修复(若有,需新 prereg)应让 provider-facing denial 的 reason_code 出现在机器可消费字段而非仅消息文本;E8 本轮按其冻结语义结案,不追溯。
5. **冻结流程缺陷**:FREEZE-VERIFICATION 的 manifest 自 digest 与实际字节不符——记录级完整性核对项,建议未来 freeze receipt 在提交后重算最终字节;不影响本轮四绑定项与运行合法性。
6. **weather 不再是主导噪声**:E8 两臂 INVALID_PROVIDER 合计仅 2/48(4.2%),为系列最低;地板机制本轮正常值守(达成),无需 INSUFFICIENT_DATA。

## 5. 复核路径(给后任)

- 复算入口:48 个 attempt json + 48 个 stderr + 1 个 verdict.json + e8-summary.json + round-console.log(全部在 `.agent_runs/selfdev-8/round/`),manifest 与 freeze receipt 在 `.agent_runs/selfdev-8/`。
- 本文件不修改任何 attempt 文件或 round-adjudication.md(one writer per file);draft 定稿时须按 §2 两处差异更新,或以本文件为准并引用。
