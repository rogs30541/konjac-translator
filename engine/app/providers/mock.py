"""確定性 Mock provider:CI 與無模型環境用,行為完全可預測。"""
from __future__ import annotations

from ..models import CaptionIn


class MockOfflinePipeline:
    """把「檔名」當劇本:回傳固定兩句雙講者字幕,便於斷言。"""

    async def transcribe_file(self, path: str, mode: str,
                              diarize: bool) -> list[CaptionIn]:
        base = [
            CaptionIn(seq=1, t_start=0.0, t_end=3.2,
                      speaker_id="S1" if diarize else None,
                      source_text="Hello, this is a mock transcript.",
                      translated_text="你好,這是一段模擬逐字稿。", is_final=True),
            CaptionIn(seq=2, t_start=3.5, t_end=6.8,
                      speaker_id="S2" if diarize else None,
                      source_text="It exists so tests never need a GPU.",
                      translated_text="它的存在讓測試永遠不需要 GPU。", is_final=True),
        ]
        return base


class MockSummarizer:
    async def summarize(self, transcript_md: str, topic: str | None,
                        template: str = "general") -> str:
        head = f"(主題:{topic})" if topic else ""
        n_lines = len([l for l in transcript_md.splitlines() if l.strip()])
        return (
            f"## 摘要{head}[模板:{template}]\n"
            f"- 這是 mock 摘要,來源逐字稿共 {n_lines} 非空行\n"
            f"- 重點與待辦由真實 LLM provider 產生\n"
        )
