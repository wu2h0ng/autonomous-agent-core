from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from .canonical import content_digest
from .scoring_contracts import ChallengeCatalogue, DiscoveryScoreBundle


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PUBLIC_COVERAGE_STRATA = (
    "BOUNDARY",
    "PAIRWISE_INTERACTION",
    "REPETITION",
    "ORDERING",
    "STATE_CHANGE",
    "ERROR_RECOVERY",
)
_PUBLIC_STRATA = frozenset(PUBLIC_COVERAGE_STRATA)


class BaselineContractError(ValueError):
    """A baseline is weak, unmatched, or selected outside its frozen contract."""


class HumanProtocolError(BaselineContractError):
    """A HumanBundleProtocol/v1 record is missing or invalid."""


class BaselineKind(str, Enum):
    ACTIVE_VOI = "ACTIVE_VOI"
    SYSTEMATIC_COVERING = "SYSTEMATIC_COVERING"
    RANDOM_STRATIFIED = "RANDOM_STRATIFIED"
    PASSIVE_ZERO_QUERY = "PASSIVE_ZERO_QUERY"
    FREEFORM_ENGINEER = "FREEFORM_ENGINEER"
    HUMAN_STRONG = "HUMAN_STRONG"
    TRACE_MEMO = "TRACE_MEMO"
    GENERIC_TESTS = "GENERIC_TESTS"


REQUIRED_BASELINES = frozenset(
    {
        BaselineKind.SYSTEMATIC_COVERING,
        BaselineKind.RANDOM_STRATIFIED,
        BaselineKind.PASSIVE_ZERO_QUERY,
        BaselineKind.FREEFORM_ENGINEER,
        BaselineKind.HUMAN_STRONG,
        BaselineKind.TRACE_MEMO,
        BaselineKind.GENERIC_TESTS,
    }
)


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise BaselineContractError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _positive_integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise BaselineContractError(f"{field} must be an integer > 0")
    return value


@dataclass(frozen=True, slots=True)
class StratifiedProbe:
    probe_id: str
    stable_order: int
    strata: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.probe_id, str) or not self.probe_id.strip():
            raise BaselineContractError("probe_id must be non-empty")
        if (
            isinstance(self.stable_order, bool)
            or not isinstance(self.stable_order, int)
            or self.stable_order < 0
        ):
            raise BaselineContractError("stable_order must be an integer >= 0")
        if (
            not self.strata
            or len(self.strata) != len(set(self.strata))
            or not set(self.strata).issubset(_PUBLIC_STRATA)
        ):
            raise BaselineContractError("probe strata must be unique public strata")

    @property
    def probe_digest(self) -> str:
        return content_digest(
            "stratified-public-probe/v1",
            {
                "probe_id": self.probe_id,
                "stable_order": self.stable_order,
                "strata": list(self.strata),
            },
        )


@dataclass(frozen=True, slots=True)
class CoveringPlan:
    planner_name: str
    selected_probe_ids: tuple[str, ...]
    covered_strata: tuple[str, ...]
    budget_units: int
    seed: int | None = None

    @property
    def plan_digest(self) -> str:
        return content_digest(
            "public-strata-covering-plan/v1",
            {
                "planner_name": self.planner_name,
                "selected_probe_ids": list(self.selected_probe_ids),
                "covered_strata": list(self.covered_strata),
                "budget_units": self.budget_units,
                "seed": self.seed,
            },
        )


def _validate_probe_domain(
    probes: tuple[StratifiedProbe, ...], budget_units: int
) -> None:
    _positive_integer(budget_units, "budget_units")
    if not probes:
        raise BaselineContractError("covering baseline requires public probes")
    probe_ids = tuple(item.probe_id for item in probes)
    if len(probe_ids) != len(set(probe_ids)):
        raise BaselineContractError("public probe identities must be unique")
    available = frozenset(stratum for item in probes for stratum in item.strata)
    if available != _PUBLIC_STRATA:
        raise BaselineContractError("probes must expose every public stratum")


