# 翻譯蒟蒻 Chrome 擴充(Phase 3)

側欄即時字幕 + 分頁錄音轉錄 + NotebookLM 轉發。需本地引擎(`127.0.0.1:8765`)。

## 安裝(開發版)

1. Chrome 開 `chrome://extensions` → 開「開發人員模式」
2. 「載入未封裝項目」→ 選 `extension/` 資料夾
3. 點工具列圖示開啟側欄

## 功能

| 功能 | 說明 |
|------|------|
| 字幕鏡像 | 桌面 App 錄製中 → 側欄即時鏡像雙語字幕(WS 連本地引擎) |
| 錄製此分頁 | tabCapture 錄 Meet/YouTube 等分頁音訊(錄音期間仍聽得到聲音),停止後上傳引擎 → Whisper 轉錄 + 雲端 LLM 翻譯 + 講者辨識 |
| ✨ 摘要 | 對目前 session 請求引擎摘要 |
| 📤 NotebookLM | 產生「摘要+逐字稿」payload → 複製剪貼簿 → 開 NotebookLM 顯示引導浮窗,並嘗試自動點「新增來源」(改版自動降級手動) |

## 架構備註

- 側欄為擴充頁面,`host_permissions` 直連本地引擎,不需引擎開 CORS 白名單。
- 分頁錄音採「整段錄完上傳」(離線管線),非逐句串流;真串流即時化為 Phase 3b
  (需引擎內建串流 ASR 端點)。
- NotebookLM 無消費者 API;自動化為 best-effort,剪貼簿 + 引導浮窗為穩定降級路徑。
