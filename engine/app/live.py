"""LiveRunner:把 jt bridge 的原始事件轉成引擎的 Caption/WsEvent。

上游只送 final(無 partial),seq 由 runner 遞增;t_start 用 session
啟動後的單調時鐘秒數,與離線管線的音檔秒數同一語意。
"""
from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path

from .db import Store
from .hub import Hub
from .models import CaptionIn, SessionStatus, WsEvent
from .providers.jt_bridge import JtLiveBridge


def _channel(source: str | None) -> str:
    # 上游 source:main / lb(loopback)= 系統音訊;mic = 麥克風
    return "mic" if source == "mic" else "system"


_TS_RANGE = re.compile(
    r"\[(?:(\d{1,2}):)?(\d{1,2}):(\d{2})-(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\]")


def _to_seconds(h: str | None, m: str, s: str) -> float:
    return float(int(h or 0) * 3600 + int(m) * 60 + int(s))


def parse_ts_range(ts: str | None) -> tuple[float, float] | None:
    """離線事件 timestamp 為音檔秒數區間:上游 _format_timestamp 在
    一小時內用 "[MM:SS-MM:SS]",超過一小時用 "[HH:MM:SS-HH:MM:SS]"。
    即時事件為牆鐘 "HH:MM:SS"(無區間),不匹配時回 None。"""
    if not ts:
        return None
    m = _TS_RANGE.match(ts)
    if not m:
        return None
    h1, m1, s1, h2, m2, s2 = m.groups()
    return _to_seconds(h1, m1, s1), _to_seconds(h2, m2, s2)


def event_to_caption(event: dict, seq: int, t_default: float) -> CaptionIn | None:
    """上游 transcription 事件 → CaptionIn;空文字(幻覺過濾殘留)回 None。

    speaker:上游是 1-based int(或無)→ 正規化為 "S{n}" 字串。"""
    src_text = (event.get("src_text") or "").strip()
    dst_text = (event.get("dst_text") or "").strip() or None
    if not src_text and not dst_text:
        return None
    spk = event.get("speaker")
    ts = parse_ts_range(event.get("timestamp"))
    t_start, t_end = ts if ts else (round(t_default, 2), None)
    return CaptionIn(
        seq=seq, t_start=t_start, t_end=t_end,
        speaker_id=f"S{spk}" if spk is not None else None,
        source_channel=_channel(event.get("source")),
        source_text=src_text or (dst_text or ""),
        translated_text=dst_text, is_final=True)


class LiveRunner:
    def __init__(self, store: Store, hub: Hub, session_id: str,
                 bridge_factory, mode: str = "en",
                 topic: str | None = None, llm_getter=None,
                 on_caption=None, idle_getter=None, on_idle=None) -> None:
        self._store = store
        self._hub = hub
        self._sid = session_id
        self._bridge: JtLiveBridge = bridge_factory(self.on_event)
        self._seq = 0
        self._t0 = time.monotonic()
        self._mode = mode
        self._topic = topic
        self._llm_getter = llm_getter or (lambda: None)
        self._on_caption = on_caption  # 關鍵字/webhook 等後處理 hook
        self._stopping = False
        self._idle_getter = idle_getter or (lambda: 0)  # 秒;<=0 停用
        self._on_idle = on_idle
        self._last_activity = time.monotonic()

    @property
    def running(self) -> bool:
        return self._bridge.running

    async def start(self, mode: str) -> None:
        self._t0 = time.monotonic()
        self._last_activity = time.monotonic()
        await self._bridge.start(mode)
        asyncio.ensure_future(self._watch_process())
        asyncio.ensure_future(self._watch_idle())

    async def _watch_idle(self) -> None:
        """閒置看門狗:超過設定秒數沒有新字幕 → 自動停止錄製。
        逾時值每輪重讀(設定頁改了即時生效);<=0 表示停用。"""
        while not self._stopping:
            timeout = float(self._idle_getter() or 0)
            interval = min(10.0, max(0.5, timeout / 4)) if timeout > 0 else 10.0
            await asyncio.sleep(interval)
            if self._stopping:
                return
            timeout = float(self._idle_getter() or 0)
            if timeout <= 0:
                continue
            if time.monotonic() - self._last_activity > timeout:
                if self._on_idle:
                    await self._on_idle()
                return

    async def _watch_process(self) -> None:
        """看門狗:上游程序死亡(非正常停止)→ session 標記 error 並通知前端,
        避免 UI 永遠卡在 recording。"""
        rc = await self._bridge.wait_proc()
        if self._stopping:
            return  # 正常停止流程,由 stop() 收尾
        self._store.set_status(self._sid, SessionStatus.error, ended=True)
        await self._hub.broadcast(self._sid, WsEvent(
            type="status",
            data={"status": "error",
                  "detail": f"AI 管線程序異常結束(rc={rc}),請查看引擎日誌"}))

    async def stop(self) -> None:
        self._stopping = True
        await self._bridge.stop()

    async def on_event(self, event: dict) -> None:
        etype = event.get("type")
        if etype == "transcription":
            cap = event_to_caption(event, self._seq + 1,
                                   time.monotonic() - self._t0)
            if cap is None:
                return  # 幻覺過濾後的空事件
            self._last_activity = time.monotonic()
            self._seq += 1
            c = self._store.upsert_caption(self._sid, cap)
            await self._hub.broadcast(
                self._sid, WsEvent(type="caption", data=c.model_dump()))
            if self._on_caption:
                await self._on_caption(self._sid, c)
            # 雲端 LLM 校正+翻譯:先播原文(低延遲),譯文完成後同 seq 更新
            llm = self._llm_getter()
            if llm is not None and c.translated_text is None:
                asyncio.ensure_future(self._translate_async(cap))
        else:
            if etype == "output_files":
                self._capture_recording_path(event)
            # summary/status/output_files 等其餘事件原樣轉給前端
            await self._hub.broadcast(
                self._sid, WsEvent(type="engine", data=event))

    def _capture_recording_path(self, event: dict) -> None:
        """上游優雅停止時回報輸出檔清單,擷取錄音檔供講者精析。
        上游會把 wav 轉存 mp3 後刪原檔,故同名互換副檔名也要試。"""
        from .providers.jt_bridge import vendor_dir
        for f in event.get("files", []):
            rel = f.get("path") or ""
            if not rel.lower().endswith((".wav", ".mp3", ".m4a")):
                continue
            p = Path(rel)
            if not p.is_absolute():
                p = vendor_dir() / rel
            for cand in (p, p.with_suffix(".mp3"), p.with_suffix(".wav")):
                if cand.is_file():
                    self._store.set_recording_path(self._sid, str(cand))
                    return

    async def _translate_async(self, cap: CaptionIn) -> None:
        llm = self._llm_getter()
        if llm is None:
            return
        try:
            translated = await llm.translate(cap.source_text, self._mode, self._topic)
        except Exception:
            return  # API 失敗:保留原文,不中斷字幕流
        if not translated:
            return
        updated = cap.model_copy(update={"translated_text": translated})
        c = self._store.upsert_caption(self._sid, updated)
        await self._hub.broadcast(
            self._sid, WsEvent(type="caption", data=c.model_dump()))
        if self._on_caption:
            await self._on_caption(self._sid, c)


