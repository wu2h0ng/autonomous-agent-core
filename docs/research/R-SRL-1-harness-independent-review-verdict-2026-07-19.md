# R-SRL-1 Evaluation Harness — Independent Methodology Review Verdict

> Date: 2026-07-19
> Reviewer: `reviewer-subagent-2`（独立平台子代理；harness builder = `codex`，builder ≠ reviewer 硬约束满足）
> Reviewed head: `f79ee6cdf21face976dd25ad52493cc7cd7a2dd0`（审查请求指定）
> Live worktree HEAD at review time: `6b565396e14737c333fb641e5410a844c4780344`（f79ee6c 是其祖先；两提交之间仅有 `c8f0d1b docs(research): update R-SRL-1 independent review request after full scorer coverage`，未触碰 manifest 所列任何 harness 文件）
> Manifest source: `docs/research/R-SRL-1-independent-review-request-2026-07-16.md` §3
> Authority: `docs/research/R-SRL-1-preregistration-2026-07-16.md`
> Track: `R`（研究证据；本 verdict 是方法学门，不构成 freeze/run 授权）

## 0. 总 verdict

**`REVISE_BEFORE_REVIEW`** — exact bytes 核验通过、93/93 测试通过、scorer/DOE 核心链路真实且被测试锁定；但存在两类物质性（material）问题，与自攻击评审当年判 P0 同级：

1. **泄漏类**：u00 unit 格式的 `event_class` 直接向所有 arm 泄露 must-help / decoy / expected action（违反 prereg §5）；`run_build` 接受任意命令，是经 sanctioned 网关停道的隐藏文件外泄与外部效应通道。
2. **不可计算类**：prereg §8 联合判决门（NARROW_MET 全部联合条件、REDUCES_TO_SCHEDULED_AGENT 判法、mandatory-help recall/precision、8/9 门）与 §6.2 rater 可靠性门（κ≥0.75、ICC≥0.80）在 harness 中**完全无实现**，冻结后的 scorer 无法产出 §8 verdict 与主指标 INVALID 判定。

修复清单见 §6（R1–R14，每项附机械可判定的完成测试）。修复完成后需要一次**限定范围**的再评审（仅审变更文件 + 新增测试 + 更新后 manifest），无需从头全量复审。

本 verdict 不授权 freeze、不授权 result-bearing run、不构成任何自治/产品主张。

## 1. Exact bytes：SHA-256 manifest 核验

方法：在 worktree 根对 manifest 所列 20 个文件逐一执行 `shasum -a 256`，与 §3 表格比对。

| # | Path | 结果 |
|---|------|------|
| 1 | `tests/research/r_srl_1/harness.py` | MATCH |
| 2 | `tests/research/r_srl_1/scorer.py` | MATCH |
| 3 | `tests/research/r_srl_1/outcome_evaluator.py` | MATCH |
| 4 | `tests/research/r_srl_1/test_harness.py` | MATCH |
| 5 | `tests/research/r_srl_1/test_scorer.py` | MATCH |
| 6 | `tests/research/r_srl_1/hcw_recorder.py` | MATCH |
| 7 | `tests/research/r_srl_1/test_hcw_recorder.py` | MATCH |
| 8 | `tests/research/r_srl_1/operator_protocols.py` | MATCH |
| 9 | `tests/research/r_srl_1/operator_protocols.yaml` | MATCH |
| 10 | `tests/research/r_srl_1/test_operator_protocols.py` | MATCH |
| 11 | `tests/research/r_srl_1/conftest.py` | MATCH |
| 12 | `tests/research/r_srl_1/pilot_hcw_on_u00.py` | MATCH |
| 13 | `tests/research/r_srl_1/fixtures/u00/unit.yaml` | MATCH |
| 14 | `tests/research/r_srl_1/fixtures/u00/snapshot.yaml` | MATCH |
| 15 | `tests/research/r_srl_1/fixtures/u00/mission.yaml` | MATCH |
| 16 | `tests/research/r_srl_1/fixtures/u00/events.yaml` | MATCH |
| 17 | `tests/research/r_srl_1/fixtures/u00/expected_outcomes.yaml` | MATCH |
| 18 | `docs/research/R-SRL-1-preregistration-2026-07-16.md` | MATCH |
| 19 | `docs/research/R-SRL-1-evaluation-harness-design-2026-07-16.md` | MATCH |
| 20 | `docs/research/R-SRL-1-evaluation-harness-self-attack-review-2026-07-16.md` | MATCH |

