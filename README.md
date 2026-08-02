# 翻譯蒟蒻 🍡

多功能即時語音紀錄工具:**即時轉錄翻譯、離線音訊處理、講者辨識、AI 摘要,一套搞定,並轉發 NotebookLM**。

整合三個開源專案的優勢架構:
[jt-live-whisper](https://github.com/jasoncheng7115/jt-live-whisper)(全地端 AI 管線)+
[GPT-Typeless](https://github.com/cablate/GPT-Typeless)(Tauri 桌面體驗)+
[meeting-APP](https://github.com/jcservice999/meeting-APP)(瀏覽器協作思路)。

## 架構

```
本地引擎(FastAPI + SQLite,127.0.0.1:8765)
 ├─ ASR:jt-live-whisper 子程序橋接(faster-whisper CUDA / 講者辨識)
 ├─ 翻譯/校正/摘要:雲端 LLM API(Claude / GPT / Gemini / 自訂,Key 只存本機)
 ├─ 關鍵字通知、Webhook 轉發(TG/Slack/Discord)、保留天數清理
 └─ NotebookLM 最佳化 Markdown 匯出
桌面 App(Tauri 2 + React):即時字幕流、懸浮字幕、離線批次、紀錄庫、系統匣
Chrome 擴充(MV3):側欄字幕鏡像、分頁錄音轉錄、NotebookLM 轉發
```

## 目錄

| 路徑 | 說明 |
|------|------|
| [engine/](engine/README.md) | 本地引擎(Python)+ pytest 36 案例 + AI 基準線 |
| [desktop/](desktop/README.md) | Tauri 桌面 App + NSIS 打包(內含引擎 EXE) |
| [extension/](extension/README.md) | Chrome 擴充(免建置,載入資料夾即用) |
| 翻譯蒟蒻-系統規劃書.md | 三專案整合分析、架構、NotebookLM 三路徑、開發階段 |
| 翻譯蒟蒻-UI規劃書.html | 設計原則與全介面視覺稿 |
| 翻譯蒟蒻-測試規劃書.md | 雙軌測試策略(軟體測試 + AI 評測基準線) |

## 快速開始(開發)

```powershell
# 1. AI 管線(上游,含模型下載約 8GB)
git clone https://github.com/jasoncheng7115/jt-live-whisper vendor/jt-live-whisper
# 依 engine/README 的推薦安裝步驟建 vendor venv 與模型

# 2. 引擎
cd engine && python -m venv .venv && .venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m pytest tests -q   # 全 mock,不需 GPU

# 3. 桌面 App
cd desktop && npm install && npm run tauri dev
```

打包:`npm run tauri build` → NSIS 安裝檔(App + 引擎 EXE,約 19MB;AI 管線另裝,
自動偵測 `C:\jt-live-whisper` 或 `KONJAC_VENDOR_DIR`)。

## 授權

Apache License 2.0(沿用 jt-live-whisper);衍生與參考之上游授權聲明見各專案原始 repo。
