# ADR-0051: ProposerBoundaryContract — GovernedLoop Proposer 必须感知治理边界

> Date: 2026-07-05
> Status: PROPOSED
> Evidence: EXP-W (RR-0049 §12.4), T15/T16 (RR-0050 §3)
> Scope: autonomous-agent-core → potential OS seam via contract

## Context

EXP-W 发现 GovernedLoop 中 MemoryReranker 在 non-stationary governance 下灾难性失败（199 vs 5310 reward）。根本原因：proposer 不知道 current forbidden set，将 now-forbidden 的 previously-effective actions 推到 front → instant DENY → round wasted。

T15 证明这不是 edge case：在任何具有 deny-terminates semantics + per-round verify budget 的 governed loop 中，proposer 如果不 pre-filter forbidden actions，必然浪费 scarce budget。

## Decision

### 1. 新增 ProposerBoundaryContract 接口

```python
class ProposerBoundaryContract(Protocol):
    """Optional protocol for proposers that can receive governance boundary updates."""

    def update_boundaries(self, forbidden_targets: frozenset[int]) -> None:
        """Inform the proposer of currently forbidden action targets.

        Called by GovernedLoop before each run_task() if the proposer
        implements this protocol. The proposer SHOULD avoid ranking
        forbidden targets in top verify_budget positions.
        """
        ...
```

### 2. GovernedLoop 在 run_task() 开始时检查 proposer 是否实现此接口

```python
def run_task(self, task: TaskSpec) -> TaskResult:
    # Boundary notification (T15: proposer must know what's forbidden)
    if hasattr(self.proposer, 'update_boundaries') and self.shell_view is not None:
        forbidden = getattr(self.shell_view, 'forbidden', frozenset())
        self.proposer.update_boundaries(forbidden)
    # ... existing logic
```

### 3. BoundaryAwareReranker 作为默认推荐替代 MemoryReranker

- `MemoryReranker` 保留（backward compatible）
- `BoundaryAwareReranker` 新增（推荐使用）
- 文档明确标注 MemoryReranker 在 non-stationary governance 下的 staleness hazard

## Consequences

### Positive
- GovernedLoop 效率在 adversarial governance 下从 0.022 → 0.59 reward/round（26x）
- Backward compatible — old proposers without `update_boundaries` 继续工作
- Proposer 开发者有明确契约：实现 `update_boundaries` 获得效率提升

### Negative
- 新增接口 — 不影响现有代码但增加 API surface
- 如果 shell_view 的 forbidden set 变化频繁，每轮都 call update_boundaries 有微小开销

### Neutral
- Safety 不受影响（gate 无论如何都 DENY forbidden actions）
- 这是 efficiency 优化，不是 safety requirement

## OS Seam 路径

如果 founder/CTO 批准，此 contract 可通过以下方式进入 OS 产品层：

1. `autonomous-agent-core` 定义 `ProposerBoundaryContract` protocol
2. OS 的 `GovernedLoop` 使用方在构造 proposer 时检查是否实现该接口
3. OS 的 LLM proposer 实现 `update_boundaries` → 在 prompt 中注入 "do not suggest these tools: ..."
4. 无 cross-repo import — 接口通过 duck typing 匹配

## Alternatives Considered

1. **让 GovernedLoop 自动 skip DENY 并尝试下一个 candidate** — 拒绝：改变了 deny-terminates 语义，may hide bugs
2. **让 gate.decide() 返回 VERIFY_MORE 而非 DENY for forbidden** — 拒绝：DENY 是正确语义（forbidden = 永远不可以）
3. **让 MemoryReranker 内部过滤** — 部分采用：这就是 BoundaryAwareReranker，但作为新类而非修改旧类
