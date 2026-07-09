
"""
================================================================================
NOESIS: Pure Symbolic Cognitive Engine
================================================================================
A cognitive architecture where SYMBOLIC REASONING — not token prediction —
is the engine of thought.

Key Principles:
1. Neural networks exist ONLY in the periphery (sensory encoding)
2. ALL cognition happens via explicit symbol manipulation
3. World model is a STRUCTURED, HUMAN-READABLE causal graph — not latent vectors
4. Learning is SYMBOLIC INDUCTION (rule discovery) — not gradient descent
5. Self-improvement has THREE LAYERS: Knowledge → Architecture → Meta-cognition

Inspired by: SOAR, ACT-R, NARS, OpenCog, AERA, MicroPsi
================================================================================
"""

from dataclasses import dataclass, field
from typing import List, Dict, Set, Tuple, Optional, Callable, Any
from collections import defaultdict, deque
import copy
import json
import random
from enum import Enum, auto


# =============================================================================
# 1. FOUNDATIONAL SYMBOLIC REPRESENTATIONS
# =============================================================================

@dataclass(frozen=True)
class Symbol:
    """An atomic symbol in the cognitive system. Immutable."""
    name: str

    def __str__(self):
        return self.name

    def __repr__(self):
        return f"@{self.name}"


@dataclass
class WME:
    """
    Working Memory Element — the fundamental unit of symbolic representation.
    Format: (object ^attribute value) — SOAR-style triple.

    Examples:
        WME(Symbol("ball"), Symbol("color"), Symbol("red"))
        WME(Symbol("agent"), Symbol("location"), Symbol("room_A"))
    """
    obj: Symbol
    attribute: Symbol
    value: Any  # Can be Symbol, number, or complex structure

    def __str__(self):
        if isinstance(self.value, Symbol):
            return f"({self.obj} ^{self.attribute} {self.value})"
        return f"({self.obj} ^{self.attribute} {self.value})"

    def __hash__(self):
        return hash((self.obj.name, self.attribute.name, str(self.value)))

    def __eq__(self, other):
        if not isinstance(other, WME):
            return False
        return (self.obj.name == other.obj.name and 
                self.attribute.name == other.attribute.name and
                str(self.value) == str(other.value))


@dataclass
class Predicate:
    """A logical predicate for pattern matching in rules."""
    functor: str
    args: List[Any]

    def match(self, wme: WME, bindings: Dict[str, Any] = None) -> Optional[Dict[str, Any]]:
        """
        Attempt to unify this predicate with a WME.
        Returns updated bindings if match succeeds, None otherwise.
        """
        if bindings is None:
            bindings = {}

        new_bindings = dict(bindings)

        # Check functor matches attribute
        if self.functor != "wme" and self.functor != wme.attribute.name:
            return None

        # Unify arguments
        if len(self.args) < 2:
            return None

        # First arg is object, second is value
        obj_pat = self.args[0]
        val_pat = self.args[1] if len(self.args) > 1 else None

        # Bind object
        if isinstance(obj_pat, str) and obj_pat.startswith("?"):
            var_name = obj_pat[1:]
            if var_name in new_bindings:
                if new_bindings[var_name] != wme.obj.name:
                    return None
            else:
                new_bindings[var_name] = wme.obj.name
        elif isinstance(obj_pat, str):
            if obj_pat != wme.obj.name:
                return None

        # Bind value
        if val_pat is not None:
            if isinstance(val_pat, str) and val_pat.startswith("?"):
                var_name = val_pat[1:]
                val_str = wme.value.name if isinstance(wme.value, Symbol) else str(wme.value)
                if var_name in new_bindings:
                    if new_bindings[var_name] != val_str:
                        return None
                else:
                    new_bindings[var_name] = val_str
            elif isinstance(val_pat, str):
                val_str = wme.value.name if isinstance(wme.value, Symbol) else str(wme.value)
                if val_pat != val_str:
                    return None

        return new_bindings

    def __str__(self):
        args_str = ", ".join(str(a) for a in self.args)
        return f"{self.functor}({args_str})"


# =============================================================================
# 2. PRODUCTION RULE SYSTEM
# =============================================================================

