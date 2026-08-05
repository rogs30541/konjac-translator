import type { Caption, Health, Session, Speaker } from "./types";

export const ENGINE_BASE = "http://127.0.0.1:8765";
export const ENGINE_WS = "ws://127.0.0.1:8765";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${ENGINE_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return (await r.json()) as T;
}

export interface LLMSettings {
  provider: string;
  model: string;
  base_url: string;
  configured: boolean;
  api_key_masked: string;
}

export interface AppSettings {
  keywords: string[];
  webhooks: Array<Partial<Record<string, string>> & { type: string }>;
  retention_days: number;
  idle_stop_minutes: number;
  vendor_dir: string;
  vendor_available: boolean;
  vendor_resolved: string;
}

export const api = {
  health: () => req<Health>("/api/health"),
  getSettings: () => req<LLMSettings>("/api/settings"),
  getAppSettings: () => req<AppSettings>("/api/settings/app"),
  putAppSettings: (body: Partial<AppSettings>) =>
    req<AppSettings>("/api/settings/app", { method: "PUT", body: JSON.stringify(body) }),
  cleanup: () =>
    req<{ deleted_sessions: number }>("/api/maintenance/cleanup", { method: "POST" }),
  putSettings: (body: Record<string, unknown>) =>
    req<LLMSettings>("/api/settings", { method: "PUT", body: JSON.stringify(body) }),
  testSettings: () =>
    req<{ ok: boolean; sample: string }>("/api/settings/test", { method: "POST" }),
  listModels: () =>
    req<{ models: string[]; recommended: string | null }>("/api/settings/models"),
  audioDiag: () =>
    req<{ devices: Array<Record<string, unknown>>; advice: string }>(
      "/api/diagnostics/audio"),
  listSessions: () => req<Session[]>("/api/sessions"),
  getSession: (id: string) =>
    req<{ session: Session; speakers: Speaker[]; summary: { content_md: string } | null }>(
      `/api/sessions/${id}`),
  liveStart: (title: string, mode: string, topic: string | null) =>
    req<Session>("/api/live/start", {
      method: "POST",
      body: JSON.stringify({ title, kind: "live", mode, topic }),
    }),
  stop: (id: string) => req<Session>(`/api/sessions/${id}/stop`, { method: "POST" }),
  deleteSession: (id: string) =>
    fetch(`${ENGINE_BASE}/api/sessions/${id}`, { method: "DELETE" }),
  captions: (id: string) => req<Caption[]>(`/api/sessions/${id}/captions`),
  star: (id: string, seq: number) =>
    req(`/api/sessions/${id}/captions/${seq}/star`, { method: "POST" }),
  renameSpeaker: (id: string, spk: string, name: string) =>
    req<Speaker[]>(`/api/sessions/${id}/speakers/${spk}`, {
      method: "PATCH",
      body: JSON.stringify({ display_name: name }),
    }),
  summarize: (id: string, template = "general") =>
    req<{ content_md: string }>(
      `/api/sessions/${id}/summary?template=${template}`, { method: "POST" }),
  exportUrl: (id: string, format: string) =>
    `${ENGINE_BASE}/api/sessions/${id}/export?format=${format}`,
  forwardNotebookLM: (
    id: string, notebook: string, scope: string, force = false, openBrowser = false,
  ) =>
    req<{ payload_md: string; opened_browser: boolean }>(
      `/api/sessions/${id}/forward/notebooklm?force=${force}`, {
        method: "POST",
        body: JSON.stringify({
          target_notebook: notebook, scope, open_browser: openBrowser,
        }),
      }),
};
