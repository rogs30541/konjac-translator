// 翻譯蒟蒻側欄:引擎狀態、字幕鏡像、分頁錄音上傳、NotebookLM 轉發
const ENGINE = "http://127.0.0.1:8765";
const WS = "ws://127.0.0.1:8765";

const el = (id) => document.getElementById(id);
const statusEl = el("status");
const capsEl = el("caps");
const hintEl = el("hint");
const msgEl = el("msg");
const btnCapture = el("btn-capture");
const btnSummary = el("btn-summary");
const btnNblm = el("nblm");

const SPEAKER_COLORS = ["#6EA8FF", "#4DD6C1", "#FFC46B", "#B18CFF", "#FF8FA3", "#8AD46B"];
let engineOk = false;
let watchedSession = null; // 目前鏡像/操作的 session
let ws = null;
const seen = new Map(); // seq -> element

// ---------- 引擎健康 + 進行中 session 探測 ----------
async function tick() {
  try {
    const h = await (await fetch(`${ENGINE}/api/health`)).json();
    engineOk = true;
    statusEl.textContent = `引擎 v${h.version}${h.llm ? ` · ${h.llm}` : " · 未設翻譯"}`;
    statusEl.className = "ok";
  } catch {
    engineOk = false;
    statusEl.textContent = "⚠ 引擎未連線";
    statusEl.className = "err";
    return;
  }
  try {
    const sessions = await (await fetch(`${ENGINE}/api/sessions`)).json();
    const rec = sessions.find((s) => s.status === "recording" && s.kind === "live");
    const target = rec ?? sessions.find((s) => s.id === watchedSession?.id) ?? sessions[0] ?? null;
    if (target && target.id !== watchedSession?.id) switchSession(target);
    else if (target) watchedSession = target;
    btnSummary.disabled = !watchedSession;
    btnNblm.disabled = !watchedSession;
  } catch { /* ignore */ }
}
setInterval(tick, 3000);
tick();

function switchSession(session) {
  watchedSession = session;
  seen.clear();
  capsEl.innerHTML = "";
  hintEl.remove?.();
  if (ws) { ws.onclose = null; ws.close(); }
  ws = new WebSocket(`${WS}/ws/sessions/${session.id}`);
  ws.onmessage = (m) => {
    const ev = JSON.parse(m.data);
    if (ev.type === "caption") renderCaption(ev.data);
  };
  ws.onclose = () => setTimeout(() => {
    if (watchedSession?.id === session.id) switchSession(session);
  }, 2000);
  msg(`鏡像:${session.title}`);
}

function renderCaption(c) {
  let node = seen.get(c.seq);
  if (!node) {
    node = document.createElement("div");
    node.className = "cap";
    seen.set(c.seq, node);
    capsEl.appendChild(node);
  }
  const color = c.speaker_id
    ? SPEAKER_COLORS[(parseInt(c.speaker_id.replace(/\D/g, ""), 10) - 1 || 0) % SPEAKER_COLORS.length]
    : null;
  const spk = c.speaker_id
    ? `<span class="spk" style="color:${color};background:${color}29">${c.speaker_id}</span>`
    : "";
  const main = c.translated_text ?? c.source_text;
  const src = c.translated_text && c.source_text !== c.translated_text
    ? `<div class="src">${spk}${escapeHtml(c.source_text)}</div>` : `<div class="src">${spk}</div>`;
  node.innerHTML = `${src}<div class="dst">${escapeHtml(main)}</div>`;
  capsEl.scrollTop = capsEl.scrollHeight;
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (ch) => `&#${ch.charCodeAt(0)};`);
}
function msg(t) { msgEl.textContent = t; }

// ---------- 分頁錄音(停止後上傳引擎)----------
let recorder = null;
let chunks = [];
let stream = null;

