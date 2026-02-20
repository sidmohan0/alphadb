use std::net::TcpStream;
use std::process::{Child, Command};
use std::sync::Mutex;

struct ServerProcess(Mutex<Option<Child>>);

impl Drop for ServerProcess {
    fn drop(&mut self) {
        if let Some(mut child) = self.0.lock().unwrap().take() {
            let _ = child.kill();
        }
    }
}

fn server_running() -> bool {
    TcpStream::connect("127.0.0.1:8787").is_ok()
}

fn main() {
    let project_root = std::env::current_dir()
        .unwrap()
        .parent()
        .map(|p| p.to_path_buf())
        .unwrap_or_else(|| std::env::current_dir().unwrap());

    let server_script = project_root.join("dashboard-server.py");

    // Only start the server if it's not already running
    let child = if !server_running() {
        let c = Command::new("python3")
            .arg(&server_script)
            .current_dir(&project_root)
            .spawn()
            .expect("Failed to start dashboard-server.py");
        std::thread::sleep(std::time::Duration::from_millis(800));
        Some(c)
    } else {
        None
    };

    let server = ServerProcess(Mutex::new(child));

    tauri::Builder::default()
        .manage(server)
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
