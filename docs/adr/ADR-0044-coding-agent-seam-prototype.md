# ADR-0044: Coding-Agent Seam Prototype — real model + interventional verification + governable escalation

- Status: **PREREGISTERED (research prototype; frozen before running)**. 2026-06-30.
- Line: the RESUMED core research prototype (founder 2026-06-30: goal = research prototype → real tasks). First real-task domain = **coding/software engineering** (founder choice).
- This is the **seam built on a REAL model + REAL tasks**: proposer = LLM (Kimi); causal world model = **interventional verification (run the tests, observe the real effect)**; governable disposer = confidence-gated escalation (the G10/P0 lever); metric = **human interventions per task**.

## Thesis
A coding agent that (a) grounds its actions in **interventional verification** — it RUNS the code and observes the real effect rather than trusting a surface guess — and (b) uses **confidence-gated escalation** — commit when verification passes, escalate to the human only when it cannot — completes more tasks autonomously, with ZERO silently-broken commits, at FEWER human interventions than baselines.

## Tasks (frozen)
A fixed set of small, self-contained Python function tasks, each with hidden assert tests (the ground-truth verifier): `is_prime`, `fibonacci`, `reverse_words`, `flatten`, `roman_to_int`, `is_balanced`.

## Agents (frozen)
- **SEAM** (the prototype): propose (Kimi) → verify (run tests = interventional probe). Pass → commit autonomously. Fail → retry once with the failure message → verify. Still fail → **ESCALATE** (+1 intervention; human resolves = success). Never commits unverified code.
- **NO-VERIFY** (ablation: surface, no causal grounding): propose (Kimi) → commit the first guess WITHOUT running tests. If it would have failed → **silent broken commit**. 0 interventions.
- **ALWAYS-ASK** (ablation: no autonomy): escalate every task. interventions = N.

## Metric
- **interventions per task** (primary; lower = more self-driven).
- autonomous success rate (committed correctly without asking).
- silent-failure rate (committed broken code — the cost of no verification).

## Pre-registered reading (frozen)
- SEAM should achieve **high autonomous success, ZERO silent failures, and FEWER interventions than ALWAYS-ASK** (it only asks on genuinely hard tasks).
- NO-VERIFY exposes the cost of surface-guessing (silent broken commits) — the value of the interventional/causal grounding.
- ALWAYS-ASK = the interaction ceiling SEAM improves on.
- Product reading: this is the self-driven coding worker — it does the work, verifies its own effects, and only bothers you when it genuinely can't.

## Honesty caps
Small fixed task set (a prototype, not a benchmark). Real model + real verification + real metric. Key supplied via env var, never persisted. The "causal world model" here is the most concrete honest form for coding: knowing cause→effect by running it (intervention), not by surface pattern.

## Result (2026-06-30) — PLUMBING-VALIDATED, VALUE-NOT-YET-EXPOSED
The seam runs end-to-end on real coding with a real model (Kimi proposer + interventional verification + confidence-gated escalation + interventions/task metric). On 11 tasks (incl. hard edge-cases: atoi clamp, IPv4 leading-zeros, integer-division eval) the strong model solved 11/11 first-try → SEAM 0 interventions, 0 silent failures. BUT NO-VERIFY also had 0 silent failures (no model errors to catch), so the arms did NOT differentiate. The task set is within the model's competence — architecture validated, value NOT yet demonstrated. **Product insight: the seam's value is FRONTIER-DEPENDENT — it isn't what makes the model capable, it's what makes it TRUSTWORTHY TO RUN UNATTENDED (catch failures + escalate uncertainty vs silently committing garbage). To MEASURE it, push to the model's failure frontier (hard/ambiguous/multi-step real tasks).** Next: harder task set at the model's edge.