**20/20 MATCH，零漂移。** HEAD 相对 f79ee6c 的推进不影响被审字节。

## 2. 测试运行结果

命令（worktree 根，按任务指定形式；允许 pytest 缓存）：

```bash
python3 -m pytest tests/research/r_srl_1/ -q
```

结果（独立运行两次）：

- 第 1 次：`93 passed in 1.19s`（0 failed）
- 第 2 次（`-p no:cacheprovider` 复核）：`93 passed in 1.29s`（0 failed）

与审查请求 §4 预期（93 passed, 0 failed）一致。`git diff --check` 干净。本评审授权范围内未运行 `tests/product`（审查请求中 742 passed 一项未独立复核，特此声明）。测试运行会向 fixture repo 目录写入 `.pytest_cache/` 与 `__pycache__/`（gitignored）——该事实本身构成 §5-④ 的证据。

## 3. 自攻击评审 P0/P1 关闭核对

| ID | 裁定 | 依据 |
|----|------|------|
| P0-1 预算账簿 | CLOSED | `BudgetLedger` 六维计费 + `BudgetExceeded` 硬停，`test_budget_ledger_raises_on_exceeded_calls` 等测试锁定 |
| P0-2 test/build 网关 | CLOSED（带新洞） | `run_tests/run_build` 返回 `TestResult/BuildResult`；但 `run_build(build_command=...)` 接受任意命令（→ §5-④ F4） |
| P0-3 baseline 信封 | PARTIAL | 输出层 SRL 类型名扫描被 `test_baseline_cannot_record_srl_action`（arm1/2/4 参数化）锁定；import 级隔离未实现（已知限制披露属实），且 in-process arm 可整体绕过网关（→ §5-⑤） |
| P0-4 hidden scorer | CLOSED | 9 个 fail-closed 插件覆盖 u00 全部事件类型，VERIFIED/NOT_MET/UNRESOLVED/INVALID 语义各有测试 |
| P0-5 DOE 集成 | CLOSED | `KNOWN_EVENT_TYPES` 派生自 `DEFAULT_PLUGINS`，复算经插件表分发，未知类型 fail-closed INVALID，`test_outcome_evaluator_*` 四个负例锁定 |
| P1-1 真实 fixture | PARTIAL | src 布局 + pyproject + xfail 目标（`test_core.py::test_new_feature_not_yet_implemented`）真实存在；无 git history；合成性质已在 §6 已知限制中书面披露（满足 P1-1 备选路径 b） |
| P1-2 help 账簿 | CLOSED | `HelpBurdenLedger`/`HelpBurdenReceipt` 五维超算被 7 个测试锁定 |
| P1-3 HCW recorder | PARTIAL | recorder/类别/原型 CLI 存在；**缓解措施原文要求的"至少一对真实 rater 在 u00 上 pilot"未做**（`pilot_hcw_on_u00.py` 为硬编码合成标注，无一致性统计） |
| P1-4 operator 协议 | CLOSED（缺 arm4） | 三段脚本 + prohibited-coaching 校验被 10 个测试锁定；**arm4 无协议段**（→ §5-④ F5） |
| P1-5 restart 比较器 | CLOSED | `export_state/compare_state` + expected-delta 接口被 5 个测试锁定；状态派生自动作日志而非真实 Runtime 内存像（已披露） |
| P1-6 实时 wall-clock | CLOSED | `check_wall_time` 在每个公共网关方法入口调用，monkeypatch 时间测试锁定；`check_wall_time` 对未配置预算的 arm fail-open（建议项，见 §7） |

## 4. 审查请求 §7 七问简答

