"""Scroll the X timeline and extract high-engagement posts."""

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from playwright.async_api import Page


@dataclass
class TimelinePost:
    author: str
    handle: str
    text: str
    likes: int
    replies: int
    views: int
    url: str
    image_urls: list = None
    posted_at: datetime | None = None
    velocity: float = 0.0
    virality_score: float = 0.0

    def __post_init__(self):
        if self.image_urls is None:
            self.image_urls = []


def _parse_count(raw: str) -> int:
    """Parse engagement count strings like '2.6K', '152K', '823K', '1.2M'."""
    raw = raw.strip().replace(",", "")
    if not raw:
        return 0
    multiplier = 1
    if raw.upper().endswith("K"):
        multiplier = 1000
        raw = raw[:-1]
    elif raw.upper().endswith("M"):
        multiplier = 1_000_000
        raw = raw[:-1]
    try:
        return int(float(raw) * multiplier)
    except ValueError:
        return 0


async def scrape_timeline(
    page: Page,
    min_likes: int = 100,
    max_posts: int = 30,
    scroll_count: int = 5,
) -> list[TimelinePost]:
    """Scroll the For You timeline and extract posts above engagement threshold."""
    await page.goto("https://x.com/home", wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)

    # Click "For you" tab if available
    try:
        for_you = page.locator('button[role="tab"]:has-text("For you")')
        if await for_you.count() > 0:
            await for_you.first.click()
            await page.wait_for_timeout(1500)
    except Exception:
        pass

    posts: list[TimelinePost] = []
    seen_urls: set[str] = set()

    for _ in range(scroll_count):
        articles = page.locator('article[data-testid="tweet"]')
        count = await articles.count()

        for i in range(count):
            if len(posts) >= max_posts:
                break
            try:
                article = articles.nth(i)
                post = await _extract_post(article)
                if post and post.url not in seen_urls and post.likes >= min_likes:
                    posts.append(post)
                    seen_urls.add(post.url)
            except Exception:
                continue

        await page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
        await page.wait_for_timeout(2000)

    posts.sort(key=lambda p: p.likes, reverse=True)
    return posts


async def _extract_post(article) -> TimelinePost | None:
    """Extract post data from a tweet article element."""
    # Get the post link (contains handle and status ID)
    links = article.locator('a[href*="/status/"]')
    link_count = await links.count()
    url = ""
    handle = ""
    for i in range(link_count):
        href = await links.nth(i).get_attribute("href")
        if href and "/status/" in href and "/analytics" not in href and "/photo/" not in href:
            url = f"https://x.com{href}"
            parts = href.split("/")
            if len(parts) >= 2:
                handle = parts[1]
            break

    if not url:
        return None

    # Get author display name
    author = ""
    try:
        user_link = article.locator(f'a[href="/{handle}"] span').first
        author = await user_link.inner_text()
    except Exception:
        author = handle

    # Get tweet text
    text = ""
    try:
        text_el = article.locator('[data-testid="tweetText"]').first
        text = await text_el.inner_text()
    except Exception:
        pass

    if not text:
        return None

    # Get engagement metrics from aria labels on the group buttons
    likes = 0
    replies = 0
    views = 0

    try:
        # Like button
        like_btn = article.locator('[data-testid="like"], [data-testid="unlike"]').first
        like_label = await like_btn.get_attribute("aria-label") or ""
        like_match = re.search(r"(\d[\d,.]*[KkMm]?)\s*[Ll]ike", like_label)
        if like_match:
            likes = _parse_count(like_match.group(1))
    except Exception:
        pass

    try:
        # Reply button
        reply_btn = article.locator('[data-testid="reply"]').first
        reply_label = await reply_btn.get_attribute("aria-label") or ""
        reply_match = re.search(r"(\d[\d,.]*[KkMm]?)\s*[Rr]epl", reply_label)
        if reply_match:
            replies = _parse_count(reply_match.group(1))
    except Exception:
        pass

    try:
        # Views — look for analytics link text
        analytics = article.locator('a[href*="/analytics"]').first
        views_text = await analytics.inner_text()
        views = _parse_count(views_text)
    except Exception:
        pass

    # Extract image URLs
    image_urls = []
    try:
        images = article.locator('[data-testid="tweetPhoto"] img, [data-testid="tweetPhoto"] [src*="pbs.twimg.com"]')
        img_count = await images.count()
        for i in range(min(img_count, 4)):
            src = await images.nth(i).get_attribute("src")
            if src and "pbs.twimg.com/media/" in src:
                clean = re.sub(r"[&?]name=\w+", "", src)
                clean += ("&" if "?" in clean else "?") + "name=large"
                image_urls.append(clean)
    except Exception:
        pass

    # Extract timestamp
    posted_at = None
    try:
        time_el = article.locator("time[datetime]").first
        if await time_el.count() > 0:
            dt_str = await time_el.get_attribute("datetime")
            if dt_str:
                posted_at = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except Exception:
        pass

    # Calculate velocity and virality
    velocity = 0.0
    virality_score = 0.0
    if posted_at and likes > 0:
        age_hours = max((datetime.now(timezone.utc) - posted_at).total_seconds() / 3600, 0.1)
        velocity = likes / age_hours
        virality_score = velocity * (1 / math.log2(replies + 2))

    return TimelinePost(
        author=author,
        handle=handle,
        text=text,
        likes=likes,
        replies=replies,
        views=views,
        url=url,
        image_urls=image_urls,
        posted_at=posted_at,
        velocity=velocity,
        virality_score=virality_score,
    )


