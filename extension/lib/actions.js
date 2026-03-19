/**
 * Browser actions — post tweet, comment, like, bookmark, follow, retweet.
 * Uses human simulation for all interactions.
 *
 * NOTE: All page navigation is handled by background.js via chrome.tabs.update.
 * Content script functions must NEVER use window.location.href (it kills the script).
 */

const _ACTION_TIMEOUT_MS = 120000;

async function _attachImages(imageUrls) {
  if (!imageUrls || imageUrls.length === 0) return;

  const fileInput = document.querySelector('input[type="file"][accept*="image"]') ||
    document.querySelector('input[type="file"]');
  if (!fileInput) {
    console.log("[DevMaker] No file input found for image upload");
    return;
  }

  const dt = new DataTransfer();
  for (const url of imageUrls.slice(0, 4)) {
    try {
      const resp = await fetch(url, { credentials: "omit" });
      if (!resp.ok) continue;
      const blob = await resp.blob();
      const ext = (blob.type || "image/jpeg").split("/")[1] || "jpg";
      dt.items.add(new File([blob], `img_${Date.now()}_${dt.files.length}.${ext}`, { type: blob.type || "image/jpeg" }));
    } catch (err) {
      console.log("[DevMaker] Failed to fetch image:", url.slice(0, 60), err.message);
    }
  }

  if (dt.files.length === 0) return;
  fileInput.files = dt.files;
  fileInput.dispatchEvent(new Event("change", { bubbles: true }));
  console.log(`[DevMaker] Attached ${dt.files.length} image(s)`);
  await sleep(randomBetween(1500, 3000));
}

function _withTimeout(fn, label) {
  return (params) => Promise.race([
    fn(params),
    new Promise((_, reject) =>
      setTimeout(() => reject(new Error(`${label} timed out internally (120s)`)), _ACTION_TIMEOUT_MS)
    ),
  ]);
}

function _isComposeStillActive() {
  const textarea = document.querySelector('[data-testid="tweetTextarea_0"]');
  if (!textarea) return false;
  if (textarea.closest('[role="dialog"]')) return true;
  if (getTextboxContent(textarea).length > 0) return true;
  return false;
}

function _isPostButtonDisabled() {
  const btn = document.querySelector('[data-testid="tweetButton"], [data-testid="tweetButtonInline"]');
  if (!btn) return true;
  return btn.getAttribute("aria-disabled") === "true" ||
    btn.disabled ||
    !!btn.closest('[aria-disabled="true"]');
}

/**
 * After humanType, verify the Post button is enabled. If not, the editor
 * didn't accept the text — clear and retry with paste.
 */
async function _ensureEditorAccepted(element, text, label) {
  if (!_isPostButtonDisabled()) return;

  console.log(`[DevMaker] ${label}: Post button disabled after typing — retrying with paste`);
  await clearTextbox(element);
  await sleep(randomBetween(300, 600));
  element.focus();
  _pasteText(element, text);
  await sleep(randomBetween(800, 1500));

  if (!_isPostButtonDisabled()) return;

  console.log(`[DevMaker] ${label}: paste also failed, trying char-by-char`);
  await clearTextbox(element);
  await sleep(randomBetween(300, 600));
  element.focus();
  await sleep(randomBetween(100, 200));
  await _typeCharByChar(element, text, 8, 25);
  await sleep(randomBetween(500, 1000));

  if (_isPostButtonDisabled()) {
    throw new Error(`${label}: Post button still disabled after 3 typing attempts`);
  }
}

async function _submitAndVerify(label) {
  const postBtn = document.querySelector('[data-testid="tweetButton"], [data-testid="tweetButtonInline"]');
  if (!postBtn) throw new Error(`${label}: Post button not found`);

  if (_isPostButtonDisabled()) {
    throw new Error(`${label}: Post button is disabled — editor did not accept the text`);
  }

  await humanClick(postBtn);
  await sleep(randomBetween(2500, 4500));

  if (!_isComposeStillActive()) return;

  console.log(`[DevMaker] ${label}: compose still active after click, retrying...`);
  const retryBtn = document.querySelector('[data-testid="tweetButton"], [data-testid="tweetButtonInline"]');
  if (retryBtn) {
    await humanClick(retryBtn);
    await sleep(randomBetween(3000, 5000));
  }

  if (_isComposeStillActive()) {
    throw new Error(`${label} failed: compose still open after 2 submit attempts`);
  }
}

