import { useEffect, useState } from "react";
import { api, type AppSettings, type LLMSettings } from "../api";

/** webhooks UI 格式:一行一個
 *  discord|https://discord.com/api/webhooks/...
 *  slack|https://hooks.slack.com/...
 *  telegram|<bot_token>|<chat_id>
 *  generic|https://example.com/hook            */
function hooksToText(hooks: AppSettings["webhooks"]): string {
  return hooks
    .map((h) =>
      h.type === "telegram"
        ? `telegram|${h.bot_token}|${h.chat_id}`
        : `${h.type}|${h.url}`)
    .join("\n");
}

function textToHooks(text: string): AppSettings["webhooks"] {
  return text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .map((l) => {
      const p = l.split("|");
      if (p[0] === "telegram" && p.length >= 3)
        return { type: "telegram", bot_token: p[1], chat_id: p[2] };
      return { type: p[0] || "generic", url: p[1] ?? "" };
    })
    .filter((h) => (h.type === "telegram" ? h.bot_token && h.chat_id : h.url));
}

const PROVIDERS = [
  ["", "(未設定 — 僅轉錄,不翻譯)"],
  ["anthropic", "Claude(Anthropic)"],
  ["openai", "GPT(OpenAI)"],
  ["gemini", "Gemini(Google)"],
  ["custom", "自訂 OpenAI 相容端點"],
] as const;

const DEFAULT_MODEL_HINT: Record<string, string> = {
  anthropic: "claude-haiku-4-5",
  openai: "gpt-4o-mini",
  gemini: "gemini-2.0-flash",
};

