/**
 * Content script — listens for commands from the background service worker
 * and dispatches to scraper/action functions.
 */

const COMMAND_HANDLERS = {
  scrape_timeline: async (params) => ({ status: "ok", data: await scrapeTimeline(params) }),
  scrape_replies: async (params) => ({ status: "ok", data: await scrapeReplies(params) }),
  scrape_who_to_follow: async () => ({ status: "ok", data: await scrapeWhoToFollow() }),
  scrape_retweets: async (params) => ({ status: "ok", data: await scrapeRetweets(params) }),
  scrape_performance: async (params) => ({ status: "ok", data: await scrapePerformance(params) }),

  post_tweet: async (params) => await actionPostTweet(params),
  post_comment: async (params) => await actionPostComment(params),
  post_thread: async (params) => await actionPostThread(params),
  quote_tweet: async (params) => await actionQuoteTweet(params),
  like_post: async (params) => await actionLikePost(params),
  bookmark_post: async (params) => await actionBookmarkPost(params),
  follow_user: async (params) => await actionFollowUser(params),
  retweet: async (params) => await actionRetweet(params),

  // navigate and session_warmup are handled by background.js
  dismiss_compose: async () => await actionDismissCompose(),
  click_following_tab: async () => await actionClickFollowingTab(),
  scroll: async (params) => await actionScroll(params),
  lurk_scroll: async (params) => await actionLurkScroll(params),

  ping: async () => ({ status: "ok" }),
  status: async () => ({ status: "ok", data: { url: window.location.href } }),
};

const _BYPASS_LOCK = new Set(["ping", "status", "dismiss_compose"]);
let _activeLock = null;

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  const handler = COMMAND_HANDLERS[msg.cmd];
  if (!handler) {
    sendResponse({ status: "error", error: `Unknown command: ${msg.cmd}` });
    return true;
  }

  if (!_BYPASS_LOCK.has(msg.cmd) && _activeLock) {
    console.log(`[DevMaker] Rejecting ${msg.cmd} — busy with ${_activeLock}`);
    sendResponse({ status: "error", error: `Busy with ${_activeLock}, rejected: ${msg.cmd}` });
    return true;
  }

  const needsLock = !_BYPASS_LOCK.has(msg.cmd);
  if (needsLock) _activeLock = msg.cmd;

  handler(msg.params || {})
    .then((result) => sendResponse(result))
    .catch((err) => sendResponse({ status: "error", error: err.message }))
    .finally(() => { if (needsLock) _activeLock = null; });

  return true;
});

console.log("[DevMaker] Content script loaded on", window.location.href);
