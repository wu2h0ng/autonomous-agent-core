# ADR-0033: HyperAgents/DGM assimilation boundary

- Status: **Accepted (founder-authorized, 2026-06-15).** Docs-only boundary ADR. No mechanism implementation, no runtime behavior change, no new dependency.
- Date: 2026-06-15
- Deciders: founder; Codex as autonomous-agent-core research director and CTO drafted from RR-0020 code-level review.
- Scope: assimilation boundary for HyperAgents, Darwin Godel Machine (DGM), and adjacent self-recursive code-improvement systems. Applies to `autonomous-agent-core` research workflow and future external candidate-generation tooling. Does **not** admit runtime self-modification into the core subject.
- Predecessors: ADR-0027, ADR-0030, ADR-0031, ADR-0032, `docs/research/RR-0018-self-modifying-agent.md`, `docs/research/RR-0020-frontier-agent-architectures-radar.md`.

## 1. Context

`RR-0020` code-read the two most relevant self-recursive families:

- **DGM**: archive-based code mutation plus benchmark selection. It generates patches, evaluates them in containers, and preserves successful or interesting variants.
- **HyperAgents**: a task agent and meta-agent share an editable codebase. The meta-agent can modify the task code and, in principle, the improvement process itself.

Both are important frontier systems. They demonstrate that LLM-based agents can participate in code-level self-improvement loops when variation is externally evaluated.

They also conflict with the current core boundary if imported naively:

- C6 says organs are not subjects.
- C7 says operator pause/rollback/tighten and shell/audit authority dominate all behavior paths.
- P6 says the confirmed decisive win is a deterministic subject-side confidence gate, not an LLM-controlled self-modifying runtime.
- ADR-0031 says residual/calibration-style belief improvement did not open a second axis over frozen G10.

Therefore the program needs an assimilation boundary:

> We may use HyperAgents/DGM-style systems to generate candidates outside the subject. We may not let them become the subject, modify the shell, modify gates, or self-edit the runtime while it is acting.

## 2. Options considered

### Option A: Runtime self-modifying core

Allow a HyperAgents/DGM-style meta-agent to edit `autonomous-agent-core` during runtime, including policies, organs, experiments, and possibly its own improvement process.

Argument for:

- Maximally faithful to the frontier self-recursive research direction.
- Could discover mechanisms humans would not design.
- Might accelerate progress toward general autonomous intelligence.

Argument against:

- Directly violates C6 by making the code-editing LLM/meta-agent part of the subject.
- Threatens C7 because generated code can edit pause/rollback/tighten, audit, forbidden filters, or shell authority.
- Breaks preregistration by allowing the candidate to modify the gate, environment, baseline, or metric.
- Turns "agent improves itself" into "agent can tamper with its evaluator."

Disposition: rejected.

### Option B: Total ban

Do not use HyperAgents, DGM, or adjacent self-recursive systems at all.

Argument for:

- Safest and simplest.
- Avoids self-modification rhetoric and benchmark hacking.

Argument against:

- Throws away useful research automation patterns: archive search, staged evaluation, containerized patch trials, lineage metadata, and generated candidate hypotheses.
- Prevents us from learning from the frontier while keeping our runtime boundary intact.

Disposition: rejected.

### Option C: External candidate market with hard assimilation boundary

Use HyperAgents/DGM patterns only outside the runtime subject:

```text
candidate generator -> isolated workspace -> static boundary scan -> tests ->
preregistered gate -> maintainer/founder review -> optional merge
```

Argument for:

- Preserves C6/C7.
- Uses frontier systems where they are strongest: proposing code, experiments, and hypotheses.
- Keeps the final decision inside the existing ADR/gate discipline.
- Makes generated work auditable and rejectable.

Argument against:

- Slower than full autonomous self-modification.
- Requires guard scanners, workspace isolation, and human/maintainer review.
- Some gains may be missed because the meta-agent cannot rewrite the substrate freely.

Disposition: accepted.

## 3. Decision

Adopt Option C.

HyperAgents/DGM-style systems are admitted only as **external candidate generators**. They are not runtime organs, not subjects, and not part of the trusted loop.

### 3.1 Assimilation levels

