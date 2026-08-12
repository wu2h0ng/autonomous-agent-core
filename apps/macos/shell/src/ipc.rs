/// Narrow, allowlisted Tauri IPC surface for the Wave 2a shell.
///
/// Only the commands listed here exist. Anything else is rejected before it
/// can reach daemon, custody, or filesystem code. The provider key value may
/// cross the bridge only inbound (renderer -> shell) for one-time Keychain
/// configuration and is never read back, logged, or stored in webview storage.

use serde::{Deserialize, Serialize};

pub const ALLOWED_COMMANDS: &[&str] = &[
    "daemon:start",
    "daemon:stop",
    "daemon:status",
    "custody:status",
    "custody:set_provider_key",
    "custody:clear_provider_key",
];

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum IpcCommand {
    DaemonStart,
    DaemonStop,
    DaemonStatus,
    CustodyStatus,
    CustodySetProviderKey,
    CustodyClearProviderKey,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct IpcRejected {
    pub command: String,
}

impl std::fmt::Display for IpcRejected {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "ipc command '{}' is not allowlisted", self.command)
    }
}

impl std::error::Error for IpcRejected {}

/// Parse one inbound IPC command name against the allowlist.
/// Rejects unknown names before any native code runs.
pub fn parse_command(name: &str) -> Result<IpcCommand, IpcRejected> {
    match name {
        "daemon:start" => Ok(IpcCommand::DaemonStart),
        "daemon:stop" => Ok(IpcCommand::DaemonStop),
        "daemon:status" => Ok(IpcCommand::DaemonStatus),
        "custody:status" => Ok(IpcCommand::CustodyStatus),
        "custody:set_provider_key" => Ok(IpcCommand::CustodySetProviderKey),
        "custody:clear_provider_key" => Ok(IpcCommand::CustodyClearProviderKey),
        other => Err(IpcRejected {
            command: other.to_string(),
        }),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn allowlist_accepts_exactly_the_six_commands() {
        for name in ALLOWED_COMMANDS {
            assert!(parse_command(name).is_ok(), "must allow {name}");
        }
    }

    #[test]
    fn allowlist_rejects_unknown_and_lookalike_commands() {
        for name in [
            "daemon:restart",
            "daemon:exec",
            "shell:run",
            "fs:read",
            "fs:write",
            "keychain:read",
            "keychain:list",
            "custody:get_provider_key",
            "custody:read_provider_key",
            "webview:inject",
            "",
            "daemon:status ",
            "Daemon:Start",
        ] {
            assert!(
                parse_command(name).is_err(),
                "must reject {name:?}"
            );
        }
    }

    #[test]
    fn rejected_command_roundtrips_through_display() {
        let rejected = parse_command("fs:read").unwrap_err();
        assert_eq!(rejected.command, "fs:read");
        assert!(rejected.to_string().contains("not allowlisted"));
    }
}
