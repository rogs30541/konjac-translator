import { useState } from "react";
import type { Speaker } from "../types";

interface Props {
  speakers: Speaker[];
  onRename: (id: string, name: string) => void;
}

export default function SpeakerPanel({ speakers, onRename }: Props) {
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  return (
    <div>
      <h4 className="mb-2 text-[11px] uppercase tracking-wider text-tx3">
        講者({speakers.length})
      </h4>
      {speakers.map((s) => (
        <div key={s.id} className="flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-panel2">
          <span className="h-2.5 w-2.5 flex-none rounded" style={{ background: s.color }} />
          {editing === s.id ? (
            <input
              autoFocus
              className="w-full rounded border border-line bg-panel2 px-1 text-[12.5px]"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && draft.trim()) {
                  onRename(s.id, draft.trim());
                  setEditing(null);
                }
                if (e.key === "Escape") setEditing(null);
              }}
              onBlur={() => setEditing(null)}
            />
          ) : (
            <>
              <span className="flex-1 text-[12.5px]">{s.display_name}</span>
              <button
                className="text-[11px] text-tx3 hover:text-tx2"
                onClick={() => {
                  setEditing(s.id);
                  setDraft(s.display_name);
                }}
              >
                ✎
              </button>
            </>
          )}
        </div>
      ))}
      {speakers.length === 0 && (
        <div className="px-2 text-[12px] text-tx3">尚未偵測到講者</div>
      )}
    </div>
  );
}
