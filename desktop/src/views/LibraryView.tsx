import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import CaptionOutline from "../components/CaptionOutline";
import ForwardDialog from "../components/ForwardDialog";
import SpeakerPanel from "../components/SpeakerPanel";
import type { Caption, Session, Speaker } from "../types";

const TEMPLATES = [
  ["general", "一般會議"],
  ["interview", "訪談"],
  ["lecture", "課程"],
  ["support", "客服"],
] as const;

/** 紀錄庫(UI 規劃書 §03):session 清單 + 詳情(摘要置頂/逐字稿/匯出/轉發)。 */
export default function LibraryView({
  selectedId,
  onSelect,
}: {
  selectedId: string | null;
  onSelect: (id: string | null) => void;
}) {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [detail, setDetail] = useState<{
    session: Session;
    speakers: Speaker[];
    summary: { content_md: string } | null;
  } | null>(null);
  const [captions, setCaptions] = useState<Caption[]>([]);
  const [busy, setBusy] = useState(false);
  const [template, setTemplate] = useState("general");
  const [showForward, setShowForward] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const refreshList = useCallback(() => {
    api.listSessions().then(setSessions).catch(() => setSessions([]));
  }, []);
  useEffect(refreshList, [refreshList]);

  const captionCount = useCallback(async (id: string) => {
    try {
      return (await api.captions(id)).length;
    } catch {
      return -1;
    }
  }, []);

  const deleteOne = async (id: string) => {
    if (!window.confirm("刪除此紀錄?(字幕、講者、摘要一併刪除,無法復原)")) return;
    await api.deleteSession(id);
    if (selectedId === id) onSelect(null);
    refreshList();
  };

  const cleanEmpty = async () => {
    if (!window.confirm("清理所有「無字幕」與「錯誤」的紀錄?")) return;
    const fresh = await api.listSessions(); // 用最新狀態,避免畫面 state 過期
    let n = 0;
    for (const it of fresh) {
      if (it.status === "recording") continue;
      if (it.status === "error" || (await captionCount(it.id)) === 0) {
        await api.deleteSession(it.id);
        n++;
      }
    }
    setMsg(`✓ 已清理 ${n} 筆`);
    if (selectedId) onSelect(null);
    refreshList();
  };

  const deleteAll = async () => {
    if (!window.confirm(`刪除全部 ${sessions.length} 筆紀錄?此動作無法復原!`)) return;
    const fresh = await api.listSessions();
    for (const it of fresh) {
      if (it.status === "recording") continue; // 錄製中不動
      await api.deleteSession(it.id);
    }
    onSelect(null);
    refreshList();
  };

  const openDetail = useCallback((id: string) => {
    api.getSession(id).then(setDetail).catch(() => setDetail(null));
    api.captions(id).then(setCaptions).catch(() => setCaptions([]));
  }, []);

  useEffect(() => {
    if (selectedId) openDetail(selectedId);
    else setDetail(null);
  }, [selectedId, openDetail]);

  const s = detail?.session;
  const speakerMap = new Map((detail?.speakers ?? []).map((sp) => [sp.id, sp]));

  const summarize = async () => {
    if (!s) return;
    setBusy(true);
    try {
      await api.summarize(s.id, template);
      openDetail(s.id);
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid h-full grid-cols-[260px_1fr]">
      {/* 清單 */}
      <div className="overflow-y-auto border-r border-line bg-[#141720] p-3">
        {sessions.length > 0 && (
          <div className="mb-2 flex gap-1.5">
            <button
              onClick={cleanEmpty}
              className="flex-1 rounded-lg border border-line bg-panel2 px-2 py-1.5 text-[11px] text-tx2"
              title="刪除無字幕與錯誤的紀錄"
            >
              🧹 清理空白/錯誤
            </button>
            <button
              onClick={deleteAll}
              className="rounded-lg border border-brand-deep/60 bg-panel2 px-2 py-1.5 text-[11px] text-brand-deep"
              title="刪除全部紀錄(錄製中除外)"
            >
              🗑 全部刪除
            </button>
          </div>
        )}
        {sessions.map((it) => (
          <button
            key={it.id}
            onClick={() => onSelect(it.id)}
            className={`mb-1 block w-full rounded-lg px-3 py-2.5 text-left ${
              selectedId === it.id ? "bg-brand/15" : "hover:bg-panel2"
            }`}
          >
            <div className="truncate text-[12.5px] font-semibold">{it.title}</div>
            <div className="text-[11px] text-tx3">
              {new Date(it.created_at).toLocaleString("zh-TW")} ·{" "}
              {it.kind === "live" ? "即時" : "離線"} · {it.status}
            </div>
            {it.notebooklm_forwarded_at && (
              <span className="mt-1 inline-block rounded-full bg-panel2 px-2 py-px text-[10px] text-[#8ab0ff]">
                已轉發 NBLM
              </span>
            )}
          </button>
        ))}
        {sessions.length === 0 && (
          <div className="mt-8 text-center text-[12.5px] text-tx3">尚無紀錄</div>
        )}
      </div>

      {/* 詳情 */}
      <div className="flex min-w-0 flex-col overflow-y-auto p-5">
        {!s && <div className="m-auto text-[13px] text-tx3">選擇左側紀錄檢視詳情</div>}
        {s && (
          <>
            <div className="flex items-start gap-3">
              <div>
                <div className="text-[15px] font-bold">{s.title}</div>
                <div className="mt-0.5 text-[11.5px] text-tx3">
                  {new Date(s.created_at).toLocaleString("zh-TW")} · {s.mode}
                  {s.topic ? ` · 主題:${s.topic}` : ""}
                </div>
              </div>
            </div>

            {detail?.summary && (
              <div className="mt-3 whitespace-pre-wrap rounded-xl border border-line border-l-4 border-l-brand bg-panel px-4 py-3 text-[13px] text-tx2">
                {detail.summary.content_md}
              </div>
            )}

            <div className="mt-3 flex flex-wrap items-center gap-2">
              {["md", "txt", "srt", "vtt"].map((f) => (
                <a
                  key={f}
                  href={api.exportUrl(s.id, f)}
                  target="_blank"
                  className="rounded-lg border border-line bg-panel2 px-3 py-1.5 text-[12px] uppercase"
                >
                  {f}
                </a>
              ))}
              <select
                value={template}
                onChange={(e) => setTemplate(e.target.value)}
                className="rounded-lg border border-line bg-panel2 px-2 py-1.5 text-[12px]"
                title="摘要模板"
              >
                {TEMPLATES.map(([v, label]) => (
                  <option key={v} value={v}>{label}</option>
                ))}
              </select>
              <button
                onClick={summarize}
                disabled={busy}
                className="rounded-lg border border-line bg-panel2 px-3 py-1.5 text-[12px] disabled:opacity-40"
              >
                {detail?.summary ? "🔄 重新摘要" : "✨ 產生摘要"}
              </button>
              <button
                onClick={() => setShowForward(true)}
                disabled={busy}
                className="rounded-lg border border-brand-deep bg-brand/15 px-3 py-1.5 text-[12px] font-semibold text-brand disabled:opacity-40"
              >
                📤 NotebookLM
              </button>
              <button
                onClick={() => deleteOne(s.id)}
                disabled={busy || s.status === "recording"}
                className="ml-auto rounded-lg border border-line bg-panel2 px-3 py-1.5 text-[12px] text-brand-deep disabled:opacity-40"
                title="刪除此紀錄"
              >
                🗑 刪除
              </button>
            </div>
            {msg && <div className="mt-2 text-[12px] text-tx2">{msg}</div>}

            <div className="mt-4 grid grid-cols-[1fr_200px] gap-4">
              <div className="flex flex-col gap-2.5">
                <CaptionOutline
                  captions={captions}
                  speakers={speakerMap}
                  collapseAll
                  onStar={(seq) =>
                    api.star(s.id, seq).then(() => openDetail(s.id)).catch(() => {})}
                />
                {captions.length === 0 && (
                  <div className="text-[12.5px] text-tx3">(無字幕資料)</div>
                )}
              </div>
              <div>
                <SpeakerPanel
                  speakers={detail?.speakers ?? []}
                  onRename={(id, name) =>
                    api.renameSpeaker(s.id, id, name).then(() => openDetail(s.id))
                  }
                />
              </div>
            </div>
          </>
        )}
      </div>

      {showForward && s && (
        <ForwardDialog
          session={s}
          onClose={() => setShowForward(false)}
          onDone={() => {
            setShowForward(false);
            setMsg("✓ 內容已複製到剪貼簿並開啟 NotebookLM:新增來源 →「複製的文字」→ 貼上即完成");
            openDetail(s.id);
            refreshList();
          }}
        />
      )}
    </div>
  );
}