async def scrape_profile_posts(
    page: Page,
    handle: str,
    max_posts: int = 5,
) -> list[TimelinePost]:
    """Visit a user's profile and extract their recent posts."""
    await page.goto(f"https://x.com/{handle}", wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)

    posts: list[TimelinePost] = []
    seen_urls: set[str] = set()

    articles = page.locator('article[data-testid="tweet"]')
    count = await articles.count()

    for i in range(min(count, max_posts + 5)):
        if len(posts) >= max_posts:
            break
        try:
            article = articles.nth(i)
            post = await _extract_post(article)
            if post and post.url not in seen_urls:
                # Only include posts from this handle (skip reposts of others)
                if post.handle.lower() == handle.lower():
                    posts.append(post)
                    seen_urls.add(post.url)
        except Exception:
            continue

    return posts


async def scrape_top_replies(
    page: Page,
    post_url: str,
    max_replies: int = 5,
) -> list[str]:
    """Visit a post and extract the text of the top visible replies for context."""
    await page.goto(post_url, wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)

    replies: list[str] = []
    articles = page.locator('article[data-testid="tweet"]')
    count = await articles.count()

    for i in range(min(count, max_replies + 3)):
        if len(replies) >= max_replies:
            break
        try:
            article = articles.nth(i)
            # Skip the original post (first article is usually the OP)
            link = article.locator('a[href*="/status/"]').first
            href = await link.get_attribute("href") or ""
            # The OP article links to its own URL; replies link to different status IDs
            if post_url.rstrip("/").endswith(href.rstrip("/")):
                continue

            text_el = article.locator('[data-testid="tweetText"]').first
            text = await text_el.inner_text()
            text = text.strip()
            if text and len(text) < 300:
                replies.append(text)
        except Exception:
            continue

    return replies


