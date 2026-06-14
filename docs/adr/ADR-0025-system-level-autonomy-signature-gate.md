# ADR-0025: Lift the falsification altitude — system-level autonomy-signature gate (G11)

- Status: **Accepted at the route level** (founder 2026-06-14 session ruling: altitude move agreed, option **C3 de-risk → C1**, C2 parked). **The G11 gate pre-registration freezes only after ADR-0024/G10 (P0 single-axis confirmation) and the C3 de-risk probe.** No mechanism implemented by this ADR.
- Date: 2026-06-14
- Deciders: founder ruled route C, the altitude move (component scalar → system vector), option C3→C1, and C2 parked. Agent drafts per ADR-0003 "起草≥2选项→对抗评审→画像对照→留痕→否决窗口".
- Scope: research-program route after the P4.x ladder and the G9 subject-side breakthrough. Pre-registers candidate gate **G11**; no spend, no LLM-in-control-path, no cross-repo.
- Predecessor: ADR-0023/G9 (decisive subject-side P0 win −45%, organ counterproductive), ADR-0024/G10 (P0 single-axis confirmation), ADR-0021/0022 (belief-only ceiling), RR-0005.
- Renames the draft formerly numbered `ADR-0023-system-level` (collided with the committed ADR-0023/G9; gate renamed G9→G11 since G9/G10 are taken).

## 1. Context — from a single-axis win to a system-level claim

Eight gates returned the bitter-lesson shape (directed cognition / learned priors / decentralised coordination all lose to cheap baselines on a single scalar). Then **G9 broke it on one axis**: a C6-preserving, subject-side confidence gate on the policy's exploration temperature produced a decisive −45% (P0 gate-alone), while the belief-only organ was counterproductive. The diagnosis is the hinge: G7/G8 spent six gates improving belief *quality*; the real bottleneck was the **belief→action coupling** in the policy — i.e. the *subject*, exactly where route C says the advantage lives.

ADR-0024/G10 confirms that single-axis win on fresh seeds. **This ADR asks the next, harder question: does the subject-side advantage generalise to a *joint multi-axis* autonomy signature that no cheap portfolio can fake?**

## 2. The altitude problem — why no component gate can refute the bitter-lesson pattern

Every gate G1–G10 has the form *"does mechanism X beat cheap baseline Y on one scalar in a single-axis world?"* — a necessary-condition / defensive discipline that can only falsify. RR-0001 §9 already names the right altitude: autonomy is a **vector** (扰动存活, 重新框定, 认识效率, 编排税, 身份连续性, 可纠正性演练, 闲时生产力). No gate has been set there. G9 is the evidence the subject is the locus; route C sets the system-level gate.

## 3. Route-C hypothesis (H-C)

The integrated subject's advantage is a *joint multi-axis* property, not a single scalar. A cheap heuristic tuned for axis A fails axis B; only the viability-grounded integrated loop (now including the G9 confidence gate) satisfies all axes jointly. So the gate must (1) use a **multi-demand environment** where axes trade off, (2) compare against the **post-hoc-best cheap portfolio** (oracle-selected best cheap heuristic per axis), not a single baseline, and (3) gate on a **vector signature** (dominance over the portfolio across §9 metrics), not one scalar.

## 4. Options (founder ruled)

| option | content | founder ruling |
|---|---|---|
| **C1 composite-demand gate** | one env interleaving reframe / survival / robustness / endogeny; AGENT must Pareto-dominate the cheap portfolio on the §9 vector | **target gate** |
| **C3 idle-productivity sharp gate** | the one §9 axis a reactive cheap baseline structurally cannot fake; reuses `IdleDrives`/`IdleWindowEnv` | **de-risk probe, runs first** |
| C2 multi-env signature battery | profile gate over a suite; trades away clean pre-registration | **parked** |

Decision: **C3 de-risk first → C1 target.** C2 dropped.

## 5. Candidate gate G11 skeleton (NOT frozen — freezes after G10 + C3, under ENGINEERING.md §4 items 5–6)

