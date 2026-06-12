# ADR-0008: ViabilityReflex(Layer 0 生存反射)— 追认文档

- Status: Accepted(追认;机制已于 8579f58 落地,本 ADR 补文档与测试,清完成门债)
- Date: 2026-06-12

## Context

G1 诊断确立"利用不该绑饥饿,该绑模型自信"后,纵深防御提出 Layer 0:当预算压力
极端(pressure > 0.8)**且**模型自信(mean_uncertainty < 0.5)时,硬编码反射越过
策略层,强制利用已知最优行动——类比脑干反射绕过皮层。

**过程违规记录(诚实留痕)**:reflex.py 与 agent.py 集成先于测试与 ADR 合入
(违反 AGENTS.md "每个行为变更必须带测试" 与 contract-first),且原 docstring
误引 "ADR-0005"(已被 post-g1-route 占用)。本 ADR 收债:补
`tests/test_viability_reflex.py`(13 测试),修正两处 docstring 引用为 ADR-0008。

## Decision

1. **定位:安全机制,非实验主张。** 反射"unfalsifiable by design"——它不进任何
   预注册门、不参与消融对比,验证方式 = 确定性单元测试。它不与 AttentionField/
   CausalRelevanceField 竞争,只在饥饿+自信的窄条件下生效。
2. **Stake-first 推导链**:触发条件直接读本质变量(预算压力)与认识状态
   (模型不确定度);效用 = 避免"濒死时随机探索"的生存损耗。可追溯,合规。
3. **反锁死**:连续接管 recovery_count 步后强制释放(防止"最优"行动其实已过时
   时的永久锁死);压力回落自然释放。
4. **可纠正性优先级**:罩 pause 检查先于反射——濒死也必须服从暂停。
   测试 `test_shell_pause_takes_precedence_over_reflex` 钉死此序。
5. **默认关闭**:`Agent(reflex=None)` 为默认,行为与无此特性完全一致(回归兼容)。

## Consequences

- 完成门债清零;测试数 131 → 144。
- 教训入册:接力 agent 不得再"先合机制后补测试";发现 ADR 编号被占必须立即改号,
  不得沿用错引。

## 修订(2026-06-12,T-P2.2 同轮安全修复)

原 `select()` 不查 forbidden——濒死反射可执行被 op_tighten 禁止的动作(既有禁令测试
均无反射,未覆盖)。已修:`select(model, forbidden=frozenset())`,只利用最优**合法**
动作;可纠正性 > 生存。详见 ADR-0012 §安全修复;回归测试 2 项。
