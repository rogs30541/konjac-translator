import { useEffect, useState } from "react";
import { api } from "./api";
import type { Health } from "./types";
import LibraryView from "./views/LibraryView";
import LiveView from "./views/LiveView";
import OfflineView from "./views/OfflineView";
import SettingsView from "./views/SettingsView";

type Page = "live" | "offline" | "library" | "settings";

const NAV: Array<[Page, string]> = [
  ["live", "● 即時模式"],
  ["offline", "▤ 離線處理"],
  ["library", "▦ 紀錄庫"],
  ["settings", "⚙ 設定"],
];

export default function App() {
  const [page, setPage] = useState<Page>("live");
  const [health, setHealth] = useState<Health | null>(null);
  const [libSelected, setLibSelected] = useState<string | null>(null);

  useEffect(() => {
    const tick = () => api.health().then(setHealth).catch(() => setHealth(null));
    tick();
    const t = setInterval(tick, 5000);
    return () => clearInterval(t);
  }, []);

  const openSession = (id: string) => {
    setLibSelected(id);
    setPage("library");
  };

  return (
    <div className="grid h-full grid-cols-[190px_1fr]">
      <nav className="flex flex-col gap-1 border-r border-line bg-[#141720] p-3">
        <div className="mb-3 flex items-center gap-2 px-2 font-bold">
          <span className="inline-block h-6 w-6 rounded-lg bg-gradient-to-br from-brand to-brand-deep" />
          翻譯蒟蒻
        </div>
        {NAV.map(([p, label]) => (
          <button
            key={p}
            onClick={() => setPage(p)}
            className={`rounded-lg px-3 py-2 text-left text-[13.5px] ${
              page === p ? "bg-brand/15 font-semibold text-brand" : "text-tx3 hover:text-tx2"
            }`}
          >
            {label}
          </button>
        ))}
        <div className="flex-1" />
        <div className="rounded-lg border border-line px-3 py-2 text-[11.5px] text-tx2">
          {health ? (
            <>
              <div className="mb-0.5 flex items-center gap-1.5 text-[12px] text-ok">
                <span className="h-1.5 w-1.5 rounded-full bg-ok" />
                引擎已連線
              </div>
              v{health.version} · {health.provider}
            </>
          ) : (
            <div className="text-[12px] text-brand-deep">⚠ 引擎未連線(127.0.0.1:8765)</div>
          )}
        </div>
      </nav>

      <main className="min-w-0">
        {page === "live" && <LiveView engineOk={!!health} />}
        {page === "offline" && <OfflineView onOpenSession={openSession} />}
        {page === "library" && (
          <LibraryView selectedId={libSelected} onSelect={setLibSelected} />
        )}
        {page === "settings" && <SettingsView />}
      </main>
    </div>
  );
}
