import { useEffect, useState } from "react";
import { api, ENGINE_BASE } from "../api";
import type { Session } from "../types";

const SCOPES = [
  ["full", "摘要 + 完整逐字稿"],
  ["summary_only", "僅摘要"],
  ["starred_only", "僅重點標記段落"],
] as const;

interface Props {
  session: Session;
  onClose: () => void;
  onDone: () => void;
}

/** NotebookLM 轉發對話框(UI 規劃書 §05):筆記本、範圍、Markdown 預覽。 */
export default function ForwardDialog({ session, onClose, onDone }: Props) {
  const [notebook, setNotebook] = useState(session.notebooklm_target || "翻譯蒟蒻紀錄");
  const [scope, setScope] = useState<string>("full");
  const [preview, setPreview] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${ENGINE_BASE}/api/sessions/${session.id}/export?format=md&scope=${scope}`)
      .then((r) => r.text())
      .then(setPreview)
      .catch(() => setPreview("(預覽載入失敗)"));
  }, [session.id, scope]);

  const send = async () => {
    setBusy(true);
    setMsg(null);
    try {
      await api.forwardNotebookLM(
        session.id, notebook.trim() || "翻譯蒟蒻紀錄", scope,
        !!session.notebooklm_forwarded_at, true);
      onDone();
    } catch (e) {
      setMsg(String(e));
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-8"
      onClick={onClose}
    >
      <div
        className="w-[520px] rounded-2xl border border-line bg-panel p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-[15px] font-bold">📤 轉發到 NotebookLM</h3>
        <div className="mt-0.5 text-[12px] text-tx3">
          {session.title}
          {session.notebooklm_forwarded_at && "(先前已轉發,將重新送出)"}
        </div>

        <label className="mt-4 block text-[11.5px] text-tx3">
          目標筆記本
          <input
            value={notebook}
            onChange={(e) => setNotebook(e.target.value)}
            className="mt-1 block w-full rounded-lg border border-line bg-panel2 px-3 py-2 text-[13px] text-tx"
          />
        </label>

        <div className="mt-3 text-[11.5px] text-tx3">內容範圍</div>
        <div className="mt-1 flex gap-2">
          {SCOPES.map(([v, label]) => (
            <button
              key={v}
              onClick={() => setScope(v)}
              className={`flex-1 rounded-lg border px-2 py-2 text-[12px] ${
                scope === v
                  ? "border-brand-deep bg-brand/15 font-semibold text-brand"
                  : "border-line bg-panel2 text-tx2"
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="mt-3 flex items-baseline gap-2 text-[11.5px] text-tx3">
          <span>內容預覽(Markdown)</span>
          <span className="text-[10.5px]">
            完整 {preview.length.toLocaleString()} 字,全部都會複製
          </span>
        </div>
        <pre className="mt-1 max-h-48 overflow-y-auto whitespace-pre-wrap rounded-lg border border-line bg-bg px-3 py-2 font-mono text-[11px] leading-relaxed text-tx2">
          {preview}
        </pre>

        {msg && <div className="mt-2 text-[12px] text-brand">{msg}</div>}
        <div className="mt-4 flex justify-end gap-2.5">
          <button
            onClick={onClose}
            className="rounded-lg border border-line bg-panel2 px-4 py-2 text-[12.5px]"
          >
            取消
          </button>
          <button
            onClick={send}
            disabled={busy}
            className="rounded-lg border border-brand-deep bg-brand/15 px-4 py-2 text-[12.5px] font-semibold text-brand disabled:opacity-40"
          >
            {busy ? "送出中…" : "複製並開啟 NotebookLM"}
          </button>
        </div>
        <div className="mt-2 text-[10.5px] text-tx3">
          送出後:內容已在剪貼簿、NotebookLM 已開啟 → 選筆記本 →「新增來源」→
          「複製的文字」→ 貼上(Ctrl+V)即完成。
        </div>
      </div>
    </div>
  );
}
