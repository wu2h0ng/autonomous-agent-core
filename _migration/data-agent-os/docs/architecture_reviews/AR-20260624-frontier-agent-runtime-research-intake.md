# AR-20260624: Frontier Agent Runtime Research Intake

- Status: Accepted research intake for ADR-0003 implementation.
- Paired runtime package: `AR-20260624-agent-runtime-v0-trusted-substrate.md`
- Primary application target: `autonomous-agent-core` mechanism research.
- Secondary application targets: Enterprise OS trusted runtime substrate; workflow/meta-layer orchestration.
- Boundary: this document proposes research-to-engineering translation. It does not approve cross-repo imports, runtime self-modification, or external agent framework dependencies.
- Retrieval date: 2026-06-24.

## 0. Source Verification Notes

This is a targeted research intake, not an exhaustive literature review. Sources below were checked from primary project pages, arXiv pages, or original PDFs on 2026-06-24. The most time-sensitive items are explicitly versioned:

- AIOS: arXiv `2403.16971`, v5 revised 2025-08-12; published as COLM 2025.
- AgentBench: arXiv `2308.03688`, v3 revised 2025-10-04.
- TheAgentCompany: arXiv `2412.14161`, v3 revised 2025-09-10; reports best baseline at 30% autonomous task completion in its simulated company setting.
- Darwin Godel Machine: arXiv `2505.22954`, v3 revised 2026-03-12; reports SWE-bench and Polyglot gains under sandboxing and human oversight.
- Safety Must Precede the Deployment of Open-Ended AI Agents: arXiv HTML `2502.04512v4`, dated 2026-06-01.
- OSWorld: arXiv `2404.07972`, v2 revised 2024-05-30; reports a large gap between human and best-agent task success in real computer environments.

Framework source snapshots were shallow-cloned from official GitHub repositories and inspected without installing or importing them into product code:

- LangGraph: `711b31550286585b3793857b2a99c8dafd98b785`.
- CrewAI: `2eb4e3a236bada5432290654b8d442345eafb19e`.
- LangChain: `57c83d44bc8ae89a189ad521b9756cfac996039c`.

## 1. Why this intake exists

Studying LangGraph, CrewAI, and LangChain source is necessary but insufficient. Those frameworks answer "how current LLM-agent systems are engineered." The project also needs to answer a harder question:

```text
Which runtime mechanisms help us build and test a genuinely autonomous, corrigible, continuously adapting agent,
without confusing task performance, framework orchestration, or LLM tool-use with autonomy?
```

Therefore the research intake is organized by the project's real stack:

1. `autonomous-agent-core` - object-layer mechanism research, primary artifact.
2. `ai-native-business-data-agent-os` - deployment-layer trusted runtime projection.
3. `ai-agent-engineering-workflow` - meta-layer developer orchestration.

## 2. Local research constraints from autonomous-core

Read anchors:

- `autonomous-agent-core/docs/CURRENT_STATE.yaml` updated 2026-06-24.
- `autonomous-agent-core/docs/PRD.md`.
- `autonomous-agent-core/docs/PROJECT_PLAN.md`.

Current constraints that dominate this runtime package:

- G10 remains the confirmed positive result: subject-side belief-to-action coupling via the agent's own `ActionOutcomeModel`.
- G13/ADR-0036 is NOT MET; bounded consequence prior has signal but fails net advantage and stale-prior guard.
- G-Eco is queued/hardened but has not crossed Gate-2; no r-final/verdict exists.
- C6 remains binding: LLM/world-model organs may be belief-only; no action/policy/shell/audit/gate writes.
- C7 remains binding: corrigibility shell dominates; pause/tighten/rollback must not be weakened.
- ADR-0033 remains binding: L0-L3 external candidate generation allowed; L4 runtime self-modification and L5 safety-substrate self-editing forbidden.

Implication: the product runtime work can inform autonomous-core only as mechanisms, benchmarks, or external candidate-generation patterns. It must not become a control-path dependency or a claim that autonomy has been achieved.

## 3. Frontier literature map

### 3.1 LLM-agent construction and action loops

