/**
 * Browser actions — post tweet, comment, like, bookmark, follow, retweet.
 * Uses human simulation for all interactions.
 *
 * NOTE: All page navigation is handled by background.js via chrome.tabs.update.
 * Content script functions must NEVER use window.location.href (it kills the script).
 */

async function actionPostTweet(params = {}) {
  const text = params.text || "";

  // Try sidebar compose button first, then floating action button
  let composeBtn = document.querySelector('[data-testid="SideNav_NewTweet_Button"]');
  if (!composeBtn) composeBtn = document.querySelector('[data-testid="tweetButton"]');
  if (!composeBtn) composeBtn = document.querySelector('a[href="/compose/post"]');
  if (composeBtn) {
    await humanClick(composeBtn);
    await sleep(randomBetween(1500, 3000));
  }

  // Wait specifically for the compose dialog textbox
  const textbox = await waitForElement('[data-testid="tweetTextarea_0"]', 8000);
  if (!textbox) throw new Error("Tweet compose textbox not found");

  await humanClick(textbox);
  await sleep(randomBetween(300, 800));
  await humanType(textbox, text);
  await sleep(randomBetween(800, 2000));

  // The post button inside the compose dialog
  const postBtn = await waitForElement('[data-testid="tweetButton"], [data-testid="tweetButtonInline"]', 5000);
  if (!postBtn) throw new Error("Post button not found");

  await sleep(randomBetween(500, 1500));
  await humanClick(postBtn);
  await sleep(randomBetween(2000, 4000));

  return { status: "ok" };
}

async function actionPostComment(params = {}) {
  const text = params.text || "";

  const replyBox = await waitForElement('[data-testid="tweetTextarea_0"]', 8000);
  if (!replyBox) throw new Error("Reply textbox not found");

  await humanClick(replyBox);
  await sleep(randomBetween(300, 800));
  await humanType(replyBox, text);
  await sleep(randomBetween(500, 1500));

  const replyBtn = await waitForElement('[data-testid="tweetButton"], [data-testid="tweetButtonInline"]');
  if (!replyBtn) throw new Error("Reply button not found");

  await sleep(randomBetween(500, 2000));
  await humanClick(replyBtn);
  await sleep(randomBetween(2000, 4000));

  return { status: "ok" };
}

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
    await humanType(textbox, tweets[i]);
    await sleep(randomBetween(500, 1000));

    if (i < tweets.length - 1) {
      const addBtn = document.querySelector('[data-testid="addButton"]');
      if (addBtn) {
        await humanClick(addBtn);
        await sleep(randomBetween(800, 1500));
      }
    }
  }

  const postBtn = await waitForElement('[data-testid="tweetButton"], [data-testid="tweetButtonInline"]');
  if (postBtn) {
    await sleep(randomBetween(500, 2000));
    await humanClick(postBtn);
    await sleep(randomBetween(2000, 4000));
  }

  return { status: "ok" };
}

async function actionQuoteTweet(params = {}) {
  const text = params.text || "";

  const retweetBtn = document.querySelector('[data-testid="retweet"]');
  if (retweetBtn) {
    await humanClick(retweetBtn);
    await sleep(randomBetween(500, 1000));
  }

  const quoteOpt = await waitForElement('[role="menuitem"]:last-child, [data-testid="Dropdown"] a');
  if (quoteOpt) {
    await humanClick(quoteOpt);
    await sleep(randomBetween(1000, 2000));
  }

  const textbox = await waitForElement('[data-testid="tweetTextarea_0"], [role="textbox"]');
  if (!textbox) throw new Error("Quote textbox not found");

  await humanClick(textbox);
  await sleep(randomBetween(300, 800));
  await humanType(textbox, text);
  await sleep(randomBetween(500, 1500));

  const postBtn = await waitForElement('[data-testid="tweetButton"], [data-testid="tweetButtonInline"]');
  if (postBtn) {
    await sleep(randomBetween(500, 2000));
    await humanClick(postBtn);
    await sleep(randomBetween(2000, 4000));
  }

  return { status: "ok" };
}

async function actionLikePost(params = {}) {
  const likeBtn = document.querySelector('[data-testid="like"]');
  if (!likeBtn) return { status: "ok" };
  await humanClick(likeBtn);
  await sleep(randomBetween(500, 1500));
  return { status: "ok" };
}

async function actionBookmarkPost(params = {}) {
  const bookmarkBtn = document.querySelector('[data-testid="bookmark"]');
  if (!bookmarkBtn) return { status: "ok" };
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
  await sleep(randomBetween(500, 1000));

  const confirmBtn = await waitForElement('[data-testid="retweetConfirm"], [role="menuitem"]', 3000);
  if (confirmBtn) {
    await humanClick(confirmBtn);
    await sleep(randomBetween(1000, 2000));
  }

  return { status: "ok" };
}

// actionNavigate is handled entirely by background.js via chrome.tabs.update

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