class LiveManager:
    """session_id → runner;引擎同時間只允許一場即時錄製。"""

    def __init__(self) -> None:
        self._runners: dict[str, LiveRunner] = {}

    def active(self) -> str | None:
        for sid, r in self._runners.items():
            if r.running:
                return sid
        return None

    def get(self, sid: str) -> LiveRunner | None:
        return self._runners.get(sid)

    async def start(self, store: Store, hub: Hub, sid: str, mode: str,
                    bridge_factory, topic: str | None = None,
                    llm_getter=None, upstream_mode: str | None = None,
                    on_caption=None, idle_getter=None) -> LiveRunner:
        async def on_idle():
            minutes = round(float(idle_getter() or 0) / 60, 1) if idle_getter else 0
            if await self.stop(store, hub, sid):
                await hub.broadcast(sid, WsEvent(
                    type="engine",
                    data={"type": "idle_stop",
                          "detail": f"超過 {minutes:g} 分鐘沒有新字幕,已自動停止錄製"}))

        runner = LiveRunner(store, hub, sid, bridge_factory,
                            mode=mode, topic=topic, llm_getter=llm_getter,
                            on_caption=on_caption, idle_getter=idle_getter,
                            on_idle=on_idle)
        await runner.start(upstream_mode or mode)
        self._runners[sid] = runner
        return runner

    async def stop(self, store: Store, hub: Hub, sid: str) -> bool:
        runner = self._runners.pop(sid, None)
        if not runner:
            return False
        await runner.stop()
        self._fallback_recording_scan(store, sid)
        store.set_status(sid, SessionStatus.done, ended=True)
        await hub.broadcast(sid, WsEvent(type="status", data={"status": "done"}))
        return True

    @staticmethod
    def _fallback_recording_scan(store: Store, sid: str) -> None:
        """output_files 事件沒接到時的保險:掃 vendor recordings 目錄,
        取本場 session 期間新建的最新錄音檔。"""
        from datetime import datetime, timezone

        from .providers.jt_bridge import vendor_dir
        s = store.get_session(sid)
        if not s or s.recording_path:
            return
        rec_dir = vendor_dir() / "recordings"
        if not rec_dir.is_dir():
            return
        started = s.created_at.timestamp()
        cands = [p for p in rec_dir.iterdir()
                 if p.suffix.lower() in (".mp3", ".wav", ".m4a")
                 and p.stat().st_mtime >= started - 5]
        if cands:
            newest = max(cands, key=lambda p: p.stat().st_mtime)
            store.set_recording_path(sid, str(newest))