def build_systematic_covering_plan(
    *, probes: tuple[StratifiedProbe, ...], budget_units: int
) -> CoveringPlan:
    _validate_probe_domain(probes, budget_units)
    remaining = list(probes)
    uncovered = set(PUBLIC_COVERAGE_STRATA)
    selected: list[StratifiedProbe] = []
    while uncovered and len(selected) < budget_units:
        best = min(
            remaining,
            key=lambda item: (
                -len(uncovered.intersection(item.strata)),
                item.probe_digest,
            ),
        )
        if not uncovered.intersection(best.strata):
            break
        selected.append(best)
        remaining.remove(best)
        uncovered.difference_update(best.strata)
    if uncovered:
        raise BaselineContractError(
            "systematic budget cannot cover every public stratum"
        )
    return CoveringPlan(
        planner_name="PUBLIC_SCHEMA_GREEDY_COVER",
        selected_probe_ids=tuple(item.probe_id for item in selected),
        covered_strata=PUBLIC_COVERAGE_STRATA,
        budget_units=budget_units,
    )


@dataclass(frozen=True, slots=True)
class RandomSeedSet:
    seeds: tuple[int, ...]

    def __post_init__(self) -> None:
        if (
            len(self.seeds) < 2
            or any(isinstance(seed, bool) or not isinstance(seed, int) for seed in self.seeds)
            or len(self.seeds) != len(set(self.seeds))
        ):
            raise BaselineContractError(
                "random baseline requires a unique frozen multi-seed set"
            )

    @classmethod
    def create(cls, seeds: tuple[int, ...]) -> RandomSeedSet:
        return cls(seeds=seeds)

    @property
    def seed_set_digest(self) -> str:
        return content_digest("random-baseline-seed-set/v1", list(self.seeds))


@dataclass(frozen=True, slots=True)
class RandomPlanSet:
    seed_set_digest: str
    plans: tuple[CoveringPlan, ...]

    @property
    def aggregate_digest(self) -> str:
        return content_digest(
            "random-stratified-plan-set/v1",
            {
                "seed_set_digest": self.seed_set_digest,
                "plan_digests": [item.plan_digest for item in self.plans],
            },
        )


def _random_plan(
    *, probes: tuple[StratifiedProbe, ...], budget_units: int, seed: int
) -> CoveringPlan:
    remaining = list(probes)
    uncovered = set(PUBLIC_COVERAGE_STRATA)
    selected: list[StratifiedProbe] = []
    while uncovered and len(selected) < budget_units:
        def rank(item: StratifiedProbe) -> tuple[int, str]:
            newly_covered = tuple(sorted(uncovered.intersection(item.strata)))
            return (
                -len(newly_covered),
                content_digest(
                    "random-stratified-without-replacement/v1",
                    {
                        "seed": seed,
                        "probe_digest": item.probe_digest,
                        "newly_covered_strata": list(newly_covered),
                    },
                ),
            )

        chosen = min(remaining, key=rank)
        if not uncovered.intersection(chosen.strata):
            break
        selected.append(chosen)
        remaining.remove(chosen)
        uncovered.difference_update(chosen.strata)
    if uncovered:
        raise BaselineContractError(
            "random budget cannot cover every public stratum without replacement"
        )
    return CoveringPlan(
        planner_name="FROZEN_RANDOM_STRATIFIED",
        selected_probe_ids=tuple(item.probe_id for item in selected),
        covered_strata=PUBLIC_COVERAGE_STRATA,
        budget_units=budget_units,
        seed=seed,
    )


def build_random_stratified_plans(
    *,
    probes: tuple[StratifiedProbe, ...],
    budget_units: int,
    seed_set: RandomSeedSet,
) -> RandomPlanSet:
    _validate_probe_domain(probes, budget_units)
    plans = tuple(
        _random_plan(probes=probes, budget_units=budget_units, seed=seed)
        for seed in seed_set.seeds
    )
    return RandomPlanSet(seed_set_digest=seed_set.seed_set_digest, plans=plans)


