// NotebookLM 頁面助手:讀取待轉發內容 → 複製到剪貼簿 + 引導浮窗,
// 並嘗試自動點「新增來源」(UI 改版時自動降級為手動指引)。
(async () => {
  const { konjac_payload } = await chrome.storage.local.get("konjac_payload");
  if (!konjac_payload) return;
  if (Date.now() - (konjac_payload.ts ?? 0) > 10 * 60 * 1000) {
    chrome.storage.local.remove("konjac_payload");
    return;
  }

  // 複製內容到剪貼簿
  let copied = false;
  try {
    await navigator.clipboard.writeText(konjac_payload.md);
    copied = true;
  } catch { /* 需使用者手勢時降級 */ }

  // 引導浮窗
  const panel = document.createElement("div");
  panel.style.cssText = [
    "position:fixed", "right:20px", "bottom:20px", "z-index:2147483647",
    "background:#1b1e27", "color:#e8eaf0", "border:1px solid #e5637e",
    "border-radius:14px", "padding:16px 18px", "width:320px",
    "font:13px/1.6 'Segoe UI','Noto Sans TC',sans-serif",
    "box-shadow:0 12px 40px rgba(0,0,0,.5)",
  ].join(";");
  panel.innerHTML = `
    <div style="font-weight:700;margin-bottom:6px">🍡 翻譯蒟蒻 — 轉發 NotebookLM</div>
    <div style="color:#9aa1b4;font-size:12px;margin-bottom:10px">
      「${(konjac_payload.title ?? "").slice(0, 40)}」的摘要與逐字稿
      ${copied ? "<b style='color:#5ad08a'>已複製到剪貼簿</b>" : "已備妥"}。<br/>
      步驟:開啟(或新建)筆記本 → 新增來源 →「複製的文字」→ 貼上(Ctrl+V)
    </div>
    <div style="display:flex;gap:8px">
      <button id="konjac-copy" style="flex:1;background:#232734;border:1px solid #2e3342;color:#e8eaf0;border-radius:8px;padding:7px;cursor:pointer">再複製一次</button>
      <button id="konjac-close" style="background:#232734;border:1px solid #2e3342;color:#9aa1b4;border-radius:8px;padding:7px 12px;cursor:pointer">完成</button>
    </div>`;
  document.documentElement.appendChild(panel);

  panel.querySelector("#konjac-copy").addEventListener("click", async () => {
    await navigator.clipboard.writeText(konjac_payload.md);
    panel.querySelector("#konjac-copy").textContent = "✓ 已複製";
  });
  panel.querySelector("#konjac-close").addEventListener("click", () => {
    chrome.storage.local.remove("konjac_payload");
    panel.remove();
  });

  // 盡力而為的自動化:嘗試點「新增來源」類按鈕(選擇器隨 Google 改版可能失效)
  const tryAutoClick = () => {
    const candidates = [...document.querySelectorAll("button,[role='button']")];
    const btn = candidates.find((b) => {
      const t = `${b.textContent} ${b.getAttribute("aria-label") ?? ""}`;
      return /新增來源|加入來源|Add source|添加来源/i.test(t);
    });
    if (btn) btn.click();
    return !!btn;
  };
  setTimeout(tryAutoClick, 2500);
})();
