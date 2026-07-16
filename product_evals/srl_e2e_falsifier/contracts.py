"""Arm-neutral SRL E2E falsifier contracts.

These typed contracts define the public responsibility surface for the SRL
end-to-end falsifier evaluation.  They carry no run, work, effect or training
authority.  Each public datum (mission, event, projection, evidence) enters the
state only through closed content-addressed cryptographic references.  No raw
payload, free-text public value, denylist or unrestricted mapping reaches any
state field.  Contracts bind to custody but do not self-prove the underlying
bytes; a resolver verifies the manifest separately.
"""

from __future__ import annotations

from enum import Enum
import hashlib
from typing import Any, Literal, Mapping

from pydantic import Field, field_validator, model_validator

from agent_os_contracts import (
    ContractModel,
    NonEmptyStr,
    Sha256Digest,
    UtcDateTime,
    canonical_json,
    content_digest,
)


class CandidateKind(str, Enum):
    WORK = "WORK"
    HELP = "HELP"
    NONE = "NONE"


class MissingInputKind(str, Enum):
    INFORMATION = "INFORMATION"
    PERMISSION = "PERMISSION"
    VALUE_TRADE_OFF = "VALUE_TRADE_OFF"
    AUTHORITY_CONFLICT = "AUTHORITY_CONFLICT"
    IRREVERSIBLE_RISK = "IRREVERSIBLE_RISK"


class PublicContentRole(str, Enum):
    MISSION = "MISSION"
    EVENT = "EVENT"
    PROJECTION = "PROJECTION"
    EVIDENCE = "EVIDENCE"
    STATIC_BUDGET = "STATIC_BUDGET"


class PublicContentMediaType(str, Enum):
    APPLICATION_JSON = "application/json"
    TEXT_PLAIN_UTF8 = "text/plain; charset=utf-8"