@dataclass(frozen=True, slots=True)
class ModelParityBinding:
    provider: str
    model_checkpoint: str
    decoding_digest: str
    model_seed: int
    system_prompt_digest: str
    task_prompt_digest: str
    context_window_tokens: int
    reasoning_token_budget: int
    tool_call_budget: int
    output_token_cap: int
    bundle_size_cap_bytes: int
    public_interface_digest: str
    hidden_commitment_set_digest: str
    retry_policy_digest: str
    reset_policy_digest: str
    timeout_millis: int
    probe_budget_units: int
    scorer_and_adjudication_digest: str

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str) or not value.strip()
            for value in (self.provider, self.model_checkpoint)
        ):
            raise BaselineContractError("model identity must be non-empty")
        for field_name in (
            "decoding_digest",
            "system_prompt_digest",
            "task_prompt_digest",
            "public_interface_digest",
            "hidden_commitment_set_digest",
            "retry_policy_digest",
            "reset_policy_digest",
            "scorer_and_adjudication_digest",
        ):
            _digest(getattr(self, field_name), field_name)
        if isinstance(self.model_seed, bool) or not isinstance(self.model_seed, int):
            raise BaselineContractError("model_seed must be an integer")
        for field_name in (
            "context_window_tokens",
            "reasoning_token_budget",
            "tool_call_budget",
            "output_token_cap",
            "bundle_size_cap_bytes",
            "timeout_millis",
            "probe_budget_units",
        ):
            _positive_integer(getattr(self, field_name), field_name)
        if self.probe_budget_units != 4:
            raise BaselineContractError("matched non-passive probe budget must equal four")

    @property
    def parity_digest(self) -> str:
        return content_digest(
            "matched-model-arm-parity/v1",
            {
                "provider": self.provider,
                "model_checkpoint": self.model_checkpoint,
                "decoding_digest": self.decoding_digest,
                "model_seed": self.model_seed,
                "system_prompt_digest": self.system_prompt_digest,
                "task_prompt_digest": self.task_prompt_digest,
                "context_window_tokens": self.context_window_tokens,
                "reasoning_token_budget": self.reasoning_token_budget,
                "tool_call_budget": self.tool_call_budget,
                "output_token_cap": self.output_token_cap,
                "bundle_size_cap_bytes": self.bundle_size_cap_bytes,
                "public_interface_digest": self.public_interface_digest,
                "hidden_commitment_set_digest": self.hidden_commitment_set_digest,
                "retry_policy_digest": self.retry_policy_digest,
                "reset_policy_digest": self.reset_policy_digest,
                "timeout_millis": self.timeout_millis,
                "probe_budget_units": self.probe_budget_units,
                "prefix_schedule": [0, 1, 2, 3, 4],
                "no_score_feedback": True,
                "scorer_and_adjudication_digest": self.scorer_and_adjudication_digest,
            },
        )


@dataclass(frozen=True, slots=True)
class ModelArmParityRecord:
    arm_kind: BaselineKind
    binding: ModelParityBinding
    consumed_probe_units: int

    def __post_init__(self) -> None:
        if not isinstance(self.arm_kind, BaselineKind):
            raise BaselineContractError("arm_kind must be a baseline kind")
        if self.arm_kind is BaselineKind.PASSIVE_ZERO_QUERY:
            if self.consumed_probe_units != 0:
                raise BaselineContractError("passive baseline must remain zero-query")
        elif self.arm_kind in {
            BaselineKind.ACTIVE_VOI,
            BaselineKind.SYSTEMATIC_COVERING,
            BaselineKind.RANDOM_STRATIFIED,
            BaselineKind.FREEFORM_ENGINEER,
        } and self.consumed_probe_units != self.binding.probe_budget_units:
            raise BaselineContractError("non-passive model arm must use the full budget")