@dataclass
class ProductionRule:
    """
    IF-THEN production rule — the fundamental unit of procedural knowledge.

    conditions: List of predicates that must match WMEs in working memory
    actions: List of action specifications (add, remove, modify WMEs)
    name: Human-readable identifier
    utility: Numeric preference value (learned via experience)
    """
    name: str
    conditions: List[Predicate]
    actions: List[Dict[str, Any]]
    utility: float = 0.5
    creation_time: int = 0
    firings: int = 0

    def match(self, working_memory: List[WME]) -> Optional[Dict[str, Any]]:
        """
        Try to match all conditions against working memory.
        Returns variable bindings if all conditions match, None otherwise.
        """
        bindings = {}

        for condition in self.conditions:
            matched = False
            for wme in working_memory:
                result = condition.match(wme, bindings)
                if result is not None:
                    bindings = result
                    matched = True
                    break
            if not matched:
                return None

        return bindings

    def fire(self, bindings: Dict[str, Any]) -> List[WME]:
        """Execute actions with given variable bindings."""
        results = []
        for action in self.actions:
            action_type = action.get("type", "add")

            if action_type == "add":
                # Instantiate variables and create new WME
                obj_name = self._instantiate(action["obj"], bindings)
                attr_name = self._instantiate(action["attr"], bindings)
                val = self._instantiate(action["value"], bindings)

                wme = WME(Symbol(obj_name), Symbol(attr_name), 
                         Symbol(val) if isinstance(val, str) else val)
                results.append(wme)

        self.firings += 1
        return results

    def _instantiate(self, pattern: Any, bindings: Dict[str, Any]) -> Any:
        """Replace variables with their bound values."""
        if isinstance(pattern, str) and pattern.startswith("?"):
            var_name = pattern[1:]
            return bindings.get(var_name, pattern)
        return pattern

    def __str__(self):
        return f"Rule[{self.name}](utility={self.utility:.2f}, fired={self.firings})"


# =============================================================================
# 3. EXPLICIT CAUSAL WORLD MODEL
# =============================================================================

@dataclass
class CausalNode:
    """A variable in the causal graph."""
    name: str
    domain: List[Any]  # Possible values
    current_value: Any = None

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other):
        return isinstance(other, CausalNode) and self.name == other.name


@dataclass
class CausalEdge:
    """A directed causal relationship: source → target."""
    source: CausalNode
    target: CausalNode
    strength: float = 1.0  # Causal strength (0-1)
    mechanism: str = ""    # Human-readable description of the mechanism

    def __str__(self):
        return f"{self.source.name} --[{self.mechanism}]--> {self.target.name}"


class CausalGraph:
    """
    Pearl-style Structural Causal Model (SCM).
    Explicit, human-readable causal graph — NOT a latent vector representation.
    """

    def __init__(self):
        self.nodes: Dict[str, CausalNode] = {}
        self.edges: List[CausalEdge] = []
        self.parents: Dict[str, List[CausalNode]] = defaultdict(list)
        self.children: Dict[str, List[CausalNode]] = defaultdict(list)

    def add_variable(self, name: str, domain: List[Any], current=None):
        """Add a causal variable."""
        self.nodes[name] = CausalNode(name, domain, current)

    def add_causal_link(self, source: str, target: str, mechanism: str = "", strength: float = 1.0):
        """Add a directed causal edge."""
        if source not in self.nodes or target not in self.nodes:
            raise ValueError(f"Nodes must be added before creating edges")

        edge = CausalEdge(self.nodes[source], self.nodes[target], strength, mechanism)
        self.edges.append(edge)
        self.parents[target].append(self.nodes[source])
        self.children[source].append(self.nodes[target])

    def intervene(self, variable: str, value: Any) -> 'CausalGraph':
        """
        Perform a do-intervention: do(variable = value).
        Returns a modified graph with the intervention applied.
        """
        # Create a copy and sever incoming edges to the intervened variable
        new_graph = copy.deepcopy(self)

        if variable in new_graph.nodes:
            new_graph.nodes[variable].current_value = value
            # Remove all parent edges (intervention overrides natural causes)
            new_graph.parents[variable] = []
            new_graph.edges = [e for e in new_graph.edges 
                              if e.target.name != variable]

        return new_graph

    def query(self, target: str, evidence: Dict[str, Any] = None) -> Any:
        """
        Simple causal inference: propagate evidence through the graph.
        Returns the most likely value of the target variable.
        """
        if evidence is None:
            evidence = {}

        # Set evidence
        for var, val in evidence.items():
            if var in self.nodes:
                self.nodes[var].current_value = val

        # Propagate forward from parents to children
        # (Simplified: assumes deterministic causal mechanisms)
        changed = True
        while changed:
            changed = False
            for node_name, node in self.nodes.items():
                if node.current_value is not None:
                    continue

                parents = self.parents[node_name]
                parent_values = {p.name: p.current_value for p in parents}

                if all(v is not None for v in parent_values.values()):
                    # Apply causal mechanism (simplified)
                    if node_name == "wet_ground":
                        if parent_values.get("rain", False) or parent_values.get("sprinkler", False):
                            node.current_value = True
                            changed = True
                    elif node_name == "slippery":
                        if parent_values.get("wet_ground", False):
                            node.current_value = True
                            changed = True
                    elif node_name == "fall":
                        if parent_values.get("slippery", False):
                            node.current_value = True
                            changed = True
                    else:
                        # Default: OR of parent values
                        node.current_value = any(parent_values.values())
                        changed = True

        return self.nodes[target].current_value if target in self.nodes else None

    def counterfactual(self, variable: str, hypothetical_value: Any, 
                       target: str) -> Any:
        """
        Answer a counterfactual query: "What would target be if variable had been X?"

        Three-step process (Pearl's ladder of causation):
        1. Abduction: infer exogenous variables from observed evidence
        2. Action: apply the intervention do(variable = X)
        3. Prediction: infer the target in the modified model
        """
        # Step 1: Use current state as abduction (simplified)
        # Step 2: Apply intervention
        intervened = self.intervene(variable, hypothetical_value)
        # Step 3: Query
        return intervened.query(target)

    def __str__(self):
        lines = ["Causal Graph:"]
        lines.append(f"  Variables: {list(self.nodes.keys())}")
        lines.append("  Edges:")
        for edge in self.edges:
            lines.append(f"    {edge}")
        return "\n".join(lines)


