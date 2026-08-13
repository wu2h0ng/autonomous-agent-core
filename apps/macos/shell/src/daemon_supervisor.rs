/// Daemon supervision for the Wave 2a shell.
///
/// Pure decision logic (`decide`) is unit-tested here; `Supervisor` owns the
/// real child process, descriptor parsing, and a minimal stdlib HTTP health
/// probe (no external HTTP dependency). The daemon Python executable is
/// resolved explicitly (PATH-independent) so GUI launches work without a
/// terminal environment.

use std::io::{Read, Write};
use std::net::TcpStream;
use std::path::PathBuf;
use std::process::{Child, Command};
use std::time::Duration;

pub const HEALTH_TIMEOUT: Duration = Duration::from_secs(10);

#[link(name = "c")]
extern "C" {
    #[link_name = "kill"]
    fn c_kill(pid: i32, sig: i32) -> i32;
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DaemonDescriptor {
    pub pid: i64,
    pub boot_id: String,
    pub port: u16,
    pub bearer_token: String,
    pub database_path: String,
    pub workspace_path: String,
}

/// Parse and strictly validate one runtime descriptor document.
pub fn parse_descriptor(json: &str) -> Result<DaemonDescriptor, String> {
    let value: serde_json::Value =
        serde_json::from_str(json).map_err(|e| format!("invalid descriptor JSON: {e}"))?;
    let obj = value
        .as_object()
        .ok_or_else(|| "descriptor must be an object".to_string())?;
    if obj.get("protocol_version").and_then(|v| v.as_str()) != Some("1.0") {
        return Err("descriptor protocol_version must be 1.0".to_string());
    }
    let pid = obj
        .get("pid")
        .and_then(|v| v.as_i64())
        .filter(|pid| *pid > 0)
        .ok_or_else(|| "descriptor pid must be a positive integer".to_string())?;
    let boot_id = obj
        .get("boot_id")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .ok_or_else(|| "descriptor boot_id must be non-empty".to_string())?
        .to_string();
    let host = obj
        .get("host")
        .and_then(|v| v.as_str())
        .ok_or_else(|| "descriptor host is missing".to_string())?;
    if host != "127.0.0.1" {
        return Err("descriptor host must be loopback".to_string());
    }
    let port = obj
        .get("port")
        .and_then(|v| v.as_u64())
        .filter(|port| (1..=65535).contains(port))
        .ok_or_else(|| "descriptor port must be within 1..65535".to_string())? as u16;
    let bearer_token = obj
        .get("bearer_token")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .ok_or_else(|| "descriptor bearer_token must be non-empty".to_string())?
        .to_string();
    let database_path = obj
        .get("database_path")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .ok_or_else(|| "descriptor database_path must be non-empty".to_string())?
        .to_string();
    let workspace_path = obj
        .get("workspace_path")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .ok_or_else(|| "descriptor workspace_path must be non-empty".to_string())?
        .to_string();
    Ok(DaemonDescriptor {
        pid,
        boot_id,
        port,
        bearer_token,
        database_path,
        workspace_path,
    })
}

/// Pure supervisor decision logic (no process spawning), unit-testable.
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

/// Decide the next supervisor action from the current observation.
/// A dead or unhealthy daemon recovers only while the restart budget is not
/// exhausted; otherwise the supervisor halts fail-closed (no crash loop).
pub fn decide(
    state: SupervisorState,
    process_alive: bool,
    health_ok: bool,
    restarts: u32,
) -> SupervisorDecision {
    match state {
        SupervisorState::Stopped | SupervisorState::Halted => SupervisorDecision::Halt,
        SupervisorState::Starting => {
            if health_ok {
                SupervisorDecision::Idle
            } else if process_alive {
                SupervisorDecision::WaitForHealth
            } else if restarts < MAX_RESTARTS_PER_HOUR {
                SupervisorDecision::Recover(std::time::Duration::from_secs(2))
            } else {
                SupervisorDecision::Halt
            }
        }
        SupervisorState::Running => {
            if health_ok {
                SupervisorDecision::Idle
            } else if restarts < MAX_RESTARTS_PER_HOUR {
                SupervisorDecision::Recover(std::time::Duration::from_secs(2))
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

/// Minimal authenticated health probe over a raw loopback socket.
/// Returns Ok(true) for HTTP 200, Ok(false) for HTTP 401 (server is up but
/// token mismatch), and Err only when the server cannot be reached.
pub fn probe_health(port: u16, token: &str) -> Result<bool, String> {    let mut stream = TcpStream::connect(("127.0.0.1", port))
        .map_err(|e| format!("health connect failed: {e}"))?;
    stream
        .set_read_timeout(Some(HEALTH_TIMEOUT))
        .map_err(|e| e.to_string())?;
    stream
        .set_write_timeout(Some(HEALTH_TIMEOUT))
        .map_err(|e| e.to_string())?;
    let request = format!(
        "GET /v1/health HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n\
         Authorization: Bearer {token}\r\nConnection: close\r\n\r\n"
    );
    stream
        .write_all(request.as_bytes())
        .map_err(|e| format!("health write failed: {e}"))?;
    let mut response = String::new();
    stream
        .read_to_string(&mut response)
        .map_err(|e| format!("health read failed: {e}"))?;
    if response.starts_with("HTTP/1.1 200") || response.starts_with("HTTP/1.0 200") {
        Ok(true)
    } else if response.starts_with("HTTP/1.1 401") || response.starts_with("HTTP/1.0 401") {
        Ok(false)
    } else {
        Err(format!("unexpected health response: {}", response.lines().next().unwrap_or("")))
    }
}

#[derive(Debug, Clone)]
pub struct DaemonConfig {
    pub python: PathBuf,
    pub database: PathBuf,
    pub workspace: PathBuf,
    pub descriptor_path: PathBuf,
    pub provider_key_env_name: String,
    pub provider_key_value: Option<String>,
    pub pythonpath: Option<String>,
}

pub struct Supervisor {
    pub state: SupervisorState,
    pub restarts: u32,
    pub config: DaemonConfig,
    pub process: Option<Child>,
    pub last_boot_id: Option<String>,
}

impl Supervisor {
    pub fn new(config: DaemonConfig) -> Self {
        Self {
            state: SupervisorState::Stopped,
            restarts: 0,
            config,
            process: None,
            last_boot_id: None,
        }
    }

    pub fn start(&mut self) {
        self.state = SupervisorState::Starting;
        self.spawn();
    }

    pub fn stop(&mut self) {
        if let Some(child) = self.process.as_mut() {
            let pid = child.id();
            // Graceful SIGTERM first so the daemon removes its own descriptor
            // (boot-id match) and closes SQLite; SIGKILL only as fallback.
            unsafe {
                c_kill(pid as i32, 15);
            }
            let mut exited = false;
            for _ in 0..50 {
                if child.try_wait().ok().flatten().is_some() {
                    exited = true;
                    break;
                }
                std::thread::sleep(Duration::from_millis(100));
            }
            if !exited {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
        self.process = None;
        self.state = SupervisorState::Stopped;
    }

    /// Advance the supervisor by one tick based on current observations.
    pub fn tick(&mut self) -> SupervisorDecision {
        let descriptor = self.current_descriptor();
        if let Some(ref descriptor) = descriptor {
            if self.last_boot_id.as_deref() != Some(descriptor.boot_id.as_str()) {
                self.last_boot_id = Some(descriptor.boot_id.clone());
            }
        }
        let process_alive = self
            .process
            .as_mut()
            .map(|child| {
                child
                    .try_wait()
                    .map(|status| status.is_none())
                    .unwrap_or(false)
            })
            .unwrap_or(false);
        let health_ok = descriptor
            .as_ref()
            .and_then(|descriptor| probe_health(descriptor.port, &descriptor.bearer_token).ok())
            .unwrap_or(false);
        if health_ok {
            self.state = SupervisorState::Running;
        }
        let decision = crate::daemon_supervisor::decide(
            self.state,
            process_alive,
            health_ok,
            self.restarts,
        );
        match decision {
            SupervisorDecision::Spawn => {
                self.restarts += 1;
                self.spawn();
            }
            SupervisorDecision::Recover(_) => {
                self.restarts += 1;
                self.state = SupervisorState::RestartBackoff;
            }
            SupervisorDecision::Halt => {
                self.stop();
            }
            SupervisorDecision::WaitForHealth | SupervisorDecision::Idle => {}
        }
        decision
    }

    fn current_descriptor(&self) -> Option<DaemonDescriptor> {
        let raw = std::fs::read_to_string(&self.config.descriptor_path).ok()?;
        parse_descriptor(&raw).ok()
    }

    fn spawn(&mut self) {
        let mut command = Command::new(&self.config.python);
        command
            .arg("-m")
            .arg("apps.runtime_daemon")
            .arg("--database")
            .arg(&self.config.database)
            .arg("--workspace")
            .arg(&self.config.workspace)
            .arg("--descriptor")
            .arg(&self.config.descriptor_path)
            .arg("--host")
            .arg("127.0.0.1")
            .arg("--port")
            .arg("0")
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null());
        if let Some(pythonpath) = &self.config.pythonpath {
            command.env("PYTHONPATH", pythonpath);
        }
        if let Some(value) = &self.config.provider_key_value {
            command.env(&self.config.provider_key_env_name, value);
        }
        match command.spawn() {
            Ok(child) => {
                self.process = Some(child);
                self.state = SupervisorState::Starting;
            }
            Err(_) => {
                self.state = SupervisorState::RestartBackoff;
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;


    #[test]
    fn stopped_supervisor_never_spawns() {
        assert_eq!(decide(SupervisorState::Stopped, false, false, 0), SupervisorDecision::Halt);
        assert_eq!(decide(SupervisorState::Halted, true, true, 0), SupervisorDecision::Halt);
    }

    #[test]
    fn starting_waits_for_health_while_process_alive() {
        assert_eq!(decide(SupervisorState::Starting, true, false, 0), SupervisorDecision::WaitForHealth);
        assert_eq!(decide(SupervisorState::Starting, true, true, 0), SupervisorDecision::Idle);
    }

    #[test]
    fn dead_process_within_budget_recovers_with_backoff() {
        assert_eq!(decide(SupervisorState::Starting, false, false, 0), SupervisorDecision::Recover(std::time::Duration::from_secs(2)));
        assert_eq!(decide(SupervisorState::Running, false, false, 2), SupervisorDecision::Recover(std::time::Duration::from_secs(2)));
    }

    #[test]
    fn restart_budget_exhaustion_halts_fail_closed() {
        assert_eq!(decide(SupervisorState::Running, false, false, MAX_RESTARTS_PER_HOUR), SupervisorDecision::Halt);
        assert_eq!(decide(SupervisorState::RestartBackoff, false, false, MAX_RESTARTS_PER_HOUR), SupervisorDecision::Halt);
    }

    #[test]
    fn backoff_respawns_only_with_budget() {
        assert_eq!(decide(SupervisorState::RestartBackoff, false, false, 0), SupervisorDecision::Spawn);
        assert_eq!(decide(SupervisorState::RestartBackoff, true, false, 0), SupervisorDecision::WaitForHealth);
    }


    #[test]
    fn parse_descriptor_accepts_valid_document() {
        let json = r#"{
            "protocol_version": "1.0",
            "pid": 42,
            "boot_id": "boot:test",
            "host": "127.0.0.1",
            "port": 18787,
            "bearer_token": "token",
            "database_path": "/tmp/db.sqlite3",
            "workspace_path": "/tmp/ws",
            "created_at": "2026-08-12T00:00:00+00:00"
        }"#;
        let descriptor = parse_descriptor(json).unwrap();
        assert_eq!(descriptor.pid, 42);
        assert_eq!(descriptor.boot_id, "boot:test");
        assert_eq!(descriptor.port, 18787);
        assert_eq!(descriptor.database_path, "/tmp/db.sqlite3");
    }

    #[test]
    fn parse_descriptor_rejects_invalid_documents() {
        for (json, needle) in [
            ("not json", "invalid descriptor JSON"),
            (r#"{"protocol_version": "2.0"}"#, "protocol_version"),
            (r#"{"protocol_version": "1.0", "pid": 0, "boot_id": "b", "host": "127.0.0.1", "port": 1, "bearer_token": "t", "database_path": "d", "workspace_path": "w"}"#, "pid"),
            (r#"{"protocol_version": "1.0", "pid": 1, "boot_id": "b", "host": "0.0.0.0", "port": 1, "bearer_token": "t", "database_path": "d", "workspace_path": "w"}"#, "loopback"),
            (r#"{"protocol_version": "1.0", "pid": 1, "boot_id": "b", "host": "127.0.0.1", "port": 70000, "bearer_token": "t", "database_path": "d", "workspace_path": "w"}"#, "port"),
            (r#"{"protocol_version": "1.0", "pid": 1, "boot_id": "b", "host": "127.0.0.1", "port": 1, "bearer_token": "", "database_path": "d", "workspace_path": "w"}"#, "bearer_token"),
        ] {
            let err = parse_descriptor(json).unwrap_err();
            assert!(err.contains(needle), "expected {needle} in {err}");
        }
    }

    #[test]
    fn probe_health_accepts_200_and_rejects_401() {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        let handle = std::thread::spawn(move || {
            for (status, body) in [("200 OK", "ok"), ("401 Unauthorized", "no")] {
                let (mut stream, _) = listener.accept().unwrap();
                let mut buf = [0u8; 1024];
                let _ = stream.read(&mut buf);
                let response = format!(
                    "HTTP/1.1 {status}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                    body.len()
                );
                let _ = stream.write_all(response.as_bytes());
            }
        });
        assert_eq!(probe_health(port, "token").unwrap(), true);
        assert_eq!(probe_health(port, "token").unwrap(), false);
        handle.join().unwrap();
    }

    #[test]
    fn probe_health_fails_when_port_closed() {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        drop(listener);
        assert!(probe_health(port, "token").is_err());
    }
}
