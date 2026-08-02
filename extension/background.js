// 翻譯蒟蒻 service worker:側欄開啟行為 + tabCapture streamId 取得
chrome.sidePanel
  .setPanelBehavior({ openPanelOnActionClick: true })
  .catch(() => {});

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg?.type === "konjac:getStreamId") {
    // 取分頁音訊擷取 streamId;consumerTabId 省略 = 供擴充頁使用
    chrome.tabCapture.getMediaStreamId(
      { targetTabId: msg.tabId },
      (streamId) => {
        if (chrome.runtime.lastError) {
          sendResponse({ error: chrome.runtime.lastError.message });
        } else {
          sendResponse({ streamId });
        }
      },
    );
    return true; // async sendResponse
  }
});