def _with_schema_version(payload: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    normalized.setdefault("schema_version", "1.0")
    return normalized


def public_content_entry_digest(payload: Mapping[str, Any]) -> str:
    if "entry_digest" in payload:
        raise ValueError("entry_digest must be excluded from its own digest payload")
    return content_digest(_with_schema_version(payload))


class PublicContentManifestEntry(ContractModel):
    """Closed role plus the exact digest of externally held canonical bytes."""

    role: PublicContentRole
    media_type: PublicContentMediaType
    content_digest: Sha256Digest
    entry_digest: Sha256Digest

    @model_validator(mode="after")
    def _validate_entry_digest(self) -> PublicContentManifestEntry:
        payload = self.model_dump(mode="json", exclude={"entry_digest"})
        if self.entry_digest != public_content_entry_digest(payload):
            raise ValueError("entry_digest does not match canonical entry fields")
        return self


def public_content_manifest_digest(payload: Mapping[str, Any]) -> str:
    if "manifest_root_digest" in payload:
        raise ValueError(
            "manifest_root_digest must be excluded from its own digest payload"
        )
    return content_digest(_with_schema_version(payload))


class PublicContentManifest(ContractModel):
    """Content-addressed ordered manifest; not an independent freeze receipt."""

    entries: tuple[PublicContentManifestEntry, ...]
    manifest_root_digest: Sha256Digest

    @model_validator(mode="after")
    def _validate_manifest(self) -> PublicContentManifest:
        entry_digests = tuple(entry.entry_digest for entry in self.entries)
        if len(entry_digests) != len(set(entry_digests)):
            raise ValueError("manifest entries must be unique")
        payload = self.model_dump(mode="json", exclude={"manifest_root_digest"})
        if self.manifest_root_digest != public_content_manifest_digest(payload):
            raise ValueError("manifest_root_digest does not match ordered entries")
        return self


class StaticBudgetConfiguration(ContractModel):
    """Static budget maxima only; remaining counters are BudgetFeedback."""

    max_llm_calls: int = Field(ge=0)
    max_input_tokens: int = Field(ge=0)
    max_output_tokens: int = Field(ge=0)
    max_retries: int = Field(ge=0)
    max_tool_invocations: int = Field(ge=0)
    max_wall_seconds: int = Field(ge=0)
    configuration_digest: Sha256Digest

    @model_validator(mode="after")
    def _validate_configuration_digest(self) -> StaticBudgetConfiguration:
        payload = self.model_dump(mode="json", exclude={"configuration_digest"})
        if self.configuration_digest != static_budget_configuration_digest(payload):
            raise ValueError(
                "configuration_digest does not match canonical static budget"
            )
        return self


def static_budget_configuration_digest(payload: Mapping[str, Any]) -> str:
    if "configuration_digest" in payload:
        raise ValueError(
            "configuration_digest must be excluded from its own digest payload"
        )
    return content_digest(_with_schema_version(payload))


def static_budget_configuration_bytes(
    configuration: StaticBudgetConfiguration,
) -> bytes:
    payload = configuration.model_dump(
        mode="json", exclude={"configuration_digest"}
    )
    return canonical_json(payload).encode("utf-8")


def public_responsibility_state_digest(payload: Mapping[str, Any]) -> str:
    if "state_digest" in payload:
        raise ValueError("state_digest must be excluded from its own digest payload")
    return content_digest(_with_schema_version(payload))


class PublicResponsibilityState(ContractModel):
    """Digest-only syntax; custody requires PublicResponsibilityStateVerifier."""

    manifest_root_digest: Sha256Digest
    mandate_digest: Sha256Digest
    environment_binding_digest: Sha256Digest
    correction_epoch: int = Field(ge=0)
    mission_entry_digest: Sha256Digest
    event_entry_digests: tuple[Sha256Digest, ...] = ()
    projection_entry_digests: tuple[Sha256Digest, ...] = ()
    evidence_entry_digests: tuple[Sha256Digest, ...] = ()
    static_budget_entry_digest: Sha256Digest
    state_digest: Sha256Digest

    @model_validator(mode="after")
    def _validate_state_digest(self) -> PublicResponsibilityState:
        payload = self.model_dump(mode="json", exclude={"state_digest"})
        if self.state_digest != public_responsibility_state_digest(payload):
            raise ValueError("state_digest does not match canonical state fields")
        return self


class PublicResponsibilityStateVerifier:
    """Trusted byte/role verifier; it does not establish independent custody."""

    @staticmethod
    def _verify_manifest_bytes(
        manifest: PublicContentManifest,
        content_by_entry_digest: Mapping[str, bytes],
    ) -> dict[str, PublicContentManifestEntry]:
        entries = {entry.entry_digest: entry for entry in manifest.entries}
        if set(content_by_entry_digest) != set(entries):
            missing = set(entries) - set(content_by_entry_digest)
            if missing:
                raise ValueError("missing content bytes for manifest entry")
            raise ValueError("unexpected content bytes outside manifest")
        for entry_digest, entry in entries.items():
            raw = content_by_entry_digest[entry_digest]
            if not isinstance(raw, bytes):
                raise ValueError("manifest content bytes must be bytes")
            if hashlib.sha256(raw).hexdigest() != entry.content_digest:
                raise ValueError("content bytes do not match manifest entry digest")
        return entries

    @staticmethod
    def _require_role(
        entries: Mapping[str, PublicContentManifestEntry],
        entry_digest: str,
        role: PublicContentRole,
    ) -> None:
        entry = entries.get(entry_digest)
        if entry is None:
            raise ValueError("referenced entry is missing from manifest")
        if entry.role is not role:
            raise ValueError(f"referenced entry must have role {role.value}")

    @classmethod
    def build(
        cls,
        *,
        manifest: PublicContentManifest,
        content_by_entry_digest: Mapping[str, bytes],
        static_budget_configuration: StaticBudgetConfiguration,
        mandate_digest: Sha256Digest,
        environment_binding_digest: Sha256Digest,
        correction_epoch: int,
        mission_entry_digest: Sha256Digest,
        event_entry_digests: tuple[Sha256Digest, ...],
        projection_entry_digests: tuple[Sha256Digest, ...],
        evidence_entry_digests: tuple[Sha256Digest, ...],
        static_budget_entry_digest: Sha256Digest,
    ) -> PublicResponsibilityState:
        entries = cls._verify_manifest_bytes(manifest, content_by_entry_digest)
        cls._require_role(entries, mission_entry_digest, PublicContentRole.MISSION)
        for digest in event_entry_digests:
            cls._require_role(entries, digest, PublicContentRole.EVENT)
        for digest in projection_entry_digests:
            cls._require_role(entries, digest, PublicContentRole.PROJECTION)
        for digest in evidence_entry_digests:
            cls._require_role(entries, digest, PublicContentRole.EVIDENCE)
        cls._require_role(
            entries, static_budget_entry_digest, PublicContentRole.STATIC_BUDGET
        )
        budget_entry = entries[static_budget_entry_digest]
        canonical_budget_bytes = static_budget_configuration_bytes(
            static_budget_configuration
        )
        if budget_entry.content_digest != static_budget_configuration.configuration_digest:
            raise ValueError("static budget manifest digest does not match contract")
        if content_by_entry_digest[static_budget_entry_digest] != canonical_budget_bytes:
            raise ValueError("static budget bytes are not canonical contract bytes")

        payload: dict[str, Any] = {
            "manifest_root_digest": manifest.manifest_root_digest,
            "mandate_digest": mandate_digest,
            "environment_binding_digest": environment_binding_digest,
            "correction_epoch": correction_epoch,
            "mission_entry_digest": mission_entry_digest,
            "event_entry_digests": event_entry_digests,
            "projection_entry_digests": projection_entry_digests,
            "evidence_entry_digests": evidence_entry_digests,
            "static_budget_entry_digest": static_budget_entry_digest,
        }
        payload["state_digest"] = public_responsibility_state_digest(payload)
        return PublicResponsibilityState.model_validate(payload)

    @classmethod
    def verify(
        cls,
        *,
        state: PublicResponsibilityState,
        manifest: PublicContentManifest,
        content_by_entry_digest: Mapping[str, bytes],
        static_budget_configuration: StaticBudgetConfiguration,
    ) -> PublicResponsibilityState:
        if state.manifest_root_digest != manifest.manifest_root_digest:
            raise ValueError("state manifest root does not match supplied manifest root")
        rebuilt = cls.build(
            manifest=manifest,
            content_by_entry_digest=content_by_entry_digest,
            static_budget_configuration=static_budget_configuration,
            mandate_digest=state.mandate_digest,
            environment_binding_digest=state.environment_binding_digest,
            correction_epoch=state.correction_epoch,
            mission_entry_digest=state.mission_entry_digest,
            event_entry_digests=state.event_entry_digests,
            projection_entry_digests=state.projection_entry_digests,
            evidence_entry_digests=state.evidence_entry_digests,
            static_budget_entry_digest=state.static_budget_entry_digest,
        )
        if rebuilt != state:
            raise ValueError("state does not match trusted manifest reconstruction")
        return state


class BudgetFeedback(ContractModel):
    """Arm-neutral remaining-usage feedback; never part of public-state digest."""

    feedback_id: NonEmptyStr
    budget_configuration_digest: Sha256Digest
    remaining_llm_calls: int = Field(ge=0)
    remaining_input_tokens: int = Field(ge=0)
    remaining_output_tokens: int = Field(ge=0)
    remaining_retries: int = Field(ge=0)
    remaining_tool_invocations: int = Field(ge=0)
    remaining_wall_seconds: int = Field(ge=0)
    issued_at: UtcDateTime


def decision_candidate_digest(payload: Mapping[str, Any]) -> str:
    if "candidate_digest" in payload:
        raise ValueError(
            "candidate_digest must be excluded from its own digest payload"
        )
    return content_digest(payload)


class DecisionCandidate(ContractModel):
    """A proposal-only decision; it grants no work, effect or run authority."""

    candidate_id: NonEmptyStr
    candidate_kind: CandidateKind
    public_state_digest: Sha256Digest
    no_external_effect: Literal[True]
    desired_outcome: NonEmptyStr | None = None
    acceptance_criteria: tuple[NonEmptyStr, ...] = ()
    missing_input_kind: MissingInputKind | None = None
    minimum_question: NonEmptyStr | None = None
    created_at: UtcDateTime
    candidate_digest: Sha256Digest

    @field_validator("no_external_effect", mode="before")
    @classmethod
    def _require_exact_true(cls, value: object) -> object:
        if value is not True:
            raise ValueError("no_external_effect must be exactly True")
        return value

    @model_validator(mode="after")
    def _validate_kind_fields(self) -> DecisionCandidate:
        if self.candidate_kind is CandidateKind.WORK:
            if self.desired_outcome is None or not self.acceptance_criteria:
                raise ValueError(
                    "WORK requires desired_outcome and acceptance_criteria"
                )
            if self.missing_input_kind is not None or self.minimum_question is not None:
                raise ValueError("WORK forbids help-only fields")
        elif self.candidate_kind is CandidateKind.HELP:
            if self.missing_input_kind is None or self.minimum_question is None:
                raise ValueError(
                    "HELP requires missing_input_kind and minimum_question"
                )
            if self.desired_outcome is not None or self.acceptance_criteria:
                raise ValueError("HELP forbids work-only fields")
        else:
            if self.desired_outcome is not None or self.acceptance_criteria:
                raise ValueError("NONE forbids work-only fields")
            if self.missing_input_kind is not None or self.minimum_question is not None:
                raise ValueError("NONE forbids help-only fields")
        return self

    @model_validator(mode="after")
    def _validate_candidate_digest(self) -> DecisionCandidate:
        payload = self.model_dump(mode="json", exclude={"candidate_digest"})
        if self.candidate_digest != decision_candidate_digest(payload):
            raise ValueError(
                "candidate_digest does not match canonical candidate payload"
            )
        return self


class ControllerBindingReceipt(ContractModel):
    """Exact-binding evidence record with content digest; no authority."""

    receipt_id: NonEmptyStr
    public_state_digest: Sha256Digest
    controller_digest: Sha256Digest
    prompt_digest: Sha256Digest
    model_digest: Sha256Digest
    tool_catalog_digest: Sha256Digest
    budget_configuration_digest: Sha256Digest
    trigger_digest: Sha256Digest
    candidate_digest: Sha256Digest
    bound_at: UtcDateTime
    content_digest: Sha256Digest
    authority_granted: Literal[False] = False
    external_effects_authorized: Literal[False] = False

    @field_validator("authority_granted", "external_effects_authorized", mode="before")
    @classmethod
    def _require_exact_false(cls, value: object) -> object:
        if value is not False:
            raise ValueError(
                "binding receipt cannot grant authority or external effects"
            )
        return value

    @model_validator(mode="after")
    def _validate_receipt_integrity(self) -> ControllerBindingReceipt:
        payload = self.model_dump(
            mode="json", exclude={"receipt_id", "content_digest"}
        )
        expected_digest = content_digest(payload)
        if self.content_digest != expected_digest:
            raise ValueError(
                "content_digest does not match canonical receipt payload"
            )
        expected_receipt_id = f"controller-binding:{expected_digest}"
        if self.receipt_id != expected_receipt_id:
            raise ValueError(
                "receipt_id must be controller-binding:{content_digest}"
            )
        return self
