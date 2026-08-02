# 翻譯蒟蒻 Engine(Phase 1)

本地核心引擎:FastAPI(REST + WebSocket)+ SQLite。桌面 App、Chrome 擴充、WebUI 三端共用。
預設只綁 `127.0.0.1:8765`。

## 啟動

```powershell
cd engine
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8765
```

測試:`.\.venv\Scripts\python -m pytest tests -q`(全 mock,不需 GPU/模型)

## 架構

```
app/
  main.py       # FastAPI 路由(sessions / ingest / export / forward / offline / ws)
  models.py     # Pydantic schemas(Session/Caption/Speaker/WsEvent…)
  db.py         # SQLite 紀錄層(Store)
  hub.py        # WebSocket 廣播 hub(每 session 一頻道)
  export.py     # md(NotebookLM 最佳化)/ txt / srt / vtt
  providers/
    base.py     # LivePipeline / OfflinePipeline / Summarizer 介面
    mock.py     # 確定性 mock(CI 用)
    jt_bridge.py# 子程序橋接:TCP server 接收上游 --webui 的 NDJSON 事件
  live.py       # LiveRunner/LiveManager:橋接事件 → Caption/WsEvent
tests/          # pytest,23 案例(fake_jt.py 模擬上游協定,免模型)
```

## API 摘要

| Method | Path | 說明 |
|--------|------|------|
| GET | `/api/health` | 引擎狀態與 provider |
| POST | `/api/sessions` | 建立 session(live/offline, mode, topic) |
| GET | `/api/sessions` `/api/sessions/{id}` | 清單 / 詳情(含講者、摘要) |
| POST | `/api/sessions/{id}/stop` | 結束錄製 |
| POST | `/api/sessions/{id}/ingest` | 管線推入字幕(partial/final 同 seq upsert) |
| GET | `/api/sessions/{id}/captions` | 字幕列表(`final_only`) |
| POST | `/api/sessions/{id}/captions/{seq}/star` | 標記重點 |
| PATCH | `/api/sessions/{id}/speakers/{sid}` | 講者改名(全文/匯出同步) |
| POST | `/api/sessions/{id}/summary` | 產生 AI 摘要 |
| GET | `/api/sessions/{id}/export?format=md\|txt\|srt\|vtt` | 匯出 |
| POST | `/api/sessions/{id}/forward/notebooklm` | 產生轉發 payload + 防重複(409/force) |
| POST | `/api/offline/jobs` | 上傳音檔批次處理(202 + job 輪詢) |
| GET | `/api/search?q=` | 全文搜尋 |
| WS | `/ws/sessions/{id}` | 字幕流(caption/speaker/status/summary);重連補發 final |

## 設計要點

- **ingest 是管線唯一入口**:真實 ASR provider 與測試走同一條路,WebSocket 測試因此完全確定性。
- **partial/final 同 seq upsert**:資料庫無重複字幕,重連補發只送 final。
- **NotebookLM payload 由引擎產生、傳送由前端執行**(Chrome 擴充/Enterprise API),引擎記錄轉發狀態防重複。
- **Provider 邊界**(`providers/base.py`):Phase 1b 在此接 jt-live-whisper(參考其 webui.py 的子程序 + TCP 事件橋接),之後逐步原生移植。

| POST | `/api/live/start` | 啟動 jt 橋接即時錄製(同時僅一場,409) |
| GET/PUT | `/api/settings` | 雲端 LLM 設定(provider/key/model;key 遮罩回傳、只存本機) |
| POST | `/api/settings/test` | 以一次翻譯呼叫測試 API 連通 |
| GET/PUT | `/api/settings/app` | 關鍵字通知、字幕轉發 webhooks(tg/slack/discord/generic)、保留天數 |
| POST | `/api/maintenance/cleanup` | 立即依保留天數刪除過期 session(啟動時也會自動執行) |

## 翻譯架構(v0.2,使用者定案)

**本地 Whisper 辨識 + 雲端 AI API 校正/翻譯/摘要**(GPT / Gemini / Claude / 自訂 OpenAI 相容)。
- 即時:上游以純轉錄模式跑(en2zh→en 映射),原文先播(低延遲),
  雲端譯文完成後同 seq 更新字幕(前端自動覆蓋)。
- 離線:轉錄完成後逐句批次翻譯;摘要在有設定 LLM 時走雲端(嚴禁捏造 prompt 約束)。
- 不做 NLLB/Argos 離線備援;未設定 API 時 = 純轉錄模式。

## 上游橋接協定

`translate_meeting.py --webui` 以 TCP client 連 `127.0.0.1:19780`,送 NDJSON 事件。
transcription 事件:`{type, source(main|lb|mic), src_lang, src_text, dst_lang, dst_text, asr_time, translate_time, timestamp}`。
引擎在 `jt_bridge.py` 開 server 接收,`live.py` 轉成 Caption(source→channel 映射、seq 遞增、
空文字幻覺事件略過),停止採三段式 terminate→kill。測試以 `tests/fake_jt.py` 模擬全協定。

注意:上游即使 CLI 參數齊全仍會印「確認開始?(Y/n)」等 stdin(`_confirm_start`),
bridge 以 stdin pipe 自動送 `y\n` 並保持 pipe 開啟(EOF 會被上游視為取消)。
離線模式(`process_audio_file`)同樣經 TCP 送 transcription 事件
(speaker 為 1-based int、timestamp 為 `[HH:MM:SS-HH:MM:SS]` 音檔秒數),
`JtOfflineBridge` 因此與即時模式共用同一條事件通道,不解析 log 檔。

## 真實管線狀態(2026-07-19)

- vendor venv 已安裝(torch 2.11.0+cu128,RTX 3060 Ti CUDA 驗證通過)
- faster-whisper 模型 ×5 已下載(base/base.en/small/small.en/large-v3-turbo)
- `smoke_real.py` 通過:TTS 合成音檔 → 上游 CUDA ASR → 引擎 API → NotebookLM md,
  14 秒完成、關鍵字 3/3、時戳對應音檔秒數
- 講者辨識(resemblyzer)通過:diarize=True 正確歸為單一講者並自動建檔
- 已知坑(已處理):上游 `_confirm_start` 需 stdin 送 y;離線完成後卡「按 ESC 鍵退出」
  → 以「處理完成」事件為訊號主動 terminate;真實埠寫死 19780

## 下一步(Phase 1d / Phase 2)

1. 翻譯管線驗證:裝 Ollama(qwen2.5)後跑 en2zh 離線與即時;或下載 NLLB 離線備援。
2. 即時模式真機驗證:需實際音訊裝置(WASAPI Loopback),列入手動驗收。
3. ~~AI 基準線~~ 已完成:`benchmarks/`(TTS bootstrap 評測集 + `run_baseline.py`,
   首輪:EN WER 0.0、ZH CER 1.19%、雙講者 2/2、靜音零幻覺;真人錄音補齊後應重建)。
   模型/參數變動後重跑,劣化 >10% 相對值視為回歸。
4. Phase 2:Tauri 桌面 App(接現有引擎 WebSocket/REST)。