async function _doPostTweet(params = {}) {
  const text = params.text || "";
  const imageUrls = params.image_urls || [];

  const existingDialog = document.querySelector('[data-testid="tweetTextarea_0"]');
  if (existingDialog && (existingDialog.textContent || "").trim().length > 0) {
    const closeBtn = document.querySelector('[data-testid="app-bar-close"], [aria-label="Close"]');
    if (closeBtn) {
      await humanClick(closeBtn);
      await sleep(randomBetween(500, 1000));
      const discardBtn = document.querySelector('[data-testid="confirmationSheetConfirm"]');
      if (discardBtn) {
        await humanClick(discardBtn);
        await sleep(randomBetween(500, 1000));
      }
    }
  }

  let composeBtn = document.querySelector('[data-testid="SideNav_NewTweet_Button"]');
  if (!composeBtn) composeBtn = document.querySelector('a[href="/compose/post"]');
  if (composeBtn) {
    await humanClick(composeBtn);
    await sleep(randomBetween(1500, 3000));
  }

  const textbox = await waitForElement('[data-testid="tweetTextarea_0"]', 8000);
  if (!textbox) throw new Error("Tweet compose textbox not found");

  if (imageUrls.length > 0) {
    await _attachImages(imageUrls);
  }

  await humanClick(textbox);
  await sleep(randomBetween(300, 800));
  await clearTextbox(textbox);
  await humanType(textbox, text);
  await sleep(randomBetween(800, 2000));

  const actual = getTextboxContent(textbox);
  const expected = text.trim();
  if (actual.length < expected.length * 0.8) {
    throw new Error(`Typed content truncated: expected ${expected.length} chars, got ${actual.length}`);
  }

  await waitForElement('[data-testid="tweetButton"], [data-testid="tweetButtonInline"]', 5000);
  await sleep(randomBetween(500, 1500));
  await _ensureEditorAccepted(textbox, text, "post_tweet");
  await _submitAndVerify("post_tweet");

  return { status: "ok" };
}

const actionPostTweet = _withTimeout(_doPostTweet, "post_tweet");

async function _doPostComment(params = {}) {
  const text = params.text || "";

  const openReplyBtn = document.querySelector('[data-testid="reply"]');
  if (openReplyBtn) {
    await humanClick(openReplyBtn);
    await sleep(randomBetween(1500, 3000));
  }

  const replyBox = await waitForElement('[data-testid="tweetTextarea_0"]', 12000);
  if (!replyBox) throw new Error("Reply textbox not found");

  await humanClick(replyBox);
  await sleep(randomBetween(300, 800));
  await clearTextbox(replyBox);
  await humanType(replyBox, text);
  await sleep(randomBetween(500, 1500));

  const actual = getTextboxContent(replyBox);
  const trimmed = text.trim();
  if (actual.length < trimmed.length * 0.8) {
    throw new Error(`Reply truncated: expected ${trimmed.length} chars, got ${actual.length}`);
  }

  await waitForElement('[data-testid="tweetButton"], [data-testid="tweetButtonInline"]', 8000);
  await sleep(randomBetween(500, 2000));
  await _ensureEditorAccepted(replyBox, text, "post_comment");
  await _submitAndVerify("post_comment");

  return { status: "ok" };
}

const actionPostComment = _withTimeout(_doPostComment, "post_comment");

