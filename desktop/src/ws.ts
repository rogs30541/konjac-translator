import { useEffect, useRef, useState } from "react";
import { ENGINE_WS } from "./api";
import type { Caption, WsEvent } from "./types";

// 即時視圖記憶體上限:僅保留最新 N 句(完整內容永遠在紀錄庫);
// 防止超長錄製讓 WebView 記憶體無限成長
const MAX_LIVE_CAPTIONS = 1000;

/** 訂閱 session 字幕流:自動重連,以 seq 去重(引擎重連會補發 final)。 */
export function useCaptionStream(sessionId: string | null) {
  const [captions, setCaptions] = useState<Caption[]>([]);
  const [connected, setConnected] = useState(false);
  const [capped, setCapped] = useState(false);
  const [lastEvent, setLastEvent] = useState<WsEvent | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    // 換場(新會議)即清空畫面與截斷旗標
    setCaptions([]);
    setCapped(false);
    if (!sessionId) return;
    let closed = false;
    let retry: number | undefined;

    const connect = () => {
      const ws = new WebSocket(`${ENGINE_WS}/ws/sessions/${sessionId}`);
      wsRef.current = ws;
      ws.onopen = () => setConnected(true);
      ws.onmessage = (m) => {
        const ev = JSON.parse(m.data) as WsEvent;
        setLastEvent(ev);
        if (ev.type === "caption") {
          const cap = ev.data as unknown as Caption;
          setCaptions((prev) => {
            const i = prev.findIndex((c) => c.seq === cap.seq);
            let next: Caption[];
            if (i >= 0) {
              next = prev.slice();
              next[i] = cap;
            } else {
              next = [...prev, cap].sort((a, b) => a.seq - b.seq);
            }
            if (next.length > MAX_LIVE_CAPTIONS) {
              setCapped(true);
              next = next.slice(next.length - MAX_LIVE_CAPTIONS);
            }
            return next;
          });
        }
      };
      ws.onclose = () => {
        setConnected(false);
        if (!closed) retry = window.setTimeout(connect, 1500);
      };
      ws.onerror = () => ws.close();
    };
    connect();
    return () => {
      closed = true;
      if (retry) window.clearTimeout(retry);
      wsRef.current?.close();
    };
  }, [sessionId]);

  return { captions, connected, capped, lastEvent, setCaptions };
}
