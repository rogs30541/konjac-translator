import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import OverlayView from "./views/OverlayView";
import "./styles.css";

/** 依 Tauri 視窗 label 路由:main → 主介面,overlay → 懸浮字幕。
 * 瀏覽器預覽用 #overlay hash 模擬。 */
async function resolveWindowLabel(): Promise<string> {
  try {
    const { getCurrentWindow } = await import("@tauri-apps/api/window");
    return getCurrentWindow().label;
  } catch {
    return window.location.hash === "#overlay" ? "overlay" : "main";
  }
}

resolveWindowLabel().then((label) => {
  if (label === "overlay") {
    document.documentElement.style.background = "transparent";
    document.body.style.background = "transparent";
  }
  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      {label === "overlay" ? <OverlayView /> : <App />}
    </React.StrictMode>,
  );
});