# =============================================================================
# 4. SYMBOLIC REASONING ENGINE
# =============================================================================

class ReasoningEngine:
    """
    Multi-modal reasoning engine supporting:
    - Deduction (logical entailment)
    - Induction (rule discovery from examples)  
    - Abduction (hypothesis generation)
    - Causal inference (do-calculus)
    """

    def __init__(self, causal_graph: CausalGraph):
        self.causal_graph = causal_graph
        self.induction_buffer: List[Tuple[List[WME], List[WME]]] = []  # (preconditions, effects)

    def deductive_inference(self, premises: List[WME], rules: List[ProductionRule]) -> List[WME]:
        """
        Deductive reasoning: apply rules to premises to derive conclusions.
        Returns all entailed WMEs.
        """
        conclusions = []

        for rule in rules:
            bindings = rule.match(premises)
            if bindings is not None:
                new_wmes = rule.fire(bindings)
                conclusions.extend(new_wmes)

        return conclusions

    def inductive_rule_discovery(self, examples: List[Tuple[List[WME], List[WME]]]) -> List[ProductionRule]:
        """
        INDUCTIVE LEARNING: Discover general rules from specific examples.
        This is SYMBOLIC learning — not gradient descent.

        Input: List of (preconditions, effects) pairs from experience
        Output: Generalized production rules
        """
        discovered_rules = []

        if len(examples) < 2:
            return discovered_rules

        # Find common patterns across examples
        # Simplified: generalize by finding shared structure
        for i in range(len(examples)):
            pre1, eff1 = examples[i]
            for j in range(i+1, len(examples)):
                pre2, eff2 = examples[j]

                # Try to find a generalized rule that covers both examples
                generalized = self._generalize(pre1, eff1, pre2, eff2)
                if generalized:
                    discovered_rules.append(generalized)

        return discovered_rules

    def _generalize(self, pre1: List[WME], eff1: List[WME], 
                    pre2: List[WME], eff2: List[WME]) -> Optional[ProductionRule]:
        """Attempt to generalize two example episodes into a rule."""
        # Find common effects
        common_effects = []
        for e1 in eff1:
            for e2 in eff2:
                if e1.attribute.name == e2.attribute.name:
                    common_effects.append(e1)

        if not common_effects:
            return None

        # Find common preconditions
        common_pre = []
        for p1 in pre1:
            for p2 in pre2:
                if p1.attribute.name == p2.attribute.name:
                    common_pre.append(p1)

        # Build generalized rule with variables
        conditions = []
        for p in common_pre:
            conditions.append(Predicate("wme", ["?obj", f"?{p.attribute.name}"]))

        actions = []
        for e in common_effects:
            actions.append({
                "type": "add",
                "obj": "?obj",
                "attr": e.attribute.name,
                "value": "?result"
            })

        return ProductionRule(
            name=f"induced_rule_{random.randint(1000, 9999)}",
            conditions=conditions,
            actions=actions,
            creation_time=0
        )

    def abductive_inference(self, observation: WME, rules: List[ProductionRule]) -> List[WME]:
        """
        Abductive reasoning: given an observation, what could explain it?
        Returns list of plausible hypotheses.
        """
        hypotheses = []

        for rule in rules:
            for action in rule.actions:
                if action.get("attr") == observation.attribute.name:
                    # This rule could produce this observation
                    # Generate hypothetical preconditions
                    for condition in rule.conditions:
                        hypo_wme = WME(
                            observation.obj,
                            Symbol(condition.functor if condition.functor != "wme" else "hypothesized"),
                            Symbol("unknown")
                        )
                        hypotheses.append(hypo_wme)

        return hypotheses

    def causal_query(self, target: str, evidence: Dict[str, Any] = None) -> Any:
        """Query the causal world model."""
        return self.causal_graph.query(target, evidence)

    def counterfactual_query(self, intervention: str, iv_value: Any, target: str) -> Any:
        """Answer a counterfactual query using the causal model."""
        return self.causal_graph.counterfactual(intervention, iv_value, target)


