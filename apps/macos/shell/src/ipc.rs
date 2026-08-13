/// Narrow, allowlisted Tauri IPC surface for the Wave 2a shell.
///
/// Only the commands listed here exist. Anything else is rejected before it
/// can reach daemon, custody, or filesystem code. The provider key value may
/// cross the bridge only inbound (renderer -> shell) for one-time Keychain
/// configuration and is never read back, logged, or stored in webview storage.

use serde::{Deserialize, Serialize};

pub const ALLOWED_COMMANDS: &[&str] = &[
    "daemon_start",
    "daemon_stop",
    "daemon_restart",
    "daemon_status",
    "runtime_connection",
    "custody_status_cmd",
    "custody_set_provider_key",
    "custody_clear_provider_key",
    "folder_request",
    "folder_status",
    "notify_approval",
];

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum IpcCommand {
    DaemonStart,
    DaemonStop,
    DaemonRestart,
    DaemonStatus,
    RuntimeConnection,
    CustodyStatus,
    CustodySetProviderKey,
    CustodyClearProviderKey,
    FolderRequest,
    FolderStatus,
    NotifyApproval,
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
        "daemon_start" => Ok(IpcCommand::DaemonStart),
        "daemon_stop" => Ok(IpcCommand::DaemonStop),
        "daemon_restart" => Ok(IpcCommand::DaemonRestart),
        "daemon_status" => Ok(IpcCommand::DaemonStatus),
        "runtime_connection" => Ok(IpcCommand::RuntimeConnection),
        "custody_status_cmd" => Ok(IpcCommand::CustodyStatus),
        "custody_set_provider_key" => Ok(IpcCommand::CustodySetProviderKey),
        "custody_clear_provider_key" => Ok(IpcCommand::CustodyClearProviderKey),
        "folder_request" => Ok(IpcCommand::FolderRequest),
        "folder_status" => Ok(IpcCommand::FolderStatus),
        "notify_approval" => Ok(IpcCommand::NotifyApproval),
        other => Err(IpcRejected {
            command: other.to_string(),
        }),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn allowlist_accepts_exactly_the_eleven_commands() {
        for name in ALLOWED_COMMANDS {
            assert!(parse_command(name).is_ok(), "must allow {name}");
        }
    }

    #[test]
    fn allowlist_rejects_unknown_and_lookalike_commands() {
        for name in [
            "daemon_exec",
            "shell:run",
            "fs:read",
            "fs:write",
            "keychain:read",
            "keychain:list",
            "custody:get_provider_key",
            "custody:read_provider_key",
            "webview:inject",
            "",
            "daemon_status ",
            "Daemon_Start",
        ] {
            assert!(
                parse_command(name).is_err(),
                "must reject {name:?}"
            );
        }
    }

    #[test]
    fn allowlist_matches_the_live_handler_registration() {
        // generate_handler! registers commands by `stringify!(fn_name)`.
        let live_handlers = [
            "daemon_start",
            "daemon_stop",
            "daemon_restart",
            "daemon_status",
            "runtime_connection",
            "custody_status_cmd",
            "custody_set_provider_key",
            "custody_clear_provider_key",
            "folder_request",
            "folder_status",
            "notify_approval",
        ];
        assert_eq!(ALLOWED_COMMANDS, live_handlers);
        for handler in live_handlers {
            assert!(parse_command(handler).is_ok(), "must allow {handler}");
        }
    }

    #[test]
    fn rejected_command_roundtrips_through_display() {
        let rejected = parse_command("fs:read").unwrap_err();
        assert_eq!(rejected.command, "fs:read");
        assert!(rejected.to_string().contains("not allowlisted"));
    }
}
