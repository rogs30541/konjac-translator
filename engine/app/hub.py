"""WebSocket hub:每個 session 一個頻道,把管線事件廣播給所有已連線前端。"""
from __future__ import annotations

import asyncio
from collections import defaultdict

from fastapi import WebSocket

from .models import WsEvent


class Hub:
    def __init__(self) -> None:
        self._channels: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def join(self, session_id: str, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._channels[session_id].add(ws)

    async def leave(self, session_id: str, ws: WebSocket) -> None:
        async with self._lock:
            self._channels[session_id].discard(ws)

    async def broadcast(self, session_id: str, event: WsEvent) -> None:
        dead: list[WebSocket] = []
        payload = event.model_dump()
        for ws in list(self._channels.get(session_id, ())):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._channels[session_id].discard(ws)
