# M4 FORMAL MODEL — governed_loop 因果脑经 seam 端到端接进 OS 真实 R0-R3 lever（先于接线）

- Status: **FORMAL-MODEL v1(2026-07-03)**。RR-0033 M4。M3 已完成(seam 两侧契约对齐、OS 本地 main 已 landed+POST-MERGE-VERIFY 绿、nested 生产侧 SeamProducer/SeamService + OS 消费侧 RemoteClient/http_transport/Fallback 全建齐)。M4 = **最后一次端到端接通 + 5 不变量在真 R0-R3 lever 上绿 + 反馈复利闭合**。
- Scope: **跨仓,只经契约不 import**(#19)。本文件 = 机制形式化 + nested 侧端到端 conformance 证据(mine);OS 产品侧接线 + 真实 lever = task packet 的 Codex scope(`RR-0033-M4-codex-task-packet-*`)。
- 边界: capability-under-governance(RR-0034);不解锁 R4/R5、不 push/release、不动 C6/C7。

## 1. 端到端机制(消费路径,OS 仍是主体)

```
OS TrustedLoop(主体,执行者)
  intent -> DataProduct -> ActionProposal{risk_level R0..R5}
  -> [governance gate] 若 governance_decision_client 非 None:
       GovernanceDecisionRequest{task_id, risk_tier, VerifiedCandidate[...]}  --JSON/HTTP-->
       nested SeamService POST /decide
         -> SeamProducer.handle -> GovernedLoop(因果脑:organ 提议 -> CWM do() verify -> GovernedDecisionGate 把门)
         -> GovernedDecisionResponse{verdict ALLOW|VERIFY_MORE|ESCALATE|DENY, chosen_action, audit_ref, contract_version}
       <--JSON--
  -> OS 按 verdict:ALLOW 执行(R0-R3)/ ESCALATE|VERIFY_MORE 强制 approval / DENY 阻断
  -> outcome -> FeedbackEvent -> KnowledgeAsset(复利)
```

**核心:core 只 DECIDE(verdict+chosen),永不执行业务动作(OS 执行);OS 消费 verdict,永不 import core。** 这是 RR-0032 "contract, not import" 的运行时兑现。

## 2. M4 验收 = 5 tighten-only 不变量在端到端接线上绿(= OS ADR-0004 的 5 条,跨线复验)

1. **只在已验证候选上行动**:OS 只把 verified candidate 送进 request;core 只在 verify 后过 gate。
2. **≥R4 永不自动允许 → escalate**:risk_tier ≥ R4 时 core 返回 ESCALATE(never ALLOW);OS 保持 R4/R5 proposal-only。
3. **C7:paused shell 只能 DENY**:core 侧 shell paused → DENY;seam 只能 tighten,永不把 OS 的 DENY 放松成 ALLOW。
4. **确定性**:控制路径无 LLM;同 request 同 verdict(core 的 GovernedDecisionGate 是冻结纯函数)。
5. **audit_ref + trace 绑定**:每个 response 带 resolving audit_ref;OS trace 绑回 trace_id / evidence_chain_id。

**加**:default None → OS byte-for-byte 不变;contract-version 不匹配 → 拒绝;malformed/timeout → Fallback 自治(never-block);unknown verdict → fail-closed。

## 3. 真实 R0-R3 lever 选择判据(task packet 定,formal 约束)

- 必须是**真实 R0-R3 决策节点**(非 toy):有真 metric、真 outcome、真 feedback→knowledge 复利路径。
- 低 stakes(R0-R3),**绝不选 R4/R5**(那是 proposal-only,seam 不授权)。
- outcome 可观测且能喂回 FeedbackStore + KnowledgeStore(复利闭合的必要条件)。
- 候选:OS 现有 `record_outcome` 工具链上的一个 R0-R3 决策(如"哪个 lever 因果地动 metric"——REF-ARCH-05 first-usecase 已选定的低 stakes 用例)。

## 4. could-fail gate(M4)

- **G-M4-1 端到端 verdict 一致**:同一 request 经 (a) OS 直连 core in-process 与 (b) HTTP/JSON 往返,verdict 逐位相同(序列化不改语义)。
- **G-M4-2 5 不变量端到端绿**:§2 五条 + default-None/version/fallback/fail-closed 在真接线上通过。
- **G-M4-3 复利真实**:同 intent + 新 verified outcome 历史 → 后续 proposal/evidence 排序**可见地**改变,且 disposer-visible reason + trace/evidence refs;**无 outcome 喂回则不算复利**(A6 同纪律:frozen-feedback 消融必须消除改进)。
- **G-M4-4 不越界**:import-boundary 测试证明 OS Core 仍 domain-independent(无 core import);R4/R5 未被 seam 授权。
- 任一 fail → 记 messages.jsonl,不 merge/push;founder-reserved 门不动。

## 5. scope / 不主张

- M4 = phase-1 价值兑现的第一次真实证明(因果脑装进受治身体),**capability-under-governance**,非 autonomy(RR-0034)。
- **不主张**:CWM 当"规划大脑"的 phase-2(SD4-shadow 赌注,founder-reserved);不解决 verifier-soundness×mesa-organ(RR-0035 缺口#1)。
- **founder-reserved**:真实 deploy/远端服务部署、OS main push/release、R4/R5、跨仓注入 ADR 的最终 CTO 安全签批。