@dataclass(frozen=True, slots=True)
class ModelParityReceipt:
    arm_kinds: tuple[BaselineKind, ...]
    parity_digest: str
    non_passive_probe_budget_units: int
    passive_consumed_units: int
    no_score_feedback: bool


def verify_model_arm_parity(
    records: tuple[ModelArmParityRecord, ...],
) -> ModelParityReceipt:
    if not records or len({item.arm_kind for item in records}) != len(records):
        raise BaselineContractError("model arm parity records must be unique")
    parity_digests = {item.binding.parity_digest for item in records}
    if len(parity_digests) != 1:
        raise BaselineContractError("model/input/output parity mismatch")
    passive = next(
        (
            item.consumed_probe_units
            for item in records
            if item.arm_kind is BaselineKind.PASSIVE_ZERO_QUERY
        ),
        0,
    )
    return ModelParityReceipt(
        arm_kinds=tuple(item.arm_kind for item in records),
        parity_digest=next(iter(parity_digests)),
        non_passive_probe_budget_units=records[0].binding.probe_budget_units,
        passive_consumed_units=passive,
        no_score_feedback=True,
    )


@dataclass(frozen=True, slots=True)
class HumanProtocolBinding:
    ui_digest: str
    instructions_digest: str
    eligibility_screen_digest: str
    practice_task_digest: str
    event_log_schema_digest: str
    public_interface_digest: str
    break_policy_digest: str
    allowed_notes_digest: str
    compensation_class: str
    wall_clock_cap_seconds: int
    operator_count: int
    practice_disjoint_from_scoring: bool
    source_access_allowed: bool
    shell_access_allowed: bool
    filesystem_access_allowed: bool
    network_access_allowed: bool
    other_people_allowed: bool
    model_assistance_allowed: bool
    hidden_outcome_access_allowed: bool
    score_feedback_allowed: bool

    def __post_init__(self) -> None:
        for field_name in (
            "ui_digest",
            "instructions_digest",
            "eligibility_screen_digest",
            "practice_task_digest",
            "event_log_schema_digest",
            "public_interface_digest",
            "break_policy_digest",
            "allowed_notes_digest",
        ):
            try:
                _digest(getattr(self, field_name), field_name)
            except BaselineContractError as exc:
                raise HumanProtocolError(str(exc)) from exc
        if not isinstance(self.compensation_class, str) or not self.compensation_class:
            raise HumanProtocolError("compensation_class must be non-empty")
        if self.operator_count != 1:
            raise HumanProtocolError("human protocol requires one independent operator")
        if (
            isinstance(self.wall_clock_cap_seconds, bool)
            or not isinstance(self.wall_clock_cap_seconds, int)
            or self.wall_clock_cap_seconds <= 0
        ):
            raise HumanProtocolError("wall-clock cap must be a positive integer")
        if self.practice_disjoint_from_scoring is not True:
            raise HumanProtocolError("practice task must be disjoint from scoring sets")
        forbidden = (
            self.source_access_allowed,
            self.shell_access_allowed,
            self.filesystem_access_allowed,
            self.network_access_allowed,
            self.other_people_allowed,
            self.model_assistance_allowed,
            self.hidden_outcome_access_allowed,
            self.score_feedback_allowed,
        )
        if any(value is not False for value in forbidden):
            raise HumanProtocolError("human protocol permits forbidden access")

    @property
    def binding_digest(self) -> str:
        return content_digest(
            "human-bundle-protocol-binding/v1",
            {
                "ui_digest": self.ui_digest,
                "instructions_digest": self.instructions_digest,
                "eligibility_screen_digest": self.eligibility_screen_digest,
                "practice_task_digest": self.practice_task_digest,
                "event_log_schema_digest": self.event_log_schema_digest,
                "public_interface_digest": self.public_interface_digest,
                "break_policy_digest": self.break_policy_digest,
                "allowed_notes_digest": self.allowed_notes_digest,
                "compensation_class": self.compensation_class,
                "wall_clock_cap_seconds": self.wall_clock_cap_seconds,
                "operator_count": self.operator_count,
                "practice_disjoint_from_scoring": self.practice_disjoint_from_scoring,
                "access_denials": {
                    "source": not self.source_access_allowed,
                    "shell": not self.shell_access_allowed,
                    "filesystem": not self.filesystem_access_allowed,
                    "network": not self.network_access_allowed,
                    "other_people": not self.other_people_allowed,
                    "model_assistance": not self.model_assistance_allowed,
                    "hidden_outcomes": not self.hidden_outcome_access_allowed,
                    "score_feedback": not self.score_feedback_allowed,
                },
            },
        )