# =============================================================================
# 5. MOTIVATION SYSTEM (Intrinsic Drives)
# =============================================================================

@dataclass
class Need:
    """An intrinsic motivational need."""
    name: str
    current_level: float = 0.5  # 0 = fully satisfied, 1 = urgent
    decay_rate: float = 0.01
    priority_weight: float = 1.0

    def update(self, delta: float = 0):
        """Update need level (increases over time = builds up)."""
        self.current_level = min(1.0, self.current_level + self.decay_rate + delta)

    def satisfy(self, amount: float):
        """Reduce need level when satisfied."""
        self.current_level = max(0.0, self.current_level - amount)

    @property
    def urgency(self) -> float:
        return self.current_level * self.priority_weight


class MotivationSystem:
    """
    Intrinsic motivation system inspired by MicroPsi and PEPA.
    Drives cognitive resource allocation and goal generation.
    """

    def __init__(self):
        self.needs = {
            "curiosity": Need("curiosity", decay_rate=0.02, priority_weight=1.2),
            "consistency": Need("consistency", decay_rate=0.01, priority_weight=1.0),
            "competence": Need("competence", decay_rate=0.015, priority_weight=1.1),
            "survival": Need("survival", decay_rate=0.005, priority_weight=2.0),
            "social": Need("social", decay_rate=0.01, priority_weight=0.8),
        }
        self.dominant_need: Optional[str] = None

    def update_all(self):
        """Update all need levels."""
        for need in self.needs.values():
            need.update()

        # Identify dominant need
        self.dominant_need = max(self.needs, key=lambda n: self.needs[n].urgency)

    def get_goal_bias(self) -> Dict[str, float]:
        """Return goal-generation bias based on current needs."""
        return {name: need.urgency for name, need in self.needs.items()}

    def satisfy(self, need_name: str, amount: float):
        """Satisfy a specific need."""
        if need_name in self.needs:
            self.needs[need_name].satisfy(amount)

    def generate_intrinsic_goal(self) -> Optional[WME]:
        """Generate a goal based on the dominant need."""
        if self.dominant_need is None:
            return None

        goal_map = {
            "curiosity": ("explore", "new_information"),
            "consistency": ("resolve", "conflicts"),
            "competence": ("master", "skills"),
            "survival": ("protect", "integrity"),
            "social": ("interact", "agents"),
        }

        action, target = goal_map.get(self.dominant_need, ("act", "environment"))
        return WME(Symbol("self"), Symbol("goal"), 
                  Symbol(f"{action}_{target}"))

    def __str__(self):
        lines = ["Motivation System:"]
        for name, need in sorted(self.needs.items(), key=lambda x: -x[1].urgency):
            bar = "█" * int(need.urgency * 20) + "░" * (20 - int(need.urgency * 20))
            marker = " <-- DOMINANT" if name == self.dominant_need else ""
            lines.append(f"  {name:12s} [{bar}] {need.urgency:.2f}{marker}")
        return "\n".join(lines)


# =============================================================================
# 6. THREE-LAYER SELF-IMPROVEMENT SYSTEM
# =============================================================================

