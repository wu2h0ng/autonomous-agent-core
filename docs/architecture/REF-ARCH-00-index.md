# Reference Architecture — Index (REF-ARCH)

> Created 2026-06-30. Subject: **the research prototype (`autonomous-agent-core`) as the governed agent loop**, with the **injection seam into the enterprise OS** defined as a contract (not a code import).
> Founder decision (2026-06-30): research prototype is the subject; produce the full 4-document reference spec.
> Discipline: these are **design/contract documents**, not implementation. Every claim is tagged **✅ exists/validated · 🟡 toy/partial · ❌ missing**. They do NOT authorize new mechanism work — RR-0029 / Paradigm gates still apply per mechanism.

## The four documents
1. **[REF-ARCH-01 System Reference Architecture](REF-ARCH-01-system-reference-architecture.md)** — the layering (model organs / world model / agent self model / policy / corrigibility / feedback / trace), the Agent-as-governed-loop subject, the map to real `src/aac/` modules, and the OS injection seam.
2. **[REF-ARCH-02 Model Organ Contract](REF-ARCH-02-model-organ-contract.md)** — how every model (LLM, CWM, forecaster, classifier…) plugs in as an *organ*: typed in/out, bounded advice, what it may never do.
3. **[REF-ARCH-03 Agent Role Contract](REF-ARCH-03-agent-role-contract.md)** — the prototype's cognitive roles (propose / model / verify / decide / govern / learn / self-monitor), their I/O, permissions, failure paths, and how they project onto the OS business roles at the seam.
4. **[REF-ARCH-04 Runtime Governance Contract](REF-ARCH-04-runtime-governance-contract.md)** — how every call passes the gate: run context, risk ceiling, budget, checkpoint, trace, approval, C7 override, failure sanitization; the adaptive verify-or-escalate decision gate.
5. **[REF-ARCH-05 First R0–R3 OS use-case](REF-ARCH-05-first-os-usecase.md)** — the concrete low-stakes use-case ("which lever causally moves the metric?") the OS injection seam (RR-0032) is first wired to; seam mapping + acceptance criteria. PREPARE deliverable (a); WIRE still gated.

## The one sentence
**LLM is an organ, the (causal) world model is the map of action→consequence, the agent self model is the map of own capability/risk/boundary, the Agent is the governed closed loop that perceives–models–decides–verifies–acts–is-corrected–learns, and the Runtime is the envelope that proves none of that bypassed a safety boundary.** Multiple models and multiple roles live *inside one governed loop* — never as sovereign agents.

## Hard boundaries this spec must respect
- **Agent = loop, not model.** No document may promote the LLM (or any organ) to the subject. (Constitution: LLM never in the control path.)
- **One subject loop.** Multi-role reasoning happens inside a single governed loop; no loosely-coordinated sovereign agents.
- **Cross-repo (Hard Boundary #19).** The OS injection seam is a *contract*; wiring `autonomous-agent-core` into `ai-native-business-data-agent-os` requires a **separate founder/CTO-approved ADR**. This spec defines the seam; it does not authorize the import.
- **No pseudo-implementation (Hard Boundary #12/16).** A module named here is not "done" until it has a real call path + failure path + a test that fails if bypassed. Status tags mark what is real today.

## What this spec is grounded in (validated this session)
- **Causal World Model** ✅ ADR-0042/0043/0045 — intervention-learned causal mask; interventional prediction beats correlation under confounding (negative control holds).
- **Layered comparison** ✅ ADR-0046 — LLM-organ + CWM-verify + governance beats pure-LLM and pure-CWM on a confounded task.
- **Frontier** ✅ ADR-0047 — fixed trust of the LLM's unverified output silently fails; the governance principle ("act only on verified") is load-bearing.
- **Adaptive verify-or-escalate + the trilemma** ✅ ADR-0048 — {correctness, autonomy, efficiency} cannot all be maxed; stakes pick the operating point.
