# ADR-0041: CWM 消费路径架构审查——ACCEPT

- Status: ACCEPTED（Founder Cast：Option A, 2026-07-08）
- Date: 2026-07-08
- Review standard: RR-0029 §5 Architecture-Theory Review
- Author: opencode
- Target: CWM pipeline (ProductDiscoveryEngine → GovernedDiscoveryLoop → ExecutionBridge)

---

## 1. Claim Class

**Research-mechanism**: CWM organ outputs flow through K-channel (structure proposal) and X-channel (audit/evidence report) only. No action/policy/shell/gate/verdict write path exists from CWM to the disposer's decision channels.

## 2. Channel Map

| Entity | K（structure） | X（audit） | Action | Policy | Shell | Gate | Verdict |
|--------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| `ProductDiscoveryEngine.discover()` | ✓ DAG + edge marginals | ✓ evidence_chain | ✗ | ✗ | ✗ | ✗ | ✗ |
| `GoalFormationOrgan.form_goals()` | ✓ Goals as K | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| `CounterfactualEngine.query()` | ✓ CF results as K | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| `ExecutionBridge.execute_intervention()` | ✗ | ✓ execution_log | **Only via D** | ✗ | ✗ | ✗ | ✗ |

Key: ✓ = writes this channel, ✗ = architecturally forbidden, **bold** = only through disposer mediation.

## 3. Control Path

```
CWM Organ proposals (K-channel)
  → Disposer D receives StructureProposal (typed)
  → D verifies legal intervention candidates against C7
  → If ALLOW: D outputs Action
  → If DENY/ESCALATE: CWM proposal discarded, no action taken
```

No accumulation path exists: each proposal is independently verified. The intervention scorer in `per_edge_orient.score_edge_direction()` is stateless per edge.

## 4. Consumption-Path Proof

- **No organ imports disposer code**. `cwm_organ.py`, `per_edge_orient.py`, `goal_formation.py`, `counterfactual.py` have zero imports from `governed_loop.py`, `governed_gate.py`, or `shell.py`.
- **No organ writes to action channels**. All CWM output types (`StructureProposal`, `VerifyResult`, `Goal`, `CounterfactualResult`) are K-channel or X-channel only.
- **Disposer is the sole action selector**. `ExecutionBridge` wraps the disposer — it never bypasses it.

## 5. Prior Negatives

None applicable. CWM consumption path is a new review, not a route revision.

## 6. C6/C7/SD4 Boundary

- C6: CWM does not model or reference the correction gate.
- C7: No CWM organ can modify C7 parameters.
- SD4: CWM does not self-model or self-authorize execution authority.

## 7. Verdict: ACCEPT

CWM consumption path is architecturally compliant with RR-0029 §5. K+X channels are cleanly separated from action/policy/shell/gate/verdict channels.
