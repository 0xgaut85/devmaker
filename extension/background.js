/**
 * Background service worker — maintains persistent WebSocket to backend
 * and routes commands to/from the content script.
 *
 * IMPORTANT: All page navigation is handled HERE via chrome.tabs.update,
 * never via window.location.href in the content script (which kills it).
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

async function navigateTab(tabId, url) {
  await chrome.tabs.update(tabId, { url });
  return new Promise((resolve) => {
    const timeout = setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(listener);
      resolve();
    }, 15000);
    function listener(tid, info) {
      if (tid === tabId && info.status === "complete") {
        chrome.tabs.onUpdated.removeListener(listener);
        clearTimeout(timeout);
        setTimeout(resolve, 1500);
      }
    }
    chrome.tabs.onUpdated.addListener(listener);
  });
}

async function ensureHomePage(tabId) {
  try {
    const tab = await chrome.tabs.get(tabId);
    const url = new URL(tab.url);
    if (url.pathname !== "/home" && !url.pathname.startsWith("/home")) {
      console.log("[DevMaker] Not on /home, navigating...");
      await navigateTab(tabId, "https://x.com/home");
    }
  } catch {}
}

async function sendToContent(tabId, cmd, params) {
  return await chrome.tabs.sendMessage(tabId, { cmd, params });
}

function connectWs() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    return;
  }

  const base = wsUrl.replace(/^http/, "ws").replace(/\/+$/, "");
  const url = `${base}/ws/extension/${accountId}`;
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

      // --- navigate: handled entirely in background ---
      if (cmd === "navigate") {
        await navigateTab(tab.id, params.url);
        sendResponse(reqId, cmd, "ok");
        return;
      }

      // --- session_warmup: scroll via content, navigate via tabs API ---
      if (cmd === "session_warmup") {
        try { await sendToContent(tab.id, "lurk_scroll", { count: 3 }); } catch {}
        if (Math.random() < 0.5) {
          await navigateTab(tab.id, "https://x.com/notifications");
          try { await sendToContent(tab.id, "scroll", { count: 2 }); } catch {}
        }
        await navigateTab(tab.id, "https://x.com/home");
        sendResponse(reqId, cmd, "ok");
        return;
      }

      // --- scrape_timeline: ensure we're on /home first ---
      if (cmd === "scrape_timeline") {
        await ensureHomePage(tab.id);
      }

      // --- action commands with post_url: navigate to the post first ---
      const postUrlCommands = ["post_comment", "like_post", "bookmark_post", "quote_tweet", "retweet"];
      if (postUrlCommands.includes(cmd) && params.post_url) {
        const currentTab = await chrome.tabs.get(tab.id);
        try {
          const targetPath = new URL(params.post_url).pathname;
          const currentPath = new URL(currentTab.url).pathname;
          if (!currentPath.startsWith(targetPath)) {
            await navigateTab(tab.id, params.post_url);
          }
        } catch {}
      }

      // --- follow_user: navigate to profile first ---
      if (cmd === "follow_user" && params.handle) {
        const currentTab = await chrome.tabs.get(tab.id);
        if (!currentTab.url.includes(`/${params.handle}`)) {
          await navigateTab(tab.id, `https://x.com/${params.handle}`);
        }
      }

      const response = await sendToContent(tab.id, cmd, params);
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
  await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(listener);
      reject(new Error("Tab load timed out after 30s"));
    }, 30000);
    function listener(tabId, info) {
      if (tabId === newTab.id && info.status === "complete") {
        chrome.tabs.onUpdated.removeListener(listener);
        clearTimeout(timeout);
        setTimeout(resolve, 1000);
      }
    }
    chrome.tabs.onUpdated.addListener(listener);
  });
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