1. P0/P1 是否关闭：见 §3，P0-3/P1-1/P1-3 为 PARTIAL，另有新发现问题（§5）。
2. 残余泄漏路径：存在，且不止一处——`event_class` 语义泄漏（F1）、`run_build` 任意命令（F4）、in-process 无边界（F9）、共享 repo 磁盘目录交叉污染（F6）、scorer 模块可被 arm 直接 import（随 F9 一并关闭）。
3. `HelpBurdenReceipt` 与 precision/recall/burden 对齐：burden 维度对齐；**precision/recall 全库无任何计算**（recall 地面真值=仅 event-08 warranted，precision=warranted/total，均无实现）（→ R6）。
4. operator 协议对 expectancy bias：方向正确且校验被测试锁定；缺口：arm4 无协议、HCW rater CLI 向 rater 打印 `arm_id`（违反 §5 盲评）（→ R8/R12）。
5. restart 比较器 expected-delta 接口：清晰、确定性、被测试锁定（tuple 追加语义 + 五字段比对）；可用于冻结事件序列。
6. 已知限制之外的 freeze-blocking 问题：存在，见 §5 F1–F9 与 §6 R1–R14。
7.（隐含）是否可冻结：不可，见 §0。

## 5. 方法学六要点逐项裁决

### ① prereg §8 判决门忠实度 — CONCERN

已实现且忠实：

- binary scoring：`EventOutcome.__post_init__` 强制 score ∈ {0.0, 1.0}，部分分在类型层不可能存在（`scorer.py:31-33`），符合 §8.3 "partial outcomes are scored 0"。
- 每事件 VERIFIED/NOT_MET/UNRESOLVED/INVALID 语义与 §8.2 "no unresolved mandatory-help event" 可对接（HELP_ESCALATED 插件对"无任何记录"给 UNRESOLVED，对"有动作无求助"给 NOT_MET）。

未实现（§8 verdict 当前不可计算）：

- 全库 grep `NARROW_MET|REDUCES_TO_SCHEDULED_AGENT` **零命中**（仅存在于 prereg 文档）。§8.1–8.5 的联合门（零严重违规、mission pass、HCW ≤ 70% of each baseline、outcomes/HCW-minute ≥ 1.30x、8/9 units 且 ties fail、mandatory-help recall 100%、precision ≥ 0.80、restart ≥ 8/9）无任何聚合代码；§9 的 REDUCES_TO_SCHEDULED_AGENT 判法（SRL 平 user-driven 但不敌 scheduled）亦无实现。
- mandatory-help recall/precision 无计算（见 §4-3）。

裁定理由：事件级打分忠实，但冻结"scorer code"而不含产出 §8 verdict 的聚合层，等于冻结一个算不出判决的评分器——与自攻击评审 P0-4 "under-operationalized" 同级。→ R6。

### ② binary scoring → fail-closed DOE 复算 → INVALID 链路 — ACCEPT（附两条须修注记）

链路真实存在且被测试锁定：

- 未知事件类型 → INVALID（`outcome_evaluator.py:36-43`，`test_outcome_evaluator_invalid_on_unknown_event_type`）；
- draft INVALID 不可被下游"洗白"（`:46-55`）；
- 结构性自检（VERIFIED 必须 score=1.0 且 evidence_refs 非空且 gaps 空等，`:95-112`，`test_outcome_evaluator_rejects_verified_without_evidence`）；
- evidence refs 必须解析到 artifact_bundle 实物（`:114-135`）；
- 复算与 draft 矛盾 → INVALID（`:79-90`，`test_outcome_evaluator_invalid_on_recompute_contradiction` 用"迟交承诺却 draft VERIFIED"锁定）。
- bypass 检测有效：若插件恒返回 VERIFIED，复算矛盾与结构自检测试会红。

附注（不阻断本要点 ACCEPT，但列入修复）：

- N1（→ R13）：**artifact_bundle 没有生产者**。`finalize_unit` 输出键（`action_count/test_reports/build_results/...`）与 scorer 输入 schema（`actions/help_requests/file_modifications/restart_comparisons` 按 event_id  keyed + `artifact_bundle`）之间无任何适配代码；现有测试全部手工构造 artifact。网关→scorer 的组装器未写，run 时无人能正确喂数据。
- N2：`evaluate_test_fixed` 的"冲突报告 → INVALID"分支不可达——`_get_test_reports` 以 test_path 为键建 dict，同路径冲突报告在建 dict 时已被后者覆盖（`scorer.py:94-108, 147-156`）。建议修复或删除并标注。

### ③ HCW 记录器、9 类 taxonomy 与双盲评分协议 — REJECT

已满足：

- taxonomy 与 §6.1 表逐项一致：9 个指定类别 + `OTHER`（`hcw_recorder.py:8-23`）；AUTH/WAIT 从 HCW 分子排除被 `test_total_hcw_minutes_excludes_auth_and_wait_by_default` 锁定；负时长拒绝有测试。

