//! Desktop shell: owns the window and the Python processing backend.
//!
//! The backend listens on 127.0.0.1 with a random per-launch token. Its stdin
//! stays open for the lifetime of the app; when the shell exits (or crashes)
//! stdin closes and the backend shuts itself down.

use serde::Serialize;
use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::{Arc, Mutex};
use tauri::{Emitter, Manager, RunEvent};

#[derive(Clone, Serialize, Default)]
struct BackendInfo {
    state: String, // starting | ready | failed
    port: u16,
    token: String,
    error: String,
    log: String,
}

#[derive(Default)]
struct Backend {
    info: BackendInfo,
    child: Option<Child>,
    stdin: Option<ChildStdin>,
}

type Shared = Arc<Mutex<Backend>>;

fn token() -> String {
    let mut bytes = [0u8; 24];
    getrandom::getrandom(&mut bytes).expect("system random source");
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

/// Packaged layout: <resources>/backend/{python,app,bin}. Development: the repo venv.
fn packaged_root(app: &tauri::AppHandle) -> Option<PathBuf> {
    let root = app.path().resource_dir().ok()?.join("backend");
    root.join("app").join("studio_backend.py").is_file().then_some(root)
}

fn backend_command(app: &tauri::AppHandle) -> Result<(PathBuf, PathBuf, PathBuf), String> {
    if let (Ok(python), Ok(script)) = (
        std::env::var("VISOMASTER_BACKEND_PYTHON"),
        std::env::var("VISOMASTER_BACKEND_SCRIPT"),
    ) {
        let script = PathBuf::from(script);
        let cwd = script.parent().map(PathBuf::from).unwrap_or_default();
        return Ok((PathBuf::from(python), script, cwd));
    }
    if let Ok(resources) = app.path().resource_dir() {
        let root = resources.join("backend");
        let python = if cfg!(windows) {
            root.join("python").join("python.exe")
        } else {
            root.join("python").join("bin").join("python3")
        };
        let script = root.join("app").join("studio_backend.py");
        if python.is_file() && script.is_file() {
            return Ok((python, script, root.join("app")));
        }
    }
    let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let python = if cfg!(windows) {
        repo.join(".venv-studio").join("Scripts").join("python.exe")
    } else {
        repo.join(".venv-studio").join("bin").join("python")
    };
    let script = repo.join("studio_backend.py");
    if python.is_file() && script.is_file() {
        return Ok((python, script, repo));
    }
    Err("找不到处理组件，请重新安装应用".into())
}

fn start_backend(app: tauri::AppHandle, shared: Shared) {
    let token = token();
    let log_path = app
        .path()
        .app_log_dir()
        .map(|d| {
            let _ = std::fs::create_dir_all(&d);
            d.join("backend.log")
        })
        .unwrap_or_else(|_| std::env::temp_dir().join("visomaster-backend.log"));
    {
        let mut b = shared.lock().unwrap();
        b.info = BackendInfo {
            state: "starting".into(),
            token: token.clone(),
            log: log_path.display().to_string(),
            ..Default::default()
        };
    }
    let fail = |shared: &Shared, app: &tauri::AppHandle, message: String| {
        let mut b = shared.lock().unwrap();
        b.info.state = "failed".into();
        b.info.error = message;
        let _ = app.emit("backend", b.info.clone());
    };
    let (python, script, cwd) = match backend_command(&app) {
        Ok(cmd) => cmd,
        Err(message) => return fail(&shared, &app, message),
    };
    let log = match std::fs::File::create(&log_path) {
        Ok(f) => Stdio::from(f),
        Err(_) => Stdio::null(),
    };
    let mut command = Command::new(&python);
    if let Some(root) = packaged_root(&app) {
        // Bundled FFmpeg first; ignore PYTHON* variables and user site-packages.
        let path = std::env::var("PATH").unwrap_or_default();
        let sep = if cfg!(windows) { ";" } else { ":" };
        command.env("PATH", format!("{}{}{}", root.join("bin").display(), sep, path));
        command.arg("-E").arg("-s").arg("-B");
    }
    command
        .arg("-u")
        .arg(&script)
        .current_dir(&cwd)
        .env("VISOMASTER_BACKEND_TOKEN", &token)
        .env("PYTHONIOENCODING", "utf-8")
        .env("PYTHONDONTWRITEBYTECODE", "1")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(log);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    let mut child = match command.spawn() {
        Ok(child) => child,
        Err(err) => return fail(&shared, &app, format!("无法启动处理组件：{err}")),
    };
    let stdout = child.stdout.take();
    {
        let mut b = shared.lock().unwrap();
        b.stdin = child.stdin.take();
        b.child = Some(child);
    }
    std::thread::spawn(move || {
        let Some(stdout) = stdout else {
            return fail(&shared, &app, "处理组件没有输出".into());
        };
        let mut lines = BufReader::new(stdout).lines();
        while let Some(Ok(line)) = lines.next() {
            if let Some(json) = line.strip_prefix("VISOMASTER_BACKEND ") {
                let port = serde_json::from_str::<serde_json::Value>(json)
                    .ok()
                    .and_then(|v| v.get("port").and_then(|p| p.as_u64()))
                    .unwrap_or(0) as u16;
                let mut b = shared.lock().unwrap();
                if port == 0 {
                    b.info.state = "failed".into();
                    b.info.error = "处理组件启动失败".into();
                } else {
                    b.info.state = "ready".into();
                    b.info.port = port;
                }
                let _ = app.emit("backend", b.info.clone());
                break;
            }
        }
        // Keep draining so the backend never blocks on a full stdout pipe.
        for _ in lines {}
        let mut b = shared.lock().unwrap();
        let exited = b.child.as_mut().and_then(|c| c.try_wait().ok().flatten());
        if b.info.state != "failed" {
            b.info.state = "failed".into();
            b.info.error = match exited {
                Some(status) => format!("处理组件已退出（{status}）"),
                None => "处理组件已停止响应".into(),
            };
            let _ = app.emit("backend", b.info.clone());
        }
    });
}

fn stop_backend(shared: &Shared) {
    let mut b = shared.lock().unwrap();
    b.stdin.take(); // closing stdin asks the backend to exit
    if let Some(mut child) = b.child.take() {
        for _ in 0..30 {
            if let Ok(Some(_)) = child.try_wait() {
                return;
            }
            std::thread::sleep(std::time::Duration::from_millis(100));
        }
        let _ = child.kill();
        let _ = child.wait();
    }
}

#[tauri::command]
fn backend_info(state: tauri::State<Shared>) -> BackendInfo {
    state.lock().unwrap().info.clone()
}

#[tauri::command]
fn restart_backend(app: tauri::AppHandle, state: tauri::State<Shared>) -> BackendInfo {
    let shared = state.inner().clone();
    stop_backend(&shared);
    start_backend(app, shared.clone());
    let info = shared.lock().unwrap().info.clone();
    info
}

pub fn run() {
    let shared: Shared = Arc::new(Mutex::new(Backend::default()));
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(shared.clone())
        .invoke_handler(tauri::generate_handler![backend_info, restart_backend])
        .setup(|app| {
            let shared = app.state::<Shared>().inner().clone();
            start_backend(app.handle().clone(), shared);
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building VisoMaster Studio");
    app.run(move |_, event| {
        if let RunEvent::Exit = event {
            stop_backend(&shared);
        }
    });
}
