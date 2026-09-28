# P-SRL Runtime Roadmap — Engineering Review

> Reviewer: Internal engineering adversarial reviewer
> Date: 2026-07-16
> Scope: `AGENT-OS-CAPABILITY-IMPLEMENTATION-MAP.md`, `P-SRL-RUNTIME-IMPLEMENTATION-ROADMAP.md`, `P-SRL-RUNTIME-VERIFICATION-MATRIX.md`, `PROJECT-PRODUCTION-INTERROGATION-2026-07-16.md`
> Constraint: Review engineering plan only; business model and resource constraints are out of scope.
> Verdict: **REVISE**

---

## Executive summary

The roadmap is internally coherent and avoids the worst traps (no premature distributed runtime, no training-before-runtime, no self-approval). The completion discipline and verification levels are well designed. However, several P0 gaps mean the first build slice (M1) is not yet ready to cut:

1. M1 does not clearly bound **draft creation** from **effect execution**; integrating directly with `TaskService` risks bypassing the already-implemented capability/policy gate.
2. M2/M3 policy gates are still **concept-level**; without concrete scoring schema, weights, and falsifiers they will collapse into prompt-engineering theater.
3. There is **no held-out task distribution or baseline** for product acceptance, so M1 cannot be falsified as solving a real problem.
4. **Security/tenant/credential model** is absent from M0-M3; production deployment is impossible without it.
5. **Outcome learning gate** is listed as an adjacent package but not wired into M1/M4; this creates a path where M4 learns from unverified outcomes.

---

## Verdict

**REVISE** — fix P0 findings before M1 implementation starts.

---

## P0 findings (must fix before M1 build)

### P0-1. M1 draft-to-effect boundary is undefined
`P-SRL-RUNTIME-IMPLEMENTATION-ROADMAP.md` §2 M1 says the system `emit_task_draft(...)` and connect it "to the existing TaskService path". At the same time M1 non-goals include "no autonomous external effects". The exit gate says "an authorized event can create a task draft through the existing TaskService path".

The ambiguity: if `MandateSteward` directly calls `TaskService` to create a task aggregate, it may trigger workers, tool calls and external effects immediately. The existing `CapabilityBroker` / `PolicyDisposer` (`AGENT-OS-CAPABILITY-IMPLEMENTATION-MAP.md` row 4) is listed as `IMPLEMENTED_LOCAL`, but M1 does not explicitly route through it.

**Required fix:**
- Define two distinct artifacts: `TaskDraft` (non-executing, proposal) and `TaskActivation` (executing).
- M1 must only emit `TaskDraft`; `TaskService` activation must require a second gate (human/policy/capability approval).
- First failing test: `test_mandate_steward_cannot_activate_task_without_policy_gate`; `test_task_draft_does_not_call_external_connectors`.

### P0-2. M2 attention and M3 method selection are concept-level policy theater
M2 lists disposition factors (impact, urgency, uncertainty, reversibility, authority, cost, latency, burden) but provides no scoring function, no weight derivation, no calibration procedure and no falsifier. M3 dispositions (`PLAN_FIRST`, `EXPLORE_FIRST`, etc.) are sensible labels but the rules for "data contract or grain is unknown" or "causal claim is required" are not reduced to typed checks.

**Required fix:**
- Publish the concrete `AttentionScore` schema and deterministic combination rule before implementation.
- Define a cheap falsifier for M2: e.g., `all-events-create-tasks` and `random-disposition` baselines must be beaten on the held-out task set.
- Define `MethodSelectionReceipt` fields that are machine-checkable (e.g., `required_evidence_present`, `causal_identifiability_status`, `data_grain_confidence`) rather than narrative.
- First failing test must fail if the model narrates a high-impact justification without a deterministic score crossing a threshold.

