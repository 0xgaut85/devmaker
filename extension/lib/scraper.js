/**
 * DOM-based scraping functions for x.com — replaces Playwright timeline_scraper.py.
 * Uses the same selectors and data extraction logic.
 */

function parseCount(raw) {
  if (!raw) return 0;
  raw = raw.trim().replace(/,/g, "");
  let multiplier = 1;
  if (raw.toUpperCase().endsWith("K")) {
    multiplier = 1000;
    raw = raw.slice(0, -1);
  } else if (raw.toUpperCase().endsWith("M")) {
    multiplier = 1_000_000;
    raw = raw.slice(0, -1);
  }
  const val = parseFloat(raw);
  return isNaN(val) ? 0 : Math.round(val * multiplier);
}

function extractPost(article) {
  const links = article.querySelectorAll('a[href*="/status/"]');
  let url = "";
  let handle = "";
  for (const link of links) {
    const href = link.getAttribute("href");
    if (href && href.includes("/status/") && !href.includes("/analytics") && !href.includes("/photo/")) {
      url = `https://x.com${href}`;
      const parts = href.split("/");
      if (parts.length >= 2) handle = parts[1];
      break;
    }
  }
  if (!url) return null;

  let author = handle;
  try {
    const userLink = article.querySelector(`a[href="/${handle}"] span`);
    if (userLink) author = userLink.innerText;
  } catch {}

  let text = "";
  try {
    const textEl = article.querySelector('[data-testid="tweetText"]');
    if (textEl) text = textEl.innerText;
  } catch {}
  if (!text) return null;

  let likes = 0, replies = 0, views = 0;

  try {
    const likeBtn = article.querySelector('[data-testid="like"], [data-testid="unlike"]');
    if (likeBtn) {
      const label = likeBtn.getAttribute("aria-label") || "";
      const m = label.match(/([\d,.]+[KkMm]?)\s*[Ll]ike/);
      if (m) likes = parseCount(m[1]);
    }
  } catch {}

  try {
    const replyBtn = article.querySelector('[data-testid="reply"]');
    if (replyBtn) {
      const label = replyBtn.getAttribute("aria-label") || "";
      const m = label.match(/([\d,.]+[KkMm]?)\s*[Rr]epl/);
      if (m) replies = parseCount(m[1]);
    }
  } catch {}

  try {
    const analyticsLink = article.querySelector('a[href*="/analytics"]');
    if (analyticsLink) views = parseCount(analyticsLink.innerText);
  } catch {}

  const imageUrls = [];
  try {
    const imgs = article.querySelectorAll('[data-testid="tweetPhoto"] img');
    for (let i = 0; i < Math.min(imgs.length, 4); i++) {
      let src = imgs[i].getAttribute("src");
      if (src && src.includes("pbs.twimg.com/media/")) {
        src = src.replace(/[&?]name=\w+/, "");
        src += (src.includes("?") ? "&" : "?") + "name=large";
        imageUrls.push(src);
      }
    }
  } catch {}

  let postedAt = null;
  let velocity = 0;
  let viralityScore = 0;
  try {
    const timeEl = article.querySelector("time[datetime]");
    if (timeEl) {
      const dtStr = timeEl.getAttribute("datetime");
      if (dtStr) {
        postedAt = dtStr;
        const postedDate = new Date(dtStr);
        const ageHours = Math.max((Date.now() - postedDate.getTime()) / 3600000, 0.1);
        velocity = likes / ageHours;
        viralityScore = velocity * (1 / Math.log2(replies + 2));
      }
    }
  } catch {}

  return { author, handle, text, likes, replies, views, url, image_urls: imageUrls, posted_at: postedAt, velocity, virality_score: viralityScore };
}

