#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Mutex, OnceLock};

use agent_os_shell_lib::daemon_supervisor::{DaemonConfig, Supervisor, SupervisorState};
use agent_os_shell_lib::keychain_custody::{
    CustodyStatus, custody_status, effective_provider_key, KeyValueStore, KeychainStore, PROVIDER_KEY_ACCOUNT,
    KEYCHAIN_SERVICE,
};

const DAEMON_KEY_ENV: &str = "AGENT_OS_PROVIDER_API_KEY";

fn env_or(name: &str, default: &str) -> String {
    std::env::var(name).unwrap_or_else(|_| default.to_string())
}

/// Dev-scope daemon configuration (PATH-independent python resolution is
/// supplied via AGENT_OS_DAEMON_PYTHON; the app config overrides env for the
/// dev artifact).
fn default_daemon_config() -> DaemonConfig {
    // PATH-independent: the daemon python must be supplied explicitly.
    let python = match std::env::var("AGENT_OS_DAEMON_PYTHON") {
        Ok(value) if !value.is_empty() => PathBuf::from(value),
        _ => {
            eprintln!("AGENT_OS_DAEMON_PYTHON is required (PATH-independent resolution)");
            std::process::exit(2);
        }
    };
    DaemonConfig {
        python,
        database: PathBuf::from(env_or("AGENT_OS_DAEMON_DATABASE", "agent-os.sqlite3")),
        workspace: PathBuf::from(env_or("AGENT_OS_DAEMON_WORKSPACE", ".")),
        descriptor_path: PathBuf::from(env_or(
            "AGENT_OS_DAEMON_DESCRIPTOR",
            &format!("{}/.agent-os/runtime.json", env_or("HOME", ".")),
        )),
        provider_key_env_name: DAEMON_KEY_ENV.to_string(),
        provider_key_value: effective_provider_key(DAEMON_KEY_ENV, Some(&KeychainStore)),
        pythonpath: std::env::var("PYTHONPATH").ok(),
    }
}

fn supervisor() -> &'static Mutex<Supervisor> {
    static SUPERVISOR: OnceLock<Mutex<Supervisor>> = OnceLock::new();
    SUPERVISOR.get_or_init(|| Mutex::new(Supervisor::new(default_daemon_config())))
}

static SHUTDOWN: AtomicBool = AtomicBool::new(false);

extern "C" fn handle_termination(_sig: i32) {
    SHUTDOWN.store(true, Ordering::SeqCst);
}

#[link(name = "c")]
extern "C" {
    #[link_name = "signal"]
    fn c_signal(sig: i32, handler: usize) -> usize;
}

fn install_termination_handlers() {
    unsafe {
        c_signal(15, handle_termination as usize); // SIGTERM
        c_signal(2, handle_termination as usize); // SIGINT
    }
}

fn main() {
    let app = tauri::Builder::default()
        .setup(|_app| {
            // The shell supervises the daemon from launch; no renderer IPC or
            // manual Python start is required (Wave 2a exit gate). A
            // background thread ticks the supervisor so crash-restart works
            // without renderer interaction, and drains it on SIGTERM/SIGINT.
            let mut guard = supervisor().lock().map_err(|e| e.to_string())?;
            guard.start();
            drop(guard);
            install_termination_handlers();
            std::thread::spawn(move || loop {
                if SHUTDOWN.load(Ordering::SeqCst) {
                    if let Ok(mut guard) = supervisor().lock() {
                        guard.stop();
                    }
                    std::process::exit(0);
                }
                if let Ok(mut guard) = supervisor().lock() {
                    guard.tick();
                }
                std::thread::sleep(std::time::Duration::from_secs(2));
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            daemon_start,
            daemon_stop,
            daemon_restart,
            daemon_status,
            runtime_connection,
            custody_status_cmd,
            custody_set_provider_key,
            custody_clear_provider_key,
        ])
        .build(tauri::generate_context!())
        .expect("error while building the Agent OS shell");
    app.run(|_handle, event| {
        if let tauri::RunEvent::Exit = event {
            // Boot-id-matched descriptor removal and SQLite close happen in
            // the daemon itself on SIGTERM; stop() reaps the child here.
            if let Ok(mut guard) = supervisor().lock() {
                guard.stop();
            }
        }
    });
}

// --- daemon lifecycle (supervisor) ---

#[tauri::command]
fn daemon_start() -> Result<String, String> {
    let mut supervisor = supervisor().lock().map_err(|e| e.to_string())?;
    if supervisor.state == SupervisorState::Stopped {
        supervisor.start();
    }
    Ok("starting".to_string())
}

#[tauri::command]
fn daemon_stop() -> Result<String, String> {
    let mut supervisor = supervisor().lock().map_err(|e| e.to_string())?;
    supervisor.stop();
    Ok("stopped".to_string())
}

#[tauri::command]
fn daemon_restart() -> Result<String, String> {
    let mut guard = supervisor().lock().map_err(|e| e.to_string())?;
    guard.stop();
    guard.start();
    Ok("restarting".to_string())
}

#[tauri::command]
fn runtime_connection() -> Result<String, String> {
    let guard = supervisor().lock().map_err(|e| e.to_string())?;
    match guard.connection() {
        Some((base_url, token)) => Ok(serde_json::json!({
            "base_url": base_url,
            "bearer_token": token,
        })
        .to_string()),
        None => Err("runtime connection is not available yet".to_string()),
    }
}

#[tauri::command]
fn daemon_status() -> Result<String, String> {
    let supervisor = supervisor().lock().map_err(|e| e.to_string())?;
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
    let status = custody_status(DAEMON_KEY_ENV, Some(&KeychainStore));
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
