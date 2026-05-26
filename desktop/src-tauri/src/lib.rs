use serde::Serialize;
use tauri::webview::PageLoadEvent;
use tauri::{Manager, WebviewUrl, WebviewWindowBuilder, WindowEvent};

const VELLUM_CHAT_URL: &str = "http://127.0.0.1:5173/ui/vellum-chat.html?desktop=1";
const DESKTOP_OVERLAY_DEV_URL: &str = "http://127.0.0.1:1420/overlay.html";

#[derive(Serialize)]
struct Health {
    ok: bool,
}

#[tauri::command]
fn backend_health() -> Health {
    let ok = ureq::get("http://127.0.0.1:8000/api/health")
        .timeout(std::time::Duration::from_secs(2))
        .call()
        .map(|response| response.status() == 200)
        .unwrap_or(false);
    Health { ok }
}

fn external_url(url: &str) -> Result<WebviewUrl, String> {
    Ok(WebviewUrl::External(
        url.parse().map_err(|err| format!("invalid desktop URL {url}: {err}"))?,
    ))
}

fn overlay_url() -> Result<WebviewUrl, String> {
    #[cfg(debug_assertions)]
    {
        external_url(DESKTOP_OVERLAY_DEV_URL)
    }
    #[cfg(not(debug_assertions))]
    {
        Ok(WebviewUrl::App("overlay.html".into()))
    }
}

#[tauri::command]
fn open_vellum_window(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(window) = app.get_webview_window("vellum") {
        window.show().map_err(|err| err.to_string())?;
        window.set_focus().map_err(|err| err.to_string())?;
        return Ok(());
    }

    WebviewWindowBuilder::new(&app, "vellum", external_url(VELLUM_CHAT_URL)?)
    .title("Vellum")
    .inner_size(1280.0, 820.0)
    .center()
    .visible(false)
    .on_page_load(|window, payload| {
        if matches!(payload.event(), PageLoadEvent::Finished) {
            let _ = window.show();
            let _ = window.set_focus();
        }
    })
    .build()
    .map_err(|err| err.to_string())?;
    Ok(())
}

#[tauri::command]
fn set_overlay(app: tauri::AppHandle, enabled: bool) -> Result<(), String> {
    if enabled {
        show_overlay(app)
    } else {
        if let Some(window) = app.get_webview_window("overlay") {
            window.close().map_err(|err| err.to_string())?;
        }
        Ok(())
    }
}

fn show_overlay(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(window) = app.get_webview_window("overlay") {
        window.set_ignore_cursor_events(true).map_err(|err| err.to_string())?;
        window.set_focusable(false).map_err(|err| err.to_string())?;
        window.show().map_err(|err| err.to_string())?;
        return Ok(());
    }

    let window = WebviewWindowBuilder::new(&app, "overlay", overlay_url()?)
        .title("Vellum Computer Use")
        .decorations(false)
        .transparent(true)
        .always_on_top(true)
        .focusable(false)
        .focused(false)
        .skip_taskbar(true)
        .fullscreen(true)
        .visible(false)
        .on_page_load(|window, payload| {
            if matches!(payload.event(), PageLoadEvent::Finished) {
                let _ = window.set_ignore_cursor_events(true);
                let _ = window.set_focusable(false);
                let _ = window.show();
            }
        })
        .build()
        .map_err(|err| err.to_string())?;
    window.set_ignore_cursor_events(true).map_err(|err| err.to_string())?;
    window.set_focusable(false).map_err(|err| err.to_string())?;
    Ok(())
}

pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![backend_health, open_vellum_window, set_overlay])
        .on_window_event(|window, event| {
            if window.label() == "main" && matches!(event, WindowEvent::CloseRequested { .. }) {
                std::process::exit(0);
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running Vellum desktop");
}