/** 設定頁:翻譯/摘要用的雲端 AI API。Key 只存本機引擎 settings.json。 */
export default function SettingsView() {
  const [cur, setCur] = useState<LLMSettings | null>(null);
  const [provider, setProvider] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [keywords, setKeywords] = useState("");
  const [hooksText, setHooksText] = useState("");
  const [retention, setRetention] = useState(0);
  const [appMsg, setAppMsg] = useState<string | null>(null);

  const refresh = () =>
    api.getSettings().then((s) => {
      setCur(s);
      setProvider(s.provider);
      setModel(s.model);
      setBaseUrl(s.base_url);
    });
  useEffect(() => {
    refresh().catch(() => setMsg("讀取設定失敗:引擎未連線?"));
    api.getAppSettings().then((a) => {
      setKeywords(a.keywords.join(", "));
      setHooksText(hooksToText(a.webhooks));
      setRetention(a.retention_days);
    }).catch(() => {});
  }, []);

  const saveApp = async () => {
    setBusy(true);
    setAppMsg(null);
    try {
      const saved = await api.putAppSettings({
        keywords: keywords.split(/[,،、\n]/).map((k) => k.trim()).filter(Boolean),
        webhooks: textToHooks(hooksText),
        retention_days: retention,
      });
      setKeywords(saved.keywords.join(", "));
      setHooksText(hooksToText(saved.webhooks));
      setAppMsg(`✓ 已儲存(關鍵字 ${saved.keywords.length}、webhook ${saved.webhooks.length})`);
    } catch (e) {
      setAppMsg(String(e));
    } finally {
      setBusy(false);
    }
  };

  const runCleanup = async () => {
    setBusy(true);
    try {
      const r = await api.cleanup();
      setAppMsg(`✓ 清理完成,刪除 ${r.deleted_sessions} 筆過期紀錄`);
    } catch (e) {
      setAppMsg(String(e));
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const body: Record<string, unknown> = { provider, model, base_url: baseUrl };
      if (apiKey.trim()) body.api_key = apiKey.trim();
      if (!provider) body.clear_key = true;
      await api.putSettings(body);
      setApiKey("");
      await refresh();
      setMsg("✓ 已儲存(Key 僅存本機 ~/.konjac/settings.json)");
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy(false);
    }
  };

  const test = async () => {
    setBusy(true);
    setMsg("測試中…(呼叫一次翻譯 API)");
    try {
      const r = await api.testSettings();
      setMsg(`✓ 連線成功,測試翻譯:「${r.sample}」`);
    } catch (e) {
      setMsg(`✗ 測試失敗:${String(e)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-xl p-6">
      <h2 className="text-[15px] font-bold">翻譯與摘要 AI(雲端 API)</h2>
      <p className="mt-1 text-[12px] text-tx3">
        架構:本地 Whisper 辨識 → 雲端 LLM 校正 + 翻譯 + 摘要。API Key
        只儲存在本機引擎,不經任何第三方伺服器。
      </p>

      <div className="mt-5 flex flex-col gap-4">
        <label className="text-[12.5px] text-tx2">
          供應商
          <select
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
            className="mt-1 block w-full rounded-lg border border-line bg-panel2 px-3 py-2"
          >
            {PROVIDERS.map(([v, label]) => (
              <option key={v} value={v}>{label}</option>
            ))}
          </select>
        </label>

        {provider && (
          <>
            <label className="text-[12.5px] text-tx2">
              API Key{" "}
              {cur?.configured && (
                <span className="text-tx3">(已設定:{cur.api_key_masked};留空 = 不變更)</span>
              )}
              <input
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder={cur?.configured ? "••••••••(留空保留原 Key)" : "貼上你的 API Key"}
                className="mt-1 block w-full rounded-lg border border-line bg-panel2 px-3 py-2 font-mono text-[12px]"
              />
            </label>
            <label className="text-[12.5px] text-tx2">
              模型 <span className="text-tx3">(留空 = 預設 {DEFAULT_MODEL_HINT[provider] ?? "—"})</span>
              <input
                value={model}
                onChange={(e) => setModel(e.target.value)}
                placeholder={DEFAULT_MODEL_HINT[provider] ?? ""}
                className="mt-1 block w-full rounded-lg border border-line bg-panel2 px-3 py-2 font-mono text-[12px]"
              />
            </label>
            {provider === "custom" && (
              <label className="text-[12.5px] text-tx2">
                Base URL(OpenAI 相容)
                <input
                  value={baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value)}
                  placeholder="https://your-endpoint.example.com"
                  className="mt-1 block w-full rounded-lg border border-line bg-panel2 px-3 py-2 font-mono text-[12px]"
                />
              </label>
            )}
          </>
        )}

        <div className="flex gap-2.5">
          <button
            onClick={save}
            disabled={busy}
            className="rounded-lg border border-brand-deep bg-brand/15 px-5 py-2 text-[13px] font-semibold text-brand disabled:opacity-40"
          >
            儲存
          </button>
          <button
            onClick={test}
            disabled={busy || !cur?.configured}
            className="rounded-lg border border-line bg-panel2 px-5 py-2 text-[13px] disabled:opacity-40"
          >
            測試連線
          </button>
        </div>
        {msg && <div className="text-[12.5px] text-tx2">{msg}</div>}
      </div>

      <h2 className="mt-9 border-t border-line pt-6 text-[15px] font-bold">通知與轉發</h2>
      <div className="mt-4 flex flex-col gap-4">
        <label className="text-[12.5px] text-tx2">
          關鍵字通知 <span className="text-tx3">(逗號分隔;字幕命中時即時提示)</span>
          <input
            value={keywords}
            onChange={(e) => setKeywords(e.target.value)}
            placeholder="roadmap, 預算, deadline"
            className="mt-1 block w-full rounded-lg border border-line bg-panel2 px-3 py-2 text-[12.5px]"
          />
        </label>
        <label className="text-[12.5px] text-tx2">
          字幕轉發 Webhook <span className="text-tx3">(一行一個:discord|url、slack|url、telegram|token|chat_id、generic|url)</span>
          <textarea
            value={hooksText}
            onChange={(e) => setHooksText(e.target.value)}
            rows={3}
            placeholder="discord|https://discord.com/api/webhooks/…"
            className="mt-1 block w-full rounded-lg border border-line bg-panel2 px-3 py-2 font-mono text-[11.5px]"
          />
        </label>
        <label className="text-[12.5px] text-tx2">
          紀錄保留天數 <span className="text-tx3">(0 = 永久保留;超過天數的 session 於引擎啟動時刪除)</span>
          <input
            type="number"
            min={0}
            value={retention}
            onChange={(e) => setRetention(Math.max(0, Number(e.target.value) || 0))}
            className="mt-1 block w-28 rounded-lg border border-line bg-panel2 px-3 py-2 text-[12.5px]"
          />
        </label>
        <div className="flex gap-2.5">
          <button
            onClick={saveApp}
            disabled={busy}
            className="rounded-lg border border-brand-deep bg-brand/15 px-5 py-2 text-[13px] font-semibold text-brand disabled:opacity-40"
          >
            儲存
          </button>
          <button
            onClick={runCleanup}
            disabled={busy}
            className="rounded-lg border border-line bg-panel2 px-5 py-2 text-[13px] disabled:opacity-40"
          >
            立即清理過期紀錄
          </button>
        </div>
        {appMsg && <div className="text-[12.5px] text-tx2">{appMsg}</div>}
      </div>
    </div>
  );
}
