/// Daemon supervision state machine for the Wave 2a shell.
///
/// Pure decision logic (no process spawning here) so it is unit-testable:
/// `SupervisorDecision` is produced from a health/descriptor observation and
/// executed by the caller.

use std::time::Duration;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SupervisorState {
    Stopped,
    Starting,
    Running,
    RestartBackoff,
    Halted,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SupervisorDecision {
    Spawn,
    WaitForHealth,
    Recover(std::time::Duration),
    Halt,
    Idle,
}

pub const MAX_RESTARTS_PER_HOUR: u32 = 4;
pub const HEALTH_TIMEOUT: Duration = Duration::from_secs(10);
pub const BACKOFF_STEP: Duration = Duration::from_secs(2);

/// Decide the next supervisor action from the current observation.
///
/// `restarts` is the number of restart events in the current rolling window.
/// A running-but-unhealthy daemon transitions to RestartBackoff only when the
/// restart budget is not exhausted; otherwise the supervisor halts and never
/// auto-respawns (fail-closed, no crash loop).
pub fn decide(
    state: SupervisorState,
    process_alive: bool,
    health_ok: bool,
    restarts: u32,
) -> SupervisorDecision {
    match state {
        SupervisorState::Stopped | SupervisorState::Halted => {
            SupervisorDecision::Halt
        }
        SupervisorState::Starting => {
            if health_ok {
                SupervisorDecision::Idle
            } else if process_alive {
                SupervisorDecision::WaitForHealth
            } else if restarts < MAX_RESTARTS_PER_HOUR {
                SupervisorDecision::Recover(BACKOFF_STEP)
            } else {
                SupervisorDecision::Halt
            }
        }
        SupervisorState::Running => {
            if health_ok {
                SupervisorDecision::Idle
            } else if restarts < MAX_RESTARTS_PER_HOUR {
                SupervisorDecision::Recover(BACKOFF_STEP)
            } else {
                SupervisorDecision::Halt
            }
        }
        SupervisorState::RestartBackoff => {
            if process_alive {
                SupervisorDecision::WaitForHealth
            } else if health_ok {
                SupervisorDecision::Idle
            } else if restarts < MAX_RESTARTS_PER_HOUR {
                SupervisorDecision::Spawn
            } else {
                SupervisorDecision::Halt
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn stopped_supervisor_never_spawns() {
        assert_eq!(
            decide(SupervisorState::Stopped, false, false, 0),
            SupervisorDecision::Halt
        );
        assert_eq!(
            decide(SupervisorState::Halted, true, true, 0),
            SupervisorDecision::Halt
        );
    }

    #[test]
    fn starting_waits_for_health_while_process_alive() {
        assert_eq!(
            decide(SupervisorState::Starting, true, false, 0),
            SupervisorDecision::WaitForHealth
        );
        assert_eq!(
            decide(SupervisorState::Starting, true, true, 0),
            SupervisorDecision::Idle
        );
    }

    #[test]
    fn dead_process_within_budget_recovers_with_backoff() {
        assert_eq!(
            decide(SupervisorState::Starting, false, false, 0),
            SupervisorDecision::Recover(BACKOFF_STEP)
        );
        assert_eq!(
            decide(SupervisorState::Running, false, false, 2),
            SupervisorDecision::Recover(BACKOFF_STEP)
        );
    }

    #[test]
    fn restart_budget_exhaustion_halts_fail_closed() {
        assert_eq!(
            decide(SupervisorState::Running, false, false, MAX_RESTARTS_PER_HOUR),
            SupervisorDecision::Halt
        );
        assert_eq!(
            decide(SupervisorState::RestartBackoff, false, false, MAX_RESTARTS_PER_HOUR),
            SupervisorDecision::Halt
        );
    }

    #[test]
    fn backoff_respawns_only_with_budget() {
        assert_eq!(
            decide(SupervisorState::RestartBackoff, false, false, 0),
            SupervisorDecision::Spawn
        );
        assert_eq!(
            decide(SupervisorState::RestartBackoff, true, false, 0),
            SupervisorDecision::WaitForHealth
        );
    }
}
