// Prevents additional console window on Windows in release
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::process::{Child, Command};
use std::sync::Mutex;
use tauri::{Manager, State, SystemTrayEvent};
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
    open::that(&url).map_err(|e| e.to_string())
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
    let updater = app.updater();
    let response = updater.check().await.map_err(|e| e.to_string())?;
    if response.is_update_available() {
        Ok(Some(UpdateInfo {
            version: response.latest_version().to_string(),
            date: response.date().map(|d| d.to_string()),
            body: response.body().cloned(),
        }))
    } else {
        Ok(None)
    }
}

#[tauri::command]
async fn install_update(app: tauri::AppHandle) -> Result<(), String> {
    let updater = app.updater();
    let response = updater.check().await.map_err(|e| e.to_string())?;
    response.download_and_install().await.map_err(|e| e.to_string())?;
    Ok(())
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
        .setup(|app| {
            use tauri::{
                CustomMenuItem, SystemTray, SystemTrayMenu,
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

#[cfg(test)]
mod tests {
    use super::*;
    use tauri::test::{mock_builder, MockRuntime};

    fn make_app() -> tauri::App<MockRuntime> {
        mock_builder()
            .manage(ServerProcess(Mutex::new(None)))
            .manage(Mutex::new(ServerSettings::default()))
            .build(tauri::generate_context!())
            .unwrap()
    }

    #[test]
    fn test_server_settings_default() {
        let s = ServerSettings::default();
        assert_eq!(s.port, 8080);
        assert!(s.auto_start);
    }

    #[test]
    fn test_get_server_status_not_running() {
        let app = make_app();
        let status = get_server_status(app.state::<ServerProcess>());
        assert!(!status.running);
        assert!(status.process_id.is_none());
        assert_eq!(status.port, 8080);
    }

    #[test]
    fn test_get_settings_defaults() {
        let app = make_app();
        let settings = get_settings(app.state::<Mutex<ServerSettings>>());
        assert_eq!(settings.port, 8080);
        assert_eq!(settings.python_path, "python");
        assert!(settings.auto_start);
    }

    #[test]
    fn test_update_settings() {
        let app = make_app();
        let new_settings = ServerSettings {
            python_path: "python3".into(),
            port: 9090,
            auto_start: false,
        };
        let result = update_settings(app.state::<Mutex<ServerSettings>>(), new_settings);
        assert!(result.is_ok());

        let updated = get_settings(app.state::<Mutex<ServerSettings>>());
        assert_eq!(updated.port, 9090);
        assert_eq!(updated.python_path, "python3");
        assert!(!updated.auto_start);
    }

    #[test]
    fn test_server_status_serialization() {
        let s = ServerStatus {
            running: true,
            port: 8080,
            process_id: Some(12345),
            error: None,
        };
        let json = serde_json::to_string(&s).unwrap();
        assert!(json.contains("running"));
        assert!(json.contains("8080"));
        assert!(json.contains("12345"));
    }

    #[test]
    fn test_update_info_serialization() {
        let info = UpdateInfo {
            version: "1.0.0".into(),
            date: Some("2026-07-04".into()),
            body: Some("Bug fixes".into()),
        };
        let json = serde_json::to_string(&info).unwrap();
        assert!(json.contains("1.0.0"));
        assert!(json.contains("2026-07-04"));
    }

    #[test]
    fn test_vault_commands_urls() {
        let settings = ServerSettings::default();
        let assert_url = |path: &str, expected: &str| {
            let url = format!("http://localhost:{}{}", settings.port, path);
            assert_eq!(url, expected);
        };
        assert_url("/api/vault/keys", "http://localhost:8080/api/vault/keys");
        assert_url("/api/vault/keys/exa", "http://localhost:8080/api/vault/keys/exa");
        assert_url("/api/enrich/lead", "http://localhost:8080/api/enrich/lead");
        assert_url("/api/enrich/providers", "http://localhost:8080/api/enrich/providers");
        assert_url("/api/enrich/batch", "http://localhost:8080/api/enrich/batch");
    }
}

#[cfg(feature = "integration-tests")]
mod integration {
    const TEST_PORT: u16 = 8081;

    async fn start_backend() -> tokio::process::Child {
        let project_root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .and_then(|p| p.parent())
            .map(|p| p.join("main.py"))
            .unwrap();

        let child = tokio::process::Command::new("python")
            .arg(project_root)
            .env("PORT", TEST_PORT.to_string())
            .env("EXA_API_KEY", "")
            .env("PERPLEXITY_API_KEY", "")
            .spawn()
            .expect("Failed to start Python backend");

        tokio::time::sleep(std::time::Duration::from_secs(3)).await;
        child
    }

    #[tokio::test]
    async fn test_vault_list_keys_integration() {
        let mut child = start_backend().await;
        let client = reqwest::Client::new();

        let resp = client
            .get(format!("http://localhost:{}/api/vault/keys", TEST_PORT))
            .send()
            .await
            .expect("GET /api/vault/keys failed");
        assert!(resp.status().is_success());
        let data: serde_json::Value = resp.json().await.unwrap();
        assert!(data.is_object());
        assert!(data.get("exa").is_some());

        child.kill().await.expect("Failed to stop backend");
    }

    #[tokio::test]
    async fn test_vault_set_key_integration() {
        let mut child = start_backend().await;
        let client = reqwest::Client::new();

        let resp = client
            .post(format!("http://localhost:{}/api/vault/keys/exa", TEST_PORT))
            .json(&serde_json::json!({"key": "test_key_123"}))
            .send()
            .await
            .expect("POST /api/vault/keys/exa failed");
        assert!(resp.status().is_success());
        let data: serde_json::Value = resp.json().await.unwrap();
        assert_eq!(data["ok"], true);

        child.kill().await.expect("Failed to stop backend");
    }

    #[tokio::test]
    async fn test_enrich_providers_integration() {
        let mut child = start_backend().await;
        let client = reqwest::Client::new();

        let resp = client
            .get(format!("http://localhost:{}/api/enrich/providers", TEST_PORT))
            .send()
            .await
            .expect("GET /api/enrich/providers failed");
        assert!(resp.status().is_success());

        child.kill().await.expect("Failed to stop backend");
    }
}
