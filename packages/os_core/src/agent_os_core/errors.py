from __future__ import annotations


class AgentOSCoreError(RuntimeError):
    pass


class ConcurrentWriteError(AgentOSCoreError):
    pass


class DuplicateEventError(AgentOSCoreError):
    pass


class EventStreamError(AgentOSCoreError):
    pass


class InvalidTransitionError(AgentOSCoreError):
    pass


class ScopeMismatchError(AgentOSCoreError):
    pass


class SituationalProposalError(AgentOSCoreError):
    pass


class SituationalScopeMismatch(SituationalProposalError):
    pass


class StaleOperationalProjection(SituationalProposalError):
    pass


class SituationalTrustDenied(SituationalProposalError):
    pass


class SituationalPersistenceConflict(SituationalProposalError):
    pass


class ProtocolIngressConflict(SituationalPersistenceConflict):
    pass


class TaskNotFoundError(AgentOSCoreError):
    pass


class CommitmentExpiredError(InvalidTransitionError):
    pass


class SignalMismatchError(InvalidTransitionError):
    pass


class WaitExpiredError(InvalidTransitionError):
    pass


class ReplanRejectedError(InvalidTransitionError):
    pass


class CandidateError(AgentOSCoreError):
    pass


class CandidateScopeMismatch(CandidateError):
    pass


class CandidateSealingDenied(CandidateError):
    pass


class CandidateIdempotencyConflict(CandidateError):
    pass


class CandidateConcurrentWrite(CandidateError):
    pass


class CandidateProvenanceError(CandidateError):
    pass


class CandidateEvaluationError(CandidateError):
    pass


class CandidateEvaluationNotFound(CandidateEvaluationError):
    pass


class CandidateEvaluationDenied(CandidateEvaluationError):
    pass


class CandidateEvaluationScopeMismatch(CandidateEvaluationError):
    pass


class CandidatePromotionError(CandidateError):
    pass


class CandidatePromotionNotFound(CandidatePromotionError):
    pass


class CandidatePromotionDenied(CandidatePromotionError):
    pass


class CandidatePromotionScopeMismatch(CandidatePromotionError):
    pass


class TaskConfigurationError(AgentOSCoreError):
    pass


class TaskConfigurationNotFound(TaskConfigurationError):
    pass


class TaskConfigurationDenied(TaskConfigurationError):
    pass


class TaskConfigurationScopeMismatch(TaskConfigurationError):
    pass


class TaskConfigurationConflict(TaskConfigurationError):
    pass


class TaskConfigurationNotBound(TaskConfigurationError):
    pass


class TaskConfigurationDrift(TaskConfigurationError):
    pass


class RunExecutionError(AgentOSCoreError):
    pass


class WorkerInterrupted(RunExecutionError):
    """Test/worker crash boundary; durable event state remains resumable."""
    pass


class WaitingForApproval(RunExecutionError):
    pass


class ProviderCorrectionHalt(RunExecutionError):
    """A correction landed while the provider invocation was in flight.

    The answer cannot be bound to the correction epoch captured before the
    invocation, so it is discarded: never recorded as a provider response,
    never dispatched. The caller must still END the turn (as
    ``correction_halted``) — raising out of the turn instead left the durable
    turn open forever, so the session reported an uncommitted turn and every
    later begin-turn was refused with ``SurfaceTurnInProgress``.
    """


class UnsupportedNodeError(RunExecutionError):
    pass
