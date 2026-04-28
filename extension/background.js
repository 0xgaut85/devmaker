/**
 * Background service worker — maintains a WebSocket to the backend and
 * dispatches commands to the content script.
 *
 * Why this looks the way it does:
 *  - Chrome MV3 service workers are killed after ~30s of inactivity. Module
 *    state (`ws`, `wsUrl`, `accountId`) is wiped on every restart. The fix is
 *    to ALWAYS re-hydrate config from `chrome.storage.local` on:
 *      (a) script load (top of file),
 *      (b) every keepalive alarm,
 *      (c) every incoming chrome.runtime message.
 *  - We use one `chrome.alarms` (Chrome's alarm minimum is 30s) to:
 *      (a) reconnect the WS if it was lost,
 *      (b) ping the backend so the server-side watchdog (90s) doesn't reap us.
 *  - All page navigation goes through `chrome.tabs.update` here, never through
 *    `window.location.href` in the content script (which kills the script).
 */

const KEEPALIVE_ALARM = "ws-keepalive";
const RECONNECT_DELAY_MS = 5000;
const NAV_TIMEOUT_MS = 15000;
const NEW_TAB_TIMEOUT_MS = 30000;
const COMPOSE_DISMISS_TIMEOUT_MS = 5000;
const SCRAPE_SETUP_TIMEOUT_MS = 30000;
const FOLLOWING_TAB_TIMEOUT_MS = 15000;

let ws = null;
let reconnectTimer = null;

// ---- config (always fetched from storage; never trusted from memory) -------

async function getConfig() {
  const data = await chrome.storage.local.get(["backendUrl", "accountId"]);
  return { backendUrl: data.backendUrl || "", accountId: data.accountId || "" };
}

async function setConfig(backendUrl, accountId) {
  await chrome.storage.local.set({ backendUrl, accountId });
}

// ---- websocket lifecycle ----------------------------------------------------

function isOpenOrConnecting() {
  return ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING);
}

function broadcastStatus(status) {
  chrome.runtime.sendMessage({ type: "status", status }).catch(() => {});
}

function scheduleReconnect() {
  clearTimeout(reconnectTimer);
  reconnectTimer = setTimeout(() => {
    ensureConnected().catch((e) => console.warn("[DevMaker] reconnect failed:", e));
  }, RECONNECT_DELAY_MS);
}

async function ensureConnected() {
  if (isOpenOrConnecting()) return;
  const { backendUrl, accountId } = await getConfig();
  if (!backendUrl || !accountId) return;

  const base = backendUrl.replace(/^http/, "ws").replace(/\/+$/, "");
  const url = `${base}/ws/extension/${accountId}`;
  console.log("[DevMaker] Connecting to", url);

  let socket;
  try {
    socket = new WebSocket(url);
  } catch (e) {
    console.warn("[DevMaker] WebSocket constructor threw:", e);
    scheduleReconnect();
    return;
  }
  ws = socket;

  socket.onopen = () => {
    console.log("[DevMaker] WebSocket connected");
    clearTimeout(reconnectTimer);
    broadcastStatus("connected");
  };

  socket.onmessage = (event) => handleMessage(event, socket);

  // onclose ALWAYS fires (whether or not onerror did), so we schedule from
  // here only and not from onerror — avoids double-scheduled reconnects.
  socket.onclose = () => {
    if (ws === socket) ws = null;
    console.log("[DevMaker] WebSocket disconnected");
    broadcastStatus("disconnected");
    scheduleReconnect();
  };

  socket.onerror = (err) => {
    console.error("[DevMaker] WebSocket error:", err);
    try { socket.close(); } catch {}
  };
}

function safeSend(payload) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return false;
  try {
    ws.send(JSON.stringify(payload));
    return true;
  } catch (e) {
    console.warn("[DevMaker] WebSocket send failed:", e);
    try { ws.close(); } catch {}
    return false;
  }
}

function sendResponse(reqId, cmd, status, data, error) {
  const resp = { req_id: reqId, cmd, status };
  if (data !== undefined && data !== null) resp.data = data;
  if (error) resp.error = error;
  safeSend(resp);
}

// ---- incoming command handling ---------------------------------------------

async function handleMessage(event, socket) {
  let msg;
  try { msg = JSON.parse(event.data); }
  catch { return; }

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

    if (cmd === "navigate") {
      await navigateTab(tab.id, params.url);
      sendResponse(reqId, cmd, "ok");
      return;
    }

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

    if (cmd === "scrape_timeline") {
      await Promise.race([
        scrapeSetup(tab.id, params),
        new Promise((r) => setTimeout(r, SCRAPE_SETUP_TIMEOUT_MS)),
      ]);
    }

    if (POST_URL_COMMANDS.has(cmd) && params.post_url) {
      await navigateIfDifferent(tab.id, params.post_url);
    }

    if (cmd === "follow_user" && params.handle) {
      const current = await chrome.tabs.get(tab.id);
      if (!current.url.toLowerCase().includes(`/${params.handle.toLowerCase()}`)) {
        await navigateTab(tab.id, `https://x.com/${params.handle}`);
      }
    }

    if (cmd === "scrape_own_profile" && params.handle) {
      await navigateTab(tab.id, `https://x.com/${params.handle}`);
    }

    const response = await sendToContent(tab.id, cmd, params);
    sendResponse(reqId, cmd, response.status || "ok", response.data, response.error);
  } catch (err) {
    sendResponse(reqId, cmd, "error", null, err.message);
  }
}

