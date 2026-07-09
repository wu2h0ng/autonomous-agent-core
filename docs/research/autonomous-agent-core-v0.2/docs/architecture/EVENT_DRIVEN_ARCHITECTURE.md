# Event Driven Architecture

All meaningful changes create immutable events.

Examples:

GoalCreated
PlanGenerated
ActionProposed
ActionApproved
ActionRejected
HumanCorrectionIssued
CommitmentUpdated
RollbackExecuted
ModelImprovementProposed

Event flow:

Producer -> Event Bus -> Consumers -> State Projection
