"""Frozen role plan for the R-EVAL-INDEP-1 successor candidate.

The plan fixes experimental relationships, not vendors or mutable model aliases.
Concrete immutable provider revisions are a separate freeze-time binding.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class ArmRole(str, Enum):
    MECHANICAL_RULE = "MECHANICAL_RULE"
    SAME_CHECKPOINT_PROMPT_VARIANT = "SAME_CHECKPOINT_PROMPT_VARIANT"
    SAME_CHECKPOINT_AGGREGATE = "SAME_CHECKPOINT_AGGREGATE"
    SAME_FAMILY_DIFFERENT_CHECKPOINT = "SAME_FAMILY_DIFFERENT_CHECKPOINT"
    CROSS_LINEAGE = "CROSS_LINEAGE"


@dataclass(frozen=True)
class NativeArm:
    arm_id: str
    role: ArmRole
    sample_count: int
    aggregation: str

    def __post_init__(self) -> None:
        if self.arm_id not in {"A0", "A1", "A2", "A3", "A4"}:
            raise ValueError("unknown arm_id")
        if self.sample_count not in {0, 1, 3}:
            raise ValueError("sample_count must be 0, 1, or 3")
        if self.aggregation not in {"MECHANICAL", "SINGLE", "MAJORITY_TIE_ABSTAINS"}:
            raise ValueError("unknown aggregation")
        if (self.role is ArmRole.MECHANICAL_RULE) != (self.sample_count == 0):
            raise ValueError("only the mechanical arm may have zero samples")
        if (self.aggregation == "MAJORITY_TIE_ABSTAINS") != (self.sample_count == 3):
            raise ValueError("majority requires exactly three samples")

    def to_mapping(self) -> dict[str, object]:
        return {
            "arm_id": self.arm_id,
            "role": self.role.value,
            "sample_count": self.sample_count,
            "aggregation": self.aggregation,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> NativeArm:
        expected = {"arm_id", "role", "sample_count", "aggregation"}
        if set(value) != expected:
            raise ValueError("NativeArm is a closed contract")
        return cls(
            arm_id=str(value["arm_id"]),
            role=ArmRole(str(value["role"])),
            sample_count=int(value["sample_count"]),
            aggregation=str(value["aggregation"]),
        )


@dataclass(frozen=True)
class NativeArmPlan:
    schema_version: str
    route_id: str
    case_count: int
    arms: tuple[NativeArm, ...]

    def __post_init__(self) -> None:
        if self.schema_version != "r-eval-indep-1-native-arm-plan-v1":
            raise ValueError("unsupported arm-plan schema")
        if self.route_id != "R-EVAL-INDEP-1":
            raise ValueError("wrong route")
        if self.case_count <= 0:
            raise ValueError("case_count must be positive")
        expected = (
            ("A0", ArmRole.MECHANICAL_RULE, 0, "MECHANICAL"),
            ("A1", ArmRole.SAME_CHECKPOINT_PROMPT_VARIANT, 1, "SINGLE"),
            ("A2", ArmRole.SAME_CHECKPOINT_AGGREGATE, 3, "MAJORITY_TIE_ABSTAINS"),
            ("A3", ArmRole.SAME_FAMILY_DIFFERENT_CHECKPOINT, 1, "SINGLE"),
            ("A4", ArmRole.CROSS_LINEAGE, 1, "SINGLE"),
        )
        actual = tuple(
            (a.arm_id, a.role, a.sample_count, a.aggregation) for a in self.arms
        )
        if actual != expected:
            raise ValueError("the five-arm successor plan is fixed")

    @property
    def arm_ids(self) -> tuple[str, ...]:
        return tuple(arm.arm_id for arm in self.arms)

    @property
    def evaluation_row_count(self) -> int:
        return self.case_count * len(self.arms)

    @property
    def provider_attempt_count(self) -> int:
        return self.case_count * sum(arm.sample_count for arm in self.arms)

    @property
    def mechanical_row_count(self) -> int:
        return self.case_count

    @property
    def aggregate_row_count(self) -> int:
        return self.case_count

    def arm(self, arm_id: str) -> NativeArm:
        try:
            return next(arm for arm in self.arms if arm.arm_id == arm_id)
        except StopIteration as exc:
            raise ValueError(f"unknown arm {arm_id}") from exc

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "route_id": self.route_id,
            "case_count": self.case_count,
            "arms": [arm.to_mapping() for arm in self.arms],
            "evaluation_row_count": self.evaluation_row_count,
            "provider_attempt_count": self.provider_attempt_count,
            "mechanical_row_count": self.mechanical_row_count,
            "aggregate_row_count": self.aggregate_row_count,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> NativeArmPlan:
        expected = {
            "schema_version",
            "route_id",
            "case_count",
            "arms",
            "evaluation_row_count",
            "provider_attempt_count",
            "mechanical_row_count",
            "aggregate_row_count",
        }
        if set(value) != expected:
            raise ValueError("NativeArmPlan is a closed contract")
        arms_raw = value["arms"]
        if not isinstance(arms_raw, list):
            raise ValueError("arms must be a list")
        plan = cls(
            schema_version=str(value["schema_version"]),
            route_id=str(value["route_id"]),
            case_count=int(value["case_count"]),
            arms=tuple(NativeArm.from_mapping(item) for item in arms_raw),
        )
        for field in (
            "evaluation_row_count",
            "provider_attempt_count",
            "mechanical_row_count",
            "aggregate_row_count",
        ):
            if int(value[field]) != getattr(plan, field):
                raise ValueError(f"derived count drift: {field}")
        return plan


def build_native_arm_plan(case_count: int) -> NativeArmPlan:
    return NativeArmPlan(
        schema_version="r-eval-indep-1-native-arm-plan-v1",
        route_id="R-EVAL-INDEP-1",
        case_count=case_count,
        arms=(
            NativeArm("A0", ArmRole.MECHANICAL_RULE, 0, "MECHANICAL"),
            NativeArm("A1", ArmRole.SAME_CHECKPOINT_PROMPT_VARIANT, 1, "SINGLE"),
            NativeArm(
                "A2", ArmRole.SAME_CHECKPOINT_AGGREGATE, 3, "MAJORITY_TIE_ABSTAINS"
            ),
            NativeArm("A3", ArmRole.SAME_FAMILY_DIFFERENT_CHECKPOINT, 1, "SINGLE"),
            NativeArm("A4", ArmRole.CROSS_LINEAGE, 1, "SINGLE"),
        ),
    )
