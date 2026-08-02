"""翻譯蒟蒻引擎服務:REST(session 管理)+ WebSocket(字幕流)。

安全預設:只綁 127.0.0.1(見 run())。AI 能力由 provider 注入,
預設 mock;之後以 --provider jt 切換 jt-live-whisper 橋接。
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from .db import Store
from .export import EXPORTERS, MEDIA_TYPES, to_notebooklm_markdown
from .hub import Hub
from .live import LiveManager
from .models import (
    CaptionIn, ForwardRequest, SessionCreate, SessionKind, SessionStatus,
    SpeakerRename, SummaryResult, WsEvent,
)
from .providers.cloud_llm import (
    CloudLLM, CloudSummarizer, LLMSettings, SettingsStore, needs_translation,
    recommend_model,
)
from .providers.forwarder import send_caption
from .providers.jt_bridge import (
    JtBridgeConfig, JtLiveBridge, JtOfflineBridge, set_vendor_override,
    vendor_available, vendor_dir,
)
from .providers.mock import MockOfflinePipeline, MockSummarizer

ENGINE_VERSION = "0.2.0"

# 翻譯模式 → 上游純轉錄模式(翻譯由引擎的雲端 LLM 執行,不用上游 Ollama)
UPSTREAM_ASR_MODE = {"en2zh": "en", "zh2en": "zh", "ja2zh": "ja"}


def default_bridge_factory(on_event):
    return JtLiveBridge(JtBridgeConfig(), on_event)


def demo_bridge_factory(on_event):
    """KONJAC_DEMO=1:live 用 tests/fake_jt.py 劇本,免音訊裝置/模型,
    供前端開發與展示。"""
    fake = Path(__file__).resolve().parents[1] / "tests" / "fake_jt.py"
    return JtLiveBridge(
        JtBridgeConfig(script=fake, python_exe=sys.executable, port=0), on_event)


def create_app(store: Optional[Store] = None,
               offline_pipeline=None, summarizer=None,
               bridge_factory=None,
               settings_store: Optional[SettingsStore] = None,
               llm_factory=None, webhook_client=None) -> FastAPI:
    app = FastAPI(title="翻譯蒟蒻 Engine", version=ENGINE_VERSION)
    # 桌面前端來源(Vite dev / Tauri WebView);引擎本身仍只綁 127.0.0.1
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:1420", "http://127.0.0.1:1420",
                       "tauri://localhost", "http://tauri.localhost",
                       "https://tauri.localhost"],
        allow_methods=["*"], allow_headers=["*"])
    app.state.store = store or Store()
    app.state.hub = Hub()
    # 離線管線:call-time 動態選擇(設定頁改 vendor 路徑即時生效)
    app.state.offline_injected = offline_pipeline

    def get_offline():
        if app.state.offline_injected is not None:
            return app.state.offline_injected
        if os.environ.get("KONJAC_DEMO") == "1" or not vendor_available():
            return MockOfflinePipeline()
        return JtOfflineBridge(JtBridgeConfig())

    app.state.get_offline = get_offline
    app.state.summarizer = summarizer or MockSummarizer()
    app.state.offline_jobs: dict[str, dict] = {}
    app.state.live = LiveManager()
    app.state.settings_store = settings_store or SettingsStore()
    app.state.llm_settings = app.state.settings_store.load()
    app.state.llm_factory = llm_factory or (lambda s: CloudLLM(s))

    def get_llm():
        s: LLMSettings = app.state.llm_settings
        return app.state.llm_factory(s) if s.configured else None

    app.state.get_llm = get_llm
    app.state.app_settings = app.state.settings_store.load_app()
    set_vendor_override(app.state.app_settings.get("vendor_dir") or None)
    app.state.webhook_client = webhook_client  # 測試注入;None = 每次自建

    async def after_caption(sid: str, cap):
        """caption 後處理:關鍵字通知 + webhook 轉發(final 才轉發)。"""
        cfg = app.state.app_settings
        text = f"{cap.source_text} {cap.translated_text or ''}".lower()
        for kw in cfg.get("keywords", []):
            if kw and kw.lower() in text:
                await app.state.hub.broadcast(sid, WsEvent(
                    type="keyword", data={"keyword": kw, "seq": cap.seq}))
        if cap.is_final and cfg.get("webhooks"):
            session = app.state.store.get_session(sid)
            names = {sp.id: sp.display_name
                     for sp in app.state.store.list_speakers(sid)}
            asyncio.create_task(send_caption(
                cfg["webhooks"], session.title if session else sid, cap,
                speaker_name=names.get(cap.speaker_id or ""),
                client=app.state.webhook_client))

    app.state.after_caption = after_caption
    # 啟動時執行保留天數清理(retention_days=0 表示不清理)
    app.state.store.delete_older_than(
        int(app.state.app_settings.get("retention_days") or 0))
    app.state.bridge_factory_injected = bridge_factory

    def get_bridge_factory():
        if app.state.bridge_factory_injected is not None:
            return app.state.bridge_factory_injected
        if os.environ.get("KONJAC_DEMO") == "1":
            return demo_bridge_factory
        return default_bridge_factory if vendor_available() else None

    app.state.get_bridge_factory = get_bridge_factory

    st: Store = app.state.store
    hub: Hub = app.state.hub

    def _session_or_404(sid: str):
        s = st.get_session(sid)
        if not s:
            raise HTTPException(404, "session not found")
        return s

    # ---------- health ----------
    @app.get("/api/health")
    async def health():
        s: LLMSettings = app.state.llm_settings
        return {"status": "ok", "version": ENGINE_VERSION,
                "provider": type(app.state.get_offline()).__name__,
                "vendor_available": vendor_available(),
                "vendor_dir": str(vendor_dir()),
                "llm": s.provider if s.configured else None}

    # ---------- settings(API Key 只存本機)----------
    @app.get("/api/settings")
    async def get_settings():
        return app.state.llm_settings.masked()

    @app.put("/api/settings")
    async def put_settings(body: dict):
        cur: LLMSettings = app.state.llm_settings
        new = LLMSettings(
            provider=str(body.get("provider", cur.provider) or ""),
            # 空字串 = 保留原 key(前端遮罩顯示不回傳原值)
            api_key=str(body.get("api_key") or cur.api_key or ""),
            model=str(body.get("model", cur.model) or ""),
            base_url=str(body.get("base_url", cur.base_url) or ""))
        if body.get("clear_key"):
            new.api_key = ""
        app.state.llm_settings = new
        app.state.settings_store.save(new)
        return new.masked()

    @app.get("/api/settings/app")
    async def get_app_settings():
        return _app_settings_view()

    def _app_settings_view() -> dict:
        return {**app.state.app_settings,
                "vendor_available": vendor_available(),
                "vendor_resolved": str(vendor_dir())}

    @app.put("/api/settings/app")
    async def put_app_settings(body: dict):
        cleaned = {}
        if "keywords" in body:
            cleaned["keywords"] = [str(k).strip() for k in (body["keywords"] or [])
                                   if str(k).strip()]
        if "webhooks" in body:
            cleaned["webhooks"] = [h for h in (body["webhooks"] or [])
                                   if isinstance(h, dict)]
        if "retention_days" in body:
            cleaned["retention_days"] = max(0, int(body["retention_days"] or 0))
        if "vendor_dir" in body:
            cleaned["vendor_dir"] = str(body["vendor_dir"] or "").strip()
        app.state.app_settings = app.state.settings_store.save_app(
            {**app.state.app_settings, **cleaned})
        set_vendor_override(app.state.app_settings.get("vendor_dir") or None)
        return _app_settings_view()

    @app.post("/api/maintenance/cleanup")
    async def cleanup():
        days = int(app.state.app_settings.get("retention_days") or 0)
        deleted = st.delete_older_than(days)
        return {"retention_days": days, "deleted_sessions": deleted}

    def _mask_key(text: str) -> str:
        """任何要回給前端的錯誤訊息,先把 API Key 遮掉(防日誌/畫面洩漏)。"""
        key = app.state.llm_settings.api_key
        return text.replace(key, "***KEY***") if key else text

    @app.post("/api/settings/test")
    async def test_settings():
        llm = app.state.get_llm()
        if llm is None:
            raise HTTPException(400, "llm not configured")
        try:
            out = await llm.translate("Hello, this is a connectivity test.", "en2zh")
            return {"ok": True, "sample": out}
        except Exception as e:
            raise HTTPException(502, _mask_key(f"llm test failed: {e}"))

    @app.get("/api/settings/models")
    async def list_models():
        """列出此 Key 可用的模型,並依 CP 值啟發式給出推薦。"""
        llm = app.state.get_llm()
        if llm is None:
            raise HTTPException(400, "llm not configured")
        try:
            models = await llm.list_models()
        except Exception as e:
            raise HTTPException(502, _mask_key(f"list models failed: {e}"))
        return {"models": sorted(models),
                "recommended": recommend_model(
                    app.state.llm_settings.provider, models)}

    # ---------- sessions ----------
    @app.post("/api/sessions", status_code=201)
    async def create_session(req: SessionCreate):
        return st.create_session(req)

    @app.get("/api/sessions")
    async def list_sessions():
        return st.list_sessions()

    @app.get("/api/sessions/{sid}")
    async def get_session(sid: str):
        s = _session_or_404(sid)
        return {"session": s, "speakers": st.list_speakers(sid),
                "summary": st.get_summary(sid)}

    @app.post("/api/sessions/{sid}/stop")
    async def stop_session(sid: str):
        _session_or_404(sid)
        if not await app.state.live.stop(st, hub, sid):
            # 非 bridge 驅動的 session(測試 ingest 等)直接標記結束
            st.set_status(sid, SessionStatus.done, ended=True)
            await hub.broadcast(sid, WsEvent(type="status", data={"status": "done"}))
        return st.get_session(sid)

    # ---------- live(jt-live-whisper 橋接)----------
    @app.post("/api/live/start", status_code=201)
    async def live_start(req: SessionCreate):
        factory = app.state.get_bridge_factory()
        if factory is None:
            raise HTTPException(
                503,
                "AI 管線(jt-live-whisper)未找到:請在「設定 → AI 管線位置」"
                "指定安裝資料夾,或安裝至 C:\\jt-live-whisper。"
                f"目前解析路徑:{vendor_dir()}")
        active = app.state.live.active()
        if active:
            raise HTTPException(409, f"another live session is recording: {active}")
        session = st.create_session(req)
        try:
            await app.state.live.start(
                st, hub, session.id, req.mode, factory,
                topic=req.topic, llm_getter=app.state.get_llm,
                upstream_mode=UPSTREAM_ASR_MODE.get(req.mode),
                on_caption=app.state.after_caption)
        except Exception as e:
            st.set_status(session.id, SessionStatus.error, ended=True)
            raise HTTPException(500, f"failed to start live pipeline: {e}")
        return session

    @app.delete("/api/sessions/{sid}", status_code=204)
    async def delete_session(sid: str):
        _session_or_404(sid)
        st.delete_session(sid)

    # ---------- captions ingest(管線 → 引擎的唯一入口;測試也走這裡)----------
    @app.post("/api/sessions/{sid}/ingest")
    async def ingest(sid: str, cap: CaptionIn):
        s = _session_or_404(sid)
        if s.status != SessionStatus.recording:
            raise HTTPException(409, f"session is {s.status.value}, not recording")
        c = st.upsert_caption(sid, cap)
        await hub.broadcast(sid, WsEvent(type="caption", data=c.model_dump()))
        await app.state.after_caption(sid, c)
        return {"ok": True, "seq": c.seq}

    @app.get("/api/sessions/{sid}/captions")
    async def captions(sid: str, final_only: bool = False):
        _session_or_404(sid)
        return st.list_captions(sid, final_only=final_only)

    @app.post("/api/sessions/{sid}/captions/{seq}/star")
    async def star(sid: str, seq: int, starred: bool = True):
        _session_or_404(sid)
        if not st.star_caption(sid, seq, starred):
            raise HTTPException(404, "caption not found")
        return {"ok": True}

    # ---------- speakers ----------
    @app.patch("/api/sessions/{sid}/speakers/{speaker_id}")
    async def rename_speaker(sid: str, speaker_id: str, req: SpeakerRename):
        _session_or_404(sid)
        if not st.rename_speaker(sid, speaker_id, req.display_name):
            raise HTTPException(404, "speaker not found")
        await hub.broadcast(sid, WsEvent(
            type="speaker", data={"id": speaker_id, "display_name": req.display_name}))
        return st.list_speakers(sid)

    # ---------- summary ----------
    @app.post("/api/sessions/{sid}/summary")
    async def make_summary(sid: str, template: str = "general"):
        s = _session_or_404(sid)
        transcript = to_notebooklm_markdown(st, s, scope="full")
        # 有設定雲端 LLM 就用雲端摘要,否則退回注入的 summarizer(mock)
        llm = app.state.get_llm()
        summarizer = CloudSummarizer(llm) if llm else app.state.summarizer
        content = await summarizer.summarize(transcript, s.topic, template)
        result = SummaryResult(session_id=sid, content_md=content)
        st.save_summary(result)
        await hub.broadcast(sid, WsEvent(type="summary", data={"content_md": content}))
        return result

    # ---------- export ----------
    @app.get("/api/sessions/{sid}/export")
    async def export(sid: str, format: str = "md", scope: str = "full"):
        s = _session_or_404(sid)
        if format not in EXPORTERS:
            raise HTTPException(400, f"unknown format: {format}")
        if format == "md":  # md 支援範圍(轉發預覽用)
            return PlainTextResponse(to_notebooklm_markdown(st, s, scope=scope),
                                     media_type=MEDIA_TYPES["md"])
        return PlainTextResponse(EXPORTERS[format](st, s),
                                 media_type=MEDIA_TYPES[format])

    # ---------- NotebookLM forward ----------
    @app.post("/api/sessions/{sid}/forward/notebooklm")
    async def forward_notebooklm(sid: str, req: ForwardRequest, force: bool = False):
        s = _session_or_404(sid)
        if s.notebooklm_forwarded_at and not force:
            raise HTTPException(409, "already forwarded; pass force=true to resend")
        payload = to_notebooklm_markdown(st, s, scope=req.scope)
        st.mark_forwarded(sid, req.target_notebook)
        # 引擎只產生 payload 並記錄;實際傳送由 Chrome 擴充/API connector 執行
        return {"target_notebook": req.target_notebook, "scope": req.scope,
                "payload_md": payload}

    # ---------- offline jobs ----------
    @app.post("/api/offline/jobs", status_code=202)
    async def create_offline_job(file: UploadFile = File(...), mode: str = "en2zh",
                                 diarize: bool = True, title: Optional[str] = None):
        suffix = Path(file.filename or "audio.wav").suffix.lower()
        # webm/ogg/opus:Chrome 擴充分頁錄音格式,上游以 ffmpeg 轉 wav
        if suffix not in {".mp3", ".wav", ".m4a", ".flac", ".webm", ".ogg", ".opus"}:
            raise HTTPException(400, f"unsupported format: {suffix}")
        session = st.create_session(SessionCreate(
            title=title or (file.filename or "offline job"),
            kind=SessionKind.offline, mode=mode))
        st.set_status(session.id, SessionStatus.processing)
        job_id = uuid.uuid4().hex[:12]
        app.state.offline_jobs[job_id] = {"job_id": job_id, "session_id": session.id,
                                          "status": "processing", "error": None}
        data = await file.read()

        async def run_job():
            job = app.state.offline_jobs[job_id]
            tmp = Path(tempfile.gettempdir()) / f"konjac_{job_id}{suffix}"
            try:
                tmp.write_bytes(data)
                caps = await app.state.get_offline().transcribe_file(
                    str(tmp), mode=UPSTREAM_ASR_MODE.get(mode, mode),
                    diarize=diarize)
                for c in caps:
                    st.upsert_caption(session.id, c)
                # 雲端 LLM 批次翻譯(逐句,失敗不擋整批)
                llm = app.state.get_llm()
                if llm and needs_translation(mode):
                    s_obj = st.get_session(session.id)
                    for c in caps:
                        if c.translated_text:
                            continue
                        try:
                            t = await llm.translate(
                                c.source_text, mode,
                                s_obj.topic if s_obj else None)
                        except Exception:
                            continue
                        if t:
                            st.upsert_caption(
                                session.id,
                                c.model_copy(update={"translated_text": t}))
                st.set_status(session.id, SessionStatus.done, ended=True)
                job["status"] = "done"
            except Exception as e:  # 損壞檔等 → 明確錯誤,不 crash
                st.set_status(session.id, SessionStatus.error, ended=True)
                job.update(status="error", error=str(e))
            finally:
                tmp.unlink(missing_ok=True)

        asyncio.create_task(run_job())
        return app.state.offline_jobs[job_id]

    @app.get("/api/offline/jobs/{job_id}")
    async def get_offline_job(job_id: str):
        job = app.state.offline_jobs.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        return job

    # ---------- search ----------
    @app.get("/api/search")
    async def search(q: str):
        return [{"session_id": sid, "seq": seq} for sid, seq in st.search_captions(q)]

    # ---------- websocket ----------
    @app.websocket("/ws/sessions/{sid}")
    async def ws_session(ws: WebSocket, sid: str):
        if not st.get_session(sid):
            await ws.close(code=4404)
            return
        await hub.join(sid, ws)
        try:
            # 重連補發:先送目前已有的 final 字幕,前端以 seq 去重
            for c in st.list_captions(sid, final_only=True):
                await ws.send_json(WsEvent(type="caption", data=c.model_dump()).model_dump())
            while True:
                await ws.receive_text()  # 心跳/忽略,前端不需上行
        except WebSocketDisconnect:
            pass
        finally:
            await hub.leave(sid, ws)

    return app


def run() -> None:
    import uvicorn
    data_dir = Path.home() / ".konjac"
    data_dir.mkdir(parents=True, exist_ok=True)
    uvicorn.run(create_app(Store(data_dir / "konjac.db")),
                host="127.0.0.1", port=8765)


if __name__ == "__main__":
    run()