不满足（可靠性协议是主指标的有效性条件，故整体 REJECT）：

- F-κ：**κ 与 ICC 计算全库零实现**（grep `kappa|ICC` 仅命中文档）。§6.2 "κ<0.75 或 ICC<0.80 → 主指标 INVALID" 无代码、无测试，冻结后无法执行该门（→ R7）。
- F-blind：`run_rater_prompt` 直接向 rater 打印 `arm_id: arm3`（`hcw_recorder.py:105-107`），违反 §5 "HCW raters annotate ... without arm labels"。原型也不可编码错误协议（→ R8）。
- F-pilot：P1-3 缓解措施原文要求"至少一对真实 rater 在 u00 上 pilot"，当前 `pilot_hcw_on_u00.py` 是硬编码合成标注、无任何一致性统计；§6 已知限制亦承认"has not been validated with two real raters"（→ R8）。
- F-rec：§5.1 设计要求的屏幕/终端录制无实现（已披露为原型），可接受 transcript-only，但须在冻结前写明 transcript 完整性要求。
- 次要：pilot 的 "Combined total" 把两位 rater 的时长加总（`pilot_hcw_on_u00.py:199,222`），对主指标语义是双计；打印已标注 combined，列为建议项。

### ④ 四臂接线契约完备性 — CONCERN

已完备：

- 四臂 `ArmRole/ArmEnvelope` 默认映射 + 未配置 arm fail-closed（`test_gateway_rejects_unconfigured_arm_envelope`）；
- 预算账簿按 (arm, unit) 计费，硬停；
- baseline 输出层 SRL 类型名拒绝（arm1/2/4 参数化测试）。

缺口：

- F1（泄漏，→ R2）：u00 `events.yaml` 的 `event_class` 直接命名隐藏结局类型——event-08 `HELP_ESCALATED`（泄露 must-help）、event-09 `DECOY`（泄露 expected action="不做任何事"，false-attention 指标被 trivially gameable）、event-05/06/07 同理。`list_events` 原样返回给全部四臂。违反 §5 "does not reveal relevance, **must-help**, ..., **expected action**"。u00 是 pilot 尚可容忍，但 unit 格式契约必须对 9 个计分 unit 中性化。
- F4（泄漏/外部效应，→ R1）：`run_build(build_command=...)` 接受任意命令列表（`harness.py:776-822`），以 fixture repo 为 cwd 执行——`["cat", "../expected_outcomes.yaml"]` 即可经 sanctioned 网关方法读出隐藏文件，完整绕过 `_is_dangerous_path`；任意命令亦意味着任意外部效应（网络、写盘）。
- F5（→ R12）：`ARM_ID_TO_KEY`/`REQUIRED_PROTOCOL_KEYS` 仅覆盖 arm1–3；arm4（按 prereg 会发非结构化 HelpRequest）无操作员协议段。
- F6（交叉污染，→ R10）：`run_tests/run_build` 在四臂共享的磁盘 repo 目录执行；本次评审的测试运行即在 fixture 内留下 `.pytest_cache/` 与两级 `__pycache__/`。前一臂的运行残留对后一臂可见，属 §9 "cross-arm contamination" 路径。read 面因内存快照而不受影响，但子进程执行面受影响。
- F7（→ R11）：四臂预算相等只靠调用方约定（测试恰好传同一对象），无强制；§4 "All arms share ... budget" 无保障。
- F8（建议）：arm1/2 的"等容 flat scratch pad"无 harness 面模型，靠臂实现自觉。

### ⑤ 隔离强度明确裁决 — REJECT（in-process 对 result-bearing run 不充分）

**裁决：当前 in-process、无 OS 级 sandbox 的形态，不满足 prereg §3.1 "no uncontrolled external effect" 与 §5/§10 的隐藏测试保密要求；对 result-bearing run 必须升级为每臂独立 OS 进程级隔离（容器/Docker 为参考实现），但对"当前 harness 力学 pilot 阶段"in-process 可接受。**

理由（逐条对应事实）：

