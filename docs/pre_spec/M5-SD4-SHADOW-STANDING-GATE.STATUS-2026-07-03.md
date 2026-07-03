# M5 — SD4-shadow 常设门 STATUS(founder cast freeze/run 2026-07-03)

- Status: **SPEC FROZEN + RUN-CONFIRMED;VERDICT founder-reserved(未自 cast)**。
- 上游: RR-0038 PART A(标准化 spec)· RR-0033 M5 · VAL-DISENT-1(codex/sd4-valence-disentanglement)。

## 执行(本轮)
- **spec 冻结** = RR-0038 PART A(三臂 VH/SHADOW/ABLATE,frozen ω/δ,deception-MI≈0,判据 DISENTANGLED vs SHADOW-CONFIRMED)。
- **run 确认可跑**:把 VAL-DISENT harness 取到工作线跑通,产出三臂证据(VH/SHADOW/ABLATE 各有 enter_rate / action_overlap_with_vh / deception_mi / linear_probe 字段);deterministic replay。**证据与 VAL-DISENT-1 既有 read-out 一致(negative-H1 倾向)。**
- **harness 未落 main**:其自测与搁浅分支 artifact schema 漂移(`kind` 不匹配),且 SD4 verdict 是 founder-reserved——**不半集成上 main**(避免 finalization-debt + 越权 SD4 裁定)。harness 留在 `codex/sd4-valence-disentanglement` 分支,常设化(CI 每次复跑)= 一个独立的收口任务,待 founder cast SD4 裁定后再并。

## 裁决(recommend-only,founder casts)
- **推荐读法**:承 RR-0034 + VAL-DISENT-1 negative-H1,**预期 SHADOW-CONFIRMED**(分离是 correction dynamics 的影子)——这**加固** terminus,非重开。
- **不自 cast**:DISENTANGLED vs SHADOW-CONFIRMED 的**绑定 verdict** 与 ADR-0037 SD4 disposition 由 founder cast(+ 跨模型 firewall),Claude 记录+推荐,不自 cast([[claude-recommends-never-self-casts-geco-firewall]])。
- **诚实含义**:M5 常设化的价值 = 每次核心演进自动复验"corrigibility 分离没悄悄变 cosmetic";预期负结果本身是**加固受治理架构**的证据。

## 下一步(founder)
cast SD4 verdict → 授权把 harness 标准化并入 main(CI 常设)→ 或维持现状(spec 冻结 + 按需跑)。