async function actionPostThread(params = {}) {
  const tweets = params.tweets || [];
  if (tweets.length === 0) throw new Error("No tweets provided");

  const composeBtn = document.querySelector('[data-testid="SideNav_NewTweet_Button"]');
  if (composeBtn) {
    await humanClick(composeBtn);
    await sleep(randomBetween(1000, 2000));
  }

  for (let i = 0; i < tweets.length; i++) {
    const textbox = await waitForElement(`[data-testid="tweetTextarea_${i}"], [role="textbox"]`, 5000);
    if (!textbox) throw new Error(`Thread textbox ${i} not found`);

    await humanClick(textbox);
    await sleep(randomBetween(300, 600));
    await clearTextbox(textbox);
    await humanType(textbox, tweets[i]);
    await sleep(randomBetween(500, 1000));

    const actual = getTextboxContent(textbox);
    const trimmed = tweets[i].trim();
    if (actual.length < trimmed.length * 0.8) {
      throw new Error(`Thread tweet ${i + 1} truncated: expected ${trimmed.length} chars, got ${actual.length}`);
    }

    if (i < tweets.length - 1) {
      const addBtn = document.querySelector('[data-testid="addButton"]');
      if (addBtn) {
        await humanClick(addBtn);
        await sleep(randomBetween(800, 1500));
      }
    }
  }

  await _ensureEditorAccepted(
    document.querySelector('[data-testid="tweetTextarea_0"], [role="textbox"]'),
    tweets[tweets.length - 1],
    "post_thread"
  );
  await _submitAndVerify("post_thread");

  return { status: "ok" };
}

async function _doQuoteTweet(params = {}) {
  const text = params.text || "";

  const retweetBtn = document.querySelector('[data-testid="retweet"]');
  if (!retweetBtn) throw new Error("Retweet button not found — cannot quote");
  await humanClick(retweetBtn);
  await sleep(randomBetween(800, 1500));

  const menuItems = document.querySelectorAll('[role="menuitem"]');
  let quoteOpt = null;
  for (const item of menuItems) {
    const label = (item.textContent || "").toLowerCase();
    if (label.includes("quote")) {
      quoteOpt = item;
      break;
    }
  }
  if (!quoteOpt && menuItems.length >= 2) {
    quoteOpt = menuItems[menuItems.length - 1];
  }
  if (!quoteOpt) throw new Error("Quote option not found in menu");
  await humanClick(quoteOpt);
  await sleep(randomBetween(1500, 3000));

  const textbox = await waitForElement('[data-testid="tweetTextarea_0"]', 8000);
  if (!textbox) throw new Error("Quote compose textbox not found");

  await humanClick(textbox);
  await sleep(randomBetween(300, 800));
  await clearTextbox(textbox);
  await humanType(textbox, text);
  await sleep(randomBetween(800, 2000));

  const actual = getTextboxContent(textbox);
  const trimmed = text.trim();
  if (actual.length < trimmed.length * 0.8) {
    throw new Error(`Quote text truncated: expected ${trimmed.length} chars, got ${actual.length}`);
  }

  await waitForElement('[data-testid="tweetButton"], [data-testid="tweetButtonInline"]', 5000);
  await sleep(randomBetween(500, 1500));
  await _ensureEditorAccepted(textbox, text, "quote_tweet");
  await _submitAndVerify("quote_tweet");

  return { status: "ok" };
}

const actionQuoteTweet = _withTimeout(_doQuoteTweet, "quote_tweet");

async function actionLikePost(params = {}) {
  const likeBtn = document.querySelector('[data-testid="like"]');
  if (!likeBtn) return { status: "skipped", error: "Like button not found" };
  await humanClick(likeBtn);
  await sleep(randomBetween(500, 1500));
  return { status: "ok" };
}

async function actionBookmarkPost(params = {}) {
  const bookmarkBtn = document.querySelector('[data-testid="bookmark"]');
  if (!bookmarkBtn) return { status: "skipped", error: "Bookmark button not found" };
  await humanClick(bookmarkBtn);
  await sleep(randomBetween(500, 1500));
  return { status: "ok" };
}

async function actionFollowUser(params = {}) {
  const handle = params.handle || "";
  if (!handle) throw new Error("No handle provided");

  const escaped = CSS.escape(`Follow @${handle}`);
  const followBtn = document.querySelector(`[data-testid="placementTracking"] [role="button"], [aria-label="${escaped}"]`);
  if (followBtn) {
    await humanClick(followBtn);
    await sleep(randomBetween(1000, 2000));
  }

  return { status: "ok" };
}