btnCapture.addEventListener("click", async () => {
  if (recorder) { recorder.stop(); return; }
  if (!engineOk) { msg("引擎未連線,無法轉錄"); return; }
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const resp = await chrome.runtime.sendMessage({ type: "konjac:getStreamId", tabId: tab.id });
    if (resp?.error) throw new Error(resp.error);
    stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        mandatory: { chromeMediaSource: "tab", chromeMediaSourceId: resp.streamId },
      },
    });
    // 擷取會靜音原分頁 → 監聽輸出讓使用者仍聽得到
    el("monitor").srcObject = stream;

    chunks = [];
    recorder = new MediaRecorder(stream, { mimeType: "audio/webm;codecs=opus" });
    recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    recorder.onstop = onRecordingStop;
    recorder.start();
    btnCapture.textContent = "■ 停止並轉錄";
    btnCapture.classList.add("on");
    msg("錄製分頁音訊中…停止後上傳引擎轉錄");
  } catch (e) {
    msg(`擷取失敗:${e.message}`);
    cleanupRecording();
  }
});

async function onRecordingStop() {
  btnCapture.textContent = "⏳ 上傳轉錄中…";
  btnCapture.disabled = true;
  try {
    const blob = new Blob(chunks, { type: "audio/webm" });
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const form = new FormData();
    form.append("file", new File([blob], "tab_capture.webm", { type: "audio/webm" }));
    const title = encodeURIComponent(`分頁錄音:${(tab?.title ?? "").slice(0, 60)}`);
    const r = await fetch(
      `${ENGINE}/api/offline/jobs?mode=en2zh&diarize=true&title=${title}`,
      { method: "POST", body: form });
    if (!r.ok) throw new Error(await r.text());
    const job = await r.json();
    msg("引擎轉錄中…完成後自動切換顯示");
    const poll = setInterval(async () => {
      const j = await (await fetch(`${ENGINE}/api/offline/jobs/${job.job_id}`)).json();
      if (j.status === "processing") return;
      clearInterval(poll);
      if (j.status === "done") {
        const detail = await (await fetch(`${ENGINE}/api/sessions/${j.session_id}`)).json();
        switchSession(detail.session);
        const caps = await (await fetch(`${ENGINE}/api/sessions/${j.session_id}/captions`)).json();
        caps.forEach(renderCaption);
        msg(`✓ 轉錄完成(${caps.length} 句)`);
      } else {
        msg(`✗ 轉錄失敗:${j.error ?? ""}`);
      }
    }, 2000);
  } catch (e) {
    msg(`上傳失敗:${e.message}`);
  } finally {
    cleanupRecording();
  }
}

function cleanupRecording() {
  stream?.getTracks().forEach((t) => t.stop());
  stream = null;
  recorder = null;
  btnCapture.textContent = "● 錄製此分頁";
  btnCapture.classList.remove("on");
  btnCapture.disabled = false;
}

// ---------- 摘要 ----------
btnSummary.addEventListener("click", async () => {
  if (!watchedSession) return;
  btnSummary.disabled = true;
  msg("產生摘要中…");
  try {
    await fetch(`${ENGINE}/api/sessions/${watchedSession.id}/summary`, { method: "POST" });
    msg("✓ 摘要完成(見桌面 App 紀錄庫,轉發時一併帶入)");
  } catch (e) {
    msg(`摘要失敗:${e.message}`);
  } finally {
    btnSummary.disabled = false;
  }
});

// ---------- NotebookLM 轉發 ----------
btnNblm.addEventListener("click", async () => {
  if (!watchedSession) return;
  btnNblm.disabled = true;
  msg("產生轉發內容…");
  try {
    const r = await fetch(
      `${ENGINE}/api/sessions/${watchedSession.id}/forward/notebooklm?force=true`,
      { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target_notebook: "翻譯蒟蒻紀錄", scope: "full" }) });
    if (!r.ok) throw new Error(await r.text());
    const { payload_md } = await r.json();
    await chrome.storage.local.set({
      konjac_payload: { md: payload_md, title: watchedSession.title, ts: Date.now() },
    });
    await chrome.tabs.create({ url: "https://notebooklm.google.com/" });
    msg("已開啟 NotebookLM,依頁面指引貼上(內容已備妥)");
  } catch (e) {
    msg(`轉發失敗:${e.message}`);
  } finally {
    btnNblm.disabled = false;
  }
});
