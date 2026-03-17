/**
 * Browser actions — post tweet, comment, like, bookmark, follow, retweet.
 * Uses human simulation for all interactions.
 */

function getPostPath(url) {
  try {
    return new URL(url).pathname;
  } catch {
    return url.replace(/https?:\/\/[^/]+/, "");
  }
}

async function navigateToPost(postUrl) {
  if (!postUrl) return;
  const path = getPostPath(postUrl);
  if (path && !window.location.pathname.startsWith(path)) {
    window.location.href = postUrl;
    await sleep(3000);
  }
}

async function actionPostTweet(params = {}) {
  const text = params.text || "";
  const imageUrls = params.image_urls || [];

  const composeBtn = document.querySelector('[data-testid="SideNav_NewTweet_Button"]');
  if (composeBtn) {
    await humanClick(composeBtn);
    await sleep(randomBetween(1000, 2000));
  }

  const textbox = await waitForElement('[data-testid="tweetTextarea_0"], [role="textbox"]');
  if (!textbox) throw new Error("Tweet textbox not found");

  await humanClick(textbox);
  await sleep(randomBetween(300, 800));
  await humanType(textbox, text);
  await sleep(randomBetween(500, 1500));

  const postBtn = await waitForElement('[data-testid="tweetButton"], [data-testid="tweetButtonInline"]');
  if (!postBtn) throw new Error("Post button not found");

  await sleep(randomBetween(500, 2000));
  await humanClick(postBtn);
  await sleep(randomBetween(2000, 4000));

  return { status: "ok" };
}

async function actionPostComment(params = {}) {
  const text = params.text || "";
  const postUrl = params.post_url || "";

  await navigateToPost(postUrl);

  const replyBox = await waitForElement('[data-testid="tweetTextarea_0"], [role="textbox"]');
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
  const postUrl = params.post_url || "";
  const text = params.text || "";

  await navigateToPost(postUrl);

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
  await navigateToPost(params.post_url);

  const likeBtn = document.querySelector('[data-testid="like"]');
  if (!likeBtn) return { status: "ok" };
  await humanClick(likeBtn);
  await sleep(randomBetween(500, 1500));
  return { status: "ok" };
}

async function actionBookmarkPost(params = {}) {
  await navigateToPost(params.post_url);

  const bookmarkBtn = document.querySelector('[data-testid="bookmark"]');
  if (!bookmarkBtn) return { status: "ok" };
  await humanClick(bookmarkBtn);
  await sleep(randomBetween(500, 1500));
  return { status: "ok" };
}

async function actionFollowUser(params = {}) {
  const handle = params.handle || "";
  if (!handle) throw new Error("No handle provided");

  if (!window.location.href.includes(`/${handle}`)) {
    window.location.href = `https://x.com/${handle}`;
    await sleep(3000);
  }

  const escaped = CSS.escape(`Follow @${handle}`);
  const followBtn = document.querySelector(`[data-testid="placementTracking"] [role="button"], [aria-label="${escaped}"]`);
  if (followBtn) {
    await humanClick(followBtn);
    await sleep(randomBetween(1000, 2000));
  }

  return { status: "ok" };
}

async function actionRetweet(params = {}) {
  const postUrl = params.post_url || "";

  await navigateToPost(postUrl);

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

async function actionNavigate(params = {}) {
  const url = params.url || "";
  if (!url) throw new Error("No URL provided");
  window.location.href = url;
  await sleep(randomBetween(2000, 4000));
  return { status: "ok" };
}

async function actionScroll(params = {}) {
  const count = params.count || 1;
  await smoothScrollDown(count);
  return { status: "ok" };
}

async function actionSessionWarmup() {
  for (let i = 0; i < randomBetween(2, 5); i++) {
    await smoothScrollDown(1);
    await sleep(randomBetween(2000, 6000));
  }

  if (Math.random() < 0.5) {
    window.location.href = "https://x.com/notifications";
    await sleep(randomBetween(3000, 8000));
    for (let i = 0; i < randomBetween(1, 3); i++) {
      await smoothScrollDown(1);
      await sleep(randomBetween(2000, 4000));
    }
  }

  window.location.href = "https://x.com/home";
  await sleep(randomBetween(2000, 5000));
  return { status: "ok" };
}

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