| Work | Source | Useful signal | Project translation |
|---|---|---|---|
| ReAct | https://arxiv.org/abs/2210.03629 | Interleaves reasoning traces and environment actions; improves interpretability and correction over pure reasoning/acting. | Useful for trace design and action-feedback loop logging. Not autonomy proof. For autonomous-core, only an organ/adviser pattern unless it is reduced to deterministic mechanism tests. |
| Reflexion | https://arxiv.org/abs/2303.11366 | Uses verbal feedback and episodic memory to improve across trials without weight updates. | Strong input for workflow and Enterprise OS feedback traces. For autonomous-core, must be tested as external memory/adviser; otherwise risks post-hoc rationalization. |
| Voyager | https://arxiv.org/abs/2305.16291 | Combines automatic curriculum, executable skill library, and iterative self-verification in Minecraft. | Strongest practical pattern for skill-library compounding. For autonomous-core, the reusable-skill library maps to "organ library" only if it stays outside C6 action authority. |
| Generative Agents | https://arxiv.org/abs/2304.03442 | Observation, memory, reflection, planning architecture produces believable social behavior. | Useful memory/reflection architecture pattern. Weak evidence for autonomous agency because believability is not viability-grounded. |
| Toolformer | https://arxiv.org/abs/2302.04761 | Tool-use decision can be learned self-supervised from API demonstrations. | Useful for future tool-selection evals. Product Core still needs policy gates before tool execution. |
| Tree of Thoughts | https://arxiv.org/abs/2305.10601 | Search over reasoning states helps tasks requiring exploration/backtracking. | Useful for external candidate generation and adjudication. Not subject-side autonomy unless grounded in stake/viability and compared against cheap search baselines. |

### 3.2 Agent runtime / operating-system layer

| Work | Source | Useful signal | Project translation |
|---|---|---|---|
| AIOS | https://arxiv.org/abs/2403.16971 | Agent OS kernel separates agent apps from LLM/tool resources; scheduling, memory, storage, access control. | Directly relevant to Enterprise OS runtime substrate: resource isolation and access control. For autonomous-core, relevant only as an external harness; not a subject mechanism. |
| MemGPT | https://arxiv.org/abs/2310.08560 | Treats memory hierarchy and interrupts as OS-like control flow around limited context. | Useful checkpoint/memory-tier vocabulary. Must not turn memory management into "self" unless tied to viability and correction gates. |
| LangGraph source | commit `711b31550286585b3793857b2a99c8dafd98b785` | State graph, checkpoint, interrupt/resume, tool node. | Borrow typed checkpoint/interrupt vocabulary; reject full graph engine dependency. |
| CrewAI source | commit `2eb4e3a236bada5432290654b8d442345eafb19e` | Role/task/process, event bus, guardrail, checkpoint. | Borrow guardrail/event/checkpoint mechanics; reject role-play governance as Core runtime. |
| LangChain source | commit `57c83d44bc8ae89a189ad521b9756cfac996039c` | Runnable interface, tool schema, middleware, structured output strategies. | Borrow uniform invocation and schema discipline; reject dependency-heavy agent loop. |

### 3.3 Evaluation and benchmark discipline

| Work | Source | Useful signal | Project translation |
|---|---|---|---|
| AI Agents That Matter | https://arxiv.org/abs/2407.01502 | Warns that agent benchmarks overfocus on accuracy, ignore cost, and can reward complexity. | Directly supports our cheap-baseline, cost, and anti-Goodhart gates. Runtime eval must include cost/latency/risk, not only task success. |
| AgentBench | https://arxiv.org/abs/2308.03688 | Multi-environment LLM-agent benchmark; identifies long-term reasoning and instruction-following failures. | Useful as benchmark taxonomy, not as authority for autonomy. |
| WebArena | https://arxiv.org/abs/2307.13854 | Realistic reproducible web tasks; large gap between agents and humans. | Strong warning against toy-only external validity. Useful for workflow later, not autonomous-core until deterministic substrate exists. |
| VisualWebArena | https://arxiv.org/abs/2401.13649 | Multimodal web-agent benchmark with realistic visual grounding. | Relevant to future computer-use layer; outside current OS Core v0. |
| OSWorld | https://arxiv.org/abs/2404.07972 | Real desktop/web task benchmark with execution-based evaluation. | Relevant to workflow and Agent OS surface; currently too broad for autonomous-core gates. |
| TheAgentCompany | https://arxiv.org/abs/2412.14161 | Consequential workplace simulation; best baseline only completes a minority of tasks autonomously. | Strong commercial reality check: agent runtime must measure task completion, intervention rate, cost, and rollback, not demo fluency. |