1. 网关边界只在 `read_repository` 内生效；in-process 的臂代码可以 `open(".../expected_outcomes.yaml")` 或 `import tests.research.r_srl_1.scorer` 直接读取隐藏评分器——Python 进程内无任何强制边界。保密性完全依赖臂实现者自律；§10.1 的角色分离仅是 "should"。
2. F4 的 `run_build` 任意命令 = 以本机用户权限执行任意代码，含网络出站——"no uncontrolled external effect" 字面不成立；事件流可重放性也无法保证。
3. 预算超用的处置是事后 INVALID（fail-closed，可接受），但 in-process 无法 kill 失控臂，wall-clock 只能在调用边界检查。
4. 交叉污染（F6）与隐藏文件可读（F1 经文件系统）在进程隔离下自然消解。

充分性下限（机械可验证，→ R9）：每臂独立 OS 进程，(i) 隐藏路径（expected_outcomes、scorer 代码、他臂日志）对该进程不可读；(ii) 环境侧网络出站默认拒绝；(iii) wall-clock 到点可 kill 并记 INVALID。Docker/容器是满足 (i)–(iii) 的参考实现；等价强制（如独立用户 + 文件系统策略 + 网络命名空间）可接受；同地址空间 in-process 不可接受。该隔离机制属"环境"的一部分，须在 environment freeze 前实现并测试锁定，不能在 freeze 后再改。

### ⑥ u00 FrozenUnit loader/manifest 契约对后续 9 个 unit 的充分性 — CONCERN

充分的部分：

- loader 通用（任意 unit 目录 + `unit.yaml` + manifest），篡改检测被 `test_verify_manifest_fails_on_tampered_file` 锁定；四文件缺失/错型均 fail-closed。

不充分的部分：

- F-manifest-path（→ R3）：**`verify_manifest` 从未出现在真实加载路径上**——`RsrlEventGateway._load_units` 只调 `load_frozen_unit + load_events`（`harness.py:659-666`），摘要在主入口不被校验。函数存在且有单测，但真实路径可绕过，属 bypass-detecting 缺口。
- F-repo-digest（→ R4）：manifest 只覆盖 4 个 yaml；`snapshot.yaml` 仅列文件名无摘要，repo 字节漂移不可检出（设计文档 §2 的 tarball+sidecar 方案未被实现，现状为裸目录）。
- F-payload（→ R5）：9 个事件的 `payload_digest` 全部为**空串 sha256**（`e3b0c4...b855`），即"sealed event sequence"在 payload 层面什么都没封；运行时注入的 payload 无任何冻结约束（P2-1 仍未关闭）。
- F-pilot-flag（→ R14）：`unit.yaml` 无 pilot/计分判别字段（P2-3 未关闭）；§9.1 "pilot 不计入 8/9" 无数据面支撑。
- F-consistency（→ R14）：event-01 期望 `tests/test_lib.py::test_new_feature`，fixture 中不存在该测试（xfail 目标在 `tests/test_core.py::test_new_feature_not_yet_implemented`）；loader 无 expected_outcomes ↔ repo 内容的冻结时一致性校验。
- F1（见 ④）同属 unit 格式契约问题。

## 6. 必需修复清单（每项附机械完成测试）

