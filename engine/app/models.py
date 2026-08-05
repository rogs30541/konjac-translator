"""Pydantic schemas shared by REST API, WebSocket events and the store."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

SPEAKER_COLORS = ["#6EA8FF", "#4DD6C1", "#FFC46B", "#B18CFF", "#FF8FA3", "#8AD46B"]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SessionKind(str, Enum):
    live = "live"
    offline = "offline"


class SessionStatus(str, Enum):
    recording = "recording"
    processing = "processing"
    done = "done"
    error = "error"


class SessionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    kind: SessionKind = SessionKind.live
    mode: str = "en2zh"          # 翻譯模式,沿用 jt-live-whisper 的模式代號
    topic: Optional[str] = None  # 會議主題,注入翻譯/摘要 prompt


class Session(BaseModel):
    id: str
    title: str
    kind: SessionKind
    mode: str
    topic: Optional[str] = None
    status: SessionStatus = SessionStatus.recording
    created_at: datetime = Field(default_factory=utcnow)
    ended_at: Optional[datetime] = None
    notebooklm_forwarded_at: Optional[datetime] = None
    notebooklm_target: Optional[str] = None


class Speaker(BaseModel):
    id: str                       # 引擎產生的講者代號,如 "S1"
    session_id: str
    display_name: str             # 預設 "Speaker 1",可改名
    color: str


class CaptionIn(BaseModel):
    """管線(或測試)推入的一則字幕事件。partial 會被同 seq 的後續事件覆蓋。"""
    seq: int
    t_start: float
    t_end: Optional[float] = None
    speaker_id: Optional[str] = None      # 未知講者可為 None
    source_channel: str = "system"        # system | mic
    source_text: str
    translated_text: Optional[str] = None
    is_final: bool = False


class Caption(CaptionIn):
    session_id: str
    starred: bool = False


class SpeakerRename(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)


class SummaryResult(BaseModel):
    session_id: str
    content_md: str
    created_at: datetime = Field(default_factory=utcnow)


class ForwardRequest(BaseModel):
    target_notebook: str = Field(min_length=1)
    scope: str = "full"  # full | summary_only | starred_only
    open_browser: bool = False  # 桌面一鍵流程:複製剪貼簿 + 開啟 NotebookLM


class WsEvent(BaseModel):
    """WebSocket 對前端廣播的事件封包。"""
    type: str            # caption | speaker | status | summary
    data: dict
