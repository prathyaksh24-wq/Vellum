use serde::Serialize;
use tauri::webview::PageLoadEvent;
use tauri::{Manager, WebviewUrl, WebviewWindowBuilder, WindowEvent};

const VELLUM_FRONTEND_URL: &str = "http://127.0.0.1:5173/design-uploads/Vellum%20Default%20Re-designed.html?desktop=1";
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

    WebviewWindowBuilder::new(&app, "vellum", external_url(VELLUM_FRONTEND_URL)?)
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

fn conversation_window_target(conversation_id: &str) -> Result<(String, String), String> {
    let clean = conversation_id.trim();
    if clean.is_empty() || clean.len() > 160 || clean.chars().any(char::is_control) {
        return Err("invalid conversation ID".to_string());
    }
    let mut hash = 0xcbf29ce484222325_u64;
    for byte in clean.as_bytes() {
        hash ^= u64::from(*byte);
        hash = hash.wrapping_mul(0x100000001b3);
    }
    let encoded = clean
        .as_bytes()
        .iter()
        .map(|byte| {
            if byte.is_ascii_alphanumeric() || matches!(*byte, b'-' | b'_' | b'.' | b'~') {
                (*byte as char).to_string()
            } else {
                format!("%{byte:02X}")
            }
        })
        .collect::<String>();
    Ok((
        format!("conversation-{hash:016x}"),
        format!("{VELLUM_FRONTEND_URL}&conversation_id={encoded}"),
    ))
}

#[tauri::command]
fn open_conversation_window(app: tauri::AppHandle, conversation_id: String) -> Result<(), String> {
    let (label, url) = conversation_window_target(&conversation_id)?;
    if let Some(window) = app.get_webview_window(&label) {
        window.show().map_err(|err| err.to_string())?;
        window.set_focus().map_err(|err| err.to_string())?;
        return Ok(());
    }

    WebviewWindowBuilder::new(&app, &label, external_url(&url)?)
        .title("Vellum · Conversation")
        .inner_size(1120.0, 780.0)
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
        .invoke_handler(tauri::generate_handler![
            backend_health,
            open_vellum_window,
            open_conversation_window,
            set_overlay
        ])
        .on_window_event(|window, event| {
            if window.label() == "main" && matches!(event, WindowEvent::CloseRequested { .. }) {
                std::process::exit(0);
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running Vellum desktop");
}

#[cfg(test)]
mod tests {
    use super::conversation_window_target;

    #[test]
    fn conversation_window_target_is_stable_and_url_encoded() {
        let first = conversation_window_target("chat / one").unwrap();
        let second = conversation_window_target("chat / one").unwrap();

        assert_eq!(first, second);
        assert!(first.0.starts_with("conversation-"));
        assert!(first.1.ends_with("conversation_id=chat%20%2F%20one"));
    }

    #[test]
    fn conversation_window_target_rejects_empty_or_controlled_ids() {
        assert!(conversation_window_target(" ").is_err());
        assert!(conversation_window_target("chat\nother").is_err());
    }
}
