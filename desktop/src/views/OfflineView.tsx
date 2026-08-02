import { useCallback, useRef, useState } from "react";
import { ENGINE_BASE } from "../api";

interface Job {
  job_id: string;
  session_id: string;
  status: string;
  error: string | null;
  filename: string;
}

const MODES = [
  ["en2zh", "英 → 繁中"],
  ["en", "英文轉錄"],
  ["zh", "中文轉錄"],
  ["ja2zh", "日 → 繁中"],
] as const;

/** 離線處理頁(UI 規劃書 §03):拖曳/選檔批次上傳、輸出選項、任務進度。 */
export default function OfflineView({ onOpenSession }: { onOpenSession: (id: string) => void }) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [mode, setMode] = useState("en");
  const [diarize, setDiarize] = useState(true);
  const [drag, setDrag] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const poll = useCallback((jobId: string) => {
    const t = setInterval(async () => {
      try {
        const r = await fetch(`${ENGINE_BASE}/api/offline/jobs/${jobId}`);
        const job = await r.json();
        setJobs((prev) => prev.map((j) => (j.job_id === jobId ? { ...j, ...job } : j)));
        if (job.status !== "processing") clearInterval(t);
      } catch {
        clearInterval(t);
      }
    }, 1500);
  }, []);

  const upload = useCallback(
    async (files: FileList | File[]) => {
      setError(null);
      for (const file of Array.from(files)) {
        const form = new FormData();
        form.append("file", file);
        try {
          const r = await fetch(
            `${ENGINE_BASE}/api/offline/jobs?mode=${mode}&diarize=${diarize}&title=${encodeURIComponent(file.name)}`,
            { method: "POST", body: form },
          );
          if (!r.ok) throw new Error(await r.text());
          const job = await r.json();
          setJobs((prev) => [{ ...job, filename: file.name }, ...prev]);
          poll(job.job_id);
        } catch (e) {
          setError(`${file.name}: ${String(e)}`);
        }
      }
    },
    [mode, diarize, poll],
  );

  return (
    <div className="flex h-full flex-col p-5">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrag(false);
          upload(e.dataTransfer.files);
        }}
        onClick={() => fileRef.current?.click()}
        className={`cursor-pointer rounded-2xl border-2 border-dashed p-9 text-center text-[13.5px] transition-colors ${
          drag ? "border-brand bg-brand/5 text-brand" : "border-line text-tx3"
        }`}
      >
        ⬇ 拖曳音訊檔到這裡,或點擊選擇
        <div className="mt-1 text-[12px]">
          <b className="text-tx2">mp3 · wav · m4a · flac</b> — 支援批次
        </div>
        <input
          ref={fileRef}
          type="file"
          multiple
          accept=".mp3,.wav,.m4a,.flac"
          className="hidden"
          onChange={(e) => e.target.files && upload(e.target.files)}
        />
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-4 text-[12.5px] text-tx2">
        <select
          value={mode}
          onChange={(e) => setMode(e.target.value)}
          className="rounded-lg border border-line bg-panel2 px-3 py-1.5"
        >
          {MODES.map(([v, label]) => (
            <option key={v} value={v}>{label}</option>
          ))}
        </select>
        <label className="flex items-center gap-1.5">
          <input type="checkbox" checked={diarize} onChange={(e) => setDiarize(e.target.checked)} />
          講者辨識
        </label>
        <span className="text-[11.5px] text-tx3">
          en2zh/ja2zh 需要 LLM 翻譯伺服器;純轉錄選「英文/中文轉錄」
        </span>
      </div>

      {error && (
        <div className="mt-3 rounded-lg bg-brand-deep/20 px-3 py-2 text-[12px] text-brand">{error}</div>
      )}

      <div className="mt-4 flex-1 overflow-y-auto">
        {jobs.map((j) => (
          <div key={j.job_id} className="flex items-center gap-3 border-t border-line px-2 py-3 text-[12.5px]">
            <span className="w-52 truncate font-mono text-[12px]">{j.filename}</span>
            {j.status === "processing" && (
              <span className="animate-pulse text-tx2">辨識中…(GPU faster-whisper)</span>
            )}
            {j.status === "done" && (
              <>
                <span className="text-ok">✓ 完成</span>
                <button
                  onClick={() => onOpenSession(j.session_id)}
                  className="rounded-lg border border-line bg-panel2 px-3 py-1 text-[12px]"
                >
                  開啟紀錄 →
                </button>
              </>
            )}
            {j.status === "error" && (
              <span className="text-brand-deep">✗ 失敗:{j.error || "未知錯誤"}</span>
            )}
          </div>
        ))}
        {jobs.length === 0 && (
          <div className="mt-8 text-center text-[12.5px] text-tx3">尚無離線任務</div>
        )}
      </div>
    </div>
  );
}
