"""匯出:NotebookLM 最佳化 Markdown、純文字、SRT、VTT。"""
from __future__ import annotations

from .db import Store
from .models import Caption, Session


def _hms(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def _srt_ts(seconds: float) -> str:
    ms = int(round((seconds - int(seconds)) * 1000))
    s = int(seconds)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d},{ms:03d}"


def _vtt_ts(seconds: float) -> str:
    return _srt_ts(seconds).replace(",", ".")


def _speaker_names(store: Store, session_id: str) -> dict[str, str]:
    return {sp.id: sp.display_name for sp in store.list_speakers(session_id)}


def _line_text(c: Caption) -> str:
    return c.translated_text or c.source_text


def to_notebooklm_markdown(store: Store, session: Session,
                           scope: str = "full") -> str:
    """摘要在前、含講者時戳逐字稿在後 —— NotebookLM 溯源提問的最佳結構。"""
    names = _speaker_names(store, session.id)
    caps = store.list_captions(session.id, final_only=True)
    if scope == "starred_only":
        caps = [c for c in caps if c.starred]

    lines = [f"# {session.title} — {session.created_at.date().isoformat()}", ""]
    summary = store.get_summary(session.id)
    if summary:
        lines += [summary.content_md.rstrip(), ""]
    else:
        lines += ["## 摘要", "(尚未產生摘要)", ""]

    if scope != "summary_only":
        lines.append("## 逐字稿")
        for c in caps:
            who = names.get(c.speaker_id or "", c.speaker_id or "未標註講者")
            lines.append(f"[{_hms(c.t_start)}] {who}:{_line_text(c)}")
            if c.translated_text and c.source_text != c.translated_text:
                lines.append(f"    └ 原文:{c.source_text}")
        lines.append("")
    return "\n".join(lines)


def to_txt(store: Store, session: Session) -> str:
    names = _speaker_names(store, session.id)
    out = []
    for c in store.list_captions(session.id, final_only=True):
        who = names.get(c.speaker_id or "", c.speaker_id or "?")
        out.append(f"[{_hms(c.t_start)}] {who}: {_line_text(c)}")
    return "\n".join(out) + "\n"


def to_srt(store: Store, session: Session) -> str:
    out = []
    for i, c in enumerate(store.list_captions(session.id, final_only=True), 1):
        end = c.t_end if c.t_end is not None else c.t_start + 2.0
        out += [str(i), f"{_srt_ts(c.t_start)} --> {_srt_ts(end)}", _line_text(c), ""]
    return "\n".join(out)


def to_vtt(store: Store, session: Session) -> str:
    out = ["WEBVTT", ""]
    for c in store.list_captions(session.id, final_only=True):
        end = c.t_end if c.t_end is not None else c.t_start + 2.0
        out += [f"{_vtt_ts(c.t_start)} --> {_vtt_ts(end)}", _line_text(c), ""]
    return "\n".join(out)


EXPORTERS = {"md": to_notebooklm_markdown, "txt": to_txt, "srt": to_srt, "vtt": to_vtt}
MEDIA_TYPES = {"md": "text/markdown", "txt": "text/plain",
               "srt": "application/x-subrip", "vtt": "text/vtt"}
