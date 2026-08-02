"""字幕 Webhook 轉發:Telegram / Slack / Discord / 一般 JSON POST。

設定格式(settings.json 的 webhooks 陣列,每項一個 dict):
  {"type": "discord", "url": "https://discord.com/api/webhooks/..."}
  {"type": "slack",   "url": "https://hooks.slack.com/services/..."}
  {"type": "telegram","bot_token": "123:abc", "chat_id": "456"}
  {"type": "generic", "url": "https://example.com/hook"}

失敗靜默忽略(fire-and-forget),不影響字幕流。
"""
from __future__ import annotations

from typing import Optional

import httpx

from ..models import Caption


def format_line(session_title: str, cap: Caption,
                speaker_name: Optional[str]) -> str:
    who = f"{speaker_name}:" if speaker_name else ""
    text = cap.translated_text or cap.source_text
    line = f"[{session_title}] {who}{text}"
    if cap.translated_text and cap.source_text != cap.translated_text:
        line += f"\n({cap.source_text})"
    return line


async def send_caption(webhooks: list[dict], session_title: str, cap: Caption,
                       speaker_name: Optional[str] = None,
                       client: Optional[httpx.AsyncClient] = None) -> int:
    """回傳成功送出的 webhook 數(供測試斷言)。"""
    if not webhooks:
        return 0
    text = format_line(session_title, cap, speaker_name)
    own_client = client is None
    client = client or httpx.AsyncClient(timeout=10.0)
    sent = 0
    try:
        for hook in webhooks:
            try:
                kind = hook.get("type", "generic")
                if kind == "telegram":
                    r = await client.post(
                        f"https://api.telegram.org/bot{hook['bot_token']}/sendMessage",
                        json={"chat_id": hook["chat_id"], "text": text})
                elif kind == "slack":
                    r = await client.post(hook["url"], json={"text": text})
                elif kind == "discord":
                    r = await client.post(hook["url"], json={"content": text})
                else:  # generic
                    r = await client.post(hook["url"], json={
                        "session": session_title, "seq": cap.seq,
                        "speaker": speaker_name, "source_text": cap.source_text,
                        "translated_text": cap.translated_text,
                        "t_start": cap.t_start})
                if r.status_code < 400:
                    sent += 1
            except Exception:
                continue  # 單一 webhook 失敗不影響其他
    finally:
        if own_client:
            await client.aclose()
    return sent
