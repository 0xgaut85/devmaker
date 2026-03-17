"""Browser actions: post tweet, quote RT, plain RT, comment, follow."""

import asyncio
import os
import random
import tempfile
import httpx
from playwright.async_api import Page


def _jitter(ms: int) -> int:
    """Add +/-30% random jitter to a delay in milliseconds."""
    return int(ms * random.uniform(0.7, 1.3))


async def post_tweet(
    page: Page, text: str, delay: int = 3, image_paths: list[str] | None = None
) -> bool:
    """Post a new tweet, optionally with images."""
    await page.goto("https://x.com/compose/post", wait_until="domcontentloaded")
    await page.wait_for_timeout(_jitter(2000))

    editor = page.locator('[data-testid="tweetTextarea_0"], [role="textbox"]').first
    await editor.click()
    await page.wait_for_timeout(_jitter(500))

    await _human_type(page, text)
    await page.wait_for_timeout(_jitter(800))

    if image_paths:
        await _attach_images(page, image_paths)
        await page.wait_for_timeout(_jitter(1500))

    post_btn = page.locator('[data-testid="tweetButton"], [data-testid="tweetButtonInline"]').first
    await post_btn.click()
    await page.wait_for_timeout(_jitter(delay * 1000))
    return True


async def post_quote_rt(page: Page, post_url: str, comment: str, delay: int = 3) -> bool:
    """Quote retweet a post with a comment."""
    await page.goto(post_url, wait_until="domcontentloaded")
    await page.wait_for_timeout(_jitter(2500))

    repost_btn = page.locator('[data-testid="retweet"]').first
    await repost_btn.click()
    await page.wait_for_timeout(_jitter(1000))

    quote_opt = page.locator('[data-testid="Dropdown"] a:has-text("Quote"), [role="menuitem"]:has-text("Quote")')
    if await quote_opt.count() == 0:
        quote_opt = page.get_by_text("Quote", exact=True)
    await quote_opt.first.click()
    await page.wait_for_timeout(_jitter(1500))

    editor = page.locator('[data-testid="tweetTextarea_0"], [role="textbox"]').first
    await editor.click()
    await page.wait_for_timeout(_jitter(500))
    await _human_type(page, comment)
    await page.wait_for_timeout(_jitter(800))

    post_btn = page.locator('[data-testid="tweetButton"], [data-testid="tweetButtonInline"]').first
    await post_btn.click()
    await page.wait_for_timeout(_jitter(delay * 1000))
    return True


async def plain_repost(page: Page, post_url: str, delay: int = 3) -> bool:
    """Plain repost (RT without comment)."""
    await page.goto(post_url, wait_until="domcontentloaded")
    await page.wait_for_timeout(_jitter(2500))

    repost_btn = page.locator('[data-testid="retweet"]').first
    await repost_btn.click()
    await page.wait_for_timeout(_jitter(1000))

    repost_opt = page.locator('[data-testid="retweetConfirm"], [role="menuitem"]:has-text("Repost")')
    if await repost_opt.count() == 0:
        repost_opt = page.get_by_text("Repost", exact=True).first
    await repost_opt.click()
    await page.wait_for_timeout(_jitter(delay * 1000))
    return True


async def post_comment(page: Page, post_url: str, comment: str, delay: int = 3) -> bool:
    """Reply to a post with a comment."""
    await page.goto(post_url, wait_until="domcontentloaded")
    await page.wait_for_timeout(_jitter(2500))

    reply_box = page.locator(
        '[data-testid="tweetTextarea_0"], '
        'div[data-testid="tweetTextarea_0"]'
    ).first

    try:
        if not await reply_box.is_visible():
            placeholder = page.get_by_text("Post your reply")
            if await placeholder.count() > 0:
                await placeholder.first.click()
                await page.wait_for_timeout(_jitter(500))
    except Exception:
        pass

    await reply_box.click()
    await page.wait_for_timeout(_jitter(500))
    await _human_type(page, comment)
    await page.wait_for_timeout(_jitter(800))

    reply_btn = page.locator(
        '[data-testid="tweetButtonInline"], [data-testid="tweetButton"]'
    ).first
    await reply_btn.click()
    await page.wait_for_timeout(_jitter(delay * 1000))
    return True


async def like_post(page: Page, post_url: str) -> bool:
    """Like a post. Returns True if successfully liked (wasn't already liked)."""
    like_btn = page.locator('[data-testid="like"]').first
    try:
        if await like_btn.count() > 0:
            await like_btn.click()
            await page.wait_for_timeout(_jitter(800))
            return True
    except Exception:
        pass
    return False