async def scrape_profile_retweets(
    page: Page,
    handle: str,
    max_scrolls: int = 50,
    log_fn=None,
) -> list[str]:
    """Scroll a profile's timeline and collect URLs of posts they retweeted.

    Returns URLs in oldest-first order (reversed from X's newest-first display).
    """
    def _log(msg: str):
        if log_fn:
            log_fn(msg)

    await page.goto(f"https://x.com/{handle}", wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)

    rt_urls: list[str] = []
    seen: set[str] = set()
    stale_rounds = 0

    for scroll_idx in range(max_scrolls):
        articles = page.locator('article[data-testid="tweet"]')
        count = await articles.count()

        found_this_scroll = 0
        for i in range(count):
            try:
                article = articles.nth(i)

                social_ctx = article.locator('[data-testid="socialContext"]')
                if await social_ctx.count() == 0:
                    continue
                ctx_text = await social_ctx.first.inner_text()
                if "reposted" not in ctx_text.lower() and "retweeted" not in ctx_text.lower():
                    continue

                links = article.locator('a[href*="/status/"]')
                link_count = await links.count()
                url = ""
                for j in range(link_count):
                    href = await links.nth(j).get_attribute("href")
                    if href and "/status/" in href and "/analytics" not in href and "/photo/" not in href:
                        url = f"https://x.com{href}"
                        break

                if url and url not in seen:
                    rt_urls.append(url)
                    seen.add(url)
                    found_this_scroll += 1
            except Exception:
                continue

        _log(f"  [Scroll {scroll_idx + 1}/{max_scrolls}] Found {found_this_scroll} new RTs (total: {len(rt_urls)})")

        if found_this_scroll == 0:
            stale_rounds += 1
            if stale_rounds >= 5:
                _log("  [Scroll] No new retweets for 5 scrolls, stopping.")
                break
        else:
            stale_rounds = 0

        await page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
        await page.wait_for_timeout(1500)

    rt_urls.reverse()
    _log(f"  [Scrape] Collected {len(rt_urls)} retweets from @{handle} (oldest first).")
    return rt_urls


async def scrape_timeline_with_age(
    page: Page,
    min_likes: int = 50,
    max_posts: int = 30,
    scroll_count: int = 5,
) -> list[TimelinePost]:
    """Like scrape_timeline but sorts by virality_score (engagement velocity / reply saturation)."""
    await page.goto("https://x.com/home", wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)

    try:
        for_you = page.locator('button[role="tab"]:has-text("For you")')
        if await for_you.count() > 0:
            await for_you.first.click()
            await page.wait_for_timeout(1500)
    except Exception:
        pass

    posts: list[TimelinePost] = []
    seen_urls: set[str] = set()

    for _ in range(scroll_count):
        articles = page.locator('article[data-testid="tweet"]')
        count = await articles.count()

        for i in range(count):
            if len(posts) >= max_posts:
                break
            try:
                article = articles.nth(i)
                post = await _extract_post(article)
                if post and post.url not in seen_urls and post.likes >= min_likes:
                    posts.append(post)
                    seen_urls.add(post.url)
            except Exception:
                continue

        await page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
        await page.wait_for_timeout(2000)

    posts.sort(key=lambda p: p.virality_score, reverse=True)
    return posts


async def check_post_performance(
    page: Page,
    handle: str,
    max_posts: int = 10,
) -> list[dict]:
    """Visit own profile and extract performance metrics for recent posts."""
    await page.goto(f"https://x.com/{handle}", wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)

    results: list[dict] = []
    seen_urls: set[str] = set()
    articles = page.locator('article[data-testid="tweet"]')
    count = await articles.count()

    for i in range(min(count, max_posts + 5)):
        if len(results) >= max_posts:
            break
        try:
            article = articles.nth(i)
            post = await _extract_post(article)
            if not post or post.url in seen_urls:
                continue
            if post.handle.lower() != handle.lower():
                continue
            seen_urls.add(post.url)
            results.append({
                "url": post.url,
                "text_preview": post.text[:100],
                "likes": post.likes,
                "replies": post.replies,
                "views": post.views,
                "posted_at": post.posted_at.isoformat() if post.posted_at else "",
            })
        except Exception:
            continue

    return results


async def scrape_who_to_follow(page: Page) -> list[str]:
    """Extract handles from the 'Who to follow' sidebar."""
    handles = []
    try:
        aside = page.locator('[aria-label="Who to follow"]')
        if await aside.count() == 0:
            aside = page.locator('aside:has-text("Who to follow")')

        follow_buttons = aside.locator('button:has-text("Follow")')
        count = await follow_buttons.count()

        for i in range(min(count, 5)):
            btn = follow_buttons.nth(i)
            label = await btn.get_attribute("aria-label") or ""
            if label.startswith("Follow @"):
                handles.append(label.replace("Follow @", "").strip())
    except Exception:
        pass

    return handles
