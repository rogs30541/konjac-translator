import { useState } from "react";
import type { Caption, Speaker } from "../types";
import CaptionCard from "./CaptionCard";

export const GROUP_SIZE = 5; // 每滿 5 句收合為一段
export const CHAPTER_SEC = 15 * 60; // 每 15 分鐘的完整段落收合為一章

/** 中文句間補逗號直接串接;英文以空格串接。 */
export function mergeParagraph(parts: string[]): string {
  const cjk = /[一-鿿]/.test(parts.join(""));
  if (!cjk) return parts.join(" ");
  return parts
    .map((p, i) => {
      const t = p.trim();
      if (i === parts.length - 1) return t;
      return /[。!?,、;:….!?,]$/.test(t) ? t : `${t},`;
    })
    .join("");
}

function hms(t: number): string {
  const s = Math.floor(t);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(Math.floor(s / 3600))}:${p(Math.floor((s % 3600) / 60))}:${p(s % 60)}`;
}

interface Props {
  captions: Caption[];
  speakers: Map<string, Speaker>;
  live?: boolean;          // 最後一句顯示 streaming 游標
  collapseAll?: boolean;   // 紀錄庫:所有 15 分鐘視窗都收合成章節
  onStar?: (seq: number) => void;
}

/** 三層收合視圖:句 → 五句段落 → 15 分鐘章節(即時模式與紀錄庫共用)。 */
export default function CaptionOutline({
  captions, speakers, live, collapseAll, onStar,
}: Props) {
  const [expandedGroups, setExpandedGroups] = useState<Set<number>>(new Set());
  const [expandedChapters, setExpandedChapters] = useState<Set<number>>(new Set());

  const nGroups = Math.floor(captions.length / GROUP_SIZE);
  const grouped = Array.from({ length: nGroups }, (_, g) =>
    captions.slice(g * GROUP_SIZE, (g + 1) * GROUP_SIZE));
  const tail = captions.slice(nGroups * GROUP_SIZE);

  const latestT = captions.length ? captions[captions.length - 1].t_start : 0;
  const currentChapterIdx = collapseAll
    ? Number.POSITIVE_INFINITY
    : Math.floor(latestT / CHAPTER_SEC);
  const chapterMap = new Map<number, number[]>();
  const currentGroupIdxs: number[] = [];
  grouped.forEach((g, gi) => {
    const ch = Math.floor(g[0].t_start / CHAPTER_SEC);
    if (ch < currentChapterIdx) {
      if (!chapterMap.has(ch)) chapterMap.set(ch, []);
      chapterMap.get(ch)!.push(gi);
    } else {
      currentGroupIdxs.push(gi);
    }
  });
  const chapterList = [...chapterMap.entries()].sort((a, b) => a[0] - b[0]);

  const toggle = (set: Set<number>, setter: (s: Set<number>) => void, k: number) => {
    const next = new Set(set);
    if (next.has(k)) next.delete(k);
    else next.add(k);
    setter(next);
  };

  const renderGroup = (gi: number) => {
    const g = grouped[gi];
    const expanded = expandedGroups.has(gi);
    const mainTexts = g.map((c) => c.translated_text ?? c.source_text);
    const srcTexts = g
      .filter((c) => c.translated_text && c.source_text !== c.translated_text)
      .map((c) => c.source_text);
    return (
      <div key={`g${gi}`} className="rounded-xl border border-line bg-[#171a22]">
        <button
          onClick={() => toggle(expandedGroups, setExpandedGroups, gi)}
          className="flex w-full items-center gap-2 px-4 py-2 text-left text-[11.5px] text-tx3"
        >
          <span>{expanded ? "▾" : "▸"}</span>
          <span>
            第 {gi + 1} 段 · {hms(g[0].t_start)}–{hms(g[g.length - 1].t_start)} ·{" "}
            {g.length} 句
          </span>
        </button>
        {expanded ? (
          <div className="flex flex-col gap-2.5 px-3 pb-3">
            {g.map((c) => (
              <CaptionCard key={c.seq} cap={c} speakers={speakers} onStar={onStar} />
            ))}
          </div>
        ) : (
          <div className="px-4 pb-3">
            {srcTexts.length > 0 && (
              <div className="mb-1 text-[12px] leading-relaxed text-tx3">
                {mergeParagraph(srcTexts)}
              </div>
            )}
            <div className="text-[14px] leading-relaxed">{mergeParagraph(mainTexts)}</div>
          </div>
        )}
      </div>
    );
  };

  return (
    <>
      {chapterList.map(([chIdx, groupIdxs], order) => {
        const chExpanded = expandedChapters.has(chIdx);
        const first = grouped[groupIdxs[0]][0];
        const lastG = grouped[groupIdxs[groupIdxs.length - 1]];
        const nSent = groupIdxs.reduce((n, gi) => n + grouped[gi].length, 0);
        const preview = mergeParagraph(
          grouped[groupIdxs[0]].map((c) => c.translated_text ?? c.source_text),
        ).slice(0, 60);
        return (
          <div key={`ch${chIdx}`} className="rounded-xl border border-[#3a3f52] bg-[#12151d]">
            <button
              onClick={() => toggle(expandedChapters, setExpandedChapters, chIdx)}
              className="flex w-full items-center gap-2 px-4 py-2.5 text-left"
            >
              <span className="text-[11.5px] text-tx3">{chExpanded ? "▾" : "▸"}</span>
              <span className="text-[12px] font-semibold text-tx2">
                第 {order + 1} 章 · {hms(first.t_start)}–
                {hms(lastG[lastG.length - 1].t_start)} · {groupIdxs.length} 段 {nSent} 句
              </span>
              {!chExpanded && (
                <span className="ml-2 flex-1 truncate text-[11.5px] text-tx3">
                  {preview}…
                </span>
              )}
            </button>
            {chExpanded && (
              <div className="flex flex-col gap-2.5 px-3 pb-3">
                {groupIdxs.map(renderGroup)}
              </div>
            )}
          </div>
        );
      })}
      {currentGroupIdxs.map(renderGroup)}
      {tail.map((c, i) => (
        <CaptionCard
          key={c.seq}
          cap={c}
          speakers={speakers}
          live={live && i === tail.length - 1}
          onStar={onStar}
        />
      ))}
    </>
  );
}
