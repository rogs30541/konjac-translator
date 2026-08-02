# 翻譯蒟蒻 Desktop(Phase 2)

Tauri 2 桌面殼層(架構參考 GPT-Typeless):React 18 + TypeScript + Tailwind 前端、Rust 後端。
連本地引擎 `127.0.0.1:8765`(REST + WebSocket)。

## 開發

```powershell
cd desktop
npm install
npm run tauri dev   # 需要 Rust + MSVC Build Tools;會自動拉起引擎 sidecar
```

前端單獨開發(不編 Rust):`npm run dev` 後開 http://localhost:1420,
引擎需另外啟動(見 engine/README.md)。

## 已實作

- 主視窗三欄佈局(UI 規劃書 §01):導覽 + 引擎狀態 / 雙語字幕流 / 講者面板
- 字幕流:WebSocket 自動重連、seq 去重、streaming 游標、自動捲底、⭐ 標記
- 即時模式:開始/停止(`/api/live/start`)、翻譯模式與會議主題選擇、錄製計時
- 講者改名(即時同步)、產生摘要、匯出 MD、轉發 NotebookLM(引擎端 payload)
- Rust:引擎 sidecar(啟動拉起、退出終止、`restart_engine` 命令)、
  全域快捷鍵 Ctrl+Shift+R(emit `konjac://toggle-record` → 前端切換錄製)

- 懸浮字幕視窗:第二 WebView(label=overlay,透明/置頂/無邊框/隱藏啟動),
  依視窗 label 路由(瀏覽器預覽用 `#overlay` hash);自動跟隨進行中的 live session,
  hover 工具鈕(字級/原文開關/隱藏),`data-tauri-drag-region` 可拖曳;
  主視窗「🪟 懸浮字幕」切換顯示
- 離線處理頁:拖曳/批次上傳、模式與講者辨識選項、任務進度輪詢、完成後跳紀錄庫
- 紀錄庫頁:session 清單(含「已轉發 NBLM」徽章)、摘要置頂詳情、
  四格式匯出、講者改名、NotebookLM 轉發(可自訂筆記本名)
- 主視窗關閉 = App 整體退出(修掉隱藏 overlay 讓程序殘留的 bug)

- 設定頁:雲端 LLM(Claude/GPT/Gemini/自訂)+ 關鍵字通知 + Webhook 轉發 + 保留天數
- 系統匣常駐:關窗縮到系統匣(引擎續跑供 Chrome 擴充),選單=開主視窗/懸浮字幕/結束
- NotebookLM 轉發對話框:筆記本、範圍(全部/僅摘要/僅標記)、Markdown 即時預覽
- 摘要模板:一般會議/訪談/課程/客服

## 打包(EXE)

`npm run tauri build` → `src-tauri\target\release\bundle\nsis\翻譯蒟蒻_0.1.0_x64-setup.exe`(約 19MB):
- 內含 `konjac-engine.exe`(PyInstaller,引擎完整 API,不需 Python 環境)
- App 啟動優先用同目錄捆綁引擎;開發環境自動退回 engine/.venv
- 結束時以 taskkill /T 終止引擎程序樹(PyInstaller onefile 雙層程序)
- **AI 管線(Whisper/講者辨識)另需 jt-live-whisper**:裝在 `C:\jt-live-whisper`
  (上游一鍵安裝預設位置)自動偵測,或設環境變數 `KONJAC_VENDOR_DIR` 指向;
  未安裝時引擎照常運作(健康檢查 `vendor_available:false`),僅無法轉錄。
- 重打包引擎:`engine\.venv\Scripts\pyinstaller --onefile --name konjac-engine
  --collect-submodules uvicorn --collect-submodules websockets --hidden-import app.main serve.py`
  後複製到 `src-tauri\binaries\konjac-engine-x86_64-pc-windows-msvc.exe`

## 待做
- Chrome 擴充真串流即時化(Phase 3b,需引擎串流 ASR 端點)
- pyannote 講者升級(需 HF token)、Supabase 多人同步(選配)