### P0-3. No held-out task distribution or baseline for product acceptance
`P-SRL-RUNTIME-IMPLEMENTATION-ROADMAP.md` §3 says the first product acceptance test should measure "cognitive load reduction vs direct model + tools baseline on a fixed set of long-horizon project or business-analysis tasks". The tasks are not named, the baseline is not specified, and the success criteria are not quantified.

**Required fix:**
- Define the exact task set (or a sampling distribution) before M1 code starts.
- Implement the `direct model + tools baseline` as code, not as a concept.
- Set numeric gates for: user prompts required, corrections required, relevant issues discovered, verified outcomes, cost and latency.
- Without this, M1 can pass unit tests while failing to reduce real operator load.

### P0-4. Security, tenant and credential model missing from M0-M3
`PROJECT-PRODUCTION-INTERROGATION-2026-07-16.md` §7.5 asks "Which secrets, credentials and tenant boundaries are production-grade, and which are local-only?" The roadmap and capability map do not answer this. `MandateSteward.observe_event(...)` will receive environment events that may contain credentials, PII or cross-tenant data; without a security model, M1 cannot be deployed.

**Required fix:**
- Add a `P-SECURITY-BOUNDARY-0` package (or fold into M0) covering: tenant-scoped mandate/binding, secret redaction in traces, credential lease scope, event-source authentication, and least-privilege capability grants.
- First failing test: `test_mandate_steward_rejects_event_from_unauthorized_binding`; `test_trace_does_not_leak_secret_payload`.

### P0-5. Outcome learning gate is not wired into M1/M4
`P-OUTCOME-EVAL-2` is listed as an adjacent package in the verification matrix but M4 "Outcome learning and knowledge update" does not explicitly consume it. M4 exit gate says "verified outcomes can create DRAFT candidates; invalid/unresolved outcomes cannot raise asset confidence". This is correct in principle, but the wiring to `OutcomeLearningGate.admit(...)` is not shown in the roadmap.

**Required fix:**
- Make `OutcomeLearningGate.admit(...)` a mandatory port for any knowledge/asset confidence update.
- First failing test: `test_knowledge_asset_rejects_unverified_outcome` must fail if M4 bypasses the gate.

---

## P1 findings (should fix before M1 freeze)

### P1-1. Cost/SLO/observability gates are missing across all packages
The verification matrix has no latency, token cost, throughput or SLO gates. M1-M3 will run in-process initially, but without cost/SLO instrumentation the "cost and latency" product acceptance metric cannot be measured honestly.

**Fix:** Add `P-OBSERVABILITY-LEDGER-0` package or require every package to emit structured traces and cost events. Baseline: direct model + tools must be compared on equal cost/latency budgets.

### P1-2. No rollback/revocation path for deployed policy or mandate changes
M5 correctly requires canary/rollback for shadow evolution, but M1-M3 policy weights, attention thresholds and mandate bindings can also change. There is no rollback story if a deployed policy starts emitting bad tasks.

**Fix:** Add versioned `AttentionPolicy` / `MandateBinding` with epoch dominance and a revert-to-previous-epoch path. Test: `test_policy_rollback_restores_previous_behavior`.

### P1-3. Local "cost and latency" metrics are misleading before distributed runtime
The roadmap defers `P-DISTRIBUTED-RUNTIME-1` until after M1-M3, but product acceptance already measures cost and latency. Local in-process measurements will not reflect queueing, retries, lease contention or multi-tenant cost attribution.

**Fix:** Treat M1-M3 product acceptance metrics as "local controlled slice" only; do not claim production cost/latency until `P-DISTRIBUTED-RUNTIME-1` gates are met.

### P1-4. Adversarial robustness baseline is missing
`PROJECT-PRODUCTION-INTERROGATION-2026-07-16.md` §9.4 asks which tests fail if model output bypasses policy, evidence or outcome truth. The verification matrix has good intent but no adversarial test suite.

**Fix:** Add `test_policy_bypass_via_jailbreak_input`, `test_model_narration_does_not_satisfy_evidence_requirement`, and `test_revoked_mandate_reused_in_assessment` to the M1-M3 matrix.