async function actionRetweet(params = {}) {
  const retweetBtn = document.querySelector('[data-testid="retweet"]');
  if (!retweetBtn) return { status: "error", error: "Retweet button not found" };

  await humanClick(retweetBtn);
  await sleep(randomBetween(800, 1500));

  const menuItems = document.querySelectorAll('[role="menuitem"]');
  let repostOpt = null;
  for (const item of menuItems) {
    const label = (item.textContent || "").toLowerCase();
    if (label.includes("repost") || label.includes("retweet")) {
      repostOpt = item;
      break;
    }
  }
  if (!repostOpt) {
    repostOpt = await waitForElement('[data-testid="retweetConfirm"]', 3000);
  }
  if (!repostOpt) {
    return { status: "error", error: "Repost menu item not found" };
  }
  await humanClick(repostOpt);
  await sleep(randomBetween(1000, 2000));

  return { status: "ok" };
}

async function actionClickFollowingTab() {
  const tabs = document.querySelectorAll('[role="tab"]');
  for (const tab of tabs) {
    if (tab.textContent.trim().toLowerCase() === "following") {
      await humanClick(tab);
      await sleep(randomBetween(1500, 3000));
      return { status: "ok" };
    }
  }
  const link = document.querySelector('a[href="/home"][role="tab"]');
  if (link) {
    const allTabs = link.closest('[role="tablist"]');
    if (allTabs) {
      const tabItems = allTabs.querySelectorAll('[role="tab"]');
      if (tabItems.length >= 2) {
        await humanClick(tabItems[1]);
        await sleep(randomBetween(1500, 3000));
        return { status: "ok" };
      }
    }
  }
  return { status: "ok" };
}

// actionNavigate is handled entirely by background.js via chrome.tabs.update

async function actionDismissCompose() {
  for (let attempt = 0; attempt < 3; attempt++) {
    const modal = document.querySelector('[role="dialog"]');
    const textarea = document.querySelector('[data-testid="tweetTextarea_0"]');
    const hasContent = textarea && (textarea.textContent || "").trim().length > 0;
    const isInModal = textarea?.closest('[role="dialog"]');

    if (!modal && !textarea) break;

    if (modal && (hasContent || textarea)) {
      if (hasContent) {
        await clearTextbox(textarea);
        await sleep(300);
      }
      const closeBtn = modal.querySelector('[data-testid="app-bar-close"]');
      if (closeBtn) {
        await humanClick(closeBtn);
        await sleep(600);
      }
      const discardBtn = document.querySelector('[data-testid="confirmationSheetConfirm"]') ||
        [...document.querySelectorAll('button, [role="button"]')].find((b) =>
          /discard|don.?t save|don.?t keep/i.test(b.textContent || "")
        );
      if (discardBtn) {
        await humanClick(discardBtn);
        await sleep(600);
      }
    } else if (textarea && hasContent && !isInModal) {
      await clearTextbox(textarea);
      await sleep(200);
    } else {
      const closeBtn = document.querySelector('[data-testid="app-bar-close"]');
      if (closeBtn) {
        await humanClick(closeBtn);
        await sleep(300);
      }
    }

    document.body?.focus();
    if (document.activeElement && document.activeElement !== document.body) {
      document.activeElement.blur?.();
    }
    await sleep(150);
  }
  return { status: "ok" };
}

async function actionScroll(params = {}) {
  const count = params.count || 1;
  await smoothScrollDown(count);
  return { status: "ok" };
}

// actionSessionWarmup is handled by background.js (scroll via content + navigate via tabs API)

async function actionLurkScroll(params = {}) {
  const count = params.count || randomBetween(3, 8);
  for (let i = 0; i < count; i++) {
    await smoothScrollDown(1);
    const pause = randomBetween(2000, 8000);
    await sleep(pause);
    if (Math.random() < 0.2) {
      await sleep(randomBetween(5000, 15000));
    }
  }
  return { status: "ok" };
}
