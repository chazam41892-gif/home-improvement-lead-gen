// Prevents additional console window on Windows in release
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::process::{Child, Command};
use std::sync::Mutex;
use tauri::{Manager, State};
use serde::{Serialize, Deserialize};

struct ServerProcess(Mutex<Option<Child>>);

#[derive(Serialize, Deserialize, Clone)]
struct ServerSettings {
    python_path: String,
    port: u16,
    auto_start: bool,
}

#[derive(Serialize, Clone)]
struct ServerStatus {
    running: bool,
    port: u16,
    process_id: Option<u32>,
    error: Option<String>,
}

impl Default for ServerSettings {
    fn default() -> Self {
        Self {
            python_path: "python".to_string(),
            port: 8080,
            auto_start: true,
        }
    }
}

#[tauri::command]
fn start_server(state: State<ServerProcess>, settings: State<Mutex<ServerSettings>>) -> Result<ServerStatus, String> {
    let mut proc = state.0.lock().map_err(|e| e.to_string())?;

    if let Some(ref mut child) = *proc {
        let _ = child.kill();
        let _ = child.wait();
    }

    let settings = settings.lock().map_err(|e| e.to_string())?;
    let project_dir = std::env::current_dir()
        .map_err(|e| e.to_string())?
        .parent()
        .and_then(|p| p.parent())
        .map(|p| p.to_path_buf())
        .unwrap_or_default();

    let main_py = project_dir.join("main.py");
    if !main_py.exists() {
        return Err(format!("main.py not found at {:?}", main_py));
    }

    match Command::new(&settings.python_path)
        .arg(&main_py)
        .current_dir(&project_dir)
        .env("PORT", settings.port.to_string())
        .spawn()
    {
        Ok(child) => {
            let pid = child.id();
            *proc = Some(child);
            Ok(ServerStatus {
                running: true,
                port: settings.port,
                process_id: Some(pid),
                error: None,
            })
        }
        Err(e) => Err(format!("Failed to start server: {}", e)),
    }
}

#[tauri::command]
fn stop_server(state: State<ServerProcess>) -> Result<(), String> {
    let mut proc = state.0.lock().map_err(|e| e.to_string())?;
    if let Some(ref mut child) = *proc {
        child.kill().map_err(|e| e.to_string())?;
        child.wait().map_err(|e| e.to_string())?;
        *proc = None;
    }
    Ok(())
}

#[tauri::command]
fn get_server_status(state: State<ServerProcess>) -> ServerStatus {
    let proc = state.0.lock().ok();
    match proc {
        Some(ref guard) if guard.is_some() => {
            let child = guard.as_ref().unwrap();
            ServerStatus {
                running: true,
                port: 8080,
                process_id: Some(child.id()),
                error: None,
            }
        }
        _ => ServerStatus {
            running: false,
            port: 8080,
            process_id: None,
            error: None,
        },
    }
}

#[tauri::command]
fn get_settings(state: State<Mutex<ServerSettings>>) -> ServerSettings {
    state.lock().map(|s| s.clone()).unwrap_or_default()
}

#[tauri::command]
fn update_settings(state: State<Mutex<ServerSettings>>, settings: ServerSettings) -> Result<(), String> {
    let mut s = state.lock().map_err(|e| e.to_string())?;
    *s = settings;
    Ok(())
}

#[tauri::command]
fn open_dashboard(port: u16) -> Result<(), String> {
    let url = format!("http://localhost:{}", port);
    tauri::api::shell::open(&tauri::api::shell::Shell::default(), &url, None)
        .map_err(|e| e.to_string())
}

#[tauri::command]
async fn discover_trades(trade: String, location: String, settings: State<'_, Mutex<ServerSettings>>) -> Result<String, String> {
    let port = settings.lock().map_err(|e| e.to_string())?.port;
    let client = reqwest::Client::new();
    let body = serde_json::json!({ "trade": trade, "location": location });
    let resp = client
        .post(format!("http://localhost:{}/api/trades/discover", port))
        .json(&body)
        .send()
        .await
        .map_err(|e| format!("Request failed: {}", e))?;
    resp.text().await.map_err(|e| format!("Read failed: {}", e))
}

#[tauri::command]
async fn get_revenue(settings: State<'_, Mutex<ServerSettings>>) -> Result<String, String> {
    let port = settings.lock().map_err(|e| e.to_string())?.port;
    let resp = reqwest::get(format!("http://localhost:{}/api/trades/revenue", port))
        .await
        .map_err(|e| format!("Request failed: {}", e))?;
    resp.text().await.map_err(|e| format!("Read failed: {}", e))
}

#[derive(Serialize)]
struct UpdateInfo {
    version: String,
    date: Option<String>,
    body: Option<String>,
}

#[tauri::command]
async fn check_update(app: tauri::AppHandle) -> Result<Option<UpdateInfo>, String> {
    let updater = app.updater().map_err(|e| e.to_string())?;
    let response = updater.check().await.map_err(|e| e.to_string())?;
    if let Some(update) = response {
        Ok(Some(UpdateInfo {
            version: update.version,
            date: update.date,
            body: update.body,
        }))
    } else {
        Ok(None)
    }
}

