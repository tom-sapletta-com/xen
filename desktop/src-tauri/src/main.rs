// xeen desktop — Tauri wrapper that spawns the Python server and opens a webview
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::TcpStream;
use std::process::{Command, Child};
use std::sync::Mutex;
use std::thread;
use std::time::Duration;

struct ServerProcess(Mutex<Option<Child>>);

fn start_python_server() -> Option<Child> {
    // Try 'xeen server --port 7600' first (installed via pip)
    let child = Command::new("xeen")
        .args(["server", "--port", "7600"])
        .spawn();

    match child {
        Ok(c) => {
            println!("[xeen-desktop] Server started (pid={})", c.id());
            Some(c)
        }
        Err(_) => {
            // Fallback: run via python -m
            println!("[xeen-desktop] 'xeen' not in PATH, trying python -m xeen.cli ...");
            match Command::new("python3")
                .args(["-m", "xeen.cli", "server", "--port", "7600"])
                .spawn()
            {
                Ok(c) => {
                    println!("[xeen-desktop] Server started via python3 (pid={})", c.id());
                    Some(c)
                }
                Err(e) => {
                    eprintln!("[xeen-desktop] Failed to start server: {}", e);
                    None
                }
            }
        }
    }
}

fn wait_for_server(addr: &str, timeout_secs: u64) -> bool {
    let start = std::time::Instant::now();
    while start.elapsed() < Duration::from_secs(timeout_secs) {
        if TcpStream::connect(addr).is_ok() {
            return true;
        }
        thread::sleep(Duration::from_millis(250));
    }
    false
}

fn main() {
    // Start the Python FastAPI server
    let server_child = start_python_server();

    // Wait for server to be ready (up to 10s)
    println!("[xeen-desktop] Waiting for server at 127.0.0.1:7600 ...");
    if !wait_for_server("127.0.0.1:7600", 10) {
        eprintln!("[xeen-desktop] Server did not start in time!");
    }

    let state = ServerProcess(Mutex::new(server_child));

    tauri::Builder::default()
        .manage(state)
        .setup(|_app| {
            // Server should be up by now
            println!("[xeen-desktop] Opening webview...");
            Ok(())
        })
        .on_window_event(|event| {
            if let tauri::WindowEvent::Destroyed = event.event() {
                // Kill the server when the window is closed
                let state: tauri::State<ServerProcess> = event.window().state();
                if let Ok(mut guard) = state.0.lock() {
                    if let Some(ref mut child) = *guard {
                        println!("[xeen-desktop] Stopping server (pid={})...", child.id());
                        let _ = child.kill();
                    }
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
