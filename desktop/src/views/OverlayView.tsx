import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { Session } from "../types";
import { useCaptionStream } from "../ws";

/** 懸浮字幕視窗(UI 規劃書 §02):自動跟隨進行中的 live session,
 * 顯示最新一句;hover 顯示工具鈕;data-tauri-drag-region 可拖曳。 */
export default function OverlayView() {
  const [session, setSession] = useState<Session | null>(null);
  const [fontScale, setFontScale] = useState(1);
  const [showSrc, setShowSrc] = useState(true);

  // 每 3 秒探測進行中的 live session(引擎重啟/換場自動跟隨)
  useEffect(() => {
    const tick = async () => {
      try {
        const sessions = await api.listSessions();
        const rec = sessions.find((s) => s.status === "recording" && s.kind === "live");
        setSession((cur) => (cur?.id === rec?.id ? cur : rec ?? null));
      } catch {
        setSession(null);
      }
    };
    tick();
    const t = setInterval(tick, 3000);
    return () => clearInterval(t);
  }, []);

  const { captions } = useCaptionStream(session?.id ?? null);
  const last = captions.length ? captions[captions.length - 1] : null;

  const hide = async () => {
    try {
      const { getCurrentWindow } = await import("@tauri-apps/api/window");
      await getCurrentWindow().hide();
    } catch {
      /* 瀏覽器預覽環境 */
    }
  };

  const main = useMemo(
    () => (last ? last.translated_text ?? last.source_text : null),
    [last],
  );

  return (
    <div className="group flex h-screen w-screen items-end justify-center bg-transparent p-2">
      <div
        data-tauri-drag-region
        className="relative w-full rounded-2xl border border-white/10 bg-[#0a0c10]/85 px-5 py-3 shadow-2xl backdrop-blur"
      >
        {/* hover 工具鈕 */}
        <div className="absolute -top-3.5 right-3 hidden gap-1.5 group-hover:flex">
          <button
            onClick={() => setFontScale((f) => Math.min(1.6, f + 0.15))}
            className="h-7 w-7 rounded-lg border border-line bg-panel2 text-[12px] text-tx2"
            title="放大字級"
          >
            A+
          </button>
          <button
            onClick={() => setFontScale((f) => Math.max(0.7, f - 0.15))}
            className="h-7 w-7 rounded-lg border border-line bg-panel2 text-[12px] text-tx2"
            title="縮小字級"
          >
            A-
          </button>
          <button
            onClick={() => setShowSrc((v) => !v)}
            className="h-7 w-7 rounded-lg border border-line bg-panel2 text-[12px] text-tx2"
            title="原文顯示開關"
          >
            ◐
          </button>
          <button
            onClick={hide}
            className="h-7 w-7 rounded-lg border border-line bg-panel2 text-[12px] text-tx2"
            title="隱藏(主視窗可重新開啟)"
          >
            ✕
          </button>
        </div>

        {!session && (
          <div className="text-center text-[13px] text-tx3">
            等待錄製開始…(在主視窗按「開始錄製」)
          </div>
        )}
        {session && !last && (
          <div className="text-center text-[13px] text-tx3">等待第一句字幕…</div>
        )}
        {last && (
          <>
            {showSrc && last.translated_text && last.source_text !== last.translated_text && (
              <div
                className="mb-0.5 truncate text-[#aeb6c8]"
                style={{ fontSize: `${12.5 * fontScale}px` }}
              >
                {last.source_text}
              </div>
            )}
            <div
              className="font-semibold text-white"
              style={{ fontSize: `${18 * fontScale}px`, lineHeight: 1.35 }}
            >
              {main}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
