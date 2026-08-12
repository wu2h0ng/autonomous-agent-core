use std::process::{Command, Stdio};
use std::time::Duration;

fn main() {
    let root = "/Users/mima1234/Documents/AI-Agent-Projects/autonomous-agent-core/.worktrees/wave2a-macos-shell-20260812";
    let tmp = "/var/folders/w8/nnfxc0ts0137qnqfgwfh78qm0000gn/T/wave2a-example-probe";
    let _ = std::fs::remove_dir_all(tmp);
    std::fs::create_dir_all(tmp).unwrap();
    let pythonpath = format!("{root}:{root}/packages/contracts/src:{root}/packages/os_core/src");
    let mut child = Command::new("/Users/mima1234/.local/bin/python3")
        .arg("-m").arg("apps.runtime_daemon")
        .arg("--database").arg(format!("{tmp}/db.sqlite3"))
        .arg("--workspace").arg(tmp)
        .arg("--descriptor").arg(format!("{tmp}/runtime.json"))
        .arg("--host").arg("127.0.0.1").arg("--port").arg("0")
        .env("PYTHONPATH", pythonpath)
        .stdout(Stdio::piped()).stderr(Stdio::piped())
        .spawn()
        .expect("spawn failed");
    std::thread::sleep(Duration::from_secs(6));
    eprintln!("status: {:?}", child.try_wait().unwrap());
    let entries = std::fs::read_dir(tmp)
        .map(|it| it.filter_map(|e| e.ok()).map(|e| e.file_name().to_string_lossy().into_owned()).collect::<Vec<_>>())
        .unwrap_or_default();
    eprintln!("tmp: {:?}", entries);
    let _ = child.kill();
    let _ = child.wait();
}