async def bookmark_post(page: Page, post_url: str) -> bool:
    """Bookmark a post. Returns True on success."""
    bookmark_btn = page.locator('[data-testid="bookmark"]').first
    try:
        if await bookmark_btn.count() > 0:
            await bookmark_btn.click()
            await page.wait_for_timeout(_jitter(600))
            return True
    except Exception:
        pass
    return False


async def post_thread(page: Page, tweets: list[str], delay: int = 3) -> bool:
    """Post a multi-tweet thread. First tweet opens compose, subsequent ones use the + button."""
    await page.goto("https://x.com/compose/post", wait_until="domcontentloaded")
    await page.wait_for_timeout(_jitter(2000))

    for idx, tweet_text in enumerate(tweets):
        if idx > 0:
            add_btn = page.locator('[data-testid="addButton"], [aria-label="Add post"]').first
            try:
                await add_btn.click()
                await page.wait_for_timeout(_jitter(800))
            except Exception:
                break

        editor = page.locator(f'[data-testid="tweetTextarea_{idx}"], [role="textbox"]').last
        await editor.click()
        await page.wait_for_timeout(_jitter(400))
        await _human_type(page, tweet_text)
        await page.wait_for_timeout(_jitter(600))

    post_btn = page.locator('[data-testid="tweetButton"], [data-testid="tweetButtonInline"]').first
    await post_btn.click()
    await page.wait_for_timeout(_jitter(delay * 1000))
    return True


async def follow_user(page: Page, handle: str, delay: int = 3) -> bool:
    """Follow a user by handle."""
    await page.goto(f"https://x.com/{handle}", wait_until="domcontentloaded")
    await page.wait_for_timeout(_jitter(2000))

    follow_btn = page.locator(
        f'[data-testid="placementTracking"] [role="button"]:has-text("Follow"), '
        f'button[aria-label*="Follow @{handle}"]'
    ).first

    try:
        if await follow_btn.is_visible():
            btn_text = await follow_btn.inner_text()
            if btn_text.strip() == "Follow":
                await follow_btn.click()
                await page.wait_for_timeout(_jitter(delay * 1000))
                return True
    except Exception:
        pass

    return False


async def download_images(image_urls: list[str]) -> list[str]:
    """Download images from URLs to temp files. Returns list of file paths."""
    paths = []
    tmp_dir = os.path.join(tempfile.gettempdir(), "devmaker_images")
    os.makedirs(tmp_dir, exist_ok=True)

    async with httpx.AsyncClient(timeout=15.0) as client:
        for i, url in enumerate(image_urls[:4]):
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    ext = ".jpg"
                    ct = resp.headers.get("content-type", "")
                    if "png" in ct:
                        ext = ".png"
                    elif "webp" in ct:
                        ext = ".webp"
                    path = os.path.join(tmp_dir, f"img_{i}_{random.randint(1000,9999)}{ext}")
                    with open(path, "wb") as f:
                        f.write(resp.content)
                    paths.append(path)
            except Exception:
                continue
    return paths


async def _attach_images(page: Page, image_paths: list[str]):
    """Attach images to the compose box using the file input."""
    file_input = page.locator('input[data-testid="fileInput"], input[type="file"][accept*="image"]').first

    try:
        if await file_input.count() > 0:
            await file_input.set_input_files(image_paths)
            return
    except Exception:
        pass

    try:
        media_btn = page.locator('[data-testid="fileInput"]').first
        async with page.expect_file_chooser() as fc_info:
            await media_btn.click()
        file_chooser = await fc_info.value
        await file_chooser.set_files(image_paths)
    except Exception:
        pass


async def _human_type(page: Page, text: str):
    """Type text character by character with realistic human-like timing."""
    for i, char in enumerate(text):
        if char == "\n":
            await page.keyboard.press("Enter")
            await asyncio.sleep(random.uniform(0.15, 0.4))
            continue

        await page.keyboard.type(char, delay=0)

        base_delay = random.uniform(0.03, 0.09)

        if char in ".!?,;:":
            base_delay += random.uniform(0.05, 0.2)

        if char == " ":
            base_delay += random.uniform(0.02, 0.08)

        if random.random() < 0.02:
            base_delay += random.uniform(0.3, 0.8)

        await asyncio.sleep(base_delay)
