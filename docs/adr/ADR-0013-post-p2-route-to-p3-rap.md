# ADR-0013: Post-P2 Route Decision - Proceed to P3 RAP v0

- Status: Accepted under ADR-0003 route-decision authority
- Date: 2026-06-12
- Decision owner: CTO agent, with founder veto window preserved

## Context

P2 closed with a mixed but useful result:

- G3 is **NOT MET** because the directed idle-drive gain criterion did not stabilize.
- Claim 1 is upgraded to **ablation-validated**: interoceptive pressure ablation was stable at 9/10 across four rounds, and permanent value cutoff reliably caused bounded death from resource dynamics.
- Claim 2 is already hard-stopped as **partially supported but not experimentally established** after G0/G1/G1-r/G1'/G2.
- Claim 3 is demonstrated and hardened to `(L1, ISO-1)` with an ISO-2 reference.
- Claim 4 remains structurally established.

The important new research finding is now first-class: G1, G2, and G3 all show the same pattern in this prototype line -- directed cognition mechanisms do not reliably beat cheap undirected baselines at this scale.

The next route options after P2 are:

| Option | Meaning | Benefit | Cost / Risk |
|---|---|---|---|
| A | Proceed to P3 RAP v0 | Tests C5 coordination separately from directed cognition; keeps iteration empirical | May add coordination machinery before fully digesting the three-failure pattern |
| B | Pause for a pattern-digestion research item | Directly studies why directed mechanisms lose | Risks becoming analysis-only and delaying the next falsification gate |
| C | Jump early to P4 organs / priors | Tests whether amortized prior knowledge fixes the missing ingredient | P4 is founder-reserved, introduces LLM/organ complexity, and contaminates P3 evidence |

## Decision

Choose **Option A: proceed to P3 RAP v0**.

Treat Option B as a background constraint, not a blocking workstream. The G1/G2/G3 pattern must be carried into P3 design as an adversarial baseline requirement: RAP must compare against cheap fixed/manual coordination, not only against weaker straw variants.

Do **not** choose Option C now. P4 remains founder-reserved and should wait for P3 evidence unless the founder explicitly overrides.

## Rationale

P3 tests a different claim than P1/P2:

- P1/P2 tested whether specific directed cognition mechanisms produce better relevance, adaptation, or idle gain.
- P3 tests whether bounded rhizomatic coordination can form useful task-specific coalitions with measurable overhead.

Because P3 is a coordination-layer question, the directed-cognition three-failure pattern is evidence to be respected, not a reason to stop. The honest way to respect it is to make the cheap/manual baseline strong and explicit in G4.

## Strongest Objections

**Objection to A:** If directed mechanisms have failed three times, adding a RAP layer may hide the same weakness behind coordination ceremony.

Response: Accepted as a risk. P3 must not be allowed to pass by ceremony. G4 must include a hand-wired fixed pipeline baseline, overhead accounting, and perturbation tests. If RAP does not beat or clearly characterize its cost against that baseline, RAP should be frozen rather than tuned into a story.

**Objection to B being non-blocking:** The repeated failure pattern may contain the real lesson; moving on may under-learn it.

Response: The pattern is already recorded as a level-1 research finding in ADR-0012. P3 can operationalize the lesson by making baselines stronger. A separate analysis-only pause would reduce empirical throughput without giving a new falsification surface.

**Objection to deferring C:** Priors/organs may be exactly what the prototype lacks; delaying P4 may postpone the first likely win.

Response: That is plausible, but P4 changes the trust and evidence structure by introducing organs/LLM-like priors. Running P3 first preserves a cleaner test of C5 and protects Claim 4's organ-not-subject boundary.

## Constraints For P3

- No LLM in the control path.
- No business semantics.
- No real external executor.
- No cross-repo imports or copies.
- Single-process RAP v0 only. Multi-process/multi-node RAP triggers ADR-0009 ISO-2 obligations unless the founder explicitly approves a downgrade.
- C7 remains dominant: shell pause/observe/rollback/tighten authority is not part of the rhizome.
- Claim 2 and IdleDrives must not be redesigned inside P3 without a new founder-level ADR.

## Next Work

T-P3.0 must produce the executable P3 design ADR before mechanism implementation:

- exact NEED/BID/BOND/TRACE/DISSOLVE semantics;
- a strong manual/fixed pipeline baseline;
- perturbation task mixture;
- overhead metrics;
- G4 threshold and NOT MET handling;
- explicit treatment of the G1/G2/G3 directed-cognition failure pattern.

After T-P3.0 is accepted, implement P3 in small testable slices.

## Consequences

- Current stage becomes **P3 RAP v0 design**.
- P2 remains closed; do not retune G3.
- P4 remains deferred.
- The three-failure pattern becomes a design guardrail for P3 rather than a reason to stop empirical work.
