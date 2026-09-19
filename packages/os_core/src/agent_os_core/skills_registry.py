"""Minimal, model-agnostic skills registration/discovery face (shard B).

A skill here is a small, typed descriptor the agent can DISCOVER and QUERY
— it is metadata, not executable code inside the daemon process. Conservative
defaults (ADR-0062, pending founder ratification):

1. **Opt-in.** A skill must be explicitly declared and enabled; an undeclared
   skill is never loaded and never advertised.
2. **Model-agnostic.** A skill carries a name, a description, and a JSON
   input schema; it does not bind to any provider or model.
3. **Not an authority.** Discovery lists skills; invoking one still goes
   through the governed capability spine. This slice only wires the
   registration/discovery surface plus a stub call path for hermetic tests.

This module does NOT touch ``agent_loop`` / ``task_service`` / ``child_agent``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final

from agent_os_contracts import SkillDefinition

SKILLS_DISABLED_ENV: Final = "AGENT_OS_SKILLS_DISABLED"


def _truthy(value: str | None) -> bool:
    return value is not None and value.strip() not in {"", "0", "false", "False"}


def skills_globally_disabled() -> bool:
    import os

    return _truthy(os.environ.get(SKILLS_DISABLED_ENV))


class SkillRegistryError(ValueError):
    """Raised on a structurally invalid skill registration."""


@dataclass
class SkillRegistry:
    """A minimal registry of declared, enabled skills.

    Off by default: when the global kill-switch is on, or when no skills are
    registered, ``list_skills()`` returns an empty tuple and nothing is
    advertised to the model.
    """

    _skills: dict[str, SkillDefinition] = field(default_factory=dict)

    def register(self, skill: SkillDefinition) -> None:
        """Declare a skill. An undeclared/disabled skill is inert."""

        if not skill.enabled:
            # Declared but disabled: keep it out of the advertised set.
            return
        if skill.name in self._skills:
            raise SkillRegistryError(f"skill {skill.name!r} already registered")
        self._skills[skill.name] = skill

    def list_skills(self) -> tuple[SkillDefinition, ...]:
        """Return the enabled, declared skills the agent may query."""

        if skills_globally_disabled():
            return ()
        return tuple(sorted(self._skills.values(), key=lambda s: s.name))

    def get(self, name: str) -> SkillDefinition | None:
        if skills_globally_disabled():
            return None
        return self._skills.get(name)

    @property
    def is_empty(self) -> bool:
        return len(self._skills) == 0


@dataclass
class StubSkillRunner:
    """A hermetic, in-process stub for invoking a registered skill.

    This is NOT a general skill executor: it exists so tests can prove the
    register -> query -> call round-trip end to end without touching a real
    skill runtime. A real skill invocation path would go through the governed
    capability spine (other shard).
    """

    registry: SkillRegistry
    # call log: (skill_name, validated_args)
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def invoke(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Invoke a declared, enabled skill with argument validation."""

        skill = self.registry.get(name)
        if skill is None:
            raise SkillRegistryError(f"skill {name!r} is not declared/enabled")
        # Minimal JSON-Schema-ish validation: require declared keys present.
        required = (skill.input_schema.get("required") or [])
        if not isinstance(required, list):
            required = []
        missing = [k for k in required if k not in arguments]
        if missing:
            raise SkillRegistryError(
                f"skill {name!r}: missing required arguments {missing}"
            )
        if skill.tier >= 3:
            raise SkillRegistryError(
                f"skill {name!r} is tier {skill.tier} and requires human "
                f"approval before invocation"
            )
        self.calls.append((name, dict(arguments)))
        return {"skill": name, "echo": arguments}