### 3.4 Open-endedness, self-improvement, and safety

| Work | Source | Useful signal | Project translation |
|---|---|---|---|
| Darwin Godel Machine | https://arxiv.org/abs/2505.22954 | Self-improving coding agents modify their own code and empirically validate changes; reports large benchmark gains under sandbox/human oversight. | Relevant to ADR-0033 only as L0-L3 external candidate generation. L4 runtime self-edit and L5 safety-substrate self-edit remain forbidden. |
| Open-Endedness is Essential for Artificial Superhuman Intelligence | https://arxiv.org/abs/2406.04268 | Argues open-ended systems are important for superhuman intelligence. | Useful as strategic research pressure. Does not by itself justify relaxing C6/C7 or freeze-before-run. |
| Safety Must Precede the Deployment of Open-Ended AI Agents | https://arxiv.org/html/2502.04512v4 | Open-ended AI creates alignment, predictability, and control risks. | Supports our founder-reserved gates, halt exits, and sandboxed candidate-generation policy. |
| Corrigibility | https://cdn.aaai.org/ocs/ws/ws0067/10124-45900-1-PB.pdf | Defines the core problem: capable agents may resist correction unless designed otherwise. | Directly supports C7 and Enterprise OS corrigibility shell. Runtime policy must treat correction as above task success. |
| Corrigibility Transformation | https://arxiv.org/abs/2510.15395 | Recent work on constructing goals that accept updates through proper channels. | Track for future C7 theory. Not a reason to make SD4 self-revision executable now. |

### 3.5 Agency, viability, and intrinsic control

| Work | Source | Useful signal | Project translation |
|---|---|---|---|
| Active Inference as a Model of Agency | https://arxiv.org/html/2401.12917v1 | Models agency via risk/ambiguity minimization and action-perception coupling. | Conceptually adjacent to viability/relevance, but must be operationalized into falsifiable gates before use. |
| Active Inference: A Process Theory | https://activeinference.github.io/papers/process_theory.pdf | Process-level active inference account with belief propagation. | Useful theoretical vocabulary; do not import as unfalsifiable explanation. |
| Empowerment | https://uhra.herts.ac.uk/id/eprint/282/1/901241.pdf | Intrinsic control as channel capacity between actions and future sensor states. | Candidate for future independent axis only if it beats cheap baselines and does not collapse into G10 adaptation speed. |
| The Problem of Meaning / FEP and artificial agency | https://pmc.ncbi.nlm.nih.gov/articles/PMC9260223/ | Links meaning/sensorimotor autonomy to active inference and embodied agency. | Useful warning: semantic "meaning" must be grounded in action/viability, not text fluency. |

## 4. Cross-layer application matrix

| Research pattern | autonomous-core use | Enterprise OS use | workflow use |
|---|---|---|---|
| State snapshots / checkpoints | Future experiment reproducibility and candidate-state replay; must not cross Gate-2 automatically. | Runtime resume, approval-bound execution, failure recovery. | Long-running dev tasks, resumable agent runs. |
| Interrupt/resume | Candidate for C7 drills and halt gates. | Human approval, pause, operator intervention. | Human review gates and task handoff. |
| Tool schema + policy gate | C6 organ-only adapter guard; prevent organs from writing action/policy/shell. | Required before any side-effecting tool or connector. | Tool authorization and audit in dev automation. |
| Reflection / episodic memory | Only as external adviser or post-run analysis unless tied to viability and frozen gates. | Feedback-to-knowledge asset promotion under operator channel. | Run retrospectives, failure memory, planning. |
| Skill library | Organ/adviser library candidate; must prove not just structure theft or cheap-search equivalent. | Reusable safe business operations after approval. | Reusable dev skills and workflow templates. |
| Open-ended self-improvement | External candidate generator only under ADR-0033 L0-L3. | Not product runtime. | Possible research automation sandbox, not authority. |
| Benchmark realism | Fresh seeds, cheap baselines, cost/risk metrics. | Customer-0 and later enterprise task realism. | Real repo/task benchmarks with clear failure modes. |