### P1-5. Human-in-the-loop resolution workflow is underspecified
`HelpRequest` is a contract, but the roadmap does not define how an operator response returns to the steward, how minimum_answer is validated, or how unresolved help requests block task creation.

**Fix:** Define `HelpResponse` → `MandateSteward` → `TaskDraft` re-entry path with explicit timeout, escalation and blocking semantics.

---

## P2 findings (nice to have / defer)

### P2-1. `P-DOMAIN-ADAPT-1` is too ambitious
"Domain expertise without hand-built vertical agent" is a research problem. The current Data Agent donor already provides governed domain analysis. Generic domain model formation risks becoming a new ontology-engineering rabbit hole.

**Recommendation:** Narrow to `P-DOMAIN-PRIOR-INGEST-1`: validate and version domain priors, but do not claim generated expertise.

### P2-2. `P-MULTIMODAL-IR-1` entry criteria need tightening
The verification matrix lists good anchor requirements, but there is no named product use case that requires multimodal semantic understanding rather than OCR/transcription + text reasoning.

**Recommendation:** Require a concrete customer or held-out task that fails on text-only processing before starting this package.

### P2-3. `R/P-MODEL-TRAINING-LOOP-1` should require a falsifier showing tools/schema are insufficient
Training is expensive and high-risk. The roadmap correctly defers it, but the entry criteria should include: a measured failure of (better tools + stricter contracts + RAG) on the held-out task set.

---

## 必须修改项

1. **M1 必须区分 `TaskDraft` 与 `TaskActivation`**，M1 只产出 draft，不能绕过 capability/policy gate 直接触发外部效应。
2. **M2/M3 必须给出可机器检查的评分模式与 falsifier**，不能停留在概念标签。
3. **产品验收必须定义 held-out 任务集和直接 model+tools baseline 的代码实现**，并给出数值门限。
4. **M0-M3 必须补全安全/租户/凭证模型**，否则无法从本地切片走向受控试点。
5. **M4 必须通过 `OutcomeLearningGate.admit(...)` 消费 outcome truth**，禁止未验证结果提升知识资产置信度。

## 可推迟项

- `P-MULTIMODAL-IR-1`：等到 M1-M3 稳定且有真实多模态用例失败证据。
- `R/P-MODEL-TRAINING-LOOP-1`：等到 (tools + contracts + RAG) 在 held-out 任务上被测量为不足。
- `P-DISTRIBUTED-RUNTIME-1`：等到 M1-M3 有受控试点证据且本地成本/延迟指标不再具有误导性。
- `P-DOMAIN-ADAPT-1` 的通用域模型生成：收窄为域 prior 的验证与版本管理。

## 建议的下一实现包

**`P-SRL-RUNTIME-M1-plus`：MandateSteward V0 + Capability/Policy Gate + Observability Trace**

范围：
- `MandateSteward.observe_event(...)` 接收已授权、已绑定的事件；
- 解析 active mandate 与 `EnvironmentBindingAuthorization`；
- 创建 `SituatedAssessmentRecord`；
- 输出 `TaskDraft` 或 `HelpRequest` 或 `NoProposal`；
- `TaskDraft` 必须经过 `PolicyDisposer` / `CapabilityBroker` 才能转为 `TaskActivation`；
- 所有评估决策写入结构化 trace；
- 重复事件幂等；
- mandate revoke/epoch-change/pause 立即生效并占优于所有未决 draft。

前置条件（必须先满足）：
1. 定义 held-out 任务集与 model+tools baseline 代码。
2. 写出 M1 first failing tests，包括 `test_mandate_steward_cannot_activate_task_without_policy_gate`。
3. 补全 M0 安全/租户/凭证边界的最小 schema 与失败测试。

不要在没有上述前置条件的情况下开始 M1 实现，否则 M1 会通过局部单元测试但无法证明减少了真实操作者的认知负载。
