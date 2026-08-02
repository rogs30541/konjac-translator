//! 翻譯蒟蒻桌面殼層:引擎 sidecar 生命週期 + 全域快捷鍵。
use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::Mutex;

use tauri::menu::{Menu, MenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::{Emitter, Manager, RunEvent};
use tauri_plugin_global_shortcut::{Code, Modifiers, Shortcut, ShortcutState};

struct EngineProc(Mutex<Option<Child>>);

/// PyInstaller onefile 是 bootstrap+子程序兩層,child.kill() 只殺得到父層,
/// Windows 上必須用 taskkill /T 終止整棵程序樹。
fn kill_engine_tree(child: &mut Child) {
    let pid = child.id();
    let _ = Command::new("taskkill")
        .args(["/PID", &pid.to_string(), "/T", "/F"])
        .status();
    let _ = child.wait();
}

/// 開發模式下引擎位於 repo 的 engine/(desktop/src-tauri 的上上層)。
/// 打包版改用 KONJAC_ENGINE_DIR 環境變數或安裝器內附路徑。
fn engine_dir() -> PathBuf {
    if let Ok(dir) = std::env::var("KONJAC_ENGINE_DIR") {
        return PathBuf::from(dir);
    }
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(|p| p.parent())
        .map(|p| p.join("engine"))
        .unwrap_or_default()
}

fn spawn_engine() -> std::io::Result<Child> {
    // 打包版:同目錄的 konjac-engine.exe(tauri externalBin);
    // 開發版:engine/.venv 的 uvicorn
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            let bundled = dir.join("konjac-engine.exe");
            if bundled.is_file() {
                return Command::new(bundled).spawn();
            }
        }
    }
    let dir = engine_dir();
    let python = dir.join(".venv").join("Scripts").join("python.exe");
    Command::new(python)
        .args([
            "-m", "uvicorn", "app.main:create_app", "--factory",
            "--host", "127.0.0.1", "--port", "8765",
        ])
        .current_dir(&dir)
        .spawn()
}

#[tauri::command]
fn engine_status(state: tauri::State<EngineProc>) -> String {
    let mut guard = state.0.lock().unwrap();
    match guard.as_mut() {
        Some(child) => match child.try_wait() {
            Ok(None) => "running".into(),
            Ok(Some(code)) => format!("exited: {code}"),
            Err(e) => format!("error: {e}"),
        },
        None => "not-started".into(),
    }
}

#[tauri::command]
fn restart_engine(state: tauri::State<EngineProc>) -> Result<String, String> {
    let mut guard = state.0.lock().unwrap();
    if let Some(child) = guard.as_mut() {
        kill_engine_tree(child);
    }
    match spawn_engine() {
        Ok(child) => {
            *guard = Some(child);
            Ok("restarted".into())
        }
        Err(e) => Err(format!("spawn failed: {e}")),
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(EngineProc(Mutex::new(None)))
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(|app, shortcut, event| {
                    // Ctrl+Shift+R:開始/停止錄製(交給前端執行)
                    if event.state() == ShortcutState::Pressed
                        && shortcut.matches(Modifiers::CONTROL | Modifiers::SHIFT, Code::KeyR)
                    {
                        let _ = app.emit("konjac://toggle-record", ());
                    }
                })
                .build(),
        )
        .invoke_handler(tauri::generate_handler![engine_status, restart_engine])
        .on_window_event(|window, event| {
            // 主視窗關閉 = 縮到系統匣(引擎續跑,供 Chrome 擴充使用);
            // 真正結束走系統匣選單「結束」
            if window.label() == "main" {
                if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                    api.prevent_close();
                    let _ = window.hide();
                }
            }
        })
        .setup(|app| {
            // 引擎 sidecar:App 啟動即拉起(已在跑則 uvicorn 綁埠失敗自然退出)
            let state = app.state::<EngineProc>();
            if let Ok(child) = spawn_engine() {
                *state.0.lock().unwrap() = Some(child);
            }
            // 註冊全域快捷鍵
            use tauri_plugin_global_shortcut::GlobalShortcutExt;
            let toggle = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::SHIFT), Code::KeyR);
            let _ = app.global_shortcut().register(toggle);

            // 系統匣:開啟主視窗 / 懸浮字幕 / 結束
            let item_show = MenuItem::with_id(app, "show", "開啟主視窗", true, None::<&str>)?;
            let item_overlay = MenuItem::with_id(app, "overlay", "懸浮字幕開/關", true, None::<&str>)?;
            let item_quit = MenuItem::with_id(app, "quit", "結束(含引擎)", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&item_show, &item_overlay, &item_quit])?;
            TrayIconBuilder::with_id("konjac-tray")
                .icon(app.default_window_icon().unwrap().clone())
                .tooltip("翻譯蒟蒻(引擎執行中)")
                .menu(&menu)
                .show_menu_on_left_click(true)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "show" => {
                        if let Some(w) = app.get_webview_window("main") {
                            let _ = w.show();
                            let _ = w.set_focus();
                        }
                    }
                    "overlay" => {
                        if let Some(w) = app.get_webview_window("overlay") {
                            if w.is_visible().unwrap_or(false) {
                                let _ = w.hide();
                            } else {
                                let _ = w.show();
                            }
                        }
                    }
                    "quit" => app.exit(0),
                    _ => {}
                })
                .build(app)?;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            // App 結束時終止引擎程序樹
            if let RunEvent::Exit = event {
                if let Some(child) = app.state::<EngineProc>().0.lock().unwrap().as_mut() {
                    kill_engine_tree(child);
                }
            }
        });
}