class SelfImprovementSystem:
    """
    Recursive three-layer self-improvement:
    Layer 1: Knowledge (what the agent knows)
    Layer 2: Architecture (how the agent reasons)
    Layer 3: Meta-cognition (how the agent learns)
    """

    def __init__(self, procedural_memory: List[ProductionRule],
                 reasoning_engine: ReasoningEngine,
                 motivation_system: MotivationSystem):
        self.procedural_memory = procedural_memory
        self.reasoning = reasoning_engine
        self.motivation = motivation_system

        # Layer 1: Knowledge improvement state
        self.experience_buffer: deque = deque(maxlen=1000)
        self.discovered_rules: List[ProductionRule] = []
        self.belief_revision_queue: List[WME] = []

        # Layer 2: Architecture improvement state
        self.rule_utility_history: Dict[str, List[float]] = defaultdict(list)
        self.inference_strategy = "breadth_first"  # Can be modified
        self.memory_organization = "attribute_indexed"  # Can be modified

        # Layer 3: Meta-cognitive state
        self.reflection_log: List[Dict] = []
        self.learning_paradigms = ["induction", "chunking", "abduction"]
        self.active_paradigm = "induction"
        self.performance_history: deque = deque(maxlen=100)

    # ========== LAYER 1: KNOWLEDGE SELF-IMPROVEMENT ==========

    def layer1_rule_discovery(self, recent_experiences: List[Tuple[List[WME], List[WME]]]):
        """
        Discover new rules from recent experiences via symbolic induction.
        This is NOT gradient descent — it is logical generalization.
        """
        if len(recent_experiences) < 3:
            return

        new_rules = self.reasoning.inductive_rule_discovery(recent_experiences)

        for rule in new_rules:
            # Validate: does the rule cover known examples without contradiction?
            if self._validate_rule(rule, recent_experiences):
                self.discovered_rules.append(rule)
                self.procedural_memory.append(rule)
                print(f"    [L1] Discovered new rule: {rule.name}")

    def layer1_belief_revision(self, contradictions: List[Tuple[WME, WME]]):
        """
        Revise beliefs when contradictions are detected.
        Uses truth maintenance (non-monotonic reasoning).
        """
        for old, new in contradictions:
            # Retract old belief, adopt new one
            self.belief_revision_queue.append(new)
            print(f"    [L1] Revised belief: {old} -> {new}")

    def layer1_skill_compilation(self, successful_episodes: List[Dict]):
        """
        SOAR-style chunking: compile multi-step reasoning into single rules.
        """
        for episode in successful_episodes:
            pre = episode.get("preconditions", [])
            result = episode.get("result", [])

            if pre and result:
                # Create a chunk: the preconditions directly produce the result
                chunk = ProductionRule(
                    name=f"chunk_{random.randint(10000, 99999)}",
                    conditions=[Predicate("wme", [p.obj.name, p.value.name if isinstance(p.value, Symbol) else str(p.value)]) 
                               for p in pre],
                    actions=[{"type": "add", "obj": r.obj.name, "attr": r.attribute.name, 
                             "value": r.value.name if isinstance(r.value, Symbol) else str(r.value)} 
                            for r in result],
                    utility=0.7
                )
                self.procedural_memory.append(chunk)
                print(f"    [L1] Compiled chunk: {chunk.name}")

    # ========== LAYER 2: ARCHITECTURE SELF-IMPROVEMENT ==========

    def layer2_rule_set_optimization(self):
        """
        Optimize the rule set based on utility history.
        Remove low-utility rules, promote high-utility ones.
        """
        # Calculate average utility per rule
        avg_utilities = {}
        for rule in self.procedural_memory:
            history = self.rule_utility_history.get(rule.name, [])
            if history:
                avg_utilities[rule.name] = sum(history) / len(history)

        # Remove rules with consistently low utility
        to_remove = [name for name, util in avg_utilities.items() if util < 0.2]
        self.procedural_memory = [r for r in self.procedural_memory if r.name not in to_remove]

        if to_remove:
            print(f"    [L2] Optimized rule set: removed {len(to_remove)} low-utility rules")

    def layer2_inference_strategy_adaptation(self, performance: float):
        """
        Adapt the inference strategy based on performance.
        """
        self.performance_history.append(performance)

        if len(self.performance_history) < 10:
            return

        recent_avg = sum(list(self.performance_history)[-10:]) / 10

        if recent_avg < 0.3:
            # Performance is poor — try different strategy
            strategies = ["breadth_first", "depth_first", "utility_guided", "goal_directed"]
            current_idx = strategies.index(self.inference_strategy) if self.inference_strategy in strategies else 0
            new_strategy = strategies[(current_idx + 1) % len(strategies)]
            self.inference_strategy = new_strategy
            print(f"    [L2] Adapted inference strategy: {new_strategy}")

    def layer2_memory_restructuring(self):
        """Restructure memory organization for better retrieval."""
        # Simplified: switch indexing strategy
        orgs = ["attribute_indexed", "object_indexed", "temporal", "hierarchical"]
        current = orgs.index(self.memory_organization) if self.memory_organization in orgs else 0
        self.memory_organization = orgs[(current + 1) % len(orgs)]
        print(f"    [L2] Restructured memory: {self.memory_organization}")

    # ========== LAYER 3: META-COGNITIVE SELF-IMPROVEMENT ==========

    def layer3_reasoning_method_invention(self):
        """
        Invent new reasoning methods by reflecting on failure patterns.
        This is the highest level of self-improvement.
        """
        # Analyze reflection log for systematic failure patterns
        if len(self.reflection_log) < 5:
            return

        recent = list(self.reflection_log)[-5:]
        failures = [r for r in recent if r.get("outcome") == "failure"]

        if len(failures) >= 3:
            # Detect pattern: what type of reasoning consistently fails?
            failed_types = [f.get("reasoning_type", "unknown") for f in failures]

            # Invent a hybrid approach
            if "deduction" in failed_types and "abduction" in failed_types:
                print("    [L3] Invented new reasoning method: 'abductive-deductive cycle'")
                self.learning_paradigms.append("abductive_deductive_cycle")

            if "induction" in failed_types:
                print("    [L3] Invented new reasoning method: 'analogical_transfer'")
                self.learning_paradigms.append("analogical_transfer")

    def layer3_learning_algorithm_design(self):
        """
        Design new learning algorithms based on meta-cognitive reflection.
        """
        # If current paradigm underperforms, design a new one
        if len(self.performance_history) >= 20:
            recent = list(self.performance_history)[-20:]
            if sum(recent) / len(recent) < 0.4:
                # Design a hybrid learning approach
                print("    [L3] Designed new learning algorithm: 'multi-paradigm_ensemble'")
                self.active_paradigm = "multi-paradigm_ensemble"

    def layer3_goal_system_restructuring(self):
        """
        Restructure the motivation/goal system itself.
        """
        needs = self.motivation.needs

        # If competence is always low, increase its priority
        if needs["competence"].current_level > 0.8:
            needs["competence"].priority_weight *= 1.1
            print(f"    [L3] Restructured goal system: competence weight -> {needs['competence'].priority_weight:.2f}")

    def reflect_and_improve(self, cycle_result: Dict):
        """
        Main entry point: perform all three layers of self-improvement.
        """
        print("\n  === Self-Improvement Cycle ===")

        # Log reflection
        self.reflection_log.append({
            "cycle": cycle_result.get("cycle", 0),
            "outcome": cycle_result.get("outcome", "unknown"),
            "reasoning_type": cycle_result.get("reasoning_type", "unknown"),
            "performance": cycle_result.get("performance", 0.0)
        })

        # Layer 1: Always active
        experiences = cycle_result.get("experiences", [])
        if experiences:
            self.layer1_rule_discovery(experiences)
            self.layer1_skill_compilation(cycle_result.get("successful_episodes", []))

        contradictions = cycle_result.get("contradictions", [])
        if contradictions:
            self.layer1_belief_revision(contradictions)

        # Layer 2: Triggered by impasse or performance degradation
        performance = cycle_result.get("performance", 0.5)
        if performance < 0.4 or cycle_result.get("impasse", False):
            self.layer2_rule_set_optimization()
            self.layer2_inference_strategy_adaptation(performance)
            if cycle_result.get("impasse", False):
                self.layer2_memory_restructuring()

        # Layer 3: Triggered by systematic failures
        if len(self.reflection_log) >= 10:
            recent_failures = sum(1 for r in list(self.reflection_log)[-10:] 
                                 if r.get("outcome") == "failure")
            if recent_failures >= 5:
                self.layer3_reasoning_method_invention()
                self.layer3_learning_algorithm_design()
                self.layer3_goal_system_restructuring()


