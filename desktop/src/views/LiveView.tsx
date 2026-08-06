import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import CaptionOutline from "../components/CaptionOutline";
import SpeakerPanel from "../components/SpeakerPanel";
import type { Session, Speaker } from "../types";
import { useCaptionStream } from "../ws";

const MODES = [
  ["en2zh", "英 → 繁中"],
  ["zh2en", "中 → 英"],
  ["ja2zh", "日 → 繁中"],
  ["en", "英文轉錄"],
  ["zh", "中文轉錄"],
] as const;


export default function LiveView({
  engineOk,
  vendorOk = true,
  onGoSettings,
}: {
  engineOk: boolean;
  vendorOk?: boolean;
  onGoSettings?: () => void;
}) {
  const [session, setSession] = useState<Session | null>(null);
  const [speakers, setSpeakers] = useState<Speaker[]>([]);
  const [mode, setMode] = useState<string>("en2zh");
  const [topic, setTopic] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [kwHits, setKwHits] = useState<Map<string, number>>(new Map());
  const [diag, setDiag] = useState<string | null>(null);
  const [diagBusy, setDiagBusy] = useState(false);

  const runDiag = async () => {
    setDiagBusy(true);
    setDiag("診斷中…請保持影片/音訊播放(約 6 秒)");
    try {
      const r = await api.audioDiag();
      setDiag(r.advice);
    } catch (e) {
      setDiag(`診斷失敗:${String(e)}`);
    } finally {
      setDiagBusy(false);
    }
  };

  const recording = session?.status === "recording";
  const { captions, connected, capped, lastEvent, setCaptions } =
    useCaptionStream(session?.id ?? null);
  const streamRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!recording || !session) return;
    // 以 session 建立時間為基準:視窗重開接回時顯示真實錄製時長
    const t0 = new Date(session.created_at).getTime();
    const tick = () => setElapsed(Math.max(0, Math.floor((Date.now() - t0) / 1000)));
    tick();
    const t = setInterval(tick, 1000);
    return () => clearInterval(t);
  }, [recording, session?.id]);

  // 視窗重開(系統匣模式)自動接回引擎上進行中的錄製,避免狀態失聯與 409
  useEffect(() => {
    if (!engineOk || session) return;
    api
      .listSessions()
      .then((all) => {
        const rec = all.find((s) => s.kind === "live" && s.status === "recording");
        if (rec) {
          setSession(rec);
          api.getSession(rec.id).then((d) => setSpeakers(d.speakers)).catch(() => {});
        }
      })
      .catch(() => {});
  }, [engineOk, session]);

  useEffect(() => {
    if (!lastEvent || !session) return;
    if (lastEvent.type === "speaker" || lastEvent.type === "caption") {
      api.getSession(session.id).then((d) => setSpeakers(d.speakers)).catch(() => {});
    }
    if (lastEvent.type === "summary") setSummary(String(lastEvent.data.content_md ?? ""));
    if (lastEvent.type === "keyword") {
      const kw = String(lastEvent.data.keyword);
      setKwHits((prev) => new Map(prev).set(kw, (prev.get(kw) ?? 0) + 1));
    }
    if (lastEvent.type === "engine" && lastEvent.data.type === "idle_stop") {
      setError(`⏱ ${String(lastEvent.data.detail ?? "已因閒置自動停止錄製")}`);
    }
    if (lastEvent.type === "status" && lastEvent.data.status === "done") {
      setSession((s) => (s ? { ...s, status: "done" } : s));
    }
  }, [lastEvent, session?.id]);

  useEffect(() => {
    streamRef.current?.scrollTo({ top: streamRef.current.scrollHeight });
  }, [captions.length]);

  const speakerMap = useMemo(() => new Map(speakers.map((s) => [s.id, s])), [speakers]);

  const start = useCallback(async () => {
    setBusy(true);
    setError(null);
    setSummary(null);
    setSession(null); // 新會議:立即清空上一場畫面
    setKwHits(new Map());
    try {
      const s = await api.liveStart(
        `即時會議 ${new Date().toLocaleString("zh-TW")}`,
        mode,
        topic.trim() || null,
      );
      setSession(s);
      setElapsed(0);
      setKwHits(new Map());
    } catch (e) {
      // 409:引擎上已有進行中的場次 → 直接接回,不報錯
      if (String(e).includes("409")) {
        try {
          const all = await api.listSessions();
          const rec = all.find((x) => x.kind === "live" && x.status === "recording");
          if (rec) {
            setSession(rec);
            setError(null);
            return;
          }
        } catch { /* fallthrough */ }
      }
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }, [mode, topic]);

  const stop = useCallback(async () => {
    if (!session) return;
    setBusy(true);
    try {
      setSession(await api.stop(session.id));
    } catch (e) {
      if (String(e).includes("404")) {
        // session 已不存在(引擎重啟後的殭屍)→ 復位回待機,不卡在錄製畫面
        setSession(null);
        setError("該場錄製已不存在(引擎曾重啟),已重置,可重新開始錄製");
      } else {
        setError(String(e));
      }
    } finally {
      setBusy(false);
    }
  }, [session]);

  // 全域快捷鍵 Ctrl+Shift+R(Rust 端 emit;非 Tauri 環境略過)
  const toggleRef = useRef<() => void>(() => {});
  useEffect(() => {
    toggleRef.current = () => (recording ? stop() : start());
  });
  useEffect(() => {
    let un: (() => void) | undefined;
    import("@tauri-apps/api/event")
      .then(({ listen }) => listen("konjac://toggle-record", () => toggleRef.current()))
      .then((u) => (un = u))
      .catch(() => {});
    return () => un?.();
  }, []);

  const toggleOverlay = useCallback(async () => {
    try {
      const { Window } = await import("@tauri-apps/api/window");
      const w = await Window.getByLabel("overlay");
      if (!w) return;
      (await w.isVisible()) ? await w.hide() : await w.show();
    } catch {
      setError("懸浮字幕僅桌面 App 環境可用");
    }
  }, []);

  const hhmmss = (s: number) =>
    [Math.floor(s / 3600), Math.floor((s % 3600) / 60), s % 60]
      .map((n) => String(n).padStart(2, "0"))
      .join(":");

  return (
    <div className="grid h-full grid-cols-[1fr_230px]">
      <div className="flex min-w-0 flex-col">
        <div className="flex flex-wrap items-center gap-2.5 border-b border-line px-4 py-3">
          <select
            value={mode}
            disabled={recording}
            onChange={(e) => setMode(e.target.value)}
            className="rounded-lg border border-line bg-panel2 px-3 py-1.5 text-[12.5px]"
          >
            {MODES.map(([v, label]) => (
              <option key={v} value={v}>{label}</option>
            ))}
          </select>
          <input
            value={topic}
            disabled={recording}
            onChange={(e) => setTopic(e.target.value)}
            placeholder="會議主題(提升術語翻譯)"
            className="w-56 rounded-lg border border-line bg-panel2 px-3 py-1.5 text-[12.5px] placeholder:text-tx3"
          />
          {recording && <span className="font-mono text-[13px] text-tx2">{hhmmss(elapsed)}</span>}
          <button
            onClick={recording ? stop : start}
            disabled={busy || !engineOk}
            className={`ml-auto rounded-lg px-5 py-2 text-[13.5px] font-bold disabled:opacity-40 ${
              recording
                ? "bg-gradient-to-br from-brand to-brand-deep text-[#1c0d12]"
                : "border border-brand-deep bg-brand/15 text-brand"
            }`}
          >
            {recording ? "■ 停止錄製" : "● 開始錄製"}
          </button>
        </div>

        {engineOk && !vendorOk && (
          <div className="flex items-center gap-3 border-b border-line bg-[#3a2f14] px-4 py-2 text-[12px] text-[#ffc46b]">
            ⚠ AI 語音管線(jt-live-whisper)尚未設定,無法轉錄。
            <button
              onClick={onGoSettings}
              className="rounded-md border border-[#ffc46b] px-2.5 py-1 text-[11.5px]"
            >
              前往設定 →
            </button>
          </div>
        )}
        {error && (
          <div className="border-b border-line bg-brand-deep/20 px-4 py-2 text-[12px] text-brand">
            {error}
          </div>
        )}
        {diag && (
          <div className="flex items-start gap-2 border-b border-line bg-panel px-4 py-2 text-[12px] text-tx2">
            <span className="flex-1 whitespace-pre-wrap">🔊 {diag}</span>
            <button onClick={() => setDiag(null)} className="text-tx3 hover:text-tx2">✕</button>
          </div>
        )}

        <div ref={streamRef} className="flex flex-1 flex-col gap-3 overflow-y-auto p-4">
          {captions.length === 0 && (
            <div className="m-auto text-center text-[13px] text-tx3">
              {recording
                ? connected
                  ? "等待第一句字幕…"
                  : "連線字幕流中…"
                : "按「開始錄製」擷取系統音訊並即時轉錄翻譯(Ctrl+Shift+R)"}
            </div>
          )}
          {capped && (
            <div className="rounded-lg border border-line bg-panel px-3 py-1.5 text-center text-[11px] text-tx3">
              為維持效能僅顯示最新 1000 句;完整內容請至「紀錄庫」檢視
            </div>
          )}
          <CaptionOutline
            captions={captions}
            speakers={speakerMap}
            live={recording}
            onStar={(seq) => session && api.star(session.id, seq).catch(() => {})}
          />
          {summary && (
            <div className="whitespace-pre-wrap rounded-xl border border-line border-l-4 border-l-brand bg-panel px-4 py-3 text-[13px] text-tx2">
              {summary}
            </div>
          )}
        </div>

        <div className="flex gap-2.5 border-t border-line px-4 py-3">
          <button
            disabled={!session || captions.length === 0}
            onClick={() => session && api.summarize(session.id).catch((e) => setError(String(e)))}
            className="rounded-lg border border-line bg-panel2 px-4 py-2 text-[12.5px] disabled:opacity-40"
          >
            ✨ 產生摘要
          </button>
          <button
            onClick={toggleOverlay}
            className="rounded-lg border border-line bg-panel2 px-4 py-2 text-[12.5px]"
          >
            🪟 懸浮字幕
          </button>
          <button
            onClick={runDiag}
            disabled={diagBusy || !engineOk}
            className="rounded-lg border border-line bg-panel2 px-4 py-2 text-[12.5px] disabled:opacity-40"
            title="播放影片時按下,檢查聲音是否流向轉錄抓取的裝置"
          >
            🔊 音訊診斷
          </button>
          {session && (
            <a
              href={api.exportUrl(session.id, "md")}
              target="_blank"
              className="rounded-lg border border-line bg-panel2 px-4 py-2 text-[12.5px]"
            >
              ⬇ 匯出 MD
            </a>
          )}
          <div className="flex-1" />
          <button
            disabled={!session || captions.length === 0}
            onClick={() =>
              session &&
              api
                .forwardNotebookLM(session.id, "翻譯蒟蒻紀錄", "full", true, true)
                .then(() =>
                  setError("✓ 內容已複製到剪貼簿並開啟 NotebookLM:新增來源 →「複製的文字」→ 貼上"))
                .catch((e) => setError(String(e)))
            }
            className="rounded-lg border border-brand-deep bg-brand/15 px-4 py-2 text-[12.5px] font-semibold text-brand disabled:opacity-40"
          >
            📤 轉發 NotebookLM
          </button>
        </div>
      </div>

      <aside className="border-l border-line bg-[#141720] p-3.5">
        <SpeakerPanel
          speakers={speakers}
          onRename={(id, name) =>
            session && api.renameSpeaker(session.id, id, name).then(setSpeakers).catch(() => {})
          }
        />
        {recording && speakers.length === 0 && (
          <div className="mt-2 text-[11px] leading-relaxed text-tx3">
            即時模式不即時標講者;停止錄製後按「講者精析」以錄音重新分析歸屬。
          </div>
        )}
        {!recording && session?.status === "done" && session.recording_path && (
          <button
            onClick={async () => {
              setError("👥 講者精析中…(重新分析錄音,長度較長時需數分鐘)");
              try {
                const r = await api.diarize(session.id);
                const fresh = await api.captions(session.id);
                setCaptions(fresh);
                const d = await api.getSession(session.id);
                setSpeakers(d.speakers);
                setError(`✓ 講者精析完成:${r.updated} 句、${d.speakers.length} 位講者`);
              } catch (e) {
                setError(String(e));
              }
            }}
            className="mt-2 w-full rounded-lg border border-line bg-panel2 px-3 py-2 text-[12px]"
          >
            👥 講者精析
          </button>
        )}
        {kwHits.size > 0 && (
          <>
            <h4 className="mb-2 mt-5 text-[11px] uppercase tracking-wider text-tx3">
              關鍵字命中
            </h4>
            <div className="flex flex-wrap gap-1.5">
              {[...kwHits.entries()].map(([kw, n]) => (
                <span
                  key={kw}
                  className="rounded-full border border-[#ffc46b] px-2.5 py-0.5 text-[11.5px] text-[#ffc46b]"
                >
                  {kw} ⚡{n}
                </span>
              ))}
            </div>
          </>
        )}
      </aside>
    </div>
  );
}
