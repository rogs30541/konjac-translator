"""Provider 介面:AI 能力的可插拔邊界。

Phase 1 只有 MockProvider(測試/無模型環境)。
Phase 1b 起新增 JtBridgeProvider,以子程序方式驅動 vendor/jt-live-whisper
(沿用其 webui.py 的 TCP 事件橋接模式),之後逐步移植為原生模組。
"""
from __future__ import annotations

from typing import AsyncIterator, Protocol

from ..models import CaptionIn


class LivePipeline(Protocol):
    """即時管線:啟動後持續產出字幕事件,stop() 後結束迭代。"""

    def events(self) -> AsyncIterator[CaptionIn]: ...
    async def stop(self) -> None: ...


class OfflinePipeline(Protocol):
    """離線管線:處理單一音檔,產出 final 字幕串列。"""

    async def transcribe_file(self, path: str, mode: str,
                              diarize: bool) -> list[CaptionIn]: ...


class Summarizer(Protocol):
    async def summarize(self, transcript_md: str, topic: str | None,
                        template: str = "general") -> str: ...
