import { useEffect, useRef, useState } from "react";
import { ENGINE_WS } from "./api";
import type { Caption, WsEvent } from "./types";

/** 訂閱 session 字幕流:自動重連,以 seq 去重(引擎重連會補發 final)。 */
export function useCaptionStream(sessionId: string | null) {
  const [captions, setCaptions] = useState<Caption[]>([]);
  const [connected, setConnected] = useState(false);
  const [lastEvent, setLastEvent] = useState<WsEvent | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    setCaptions([]);
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
            if (i >= 0) {
              const next = prev.slice();
              next[i] = cap;
              return next;
            }
            return [...prev, cap].sort((a, b) => a.seq - b.seq);
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

  return { captions, connected, lastEvent, setCaptions };
}
