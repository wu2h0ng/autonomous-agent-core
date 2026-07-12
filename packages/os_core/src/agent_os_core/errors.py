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
