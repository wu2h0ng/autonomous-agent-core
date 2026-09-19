"""Hermetic tests for the minimal model-agnostic skills face (shard B / ADR-0067).

Proves:
- skills are opt-in (disabled/undeclared skills are never advertised);
- register -> query -> stub-call round-trip;
- tier>=3 skills require approval (refused by the stub runner);
- global kill-switch hides all skills.
"""

from __future__ import annotations

import pytest

from agent_os_contracts import SkillDefinition
from agent_os_core import (
    SKILLS_DISABLED_ENV,
    SkillRegistry,
    SkillRegistryError,
    StubSkillRunner,
)


def test_disabled_skill_is_not_advertised() -> None:
    registry = SkillRegistry()
    registry.register(SkillDefinition(
        name="drafting",
        description="draft notes",
        input_schema={"type": "object"},
        tier=1,
        enabled=False,
    ))
    assert registry.list_skills() == ()
    assert registry.is_empty is True


def test_register_query_call_round_trip() -> None:
    registry = SkillRegistry()
    registry.register(SkillDefinition(
        name="summarize",
        description="summarize text",
        input_schema={
            "type": "object",
            "required": ["text"],
            "properties": {"text": {"type": "string"}},
        },
        tier=1,
        enabled=True,
    ))
    names = tuple(s.name for s in registry.list_skills())
    assert names == ("summarize",)

    runner = StubSkillRunner(registry)
    out = runner.invoke("summarize", {"text": "hello"})
    assert out == {"skill": "summarize", "echo": {"text": "hello"}}
    assert runner.calls == [("summarize", {"text": "hello"})]


def test_required_argument_enforced() -> None:
    registry = SkillRegistry()
    registry.register(SkillDefinition(
        name="greet",
        description="greet",
        input_schema={"type": "object", "required": ["who"]},
        tier=1,
        enabled=True,
    ))
    runner = StubSkillRunner(registry)
    with pytest.raises(SkillRegistryError, match="missing required"):
        runner.invoke("greet", {})


def test_undeclared_skill_is_refused() -> None:
    registry = SkillRegistry()
    runner = StubSkillRunner(registry)
    with pytest.raises(SkillRegistryError, match="not declared"):
        runner.invoke("ghost", {})


def test_tier3_skill_requires_approval() -> None:
    registry = SkillRegistry()
    registry.register(SkillDefinition(
        name="delete_db",
        description="delete records (side effect)",
        input_schema={"type": "object"},
        tier=3,
        enabled=True,
    ))
    runner = StubSkillRunner(registry)
    with pytest.raises(SkillRegistryError, match="requires human approval"):
        runner.invoke("delete_db", {})


def test_global_kill_switch_hides_skills(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = SkillRegistry()
    registry.register(SkillDefinition(
        name="visible",
        description="visible skill",
        tier=1,
        enabled=True,
    ))
    monkeypatch.setenv(SKILLS_DISABLED_ENV, "1")
    assert registry.list_skills() == ()
    assert registry.get("visible") is None
    runner = StubSkillRunner(registry)
    with pytest.raises(SkillRegistryError, match="not declared"):
        runner.invoke("visible", {})