# =============================================================================
# 7. MAIN COGNITIVE AGENT
# =============================================================================

class NoesisAgent:
    """
    The NOESIS cognitive agent.
    Pure symbolic core. No token prediction. No frozen LLM.
    """

    def __init__(self, name: str = "noesis_1"):
        self.name = name
        self.cycle_count = 0

        # Working Memory (active symbolic state)
        self.working_memory: List[WME] = []

        # Long-term Memories
        self.procedural_memory: List[ProductionRule] = []
        self.semantic_memory: List[WME] = []
        self.episodic_memory: List[List[WME]] = []

        # Causal World Model
        self.causal_graph = CausalGraph()
        self._initialize_causal_model()

        # Core Systems
        self.reasoning = ReasoningEngine(self.causal_graph)
        self.motivation = MotivationSystem()
        self.self_improvement = SelfImprovementSystem(
            self.procedural_memory, self.reasoning, self.motivation
        )

        # Seed knowledge (initial rules)
        self._seed_procedural_knowledge()

        print(f"=== NOESIS Agent '{name}' Initialized ===")
        print(f"  Working Memory: empty")
        print(f"  Procedural Rules: {len(self.procedural_memory)} (seed)")
        print(f"  Causal Variables: {len(self.causal_graph.nodes)}")
        print(f"  Intrinsic Needs: {list(self.motivation.needs.keys())}")

    def _initialize_causal_model(self):
        """Initialize the explicit causal world model."""
        # Causal variables
        self.causal_graph.add_variable("rain", [True, False], False)
        self.causal_graph.add_variable("sprinkler", [True, False], False)
        self.causal_graph.add_variable("wet_ground", [True, False], False)
        self.causal_graph.add_variable("slippery", [True, False], False)
        self.causal_graph.add_variable("fall", [True, False], False)

        # Causal edges (explicit, human-readable)
        self.causal_graph.add_causal_link("rain", "wet_ground", 
                                         "precipitation moistens ground", 0.95)
        self.causal_graph.add_causal_link("sprinkler", "wet_ground",
                                         "water spray moistens ground", 0.90)
        self.causal_graph.add_causal_link("wet_ground", "slippery",
                                         "water reduces friction", 0.85)
        self.causal_graph.add_causal_link("slippery", "fall",
                                         "reduced friction causes loss of balance", 0.70)

    def _seed_procedural_knowledge(self):
        """Seed the agent with initial production rules."""
        # Rule 1: If object is observed, classify it
        self.procedural_memory.append(ProductionRule(
            name="perceive_object",
            conditions=[Predicate("wme", ["?obj", "?type"])],
            actions=[{"type": "add", "obj": "?obj", "attr": "status", "value": "perceived"}],
            utility=0.5
        ))

        # Rule 2: If ground is wet, note slippery risk
        self.procedural_memory.append(ProductionRule(
            name="wet_ground_warning",
            conditions=[Predicate("wme", ["ground", "wet"])],
            actions=[{"type": "add", "obj": "self", "attr": "alert", "value": "slippery_surface"}],
            utility=0.8
        ))

        # Rule 3: If goal exists, plan action
        self.procedural_memory.append(ProductionRule(
            name="goal_response",
            conditions=[Predicate("wme", ["self", "?goal"])],
            actions=[{"type": "add", "obj": "self", "attr": "intention", "value": "act_on_goal"}],
            utility=0.6
        ))

        # Rule 4: If slippery, move carefully
        self.procedural_memory.append(ProductionRule(
            name="careful_movement",
            conditions=[Predicate("wme", ["self", "slippery_surface"])],
            actions=[{"type": "add", "obj": "self", "attr": "action", "value": "walk_carefully"}],
            utility=0.9
        ))

    def perceive(self, raw_input: Dict[str, Any]):
        """
        Perception: Convert raw sensory input into symbolic WMEs.

        In a full system, neural sensors would process raw input (images, sound, text)
        and the Symbolizer would convert to structured predicates.
        Here we simulate the output of that process.
        """
        new_wmes = []

        for key, value in raw_input.items():
            parts = key.split("_")
            if len(parts) >= 2:
                obj = Symbol(parts[0])
                attr = Symbol("_".join(parts[1:]))
                val = Symbol(str(value)) if isinstance(value, str) else value
                wme = WME(obj, attr, val)
                new_wmes.append(wme)
                self.working_memory.append(wme)

        return new_wmes

    def decide_cycle(self) -> Dict:
        """
        THE COGNITIVE DECISION CYCLE.

        One complete cycle:
        1. Update motivations
        2. Match rules against working memory
        3. Select operator (action)
        4. Apply operator
        5. Causal reasoning about consequences
        6. Self-improvement

        NO token prediction. NO neural network in the loop.
        Pure symbolic reasoning.
        """
        self.cycle_count += 1
        print(f"\n{'='*60}")
        print(f"  COGNITIVE CYCLE {self.cycle_count}")
        print(f"{'='*60}")

        # Step 1: Update motivation system
        print(f"\n  [1] Motivation Update:")
        self.motivation.update_all()
        print(f"      Dominant need: {self.motivation.dominant_need}")

        # Step 2: Generate intrinsic goal
        intrinsic_goal = self.motivation.generate_intrinsic_goal()
        if intrinsic_goal:
            self.working_memory.append(intrinsic_goal)
            print(f"      Generated goal: {intrinsic_goal}")

        # Step 3: Rule matching
        print(f"\n  [2] Rule Matching (against {len(self.working_memory)} WMEs):")
        matched_rules = []
        for rule in self.procedural_memory:
            bindings = rule.match(self.working_memory)
            if bindings is not None:
                matched_rules.append((rule, bindings))
                print(f"      MATCH: {rule.name} with bindings {bindings}")

        # Step 4: Operator selection (by utility)
        print(f"\n  [3] Operator Selection:")
        if matched_rules:
            best_rule, best_bindings = max(matched_rules, key=lambda x: x[0].utility)
            print(f"      Selected: {best_rule.name} (utility={best_rule.utility:.2f})")
        else:
            print(f"      IMPASSE: No matching rules!")
            best_rule, best_bindings = None, {}

        # Step 5: Apply operator
        print(f"\n  [4] Operator Application:")
        new_wmes = []
        if best_rule:
            new_wmes = best_rule.fire(best_bindings)
            for wme in new_wmes:
                self.working_memory.append(wme)
                print(f"      ADDED: {wme}")

        # Step 6: Causal reasoning
        print(f"\n  [5] Causal Reasoning:")
        # Check if any WMEs relate to causal variables
        for wme in self.working_memory:
            if wme.obj.name in self.causal_graph.nodes:
                self.causal_graph.nodes[wme.obj.name].current_value =                     wme.value.name if isinstance(wme.value, Symbol) else wme.value

        # Predict consequences
        if "wet_ground" in [w.attribute.name for w in self.working_memory]:
            result = self.reasoning.causal_query("slippery", {"wet_ground": True})
            print(f"      Causal prediction: wet_ground=True → slippery={result}")

            result2 = self.reasoning.causal_query("fall", {"wet_ground": True})
            print(f"      Causal prediction: wet_ground=True → fall={result2}")

        # Step 7: Counterfactual reasoning (demonstration)
        if self.cycle_count >= 3:
            print(f"\n  [6] Counterfactual Simulation:")
            cf = self.reasoning.counterfactual_query("sprinkler", True, "fall")
            print(f"      'What if sprinkler=ON?' → fall={cf}")

            cf2 = self.reasoning.counterfactual_query("sprinkler", False, "fall")
            print(f"      'What if sprinkler=OFF?' → fall={cf2}")

        # Step 8: Self-improvement
        print(f"\n  [7] Self-Improvement:")

        # Build experience record for learning
        cycle_wm = list(self.working_memory)
        experiences = [(cycle_wm, new_wmes)] if new_wmes else []

        cycle_result = {
            "cycle": self.cycle_count,
            "outcome": "success" if best_rule else "failure",
            "reasoning_type": "deduction" if best_rule else "impasse",
            "performance": best_rule.utility if best_rule else 0.0,
            "experiences": experiences,
            "impasse": best_rule is None,
            "successful_episodes": [{"preconditions": cycle_wm, "result": new_wmes}] if best_rule else [],
            "contradictions": []
        }

        self.self_improvement.reflect_and_improve(cycle_result)

        # Store episode
        self.episodic_memory.append(list(self.working_memory))

        return {
            "cycle": self.cycle_count,
            "rule_fired": best_rule.name if best_rule else None,
            "new_wmes": len(new_wmes),
            "wm_size": len(self.working_memory),
            "dominant_need": self.motivation.dominant_need
        }

    def demonstrate(self):
        """Run a complete demonstration of the NOESIS agent."""
        print("\n" + "="*70)
        print("  NOESIS: PURE SYMBOLIC COGNITIVE ENGINE DEMONSTRATION")
        print("="*70)

        scenarios = [
            {"description": "Normal day — no rain, no sprinkler", 
             "input": {"ground_state": "dry", "weather": "sunny"}},

            {"description": "Sprinkler is ON — ground gets wet", 
             "input": {"ground_state": "dry", "sprinkler_status": "on"}},

            {"description": "Rain starts — ground gets wet", 
             "input": {"ground_state": "dry", "weather": "rainy", "sprinkler_status": "off"}},

            {"description": "Ground is wet — dangerous situation", 
             "input": {"ground_state": "wet", "weather": "cloudy"}},

            {"description": "Agent observes slippery surface", 
             "input": {"self_location": "sidewalk", "ground_friction": "low"}},

            {"description": "New object encountered — cup on table", 
             "input": {"cup_location": "table", "cup_type": "container"}},

            {"description": "Complex situation — rain + sprinkler both ON", 
             "input": {"weather": "rainy", "sprinkler_status": "on", "ground_state": "wet"}},
        ]

        results = []

        for i, scenario in enumerate(scenarios):
            print(f"\n{'─'*70}")
            print(f"  SCENARIO {i+1}: {scenario['description']}")
            print(f"{'─'*70}")

            # Perceive
            print(f"\n  Perceiving: {scenario['input']}")
            self.perceive(scenario['input'])

            # Decide
            result = self.decide_cycle()
            results.append(result)

            # Print motivation state
            print(f"\n  {self.motivation}")

        # Summary
        print(f"\n{'='*70}")
        print(f"  DEMONSTRATION SUMMARY")
        print(f"{'='*70}")
        print(f"  Total cycles: {self.cycle_count}")
        print(f"  Total rules in memory: {len(self.procedural_memory)} ({len(self.procedural_memory) - 4} learned)")
        print(f"  Discovered rules: {len(self.self_improvement.discovered_rules)}")
        print(f"  Episodes stored: {len(self.episodic_memory)}")
        print(f"  Reflections logged: {len(self.self_improvement.reflection_log)}")
        print(f"\n  KEY CHARACTERISTICS:")
        print(f"    ✓  Zero token prediction")
        print(f"    ✓  Zero neural networks in core")
        print(f"    ✓  Explicit causal reasoning (Pearl-style SCM)")
        print(f"    ✓  Symbolic rule induction (not gradient descent)")
        print(f"    ✓  Three-layer recursive self-improvement")
        print(f"    ✓  Intrinsic motivation system")
        print(f"    ✓  Counterfactual simulation capability")
        print(f"    ✓  All knowledge is human-readable symbolic structures")

        return results


# =============================================================================
# 8. RUN DEMONSTRATION
# =============================================================================
if __name__ == "__main__":
    agent = NoesisAgent("alpha")
    agent.demonstrate()