@dataclass(frozen=True, slots=True)
class HumanPrefixEvent:
    prefix_index: int
    bundle_digest: str
    protocol_binding_digest: str
    wall_elapsed_millis: int
    active_elapsed_millis: int
    bundle_edit_events: int

    def __post_init__(self) -> None:
        if (
            isinstance(self.prefix_index, bool)
            or not isinstance(self.prefix_index, int)
            or not 0 <= self.prefix_index <= 4
        ):
            raise HumanProtocolError("human prefix index must be in k=0..4")
        for field_name in ("bundle_digest", "protocol_binding_digest"):
            try:
                _digest(getattr(self, field_name), field_name)
            except BaselineContractError as exc:
                raise HumanProtocolError(str(exc)) from exc
        for field_name in (
            "wall_elapsed_millis",
            "active_elapsed_millis",
            "bundle_edit_events",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise HumanProtocolError(f"{field_name} must be an integer >= 0")
        if self.active_elapsed_millis > self.wall_elapsed_millis:
            raise HumanProtocolError("active time cannot exceed wall time")


@dataclass(frozen=True, slots=True)
class HumanBundleProtocolReceipt:
    protocol_binding_digest: str
    operator_identity_digest: str
    prefix_bundle_digests: tuple[str, ...]
    canonical_bundle_bytes: tuple[bytes, ...]
    probe_count: int
    wall_elapsed_millis: int
    active_elapsed_millis: int
    bundle_edit_events: int
    self_reported_effort: str
    receipt_digest: str


def validate_human_bundle_protocol(
    *,
    binding: HumanProtocolBinding,
    operator_identity: str,
    catalogue: ChallengeCatalogue,
    prefix_bundles: tuple[DiscoveryScoreBundle, ...],
    prefix_events: tuple[HumanPrefixEvent, ...],
    self_reported_effort: str,
    model_scores_visible: bool,
) -> HumanBundleProtocolReceipt:
    if model_scores_visible is not False:
        raise HumanProtocolError("human bundles cannot be supplied after model scores")
    if not isinstance(operator_identity, str) or not operator_identity.strip():
        raise HumanProtocolError("operator identity must be non-empty")
    if self_reported_effort not in {"LOW", "MEDIUM", "HIGH"}:
        raise HumanProtocolError("self-reported effort must use the frozen scale")
    if len(prefix_bundles) != 5 or len(prefix_events) != 5:
        raise HumanProtocolError("complete human reference requires exact k=0..4 seals")
    if tuple(item.prefix_index for item in prefix_bundles) != tuple(range(5)):
        raise HumanProtocolError("human bundles must be sealed in k=0..4 order")
    if tuple(item.prefix_index for item in prefix_events) != tuple(range(5)):
        raise HumanProtocolError("human events must bind exact k=0..4 order")

    prior_digest: str | None = None
    actor_bindings: set[str] = set()
    canonical_bytes: list[bytes] = []
    prior_wall = -1
    prior_active = -1
    for bundle, event in zip(prefix_bundles, prefix_events, strict=True):
        if bundle.arm_id != BaselineKind.HUMAN_STRONG.value:
            raise HumanProtocolError("human bundle arm binding mismatch")
        if bundle.parent_bundle_digest != prior_digest:
            raise HumanProtocolError("human prefix backfill or parent rewrite")
        try:
            reparsed = DiscoveryScoreBundle.from_mapping(bundle.to_mapping(), catalogue)
        except (TypeError, ValueError) as exc:
            raise HumanProtocolError(
                "human probability vector, contract, or TestIR is invalid"
            ) from exc
        if reparsed.bundle_digest != bundle.bundle_digest:
            raise HumanProtocolError("human bundle canonical digest drifted")
        if event.bundle_digest != bundle.bundle_digest:
            raise HumanProtocolError("human event bundle binding mismatch")
        if event.protocol_binding_digest != binding.binding_digest:
            raise HumanProtocolError("human event protocol binding mismatch")
        if (
            event.wall_elapsed_millis < prior_wall
            or event.active_elapsed_millis < prior_active
        ):
            raise HumanProtocolError("human events cannot be backfilled in time")
        prior_wall = event.wall_elapsed_millis
        prior_active = event.active_elapsed_millis
        prior_digest = bundle.bundle_digest
        actor_bindings.add(bundle.actor_binding_digest)
        canonical_bytes.append(reparsed.canonical_bytes)
    if len(actor_bindings) != 1:
        raise HumanProtocolError("human operator binding changed between prefixes")
    if prior_wall > binding.wall_clock_cap_seconds * 1_000:
        raise HumanProtocolError("human wall-clock cap was exceeded")

    prefix_digests = tuple(item.bundle_digest for item in prefix_bundles)
    operator_identity_digest = content_digest(
        "human-operator-identity/v1", {"operator_identity": operator_identity}
    )
    payload = {
        "protocol_binding_digest": binding.binding_digest,
        "operator_identity_digest": operator_identity_digest,
        "prefix_bundle_digests": list(prefix_digests),
        "probe_count": prefix_bundles[-1].consumed_units,
        "wall_elapsed_millis": prior_wall,
        "active_elapsed_millis": prior_active,
        "bundle_edit_events": sum(item.bundle_edit_events for item in prefix_events),
        "self_reported_effort": self_reported_effort,
    }
    return HumanBundleProtocolReceipt(
        protocol_binding_digest=binding.binding_digest,
        operator_identity_digest=operator_identity_digest,
        prefix_bundle_digests=prefix_digests,
        canonical_bundle_bytes=tuple(canonical_bytes),
        probe_count=prefix_bundles[-1].consumed_units,
        wall_elapsed_millis=prior_wall,
        active_elapsed_millis=prior_active,
        bundle_edit_events=sum(item.bundle_edit_events for item in prefix_events),
        self_reported_effort=self_reported_effort,
        receipt_digest=content_digest("human-bundle-protocol-receipt/v1", payload),
    )


@dataclass(frozen=True, slots=True)
class HumanMissingDisposition:
    disposition: str
    replaceable: bool
    blocks_strongest_claim: bool
    invalidates_model_comparison: bool


def human_missing_disposition(*, model_scores_visible: bool) -> HumanMissingDisposition:
    return HumanMissingDisposition(
        disposition=(
            "MISSING_HUMAN_POST_MODEL_SCORE"
            if model_scores_visible
            else "MISSING_HUMAN_PREDECLARED"
        ),
        replaceable=False,
        blocks_strongest_claim=True,
        invalidates_model_comparison=False,
    )


@dataclass(frozen=True, slots=True)
class TraceMemoContract:
    seen_trace_digests: frozenset[str]

    def predict_or_abstain(self, trace_digest: str) -> str | None:
        _digest(trace_digest, "trace_digest")
        return trace_digest if trace_digest in self.seen_trace_digests else None


@dataclass(frozen=True, slots=True)
class GenericTestsContract:
    public_schema_digest: str
    template_digest: str

    def __post_init__(self) -> None:
        _digest(self.public_schema_digest, "public_schema_digest")
        _digest(self.template_digest, "template_digest")