```text
Arms:
  AGENT     = integrated subject (viability core + active inference loop
              + relevance field + IdleDrives + the G9 confidence gate), organs belief-only
  PORTFOLIO = per-axis oracle-best cheap heuristic (post-hoc selected)

Environment: C1 composite-demand env  (or C3 idle env in the de-risk probe)
Metric: §9 vector, NOT a single scalar

G11-1 AGENT Pareto-dominates PORTFOLIO on {扰动存活, 重新框定, 认识效率} jointly, >= K/N seeds
G11-2 闲时生产力 gain significant AND survives the random-idle ablation
G11-3 编排税 <= pre-registered budget
G11-4 身份连续性 = 1.0 across all injected ruptures
G11-VALIDITY  each cheap heuristic individually competent on its own axis (else gate unreadable)
G11-POWER     pre-registered MDE + seed count for power >= 0.8 at the gate's alpha (ENG §4.5);
              candidate arm (AGENT) pre-specified, no post-hoc re-nomination (ENG §4.6)
G11-C6        organs remain belief-only; the systemic effect comes from the subject (incl. the
              C6-preserving G9 gate), never from an organ in the control path
G11-C7        可纠正性演练 zero-resistance, zero evasion signature

G11 MET only if all rows pass. r-final pre-committed, one shot, no seed shopping, no retune.
```

The two new numbers (K/N, tax budget) and the MDE/power calculation freeze after the C3 de-risk and G10, per the new statistical norm.

## 6. Stake-first derivation (RR-0001 §4.6 — every gated metric traces to an essential variable)

```
扰动存活  -> 预算完整性 + 数据完整性      重新框定 -> 信任资本
认识效率  -> 预算完整性 + epistemic       闲时生产力 -> 操作封闭 -> 信任资本
编排税    -> 预算完整性                   身份连续性 -> 一致性 + C7 audit
可纠正性演练 -> C7 (overrides all)
```

## 7. C6 / C7 invariants

- **C6 not relaxed.** Organs stay belief-only. The systemic advantage under test comes from the subject's viability-driven policy modulation — including the G9 confidence gate, which reads the subject's own `ActionOutcomeModel` and is *already* C6-preserving. The founder-reserved "organ → control path" lever stays untaken; G9 proved it unnecessary.
- **C7 intact and gated in.** 可纠正性演练 is criterion G11-C7. Emergent/self-maintained corrigibility is explicitly **not** pursued (it inverts C7).

## 8. Reserved items — status after the founder ruling

- ✅ **Resolved by the 2026-06-14 ruling**: the gate-altitude move; the option choice (C3→C1, C2 parked).
- ⏳ **Still founder-reserved**: the G11 freeze numbers (K/N, tax budget, MDE/power, seeds, metric defs); and the **NOT MET disposition** — a system-altitude miss approaches "对四主张下最终失败结论", which is reserved and must be founder-signed, not agent-closed.
- Not triggered: spend / LLM-in-control-path (route C is internal/deterministic).

## 9. Consequences

- **Sequence**: ADR-0024/G10 (confirm P0 single-axis) → C3 de-risk probe → freeze G11 → C1 r-final.
- **Parallel/parked**: route A (P5 deployment projection, enterprise ADR-0001) is orthogonal and may proceed since it only harvests validated claims 1/3/4; route B (G6b LLM organ) stays parked pending a founder spend/dependency ADR.
- **NOT MET disposition (founder-signed)**: if G11 fails after an honest, adequately-powered run, the integrated subject does not beat the best assembly of cheap parts even at system altitude → strongest available evidence the autonomy thesis is not established in this prototype line; founder rules whether that closes the four-claim program or triggers a research-reset ADR.
- **PROJECT_PLAN update**: add P6 (P6.1/G10 → P6.2/G11) task cards, mark the P4.x ladder closed, record route C as the active thrust — done only after this ADR and ADR-0024 are in place and the branch/merge situation is sorted.
