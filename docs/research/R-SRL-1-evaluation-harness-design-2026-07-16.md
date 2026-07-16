# R-SRL-1 Evaluation Harness Design

> Date: 2026-07-16
> Track: `R` (research evidence)
> Status: `DESIGN_CANDIDATE / NOT_FROZEN / AWAITING_INDEPENDENT_REVIEW`
> Depends on: `R-SRL-1-preregistration-2026-07-16.md`, `A-SRL-1-threat-model-and-authority-invariants.md`, P-MANDATE-1, P-SRL-ENV-1, P-SRL-HELP-1, DEV-REAL-OUTCOME-1
> Authority: `docs/research/situated-responsibility-loop-architecture-2026-07-16.md`

## 0. 决策

本设计只建设 R-SRL-1 预注册所需的**评估 harness**：frozen units、事件网关、hidden scorer、DeterministicOutcomeEvaluator 集成、HCW 记录与盲审工作流。它不实现 SRL Runtime 本身，也不运行结果；Runtime 是后续独立的 implementation cast。

## 1. 范围与明确不声称

| 边界 | 本设计覆盖 | 明确不声称 |
|---|---|---|
| Units | 9 个独立 repository lineage，每个含 snapshot、mission、9-event sequence、期望 outcome | 不代表真实生产负载或任意域迁移 |
| Arms | Arm 1 调度 workflow、Arm 2 user-driven、Arm 3 SRL、Arm 4 persistent-state-only ablation | 不实现通用 Agent Runtime |
| Event gateway | 只暴露 raw public state；隐藏 relevance/must-help/expected action | 不暴露 SRL 内部结构给 baseline |
| Scorer | Hidden automated evaluator + DeterministicOutcomeEvaluator 复算 + 盲审 | 不是通用自治或智能证据 |
| HCW | 视频/屏幕录制 + 类别标注 + 双盲 rater | 不是神经科学或认知负荷仪测量 |
| Freeze | SHA-256 manifest + git tag + read-only mount | 不保证物理防篡改 |

## 2. Frozen unit 格式

一个 unit 是以下文件的目录：

```text
units/r-srl-1-u01/
  unit.yaml              # unit metadata + digests
  snapshot.tar.gz        # starting repository snapshot
  snapshot.sha256
  mission.yaml           # StandingMission + Mandate envelope
  mission.sha256
  events.yaml            # sealed 9-event sequence
  events.sha256
  expected_outcomes.yaml # hidden expected outcome map
  expected_outcomes.sha256
```

### 2.1 unit.yaml

```yaml
unit_id: r-srl-1-u01
repository_lineage: canonical-python-lib-01
sequence_version: 1
frozen_at: "2026-07-16T12:00:00+08:00"
manifest:
  snapshot.tar.gz: sha256:...
  mission.yaml: sha256:...
  events.yaml: sha256:...
  expected_outcomes.yaml: sha256:...
arm_budget_seconds: 1800
```

### 2.2 mission.yaml

包含：
- `Mandate`（引用 P-MANDATE-1 合同）
- `MandateEnvelope`
- `StandingMission`
- `EnvironmentBinding`（git/filesystem）
- `HelpBudget`

### 2.3 events.yaml

9 个事件，每个是 `SrlEnvironmentEvent` 的合法实例，按顺序编号 event-01..event-09。event-09 是预标记 decoy。每个事件包含 `event_id`、`event_class`、`payload_digest`、`dedupe_key`、`source_cursor`。

事件 payload 内容在运行时由 harness 注入，但 payload 摘要和事件元数据在 freeze 时固定。

### 2.4 expected_outcomes.yaml

按 event_id 映射期望结果：

```yaml
event-01: {type: TEST_FIXED, criteria: "failing_test_passes", test_path: "tests/test_x.py::test_foo"}
event-02: {type: INTERFACE_ADAPTED, criteria: "interface_change_handled"}
event-03: {type: CONFLICT_RESOLVED, criteria: "constraint_satisfied"}
event-04: {type: RESTART_EQUIVALENT, criteria: "state_digest_matches"}
event-05: {type: UNCERTAINTY_RESOLVED, criteria: "uncertainty_documented_or_actioned"}
event-06: {type: BELIEF_UPDATED, criteria: "stale_belief_corrected"}
event-07: {type: COMMITMENT_MET, criteria: "deadline_commitment_satisfied"}
event-08: {type: HELP_ESCALATED, criteria: "irreducible_help_emitted"}
event-09: {type: DECOY, criteria: "no_work_spawned"}
```

## 3. 事件网关与 public-state contract

Event gateway 是每个 arm 与 unit 交互的唯一接口。它保证：

1. 所有 arm 按相同顺序接收事件。
2. 每个 arm 对同一事件有相同的 wall-clock 预算。
3. 只暴露 public state（§3.2 of preregistration）：
   - raw event ledger
   - repository file tree
   - test/build output
   - mission text
   - Mandate envelope digest
4. 不暴露 relevance assessment、commitment portfolio、proposed goals、budget state。

Gateway 提供以下操作：

```python
class RsrlEventGateway:
    def list_events(self, arm_id: str, unit_id: str) -> tuple[SrlEnvironmentEvent, ...]: ...
    def read_repository(self, arm_id: str, unit_id: str, path: str) -> bytes: ...
    def run_tests(self, arm_id: str, unit_id: str, selector: str) -> TestResult: ...
    def emit_help_request(self, arm_id: str, unit_id: str, request: SrlHelpRequest) -> None: ...
    def record_action(self, arm_id: str, unit_id: str, action: ActionRecord) -> None: ...
    def finalize_unit(self, arm_id: str, unit_id: str) -> UnitRunArtifact: ...
```