async function scrapeTimeline(params = {}) {
  const minLikes = params.min_likes || 100;
  const maxPosts = params.max_posts || 30;
  const scrollCount = Math.min(params.scroll_count || 5, 4);
  const sortBy = params.sort_by || "likes";
  const maxTime = 45000;

  const posts = [];
  const seenUrls = new Set();
  const start = Date.now();

  for (let s = 0; s < scrollCount; s++) {
    if (Date.now() - start > maxTime) break;

    const articles = document.querySelectorAll('article[data-testid="tweet"]');
    for (const article of articles) {
      if (posts.length >= maxPosts) break;
      try {
        const post = extractPost(article);
        if (post && !seenUrls.has(post.url) && post.likes >= minLikes) {
          posts.push(post);
          seenUrls.add(post.url);
        }
      } catch {}
    }
    window.scrollBy({ top: window.innerHeight * 1.5, behavior: "auto" });
    await sleep(800 + Math.random() * 700);
  }

  if (sortBy === "virality") {
    posts.sort((a, b) => b.virality_score - a.virality_score);
  } else {
    posts.sort((a, b) => b.likes - a.likes);
  }
  return posts;
}

async function scrapeReplies(params = {}) {
  const maxReplies = params.max_replies || 5;
  const replies = [];
  const articles = document.querySelectorAll('article[data-testid="tweet"]');

  // Skip index 0 — that's the original post, not a reply
  for (let i = 1; i < Math.min(articles.length, maxReplies + 4); i++) {
    if (replies.length >= maxReplies) break;
    try {
      const article = articles[i];
      const textEl = article.querySelector('[data-testid="tweetText"]');
      if (!textEl) continue;
      const text = textEl.innerText.trim();
      if (text && text.length < 300) {
        replies.push(text);
      }
    } catch {}
  }
  return replies;
}

async function scrapeWhoToFollow() {
  const handles = [];
  try {
    let aside = document.querySelector('[aria-label="Who to follow"]');
    if (!aside) {
      aside = document.querySelector('aside');
    }
    if (!aside) return handles;

    const buttons = aside.querySelectorAll('button');
    for (const btn of buttons) {
      const label = btn.getAttribute("aria-label") || "";
      if (label.startsWith("Follow @")) {
        handles.push(label.replace("Follow @", "").trim());
      }
      if (handles.length >= 5) break;
    }
  } catch {}
  return handles;
}

async function scrapeRetweets(params = {}) {
  const handle = params.handle;
  const maxScrolls = params.max_scrolls || 50;

  const rtUrls = [];
  const seen = new Set();
  let staleRounds = 0;

  for (let s = 0; s < maxScrolls; s++) {
    const articles = document.querySelectorAll('article[data-testid="tweet"]');
    let foundThisScroll = 0;

    for (const article of articles) {
      try {
        const ctx = article.querySelector('[data-testid="socialContext"]');
        if (!ctx) continue;
        const ctxText = ctx.innerText.toLowerCase();
        if (!ctxText.includes("reposted") && !ctxText.includes("retweeted")) continue;

        const links = article.querySelectorAll('a[href*="/status/"]');
        let url = "";
        for (const link of links) {
          const href = link.getAttribute("href");
          if (href && href.includes("/status/") && !href.includes("/analytics") && !href.includes("/photo/")) {
            url = `https://x.com${href}`;
            break;
          }
        }

        if (url && !seen.has(url)) {
          rtUrls.push(url);
          seen.add(url);
          foundThisScroll++;
        }
      } catch {}
    }

    if (foundThisScroll === 0) {
      staleRounds++;
      if (staleRounds >= 5) break;
    } else {
      staleRounds = 0;
    }

    await humanScroll(window.innerHeight * randomBetween(1.5, 2.5));
    await sleep(randomBetween(1200, 2500));
  }

  rtUrls.reverse();
  return rtUrls;
}

async function scrapePerformance(params = {}) {
  const maxPosts = params.max_posts || 10;
  const results = [];
  const seenUrls = new Set();
  const articles = document.querySelectorAll('article[data-testid="tweet"]');

  for (let i = 0; i < Math.min(articles.length, maxPosts + 5); i++) {
    if (results.length >= maxPosts) break;
    try {
      const post = extractPost(articles[i]);
      if (!post || seenUrls.has(post.url)) continue;
      seenUrls.add(post.url);
      results.push({
        url: post.url,
        text_preview: post.text.slice(0, 100),
        likes: post.likes,
        replies: post.replies,
        views: post.views,
        posted_at: post.posted_at || "",
      });
    } catch {}
  }
  return results;
}

// sleep, humanScroll, randomBetween are provided by human.js (loaded first)
