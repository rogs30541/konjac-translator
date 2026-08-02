// 與 engine/app/models.py 對齊的型別
export interface Session {
  id: string;
  title: string;
  kind: "live" | "offline";
  mode: string;
  topic: string | null;
  status: "recording" | "processing" | "done" | "error";
  created_at: string;
  ended_at: string | null;
  notebooklm_forwarded_at: string | null;
  notebooklm_target: string | null;
}

export interface Speaker {
  id: string;
  session_id: string;
  display_name: string;
  color: string;
}

export interface Caption {
  session_id: string;
  seq: number;
  t_start: number;
  t_end: number | null;
  speaker_id: string | null;
  source_channel: "system" | "mic";
  source_text: string;
  translated_text: string | null;
  is_final: boolean;
  starred: boolean;
}

export interface WsEvent {
  type: "caption" | "speaker" | "status" | "summary" | "engine" | "keyword";
  data: Record<string, unknown>;
}

export interface Health {
  status: string;
  version: string;
  provider: string;
  vendor_available?: boolean;
  vendor_dir?: string;
  llm?: string | null;
}
