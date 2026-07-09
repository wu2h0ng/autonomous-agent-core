"""Ontology Engine — Palantir-style real-world semantic anchoring.

Bridges the gap between engine abstractions (V1→V4) and business concepts
("discount causes sales"). Four-layer ontology stack:

Layer 1 — Object Types: business entity classes
    e.g., PricingVariable, RevenueMetric, MarketingCampaign, RiskIndicator
Layer 2 — Properties: entity attributes mapped to data columns
    e.g., PricingVariable.unit_price → data[:,0], RevenueMetric.daily_sales → data[:,4]
Layer 3 — Links: relationships between entities
    e.g., PricingVariable.causes→RevenueMetric (from CWM DAG), MarketingCampaign.affects→PricingVariable
Layer 4 — Actions: executable interventions on entities
    e.g., AdjustDiscount on PricingVariable, BoostTraffic on MarketingCampaign

The ontology is auto-seeded from variable names then enrichable by operator.
CWM-discovered DAG edges become causal Links. Goals become proposed Actions.
The ExecutionBridge executes Actions on typed entities.

Usage:
    from aac.ontology_engine import OntologyEngine
    onto = OntologyEngine()
    onto.add_object_type("PricingVariable", "price")
    onto.bind_variable(0, "PricingVariable", "unit_price")
    onto.add_link(0, 4, "causes", "CWM")
    onto.add_action("AdjustDiscount", "PricingVariable", {"min": 0.05, "max": 0.50})
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class ObjectType:
    """Business entity class."""
    type_id: str          # e.g., "PricingVariable"
    label: str            # e.g., "定价变量"
    description: str = ""
    parent_type: str = "" # e.g., "BusinessMetric" (inheritance)
    is_intervenable: bool = False


@dataclass
class Property:
    """Measurable attribute of an ObjectType, mapped to a data column."""
    prop_id: str          # e.g., "unit_price"
    label: str            # e.g., "单价"
    object_type: str      # parent ObjectType
    data_column: int      # column index in observation matrix
    unit: str = ""        # e.g., "CNY", "%", "count"
    value_range: tuple[float, float] = (0.0, 0.0)  # (min, max) from data
    is_target: bool = False   # can be a goal target
    is_intervenable: bool = False  # can be intervened on


@dataclass
class Link:
    """Directed relationship between two ObjectTypes."""
    link_id: str          # e.g., "price_causes_sales"
    source_type: str      # source ObjectType
    target_type: str      # target ObjectType
    relation: str         # "causes", "correlates_with", "affects", "inhibits"
    source_var: int       # source variable index
    target_var: int       # target variable index
    confidence: float = 0.5
    evidence: str = ""    # "CWM", "operator", "temporal", "LLM"
    is_verified: bool = False  # confirmed by intervention data


@dataclass
class Action:
    """Executable intervention on an ObjectType."""
    action_id: str        # e.g., "AdjustDiscount"
    label: str            # e.g., "调整折扣"
    target_type: str      # ObjectType to act on
    target_var: int       # variable index
    parameters: dict = field(default_factory=dict)  # {"min": 0.05, "max": 0.50}
    expected_effect: str = ""  # "increases sales by ~200/unit"
    risk_tier: int = 1    # R1 (safe) to R5 (dangerous)
    approved: bool = False


@dataclass
class BusinessOntology:
    """Complete four-layer business ontology."""
    object_types: dict[str, ObjectType] = field(default_factory=dict)
    properties: dict[str, Property] = field(default_factory=dict)
    links: list[Link] = field(default_factory=list)
    actions: dict[str, Action] = field(default_factory=dict)
    variable_bindings: dict[int, str] = field(default_factory=dict)
    n_variables: int = 0
    source: str = "auto"  # "auto", "operator", "mixed"

    def to_json(self) -> str:
        d = {
            "object_types": {k: asdict(v) for k, v in self.object_types.items()},
            "properties": {k: asdict(v) for k, v in self.properties.items()},
            "links": [asdict(l) for l in self.links],
            "actions": {k: asdict(v) for k, v in self.actions.items()},
            "variable_bindings": self.variable_bindings,
            "n_variables": self.n_variables,
            "source": self.source,
        }
        return json.dumps(d, indent=2, ensure_ascii=False)

    @classmethod
    def from_json(cls, s: str) -> BusinessOntology:
        d = json.loads(s)
        onto = cls(n_variables=d["n_variables"], source=d.get("source", "auto"))
        onto.object_types = {k: ObjectType(**v) for k, v in d.get("object_types", {}).items()}
        onto.properties = {k: Property(**v) for k, v in d.get("properties", {}).items()}
        onto.links = [Link(**l) for l in d.get("links", [])]
        onto.actions = {k: Action(**v) for k, v in d.get("actions", {}).items()}
        onto.variable_bindings = {int(k): v for k, v in d.get("variable_bindings", {}).items()}
        return onto


class OntologyEngine:
    """Builds and maintains the four-layer business ontology — DOMAIN-AGNOSTIC.

    Works on ANY domain by combining:
    1. LLM inference: propose ObjectTypes from variable names (domain knowledge)
    2. CWM structural clustering: densely connected variables → same conceptual type
    3. Operator enrichment: manual type assignment, correction, override
    4. Schema persistence: save/load as JSON

    Without LLM backend: uses CWM structural clustering + generic naming.
    With LLM backend: uses domain knowledge to propose meaningful type labels.
    """

    def __init__(self, llm_backend: Any = None):
        self.onto = BusinessOntology()
        self.backend = llm_backend

    def auto_discover(self, variable_names: list[str],
                      dag: frozenset[tuple[int, int]] | None = None,
                      skeleton: frozenset[frozenset] | None = None,
                      obs: list[list[float]] | None = None,
                      domain_hint: str = ""):
        """Auto-build ontology from CWM pipeline output.

        Uses LLM (if available) to infer ObjectTypes, falls back to
        CWM structural clustering + generic naming.
        """
        n = len(variable_names)
        self.onto.n_variables = n
        self.onto.source = "auto"

        type_map = self._infer_types(variable_names, dag, domain_hint)

        import statistics
        for i, name in enumerate(variable_names):
            type_id = type_map.get(i, "Variable")
            if type_id not in self.onto.object_types:
                self.onto.object_types[type_id] = ObjectType(
                    type_id=type_id, label=type_id,
                )
            prop_id = f"{type_id}.{name}"
            self.onto.properties[prop_id] = Property(
                prop_id=prop_id, label=name, object_type=type_id,
                data_column=i,
            )
            self.onto.variable_bindings[i] = prop_id
            if obs:
                col = [obs[t][i] for t in range(len(obs))]
                self.onto.properties[prop_id].value_range = (
                    min(col), max(col),
                )

        if dag:
            for u, v in dag:
                src_name = variable_names[u] if u < n else f"V{u}"
                tgt_name = variable_names[v] if v < n else f"V{v}"
                self.add_link(u, v, "causes", "CWM")

    def _infer_types(self, names: list[str], dag, hint: str) -> dict[int, str]:
        """Infer ObjectTypes via LLM or structural clustering."""
        if self.backend:
            try:
                return self._llm_infer_types(names, dag, hint)
            except Exception:
                pass
        return self._structural_infer_types(names, dag)

    def _llm_infer_types(self, names, dag, hint) -> dict[int, str]:
        import json
        name_list = ", ".join(f"{i}:{n}" for i, n in enumerate(names))
        edge_list = ", ".join(f"{u}→{v}" for u, v in (dag or []))[:500]
        prompt = (
            f"Classify these {len(names)} variables into 2-5 ObjectTypes "
            f"(business concept categories).\n"
            f"Variables: {name_list}\n"
            + (f"Edges: {edge_list}\n" if edge_list else "")
            + (f"Domain hint: {hint}\n" if hint else "")
            + "Return ONLY JSON: {\"types\": {\"TypeName\": [0,3,5], ...}}"
        )
        raw = self.backend.propose(prompt)
        content = str(raw) if isinstance(raw, str) else raw.get("content", "{}")
        if content.startswith("```"): content = content.split("```")[1]
        if content.startswith("json"): content = content[4:]
        type_groups = json.loads(content).get("types", {})
        result = {}
        for type_name, indices in type_groups.items():
            for idx in indices:
                result[int(idx)] = type_name
        for i in range(len(names)):
            if i not in result:
                result[i] = "Variable"
        return result

    def _structural_infer_types(self, names, dag) -> dict[int, str]:
        """Infer types from DAG connectivity: densely connected nodes → same type."""
        n = len(names)
        if not dag:
            return {i: "Variable" for i in range(n)}

        adj = {i: set() for i in range(n)}
        for u, v in dag:
            adj[u].add(v); adj[v].add(u)
        visited = set()
        clusters = {}

        for v in range(n):
            if v in visited: continue
            stack = [v]; comp = []
            while stack:
                node = stack.pop()
                if node in visited: continue
                visited.add(node); comp.append(node)
                for nb in adj[node]:
                    if nb not in visited: stack.append(nb)
            if len(comp) >= 2:
                cluster_id = f"Group{len(clusters)+1}"
                clusters[cluster_id] = comp

        result = {}
        for cluster_id, indices in clusters.items():
            for idx in indices:
                result[idx] = cluster_id
        for i in range(n):
            if i not in result:
                result[i] = "Variable"
        return result

    def override_type(self, var_idx: int, new_type: str):
        """Operator manually assigns a variable to a different ObjectType."""
        old_prop_id = self.onto.variable_bindings.get(var_idx)
        if old_prop_id and old_prop_id in self.onto.properties:
            old = self.onto.properties[old_prop_id]
            new_prop_id = f"{new_type}.{old.label}"
            self.onto.properties[new_prop_id] = Property(
                prop_id=new_prop_id, label=old.label,
                object_type=new_type, data_column=var_idx,
                unit=old.unit, value_range=old.value_range,
            )
            self.onto.variable_bindings[var_idx] = new_prop_id
            self.onto.source = "mixed"
        if new_type not in self.onto.object_types:
            self.onto.object_types[new_type] = ObjectType(
                type_id=new_type, label=new_type,
            )

    def add_object_type(self, type_id: str, label: str, parent: str = "",
                        intervenable: bool = False):
        self.onto.object_types[type_id] = ObjectType(
            type_id=type_id, label=label, parent_type=parent,
            is_intervenable=intervenable,
        )

    def bind_variable(self, var_idx: int, object_type: str, prop_name: str,
                      unit: str = ""):
        prop_id = f"{object_type}.{prop_name}"
        self.onto.properties[prop_id] = Property(
            prop_id=prop_id, label=prop_name, object_type=object_type,
            data_column=var_idx, unit=unit,
        )
        self.onto.variable_bindings[var_idx] = prop_id

    def add_link(self, src_var: int, tgt_var: int, relation: str,
                 evidence: str = "operator", confidence: float = 0.5):
        src_type = self._type_for_var(src_var)
        tgt_type = self._type_for_var(tgt_var)
        self.onto.links.append(Link(
            link_id=f"{src_var}_{relation}_{tgt_var}",
            source_type=src_type, target_type=tgt_type,
            relation=relation, source_var=src_var, target_var=tgt_var,
            confidence=confidence, evidence=evidence,
        ))

    def _type_for_var(self, var_idx: int) -> str:
        prop_id = self.onto.variable_bindings.get(var_idx, "")
        if prop_id and prop_id in self.onto.properties:
            return self.onto.properties[prop_id].object_type
        return "MeasuredVariable"

    def add_action(self, action_id: str, label: str, target_var: int,
                   parameters: dict | None = None, risk_tier: int = 1,
                   expected_effect: str = ""):
        target_type = self._type_for_var(target_var)
        self.onto.actions[action_id] = Action(
            action_id=action_id, label=label,
            target_type=target_type, target_var=target_var,
            parameters=parameters or {}, expected_effect=expected_effect,
            risk_tier=risk_tier,
        )

    def enrich_from_goals(self, goals: list, variable_names: list[str]):
        """Convert GoalFormation output into Action definitions."""
        for g in goals:
            target = g.get("target", 0)
            direction = g.get("direction", "maximize")
            name = variable_names[target] if target < len(variable_names) else f"V{target}"
            action_id = f"{direction}_{name}"
            self.add_action(
                action_id=action_id,
                label=f"{'最大化' if direction == 'maximize' else '最小化'} {name}",
                target_var=target,
                expected_effect=f"因果路径可执行" if g.get("executable_leaves", 0) > 0 else "无可干预祖先",
            )

    def export(self) -> str:
        return self.onto.to_json()

    def summary(self) -> str:
        lines = ["=== Business Ontology ===", ""]
        lines.append(f"Object Types: {len(self.onto.object_types)}")
        for tid, ot in sorted(self.onto.object_types.items()):
            lines.append(f"  {tid}: {ot.label}")
        lines.append(f"\nProperties: {len(self.onto.properties)}")
        lines.append(f"Links: {len(self.onto.links)}")
        for l in self.onto.links[:5]:
            lines.append(f"  {l.source_type} --{l.relation}→ {l.target_type} ({l.evidence})")
        lines.append(f"\nActions: {len(self.onto.actions)}")
        for aid, a in sorted(self.onto.actions.items()):
            lines.append(f"  {aid}: {a.label} (R{a.risk_tier})")
        return "\n".join(lines)
