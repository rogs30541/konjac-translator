"""SQLite 紀錄層。單執行緒寫入(FastAPI 端以 lock 保護),檔案即備份。"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import (
    Caption, CaptionIn, Session, SessionCreate, SessionStatus,
    Speaker, SPEAKER_COLORS, SummaryResult, utcnow,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    kind TEXT NOT NULL,
    mode TEXT NOT NULL,
    topic TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    ended_at TEXT,
    notebooklm_forwarded_at TEXT,
    notebooklm_target TEXT
);
CREATE TABLE IF NOT EXISTS speakers (
    id TEXT NOT NULL,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    display_name TEXT NOT NULL,
    color TEXT NOT NULL,
    PRIMARY KEY (session_id, id)
);
CREATE TABLE IF NOT EXISTS captions (
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    t_start REAL NOT NULL,
    t_end REAL,
    speaker_id TEXT,
    source_channel TEXT NOT NULL,
    source_text TEXT NOT NULL,
    translated_text TEXT,
    is_final INTEGER NOT NULL DEFAULT 0,
    starred INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (session_id, seq)
);
CREATE TABLE IF NOT EXISTS summaries (
    session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    content_md TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def _dt(v: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(v) if v else None


class Store:
    def __init__(self, path: str | Path = ":memory:"):
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # ---- sessions ----
    def create_session(self, req: SessionCreate) -> Session:
        s = Session(id=uuid.uuid4().hex[:12], **req.model_dump())
        with self._lock:
            self._conn.execute(
                "INSERT INTO sessions (id,title,kind,mode,topic,status,created_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (s.id, s.title, s.kind.value, s.mode, s.topic,
                 s.status.value, s.created_at.isoformat()),
            )
            self._conn.commit()
        return s

    def get_session(self, sid: str) -> Optional[Session]:
        row = self._conn.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
        if not row:
            return None
        return Session(
            id=row["id"], title=row["title"], kind=row["kind"], mode=row["mode"],
            topic=row["topic"], status=row["status"],
            created_at=_dt(row["created_at"]), ended_at=_dt(row["ended_at"]),
            notebooklm_forwarded_at=_dt(row["notebooklm_forwarded_at"]),
            notebooklm_target=row["notebooklm_target"],
        )

    def list_sessions(self) -> list[Session]:
        rows = self._conn.execute(
            "SELECT id FROM sessions ORDER BY created_at DESC").fetchall()
        return [self.get_session(r["id"]) for r in rows]

    def set_status(self, sid: str, status: SessionStatus, ended: bool = False) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET status=?, ended_at=COALESCE(?, ended_at) WHERE id=?",
                (status.value, utcnow().isoformat() if ended else None, sid))
            self._conn.commit()

    def mark_forwarded(self, sid: str, target: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET notebooklm_forwarded_at=?, notebooklm_target=? WHERE id=?",
                (utcnow().isoformat(), target, sid))
            self._conn.commit()

    def delete_session(self, sid: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM sessions WHERE id=?", (sid,))
            self._conn.commit()

    def reconcile_zombies(self) -> int:
        """引擎啟動時:上次沒正常結束的 recording/processing session
        全部標記 error(啟動當下不可能有真正在跑的 runner)。"""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE sessions SET status='error', ended_at=? "
                "WHERE status IN ('recording','processing')",
                (utcnow().isoformat(),))
            self._conn.commit()
        return cur.rowcount

    def delete_older_than(self, days: int) -> int:
        """隱私保留:刪除超過 days 天的 session(cascade 字幕/講者/摘要)。"""
        if days <= 0:
            return 0
        from datetime import timedelta
        cutoff = (utcnow() - timedelta(days=days)).isoformat()
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM sessions WHERE created_at < ?", (cutoff,))
            self._conn.commit()
        return cur.rowcount

    # ---- speakers ----
    def ensure_speaker(self, session_id: str, speaker_id: str) -> Speaker:
        row = self._conn.execute(
            "SELECT * FROM speakers WHERE session_id=? AND id=?",
            (session_id, speaker_id)).fetchone()
        if row:
            return Speaker(id=row["id"], session_id=session_id,
                           display_name=row["display_name"], color=row["color"])
        n = self._conn.execute(
            "SELECT COUNT(*) c FROM speakers WHERE session_id=?",
            (session_id,)).fetchone()["c"]
        sp = Speaker(
            id=speaker_id, session_id=session_id,
            display_name=f"Speaker {n + 1}",
            color=SPEAKER_COLORS[n % len(SPEAKER_COLORS)],
        )
        with self._lock:
            self._conn.execute(
                "INSERT INTO speakers (id,session_id,display_name,color) VALUES (?,?,?,?)",
                (sp.id, sp.session_id, sp.display_name, sp.color))
            self._conn.commit()
        return sp

    def rename_speaker(self, session_id: str, speaker_id: str, name: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE speakers SET display_name=? WHERE session_id=? AND id=?",
                (name, session_id, speaker_id))
            self._conn.commit()
        return cur.rowcount > 0

    def list_speakers(self, session_id: str) -> list[Speaker]:
        rows = self._conn.execute(
            "SELECT * FROM speakers WHERE session_id=? ORDER BY display_name",
            (session_id,)).fetchall()
        return [Speaker(id=r["id"], session_id=session_id,
                        display_name=r["display_name"], color=r["color"]) for r in rows]

    # ---- captions ----
    def upsert_caption(self, session_id: str, c: CaptionIn) -> Caption:
        """partial 與 final 共用 seq;final 覆蓋 partial(斷線重連不重複)。"""
        if c.speaker_id:
            self.ensure_speaker(session_id, c.speaker_id)
        with self._lock:
            self._conn.execute(
                "INSERT INTO captions (session_id,seq,t_start,t_end,speaker_id,"
                " source_channel,source_text,translated_text,is_final)"
                " VALUES (?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(session_id,seq) DO UPDATE SET"
                " t_end=excluded.t_end, speaker_id=excluded.speaker_id,"
                " source_text=excluded.source_text,"
                " translated_text=excluded.translated_text, is_final=excluded.is_final",
                (session_id, c.seq, c.t_start, c.t_end, c.speaker_id,
                 c.source_channel, c.source_text, c.translated_text, int(c.is_final)))
            self._conn.commit()
        return Caption(session_id=session_id, **c.model_dump())

    def list_captions(self, session_id: str, final_only: bool = False) -> list[Caption]:
        q = "SELECT * FROM captions WHERE session_id=?"
        if final_only:
            q += " AND is_final=1"
        rows = self._conn.execute(q + " ORDER BY seq", (session_id,)).fetchall()
        return [Caption(
            session_id=session_id, seq=r["seq"], t_start=r["t_start"], t_end=r["t_end"],
            speaker_id=r["speaker_id"], source_channel=r["source_channel"],
            source_text=r["source_text"], translated_text=r["translated_text"],
            is_final=bool(r["is_final"]), starred=bool(r["starred"])) for r in rows]

    def star_caption(self, session_id: str, seq: int, starred: bool = True) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE captions SET starred=? WHERE session_id=? AND seq=?",
                (int(starred), session_id, seq))
            self._conn.commit()
        return cur.rowcount > 0

    # ---- summaries ----
    def save_summary(self, s: SummaryResult) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO summaries (session_id,content_md,created_at) VALUES (?,?,?)"
                " ON CONFLICT(session_id) DO UPDATE SET"
                " content_md=excluded.content_md, created_at=excluded.created_at",
                (s.session_id, s.content_md, s.created_at.isoformat()))
            self._conn.commit()

    def get_summary(self, session_id: str) -> Optional[SummaryResult]:
        row = self._conn.execute(
            "SELECT * FROM summaries WHERE session_id=?", (session_id,)).fetchone()
        if not row:
            return None
        return SummaryResult(session_id=session_id, content_md=row["content_md"],
                             created_at=_dt(row["created_at"]))

    def search_captions(self, text: str) -> list[tuple[str, int]]:
        rows = self._conn.execute(
            "SELECT session_id, seq FROM captions WHERE is_final=1 AND"
            " (source_text LIKE ? OR translated_text LIKE ?) ORDER BY session_id, seq",
            (f"%{text}%", f"%{text}%")).fetchall()
        return [(r["session_id"], r["seq"]) for r in rows]
