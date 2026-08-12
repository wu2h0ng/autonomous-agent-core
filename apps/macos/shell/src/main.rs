#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::path::PathBuf;
use std::sync::Mutex;

use agent_os_shell_lib::daemon_supervisor::{DaemonConfig, Supervisor, SupervisorState};
use agent_os_shell_lib::keychain_custody::{
    effective_provider_key, custody_status, CustodyStatus, KeyValueStore, KeychainStore,
    PROVIDER_KEY_ACCOUNT, KEYCHAIN_SERVICE,
};

const PROVIDER_KEY_ENV: &str = "AGENT_OS_PROVIDER_API_KEY_ENV";
const DAEMON_KEY_ENV: &str = "AGENT_OS_PROVIDER_API_KEY";

fn env_or(name: &str, default: &str) -> String {
    std::env::var(name).unwrap_or_else(|_| default.to_string())
}

/// Dev-scope daemon configuration (PATH-independent python resolution is
/// supplied by the caller; the app config overrides env for the dev artifact).
fn default_daemon_config() -> DaemonConfig {
    let python = PathBuf::from(env_or("AGENT_OS_DAEMON_PYTHON", "python3"));
    DaemonConfig {
        python,
        database: PathBuf::from(env_or("AGENT_OS_DAEMON_DATABASE", "agent-os.sqlite3")),
        workspace: PathBuf::from(env_or("AGENT_OS_DAEMON_WORKSPACE", ".")),
        descriptor_path: PathBuf::from(env_or(
            "AGENT_OS_DAEMON_DESCRIPTOR",
            &format!("{}/.agent-os/runtime.json", env_or("HOME", ".")),
        )),
        provider_key_env_name: DAEMON_KEY_ENV.to_string(),
        provider_key_value: effective_provider_key(PROVIDER_KEY_ENV, Some(&KeychainStore)),
        pythonpath: std::env::var("PYTHONPATH").ok(),
    }
}

struct AppState {
    supervisor: Mutex<Supervisor>,
}

fn main() {
    let state = AppState {
        supervisor: Mutex::new(Supervisor::new(default_daemon_config())),
    };
    tauri::Builder::default()
        .manage(state)
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
fn daemon_start(state: tauri::State<'_, AppState>) -> Result<String, String> {
    let mut supervisor = state.supervisor.lock().map_err(|e| e.to_string())?;
    if supervisor.state == SupervisorState::Stopped {
        supervisor.start();
    }
    Ok("starting".to_string())
}

#[tauri::command]
fn daemon_stop(state: tauri::State<'_, AppState>) -> Result<String, String> {
    let mut supervisor = state.supervisor.lock().map_err(|e| e.to_string())?;
    supervisor.stop();
    Ok("stopped".to_string())
}

#[tauri::command]
fn daemon_status(state: tauri::State<'_, AppState>) -> Result<String, String> {
    let supervisor = state.supervisor.lock().map_err(|e| e.to_string())?;
    let state_name = match supervisor.state {
        SupervisorState::Stopped => "stopped",
        SupervisorState::Starting => "starting",
        SupervisorState::Running => "running",
        SupervisorState::RestartBackoff => "restart_backoff",
        SupervisorState::Halted => "halted",
    };
    Ok(serde_json::json!({
        "state": state_name,
        "restarts": supervisor.restarts,
        "boot_id": supervisor.last_boot_id,
    })
    .to_string())
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
    KeychainStore.set_secret(KEYCHAIN_SERVICE, PROVIDER_KEY_ACCOUNT, &provider_key)?;
    Ok(true)
}

#[tauri::command]
fn custody_clear_provider_key() -> Result<bool, String> {
    KeychainStore.delete_secret(KEYCHAIN_SERVICE, PROVIDER_KEY_ACCOUNT)?;
    Ok(true)
}