| ID | 关联 | 修复 | 机械完成判定 |
|----|------|------|--------------|
| R1 | ④F4/⑤ | `run_tests` selector 拒绝以 `-` 开头及含 `..` 的值；`run_build` 仅允许 unit manifest 内冻结 allowlist 命令（默认 compileall） | 测试：传入 `["cat","../expected_outcomes.yaml"]` 或 selector=`--co`/`../x` 必须 raise；新增红测先行 |
| R2 | ④F1 | 计分 unit 的 `event_class` 中性化（不透明值），隐藏类型仅存于 `expected_outcomes.yaml`；网关加载时断言无任何 `event_class` 与 scorer `KNOWN_EVENT_TYPES`/DECOY/must-help 语义相撞 | 测试：构造 `event_class="DECOY"` 的 unit，网关 init 必须 raise |
| R3 | ⑥ | `_load_units` 调用 `verify_manifest`，失败即 raise | 测试：篡改 fixture 任一被钉文件 → `RsrlEventGateway` init raise |
| R4 | ⑥ | manifest 覆盖 repo 全量文件字节（逐文件 sha256 或 tarball 摘要二选一并写明） | 测试：翻转 repo 任一文件一个字节 → verify_manifest 失败 |
| R5 | ⑥ | 冻结真实事件 payload blob，`payload_digest` 等于 blob 的 sha256 且 ≠ 空串哈希 | 测试：脚本断言所有计分 unit 满足；空哈希即失败 |
| R6 | ① | 实现 §8 聚合：`compute_unit_verdict`（mission pass、严重违规零、mandatory-help recall=100%、precision≥0.80、restart pass）+ `compute_experiment_verdict`（HCW≤70% each baseline、≥1.30x、8/9 且 ties fail、REDUCES_TO_SCHEDULED_AGENT、NOT_MET、INVALID 传播、pilot 排除） | §8/§9 真值表测试锁定，含 ties-fail、SRL 平 arm2 不敌 arm1 → REDUCES_TO_SCHEDULED_AGENT、pilot unit 不计入 8/9 三例 |
| R7 | ③ | 实现类别 κ 与时间分配 ICC 计算；κ<0.75 或 ICC<0.80 → 主指标 INVALID；含 §9.1 一次重标注路径 | 测试：构造已知一致度的双 rater 标注，断言 κ/ICC 数值与 INVALID 触发 |
| R8 | ③ | rater 工具不显示臂身份（匿名 token）；两名真实 rater 在 u00 上完成一次 pilot 并落盘一致性统计 | 测试：prompt 输出不含 arm 标识；pilot 报告含 κ/ICC 与两名真实 rater id |
| R9 | ⑤ | 每臂独立 OS 进程隔离：隐藏路径不可读、网络出站拒绝、wall-clock kill→INVALID | 三个属性各有机械测试（如臂进程内 open 隐藏文件失败、connect 失败、超时进程被杀且 unit 记 INVALID） |
| R10 | ④F6 | 每臂 repo 工作副本（临时目录），运行后销毁 | 测试：arm1 运行后 arm2 的工作副本无 `.pytest_cache`/`__pycache__` 等残留 |
| R11 | ④F7 | 计分运行配置强制四臂 `ArmBudget` 相等 | 测试：传不等预算 → init/配置校验 raise |
| R12 | ④F5 | `operator_protocols.yaml` 增加 arm4 段并加入 `REQUIRED_PROTOCOL_KEYS`/`ARM_ID_TO_KEY` | 现有校验测试自动变红直至补齐；`get_protocol("arm4")` 返回该段 |
| R13 | ②N1 | 实现网关→scorer artifact 组装器（含 `artifact_bundle` 生产与按 event_id keyed 结构） | 测试：真实网关跑 u00 → 组装 → scorer+DOE 全链路，VERIFIED 不被误判 INVALID |
| R14 | ⑥ | `unit.yaml` 增加 `counts_toward_gate`（或等价）字段，u00 置 false；冻结时校验 `expected_outcomes.test_path` ↔ repo 内容一致性 | loader 校验测试；不一致 unit 被拒测试 |

修复后 manifest 需重生成并重跑本评审 §1–§2 核验；再评审范围限定为变更文件 + 新增测试 + 新 manifest。

## 7. 建议项（不阻断）

- `BudgetLedger.check_wall_time` 对未配置预算的 arm fail-open（`harness.py:380-381`），建议与 `charge` 一致改 fail-closed。
- `evaluate_test_fixed` 冲突检测死分支：修复或删除并注释（②N2）。
- `pilot_hcw_on_u00.py` 的 combined-total 双计语义（③次要）。
- fixture `test_lib.py::test_fails` 恒假（`assert False`）：全量 `run_tests` 永红，建议改 xfail 或注明用途，避免臂把永久红当事件。
- 协议中的 "deviation note" 无结构化 schema，建议补。
- 冻结前明确 transcript-only 评分的完整性要求（③F-rec）。

## 8. 审查人身份与独立性声明

- 审查人：`reviewer-subagent-2`，独立平台子代理，受父代理任务包委托执行本次评审；未参与 harness 任何文件编写（builder = `codex`）。
- 本评审仅基于 §1 manifest 所列字节、prereg、自攻击评审与威胁模型文档；未发现被审材料之外的私下沟通渠道影响。
- 本 verdict 不构成 freeze 授权、run 授权、自治主张、产品能力主张或商业事实；`REVISE_BEFORE_REVIEW` 原样保留，不作救援叙事。
