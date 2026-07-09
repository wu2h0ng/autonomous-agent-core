"""LLM Prompt Engineering — domain-specific few-shot templates.

Improves LLM causal reasoning without fine-tuning. Each domain template
provides system instructions + few-shot examples demonstrating correct
causal orientations, goal formulation, and counterfactual reasoning.

Domains: Sachs (biology), Lazada (e-commerce), FinCARE (finance), Generic.
"""
from __future__ import annotations


PROMPT_TEMPLATES = {
    "causal_orientation": {
        "system": (
            "You are a causal discovery expert. Given variable names and undirected "
            "edges, determine causal direction based on domain knowledge. "
            "In biology: upstream signaling proteins activate downstream targets "
            "(e.g., Raf→Mek→Erk). In e-commerce: price→sales, discount→sales, "
            "traffic→sales, holiday→discount. In finance: rd_spend→revenue→profit, "
            "leverage→risk→profit. Always prefer temporal precedence (cause before effect). "
            "Return ONLY JSON with orientations array."
        ),
        "sachs_examples": """
Example 1:
Proteins: [Raf, Mek, Plcg, PIP2, PIP3, Erk, Akt, PKA, PKC, P38, Jnk]
Edge: (0:Raf) -- (1:Mek)
Output: {"orientations": [{"i": 0, "j": 1, "direction": "0→1", "score": 0.95}]}
Reason: Raf is a MAPK kinase kinase that phosphorylates and activates Mek in the MAPK cascade.

Example 2:
Edge: (5:Erk) -- (6:Akt)
Output: {"orientations": [{"i": 5, "j": 6, "direction": "5→6", "score": 0.85}]}
Reason: Erk activates Akt through phosphorylation. The direction Erk→Akt is well-established.

Example 3:
Edge: (2:Plcg) -- (3:PIP2)
Output: {"orientations": [{"i": 2, "j": 3, "direction": "2→3", "score": 0.90}]}
Reason: PLCγ hydrolyzes PIP2, making it a downstream target, not an upstream activator.
""",
        "lazada_examples": """
Example 1:
Variables: [price, discount, ad_spend, traffic, sales, holiday]
Edge: (1:discount) -- (4:sales)
Output: {"orientations": [{"i": 1, "j": 4, "direction": "1→4", "score": 0.90}]}
Reason: Higher discounts causally lead to higher sales volume. Sales don't cause discounts.

Example 2:
Edge: (3:traffic) -- (4:sales)
Output: {"orientations": [{"i": 3, "j": 4, "direction": "3→4", "score": 0.85}]}
Reason: More website traffic leads to more sales. Sales don't cause traffic.

Example 3:
Edge: (5:holiday) -- (1:discount)
Output: {"orientations": [{"i": 5, "j": 1, "direction": "5→1", "score": 0.80}]}
Reason: Holiday seasons cause businesses to offer discounts, not vice versa.
""",
        "fincare_examples": """
Example 1:
Variables: [rd_spend, revenue, leverage, risk, dividend, profit, cash_flow, investment]
Edge: (0:rd_spend) -- (1:revenue)
Output: {"orientations": [{"i": 0, "j": 1, "direction": "0→1", "score": 0.85}]}
Reason: R&D spending causally leads to future revenue through product development.

Example 2:
Edge: (2:leverage) -- (3:risk)
Output: {"orientations": [{"i": 2, "j": 3, "direction": "2→3", "score": 0.90}]}
Reason: Higher financial leverage increases risk, not vice versa.
""",
    },
    "goal_formation": {
        "system": (
            "You are a business strategy assistant. Given a causal DAG and business "
            "context, propose actionable goals. Always prefer goals whose causal "
            "ancestors are directly intervenable. If a target has no intervenable "
            "ancestors, honestly state that it cannot be directly influenced."
        ),
        "examples": """
Example 1 (E-commerce DAG: discount→sales, traffic→sales, holiday→traffic):
Query: "How do I increase sales?"
Response: "To increase sales, I recommend two levers: (1) Increase discount rate — "
"the DAG shows a strong causal edge from discount to sales. (2) Increase traffic — "
"traffic causally drives sales. Both are directly intervenable. Holiday is a "
"confounding factor (it drives both traffic and discount), so be aware of seasonal effects."

Example 2 (Finance DAG: rd_spend→revenue→profit, leverage→risk→profit):
Query: "How do I maximize profit while minimizing risk?"
Response: "These goals conflict: maximizing profit requires increasing revenue "
"(via rd_spend) but this also increases risk (via leverage). "
"The Pareto frontier suggests: moderate rd_spend increase (+10%) can boost "
"revenue without significantly increasing leverage. Avoid leverage increases."
""",
    },
    "counterfactual": {
        "system": (
            "You are a counterfactual reasoning assistant. Given observed outcomes "
            "and a causal model, answer 'what if' questions. Use the causal DAG to "
            "propagate changes through mechanistic equations. Be precise about "
            "uncertainty — if the DAG doesn't confidently model a relationship, "
            "state the uncertainty rather than guessing."
        ),
        "examples": """
Example 1:
Query: "What if I had set discount to 30% instead of 15%?"
DAG: discount→sales, traffic→sales
Observed: sales=85.4, discount=0.15, traffic=800
Response: "Based on the causal model, setting discount to 30% would have resulted "
"in approximately 175.6 units of sales (95% CI: [164, 185]), compared to the actual 85.4. "
"This is an increase of ~105%. The uncertainty range reflects the model's fit quality."

Example 2:
Query: "What if I had reduced leverage to 2x instead of 4x?"
DAG: leverage→risk→profit
Observed: profit=50, leverage=4, risk=1.2
Response: "Reducing leverage to 2x would have decreased risk to ~0.6, which would "
"have improved profit by approximately 12%. However, this estimate has high uncertainty "
"because the leverage→risk→profit chain involves intermediate nodes with modest R²."
""",
    },
}


def build_prompt(task: str, domain: str = "generic", query: str = "",
                 edges: str = "", variables: str = "", extra: str = "") -> str:
    """Build a domain-specific few-shot prompt for LLM reasoning.

    Args:
        task: "causal_orientation", "goal_formation", or "counterfactual".
        domain: "sachs", "lazada", "fincare", or "generic".
        query: the user's actual query.
        edges: undirected edges formatted as "(i:name) -- (j:name)".
        variables: variable names for context.
        extra: any additional context (DAG state, execution history, etc.).

    Returns:
        Full prompt string with system instruction + domain examples + query.
    """
    template = PROMPT_TEMPLATES.get(task, PROMPT_TEMPLATES["causal_orientation"])
    parts = [template["system"]]

    example_key = f"{domain}_examples"
    if example_key in template:
        parts.append(template[example_key])
    elif "examples" in template:
        parts.append(template["examples"])

    parts.append(f"\nCurrent task ({domain} domain):")
    if variables:
        parts.append(f"Variables: {variables}")
    if edges:
        parts.append(f"Edges:\n{edges}")
    if extra:
        parts.append(f"Context: {extra}")
    if query:
        parts.append(f"\nQuery: {query}")
    parts.append("\nReturn ONLY valid JSON.")

    return "\n".join(parts)
