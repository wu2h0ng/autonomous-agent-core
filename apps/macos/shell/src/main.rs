#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use agent_os_shell_lib::daemon_supervisor::SupervisorState;
use agent_os_shell_lib::keychain_custody::{
    custody_status, effective_provider_key, CustodyStatus, KeyValueStore, KeychainStore,
    PROVIDER_KEY_ACCOUNT, KEYCHAIN_SERVICE,
};

const PROVIDER_KEY_ENV: &str = "AGENT_OS_PROVIDER_API_KEY_ENV";
const DAEMON_ENV_KEY: &str = "AGENT_OS_PROVIDER_API_KEY";

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            daemon_start,
            daemon_stop,
            daemon_status,
            custody_status_cmd,
            custody_set_provider_key,
            custody_clear_provider_key,
        ])
        .run(tauri::generate_context!())
        .expect("error while running the Agent OS shell");
}

// --- daemon lifecycle (supervisor) ---

#[tauri::command]
fn daemon_start() -> Result<String, String> {
    // Wave 2a: supervision integration is wired in Task 3; the state machine
    // decision logic is already unit-tested in daemon_supervisor.rs.
    let _ = SupervisorState::Stopped;
    Err("daemon supervision integration pending Task 3".to_string())
}

#[tauri::command]
fn daemon_stop() -> Result<String, String> {
    Ok("stopping".to_string())
}

#[tauri::command]
fn daemon_status() -> Result<String, String> {
    Ok("stopped".to_string())
}

// --- keychain custody (ADR-0058) ---

#[tauri::command]
fn custody_status_cmd() -> Result<String, String> {
    let status = custody_status(PROVIDER_KEY_ENV, Some(&KeychainStore));
    Ok(match status {
        CustodyStatus::Present => "present",
        CustodyStatus::Absent => "absent",
        CustodyStatus::EnvOverride => "env",
    }
    .to_string())
}

/// Write-only inbound: sets the provider key in Keychain and returns a
/// boolean. The value is never read back through IPC.
#[tauri::command]
fn custody_set_provider_key(provider_key: String) -> Result<bool, String> {
    if provider_key.is_empty() {
        return Err("provider key must be non-empty".to_string());
    }
    let store = KeychainStore;
    store.set_secret(KEYCHAIN_SERVICE, PROVIDER_KEY_ACCOUNT, &provider_key)?;
    // Never echo the value.
    let _ = effective_provider_key(PROVIDER_KEY_ENV, Some(&store));
    Ok(true)
}

#[tauri::command]
fn custody_clear_provider_key() -> Result<bool, String> {
    let store = KeychainStore;
    store.delete_secret(KEYCHAIN_SERVICE, PROVIDER_KEY_ACCOUNT)?;
    Ok(true)
}

// The daemon startup injects DAEMON_ENV_KEY with the effective key value
// resolved by the shell (Task 4 wires this through the supervisor).
#[allow(dead_code)]
fn _daemon_environment() -> Vec<(String, String)> {
    let mut env = Vec::new();
    if let Some(key) = effective_provider_key(PROVIDER_KEY_ENV, Some(&KeychainStore)) {
        env.push((DAEMON_ENV_KEY.to_string(), key));
    }
    env
}
