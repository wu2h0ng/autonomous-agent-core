//! Integration: the Rust supervisor manages a real Wave 1 daemon process.
//!
//! Requires the repository Python + packages on PYTHONPATH (set in the test).
//! Skipped automatically when the repository layout is unavailable.

use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{Duration, Instant};

use agent_os_shell_lib::daemon_supervisor::{DaemonConfig, Supervisor, SupervisorState};

fn repo_root() -> PathBuf {
    // CARGO_MANIFEST_DIR = <root>/apps/macos/shell; three parents = <root>
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .to_path_buf()
}

fn python_on_path() -> Option<PathBuf> {
    for name in ["python3", "python"] {
        let probe = Command::new(name)
            .arg("-c")
            .arg("import sys; print(sys.executable)")
            .output();
        if let Ok(out) = probe {
            if out.status.success() {
                return Some(PathBuf::from(
                    String::from_utf8_lossy(&out.stdout).trim(),
                ));
            }
        }
    }
    None
}

fn wait_until(mut condition: impl FnMut() -> bool, timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if condition() {
            return true;
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    condition()
}

#[test]
fn supervisor_respawns_killed_daemon_with_new_boot_id() {
    let root = repo_root();
    let tmp = std::env::temp_dir().join(format!("wave2a-supervisor-{}", std::process::id()));
    let _ = std::fs::create_dir_all(&tmp);

    let python = match python_on_path() {
        Some(python) => python,
        None => {
            eprintln!("skipping: no python on PATH");
            return;
        }
    };
    let packages = format!(
        "{}:{}",
        root.display(),
        root.join("packages/contracts/src").display()
    );
    let pythonpath = format!(
        "{packages}:{}",
        root.join("packages/os_core/src").display()
    );

    let config = DaemonConfig {
        python,
        database: tmp.join("agent-os.sqlite3"),
        workspace: tmp.clone(),
        descriptor_path: tmp.join("runtime.json"),
        provider_key_env_name: "AGENT_OS_PROVIDER_API_KEY".to_string(),
        provider_key_value: None,
        pythonpath: Some(pythonpath),
    };
    let mut supervisor = Supervisor::new(config);
    supervisor.start();
    assert!(wait_until(
        || {
            supervisor
                .tick();
            supervisor.last_boot_id.is_some()
        },
        Duration::from_secs(20)
    ));
    let first_boot = supervisor.last_boot_id.clone().unwrap();

    // Kill the daemon out from under the supervisor; the next tick must
    // observe the dead process and schedule a supervised restart.
    let child = supervisor.process.as_mut().unwrap();
    unsafe {
        libc_kill(child.id() as i32, 9); // SIGKILL
    }
    let _ = child.wait();

    assert!(wait_until(
        || {
            supervisor
                .tick();
            supervisor.last_boot_id.as_deref() != Some(first_boot.as_str())
        },
        Duration::from_secs(20)
    ));
    assert!(supervisor.restarts >= 1);
    assert_ne!(
        supervisor.last_boot_id.as_deref(),
        Some(first_boot.as_str())
    );

    supervisor.stop();
    assert_eq!(supervisor.state, SupervisorState::Stopped);
    let _ = std::fs::remove_dir_all(&tmp);
}

#[link(name = "c")]
extern "C" {
    #[link_name = "kill"]
    fn libc_kill(pid: i32, sig: i32) -> i32;
}