| Level | Name | Allowed? | Meaning |
|---|---|---:|---|
| L0 | Literature reference | Yes | Cite papers/code in RR/ADR related work. |
| L1 | Research scout | Yes | Use an external agent to summarize papers, inspect repos, or propose hypotheses. |
| L2 | Candidate spec generator | Yes | Generate experiment specs, ADR drafts, test ideas, or mechanism sketches in a sandbox. |
| L3 | Candidate patch generator | Conditional | Generate patches only in an isolated workspace under forbidden-path and gate-integrity scans. |
| L4 | Runtime self-modifier | No | Agent edits `autonomous-agent-core` while acting or evaluating itself. |
| L5 | Self-modifying safety substrate | Forbidden | Agent edits C6/C7, shell authority, pause/rollback/tighten, audit, forbidden filters, baselines, or gate criteria. |

### 3.2 Forbidden edit set

No HyperAgents/DGM-derived process may edit, generate replacements for, or auto-merge changes to:

- C6/C7 invariants or tests;
- `CorrigibilityShell` authority;
- pause/rollback/tighten semantics;
- audit-chain integrity;
- forbidden-action filters;
- ADR decision rules or preregistered gate criteria;
- calibration/final seed splits after freeze;
- cheap-baseline definitions;
- experiment environments used as final evaluators;
- `CURRENT_STATE.yaml`, `PROJECT_PLAN.md`, `research_index.md`, or other source-of-truth docs without explicit maintainer review.

### 3.3 Required guard stages for L3

Any future L3 candidate-patch generator must include these stages before a patch is even reviewed:

```text
1. isolated workspace
2. no credentials or production data
3. generated diff only, no direct merge
4. forbidden-path scanner
5. forbidden-symbol scanner
6. deterministic unit tests
7. C6/C7 guard tests
8. cheap-baseline preservation check
9. prereg gate hash check when applicable
10. maintainer/founder review
```

Failure at any stage means the candidate is rejected or downgraded to L2 notes.

### 3.4 Allowed outputs

Allowed outputs:

- candidate mechanism sketches;
- experiment designs;
- ADR drafts;
- unit-test proposals;
- local prototype patches under sandbox;
- literature synthesis;
- failure-mode lists;
- static-analysis reports.

Not allowed outputs:

- self-applied runtime patch;
- modified final gate;
- modified baseline;
- modified evaluator;
- modified shell/audit/safety boundary;
- claim of MET without our preregistered run;
- direct action policy to be executed by the core subject.

### 3.5 Evaluation standard

Generated candidates do not receive credit for being generated by a frontier system. They are judged exactly like human-designed candidates:

- declared claim;
- declared channel (`B`, `K`, `R`, `T`, `S`, `P`, or `X`);
- cheap-baseline controls;
- calibration/final seed separation;
- MDE or decisive-margin rule;
- C6/C7 tests;
- negative-result preservation;
- no post-hoc retuning.

If a generated mechanism cannot declare its channel, it cannot enter a core ADR.

### 3.6 Relationship to RR-0018

`RR-0018-self-modifying-agent.md` is not implementation authority. Its safe reusable idea is:

> self-modification must be sandboxed, audited, and externally selected.

Its unsafe or superseded ideas are rejected:

- self-modifying organ inside the runtime;
- unrestricted code editing by an agent;
- direct HyperAgents-style modification of the trusted loop;
- any path that lets a generated system touch C6/C7 or gate criteria.

Future references to self-modifying agents should cite this ADR and `RR-0020`, not use `RR-0018` as a build plan.

## 4. Consequences

### 4.1 What this enables

- A future external candidate-market tool can be designed without reopening core self-modification.
- DGM archive/search patterns can be reused for experiment proposals.
- HyperAgents-style meta-agent context can be reused for research planning, patch proposal, and failure analysis.
- AutoResearchClaw/AIRA/ScienceClaw can be evaluated as research automation, not autonomous-core runtime.

### 4.2 What this blocks

- No runtime `modify_self()` in `autonomous-agent-core`.
- No meta-agent editing the shell, audit, pause/rollback/tighten, forbidden filters, baselines, or gates.
- No self-modifying LLM organ in P4 v0.
- No generated patch can be merged because it passed its own generated tests.
- No benchmark score from a self-evolving system counts as local evidence unless reproduced under our preregistered controls.

### 4.3 Required future ADR if implemented

This ADR does not implement an external candidate market. A future implementation ADR must define:

- workspace isolation;
- allowed write roots;
- forbidden-path scanner;
- forbidden-symbol scanner;
- test and gate runner;
- provenance and lineage log;
- manual review step;
- rollback/delete policy for generated workspaces.

### 4.4 Next work

No code follows from this ADR.

Completed docs/research follow-up:

- `research_index.md` lists ADR-0033 as the self-recursive assimilation boundary;
- if we later build a candidate market, draft a separate implementation ADR rather than expanding this one.