const POST_URL_COMMANDS = new Set([
  "post_comment", "like_post", "bookmark_post", "quote_tweet", "retweet",
]);

async function scrapeSetup(tabId, params) {
  await ensureHomePage(tabId);
  if (params.use_following_tab) {
    try {
      await Promise.race([
        sendToContent(tabId, "click_following_tab", {}),
        new Promise((_, r) => setTimeout(() => r(new Error("timeout")), FOLLOWING_TAB_TIMEOUT_MS)),
      ]);
    } catch {}
  }
}

async function navigateIfDifferent(tabId, targetUrl) {
  const current = await chrome.tabs.get(tabId);
  try {
    const targetPath = new URL(targetUrl).pathname;
    const currentPath = new URL(current.url).pathname;
    if (!currentPath.startsWith(targetPath)) {
      await navigateTab(tabId, targetUrl);
    }
  } catch {
    await navigateTab(tabId, targetUrl);
  }
}

// ---- tab + content-script helpers ------------------------------------------

async function dismissComposeBeforeNav(tabId) {
  try {
    await Promise.race([
      sendToContent(tabId, "dismiss_compose", {}),
      new Promise((r) => setTimeout(r, COMPOSE_DISMISS_TIMEOUT_MS)),
    ]);
  } catch {}
  await new Promise((r) => setTimeout(r, 400));
}

async function navigateTab(tabId, url) {
  await dismissComposeBeforeNav(tabId);
  await chrome.tabs.update(tabId, { url });
  return new Promise((resolve) => {
    const timeout = setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(listener);
      resolve();
    }, NAV_TIMEOUT_MS);
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
    if (!url.pathname.startsWith("/home")) {
      console.log("[DevMaker] Not on /home, navigating...");
      await navigateTab(tabId, "https://x.com/home");
    }
  } catch {}
}

async function sendToContent(tabId, cmd, params) {
  return await chrome.tabs.sendMessage(tabId, { cmd, params });
}

async function getXTab() {
  const tabs = await chrome.tabs.query({ url: ["*://x.com/*", "*://twitter.com/*"] });
  if (tabs.length > 0) return tabs[0];

  const newTab = await chrome.tabs.create({ url: "https://x.com/home", active: false });
  await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(listener);
      reject(new Error(`Tab load timed out after ${NEW_TAB_TIMEOUT_MS / 1000}s`));
    }, NEW_TAB_TIMEOUT_MS);
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

// ---- alarms (keepalive + auto-reconnect) ------------------------------------

// Chrome enforces a 30s minimum for alarm periods in production; passing
// 0.5min explicitly so behavior is predictable across Chrome versions.
chrome.alarms.create(KEEPALIVE_ALARM, { periodInMinutes: 0.5 });

chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name !== KEEPALIVE_ALARM) return;
  await ensureConnected();
  if (ws && ws.readyState === WebSocket.OPEN) {
    safeSend({ cmd: "ping" });
  }
});

// ---- runtime lifecycle hooks ------------------------------------------------

chrome.runtime.onStartup.addListener(() => { ensureConnected().catch(() => {}); });
chrome.runtime.onInstalled.addListener(() => { ensureConnected().catch(() => {}); });

// Top-level: runs on every SW (re)load. Idempotent.
ensureConnected().catch(() => {});

// ---- popup messages ---------------------------------------------------------

chrome.runtime.onMessage.addListener((msg, _sender, sendResponseFn) => {
  if (msg.type === "configure") {
    setConfig(msg.backendUrl, msg.accountId).then(async () => {
      if (ws) { try { ws.close(); } catch {} }
      await ensureConnected();
      sendResponseFn({ ok: true });
    });
    return true;
  }
  if (msg.type === "getStatus") {
    getConfig().then(({ backendUrl, accountId }) => {
      sendResponseFn({
        connected: !!(ws && ws.readyState === WebSocket.OPEN),
        backendUrl,
        accountId,
      });
    });
    return true;
  }
  if (msg.type === "disconnect") {
    setConfig("", "").then(() => {
      if (ws) { try { ws.close(); } catch {} }
      ws = null;
      sendResponseFn({ ok: true });
    });
    return true;
  }
  return false;
});