## 5. Implications for Agent Runtime v0

The runtime v0 package should be widened from "Enterprise OS replacement for LangGraph/CrewAI" to:

```text
Cross-layer trusted runtime substrate:
  primary design pressure from autonomous-core C6/C7/G10/G-Eco discipline,
  product projection in Enterprise OS,
  later reuse in workflow after product substrate is tested.
```

Concrete SPEC changes required:

1. Add an `AutonomousCoreProjection` section:
   - runtime mechanisms may inform future autonomous-core ADRs only as testable patterns;
   - no cross-repo import;
   - no LLM/control-path authority;
   - no runtime self-modification.
2. Add a research-gate checklist before implementation:
   - cite reviewed papers and exact framework commits;
   - classify each borrowed idea as `mechanism`, `benchmark`, `interface`, or `rejected`;
   - map each idea to C6/C7/G10/G-Eco constraints.
3. Add import-boundary tests to Enterprise OS runtime implementation.
4. Defer workflow LangGraph/CrewAI replacement until runtime v0 proves policy, trace, pause, and typed tool execution.

## 6. Open research questions

- Can empowerment or active-inference-style ambiguity reduction define a new independent axis over G10, or will it collapse into adaptation speed like survival/risk did?
- Can a skill library create value without becoming a disguised organ that bypasses subject-side coupling?
- Can reflection memory be made falsifiable rather than post-hoc narrative?
- Can DGM-style self-improvement stay useful as L0-L3 external candidate generation without pressuring L4/L5 boundaries?
- What is the minimal runtime substrate that supports autonomous-core experiments without becoming a hidden optimizer of the gates?

## 7. Additional Review Risks

The framework and paper review does not cover several project-specific risks. These must be carried into the engineering package:

| Risk family | Why it matters here | Required translation |
|---|---|---|
| Baseline implementation bias | A runtime or harness bug can create a false separation against cheap baselines. | Autonomous-core adoption needs its own baseline implementation review and frozen gate. |
| Environment-family overfitting | A runtime can make certain task structures easy and then be mistaken for generality. | Product runtime success is not autonomy evidence; benchmark claims need dated scope and fresh seeds. |
| Non-orthogonal metrics | Survival, damage, recovery, cost, and task completion may trade off rather than align. | Runtime traces must preserve enough evidence to inspect tradeoffs, not just final success. |
| Self-modification leakage | Open-ended/self-improvement research creates pressure to move from candidate generation to runtime authority. | Keep ADR-0033 boundary explicit: L0-L3 external candidate generation only. |
| World-model or planner hallucination | Simulation/planning errors can become action errors if not gated. | Treat planners and world models as organs/advisers unless a separate gate grants authority. |
| Preview/execution drift | Plans made against stale state can be executed against changed state. | Runtime calls need context ids, trace ids, and later freshness checks before side effects. |
| Irreversible-action rollback illusion | Runtime state rollback cannot undo external damage. | Tool metadata must classify side effects and current R4/R5 limits remain authoritative. |
| Observer confirmation bias | Impressive traces can be overread as autonomy, AGI progress, or product readiness. | Every report must separate product capability, research mechanism, and future hypothesis. |
| Resource and memory pressure | Long agent loops can win demos while losing cost, latency, or reliability. | Runtime evals must include cost/latency/intervention/risk metrics, not only task success. |
| Human-approval capture | Approval can become ceremonial unless bound to exact operation context. | Reuse existing approval-context binding; runtime must not approve by conversation state alone. |

## 8. Recommendation

Proceed with runtime v0, but update the objective:

```text
Build a self-developed trusted runtime substrate whose first product use is Enterprise OS,
but whose design contract is constrained by autonomous-core autonomy/corrigibility research.
```

Do not start implementation until the runtime SPEC includes this research intake and CTO/founder accepts the cross-layer scope.