#[tauri::command]
async fn install_update(app: tauri::AppHandle) -> Result<(), String> {
    let updater = app.updater().map_err(|e| e.to_string())?;
    let response = updater.check().await.map_err(|e| e.to_string())?;
    if let Some(update) = response {
        update.download_and_install().await.map_err(|e| e.to_string())?;
        Ok(())
    } else {
        Err("No update available".to_string())
    }
}

#[tauri::command]
async fn get_vault_keys(settings: State<'_, Mutex<ServerSettings>>) -> Result<String, String> {
    let port = settings.lock().map_err(|e| e.to_string())?.port;
    let client = reqwest::Client::new();
    let resp = client
        .get(format!("http://localhost:{}/api/vault/keys", port))
        .send()
        .await
        .map_err(|e| format!("Request failed: {}", e))?;
    resp.text().await.map_err(|e| format!("Read failed: {}", e))
}

#[tauri::command]
async fn set_vault_key(service: String, key: String, settings: State<'_, Mutex<ServerSettings>>) -> Result<String, String> {
    let port = settings.lock().map_err(|e| e.to_string())?.port;
    let client = reqwest::Client::new();
    let body = serde_json::json!({"key": key});
    let resp = client
        .post(format!("http://localhost:{}/api/vault/keys/{}", port, service))
        .json(&body)
        .send()
        .await
        .map_err(|e| format!("Request failed: {}", e))?;
    resp.text().await.map_err(|e| format!("Read failed: {}", e))
}

#[tauri::command]
async fn delete_vault_key(service: String, settings: State<'_, Mutex<ServerSettings>>) -> Result<String, String> {
    let port = settings.lock().map_err(|e| e.to_string())?.port;
    let client = reqwest::Client::new();
    let resp = client
        .delete(format!("http://localhost:{}/api/vault/keys/{}", port, service))
        .send()
        .await
        .map_err(|e| format!("Request failed: {}", e))?;
    resp.text().await.map_err(|e| format!("Read failed: {}", e))
}

#[tauri::command]
async fn get_enrich_providers(settings: State<'_, Mutex<ServerSettings>>) -> Result<String, String> {
    let port = settings.lock().map_err(|e| e.to_string())?.port;
    let client = reqwest::Client::new();
    let resp = client
        .get(format!("http://localhost:{}/api/enrich/providers", port))
        .send()
        .await
        .map_err(|e| format!("Request failed: {}", e))?;
    resp.text().await.map_err(|e| format!("Read failed: {}", e))
}

#[tauri::command]
async fn enrich_lead(business_name: String, trade: String, location: String, settings: State<'_, Mutex<ServerSettings>>) -> Result<String, String> {
    let port = settings.lock().map_err(|e| e.to_string())?.port;
    let client = reqwest::Client::new();
    let body = serde_json::json!({"business_name": business_name, "trade": trade, "location": location});
    let resp = client
        .post(format!("http://localhost:{}/api/enrich/lead", port))
        .json(&body)
        .send()
        .await
        .map_err(|e| format!("Request failed: {}", e))?;
    resp.text().await.map_err(|e| format!("Read failed: {}", e))
}

fn main() {
    let settings = Mutex::new(ServerSettings::default());

    tauri::Builder::default()
        .manage(ServerProcess(Mutex::new(None)))
        .manage(settings)
        .plugin(tauri_plugin_updater::Builder::default().build())
        .setup(|app| {
            use tauri::{
                CustomMenuItem, SystemTray, SystemTrayEvent, SystemTrayMenu,
            };

            let open_item = CustomMenuItem::new("open".to_string(), "Open Dashboard");
            let start_item = CustomMenuItem::new("start".to_string(), "Start Server");
            let stop_item = CustomMenuItem::new("stop".to_string(), "Stop Server");
            let quit_item = CustomMenuItem::new("quit".to_string(), "Quit");

            let tray_menu = SystemTrayMenu::new()
                .add_item(open_item)
                .add_item(start_item)
                .add_item(stop_item)
                .add_native_item(tauri::SystemTrayMenuItem::Separator)
                .add_item(quit_item);

            let tray = SystemTray::new().with_menu(tray_menu);
            app.manage(tray);

            Ok(())
        })
        .on_system_tray_event(|app, event| {
            match event {
                SystemTrayEvent::MenuItemClick { id, .. } => {
                    match id.as_str() {
                        "open" => {
                            if let Some(window) = app.get_window("main") {
                                let _ = window.show();
                                let _ = window.set_focus();
                            }
                        }
                        "start" => {
                            let state: State<ServerProcess> = app.state();
                            let settings_state: State<Mutex<ServerSettings>> = app.state();
                            let _ = start_server(state, settings_state);
                        }
                        "stop" => {
                            let state: State<ServerProcess> = app.state();
                            let _ = stop_server(state);
                        }
                        "quit" => {
                            let state: State<ServerProcess> = app.state();
                            let _ = stop_server(state);
                            app.exit(0);
                        }
                        _ => {}
                    }
                }
                _ => {}
            }
        })
        .invoke_handler(tauri::generate_handler![
            start_server,
            stop_server,
            get_server_status,
            get_settings,
            update_settings,
            open_dashboard,
            discover_trades,
            get_revenue,
            check_update,
            install_update,
            get_vault_keys,
            set_vault_key,
            delete_vault_key,
            get_enrich_providers,
            enrich_lead,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
