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
