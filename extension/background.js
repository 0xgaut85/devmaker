/**
 * Background service worker — maintains persistent WebSocket to backend
 * and routes commands to/from the content script.
 */

let ws = null;
let wsUrl = "";
let accountId = "";
let reconnectTimer = null;
let contentTabId = null;

chrome.storage.local.get(["backendUrl", "accountId"], (data) => {
  if (data.backendUrl && data.accountId) {
    wsUrl = data.backendUrl;
    accountId = data.accountId;
    connectWs();
  }
});

function connectWs() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    return;
  }

  const url = `${wsUrl.replace(/^http/, "ws")}/ws/extension/${accountId}`;
  console.log("[DevMaker] Connecting to", url);
  ws = new WebSocket(url);

  ws.onopen = () => {
    console.log("[DevMaker] WebSocket connected");
    clearTimeout(reconnectTimer);
    broadcastStatus("connected");
  };

  ws.onmessage = async (event) => {
    let msg;
    try {
      msg = JSON.parse(event.data);
    } catch {
      return;
    }

    if (msg.cmd === "pong") return;

    const reqId = msg.req_id;
    const cmd = msg.cmd;
    const params = msg.params || {};

    try {
      const tab = await getXTab();
      if (!tab) {
        sendResponse(reqId, cmd, "error", null, "No x.com tab found");
        return;
      }
      contentTabId = tab.id;

      const response = await chrome.tabs.sendMessage(tab.id, { cmd, params });
      sendResponse(reqId, cmd, response.status || "ok", response.data, response.error);
    } catch (err) {
      sendResponse(reqId, cmd, "error", null, err.message);
    }
  };

  ws.onclose = () => {
    console.log("[DevMaker] WebSocket disconnected");
    broadcastStatus("disconnected");
    scheduleReconnect();
  };

  ws.onerror = (err) => {
    console.error("[DevMaker] WebSocket error:", err);
    ws.close();
  };
}

function sendResponse(reqId, cmd, status, data, error) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  const resp = { req_id: reqId, cmd, status };
  if (data !== undefined && data !== null) resp.data = data;
  if (error) resp.error = error;
  ws.send(JSON.stringify(resp));
}

function scheduleReconnect() {
  clearTimeout(reconnectTimer);
  reconnectTimer = setTimeout(() => connectWs(), 5000);
}

async function getXTab() {
  const tabs = await chrome.tabs.query({ url: ["*://x.com/*", "*://twitter.com/*"] });
  if (tabs.length > 0) {
    return tabs[0];
  }
  const newTab = await chrome.tabs.create({ url: "https://x.com/home", active: false });
  await new Promise((r) => setTimeout(r, 5000));
  return newTab;
}

function broadcastStatus(status) {
  chrome.runtime.sendMessage({ type: "status", status }).catch(() => {});
}

// Ping to keep alive
setInterval(() => {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ cmd: "ping" }));
  }
}, 25000);

// Listen for config updates from popup
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === "configure") {
    wsUrl = msg.backendUrl;
    accountId = msg.accountId;
    chrome.storage.local.set({ backendUrl: wsUrl, accountId });
    if (ws) ws.close();
    connectWs();
    sendResponse({ ok: true });
  } else if (msg.type === "getStatus") {
    sendResponse({
      connected: ws && ws.readyState === WebSocket.OPEN,
      backendUrl: wsUrl,
      accountId,
    });
  } else if (msg.type === "disconnect") {
    if (ws) ws.close();
    ws = null;
    sendResponse({ ok: true });
  }
  return true;
});
