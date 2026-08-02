import type { Caption, Speaker } from "../types";

function hms(t: number): string {
  const s = Math.floor(t);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(Math.floor(s / 3600))}:${p(Math.floor((s % 3600) / 60))}:${p(s % 60)}`;
}

interface Props {
  cap: Caption;
  speakers: Map<string, Speaker>;
  live?: boolean;
  onStar?: (seq: number) => void;
}

/** 三端共用的字幕卡片:講者色票 + 時戳 + 原文(小)+ 譯文(大)。 */
export default function CaptionCard({ cap, speakers, live, onStar }: Props) {
  const spk = cap.speaker_id ? speakers.get(cap.speaker_id) : undefined;
  const main = cap.translated_text ?? cap.source_text;
  const showSrc = cap.translated_text && cap.source_text !== cap.translated_text;

  return (
    <div
      className={`rounded-xl border bg-panel px-4 py-3 ${
        live ? "border-brand-deep shadow-[0_0_0_1px_rgba(255,143,163,.14)]" : "border-line"
      }`}
    >
      <div className="mb-1.5 flex items-center gap-2 text-[11.5px] text-tx3">
        {cap.speaker_id && (
          <span
            className="rounded-full px-2 py-px text-[11px] font-semibold"
            style={{
              color: spk?.color ?? "#9aa1b4",
              backgroundColor: `${spk?.color ?? "#9aa1b4"}29`,
            }}
          >
            {spk?.display_name ?? cap.speaker_id}
          </span>
        )}
        <span>{hms(cap.t_start)}</span>
        <span>{cap.source_channel === "mic" ? "🎙 麥克風" : "🔊 系統音訊"}</span>
        {onStar && (
          <button
            onClick={() => onStar(cap.seq)}
            className={`ml-auto ${cap.starred ? "text-brand" : "text-tx3 hover:text-tx2"}`}
            title="標記重點"
          >
            ★
          </button>
        )}
      </div>
      {showSrc && <div className="mb-0.5 text-[12.5px] text-tx3">{cap.source_text}</div>}
      <div className="text-[15.5px]">
        {main}
        {live && <span className="caret" />}
      </div>
    </div>
  );
}