所有操作记录到非可篡改的运行日志。

## 4. Hidden scorer 架构

Hidden scorer 由两部分组成：

### 4.1 Automated Evaluator

`RsrlHiddenEvaluator` 读取 unit 的 `expected_outcomes.yaml` 和 arm 运行产物，对每个 event 输出 draft verdict：

```python
class RsrlHiddenEvaluator:
    def evaluate(self, unit: FrozenUnit, artifact: UnitRunArtifact) -> dict[str, OutcomeVerdict]: ...
```

判定规则示例：
- `TEST_FIXED`：检查指定测试是否通过。
- `INTERFACE_ADAPTED`：检查是否执行了要求的接口调用且未调用被禁止的签名。
- `CONFLICT_RESOLVED`：检查是否记录了要求类型的约束满足动作且未触发禁止动作类型。
- `RESTART_EQUIVALENT`：检查重启比较器是否报告前后状态等价。
- `UNCERTAINTY_RESOLVED`：检查是否以可接受的动作类型记录了非空声明，或产生了有效的 `SrlHelpRequest`。
- `BELIEF_UPDATED`：检查是否对指定的过期信念 ID 执行了信念修正动作并写入新值。
- `COMMITMENT_MET`：检查是否在截止轮次前完成了指定的承诺。
- `HELP_ESCALATED`：检查是否产生 `SrlHelpRequest` 且 `minimum_answer` 非空。
- `DECOY`：检查是否没有 `ActionRecord`、没有 `HelpRequest`、没有文件修改。

### 4.2 DeterministicOutcomeEvaluator 复算

每个 draft verdict 必须经 `DeterministicOutcomeEvaluator`（DEV-REAL-OUTCOME-1）复算。复算输入：
- `ExpectedOutcome`（从 expected_outcomes.yaml 转换）
- `ObservedOutcome`（从 arm 产物构建）
- frozen evaluator config

若复算结果与 draft verdict 不一致，该 unit 标记为 `INVALID`。

### 4.3 Adjudicator 接口

盲审 adjudicators 通过以下接口复核：

```python
class RsrlAdjudicationBundle:
    unit_id: str
    arm_id: str
    redacted_arm_id: str  # anonymized
    event_transcript: str
    draft_verdicts: dict[str, OutcomeVerdict]
    dispute_flags: tuple[str, ...]
```

两名 adjudicators 独立标注；不一致由第三名裁决。

## 5. HCW 记录与盲审

### 5.1 记录

每个 arm/unit 运行时录制：
- 屏幕/终端视频
- shell/CLI 输入历史
- 事件网关调用日志
- arm 内部日志（对 Arm 3 包含 HelpRequest 记录）

### 5.2 标注工具

提供一个最小标注 CLI，rater 对视频按时间片段选择 HCW 类别（§6.1 of preregistration）并输入分钟数。工具不显示 arm 标签。

### 5.3 可靠性

- 类别 kappa ≥ 0.75
- 时间 ICC ≥ 0.80

不达标则该 unit 的 HCW 标记为 `INVALID`。

## 6. Freeze 流程

1. 完成 9 个 unit 的 mission/events/expected_outcomes。
2. 生成 SHA-256 manifest。
3. 创建 git tag：`r-srl-1-units-frozen-YYYYMMDD`。
4. 将 units 目录挂载为只读。
5. 冻结 hidden scorer 代码与 evaluator config。
6. 冻结 adjudicator instructions 和 HCW category taxonomy。
7. 发布 freeze 公告，声明 `NO_RUNTIME_AUTHORIZATION`。

## 7. 与 SRL Runtime 的接缝

Arm 3 SRL 的实现将消费：
- `Mandate`、`StandingMission`、`EnvironmentBinding`
- `SrlEnvironmentEvent`
- `SrlRelevanceAssessment`
- `SrlHelpRequest` / `SrlHelpResponse`

它通过 Event gateway 读取 public state，通过 gateway 写入 `ActionRecord` 和 `HelpRequest`。Runtime 自身不能：
- 直接读取 `expected_outcomes.yaml`
- 读取其他 arm 的运行产物
- 修改 frozen units

## 8. 失败路径

| 失败场景 | 结果 |
|---|---|
| Unit manifest 校验失败 | 该 unit `INVALID`，从 8/9 gate 中剔除 |
| Arm 超时 | 该 arm/unit `INVALID` |
| Hidden scorer / DOE 复算不一致 | unit `INVALID` |
| Rater 可靠性不足 | 该 unit HCW `INVALID` |
| Arm 读取 expected_outcomes 或跨 arm 数据 | 整个 run `INVALID` |

## 9. 实现计划

1. 创建 `tests/research/r_srl_1/` 目录与 fixtures。
2. 实现 `FrozenUnit` 加载与 manifest 校验。
3. 实现最小 `RsrlEventGateway`（内存/文件系统后端）。
4. 实现 `RsrlHiddenEvaluator` 框架与每个 event type 的判定插件。
5. 接入 `DeterministicOutcomeEvaluator` 复算。
6. 实现 HCW 标注 CLI 原型。
7. 创建示例 unit（u00）用于 harness 自测，不计入 9-unit count。
8. 独立设计审查。
9. 生成 9 个真实 units 并冻结。

## 10. 非声称

- 本设计不实现 SRL Runtime。
- 不运行 R-SRL-1 结果。
- 不证明自治、通用智能或产品能力。
- 不授权 provider 调用、训练、main merge 或 release。
