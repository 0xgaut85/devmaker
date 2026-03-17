"""Full sequence orchestrator supporting Dev, Project, and Degen farming modes."""

import asyncio
import random
from datetime import datetime, timezone
from typing import Callable
from zoneinfo import ZoneInfo

from core.config import Config
from core.state_manager import SequenceState
from browser.x_client import XClient
from browser.timeline_scraper import (
    scrape_timeline,
    scrape_timeline_with_age,
    scrape_who_to_follow,
    scrape_profile_posts,
    scrape_top_replies,
    scrape_profile_retweets,
    check_post_performance,
    TimelinePost,
)
from browser.actions import (
    post_tweet,
    post_quote_rt,
    plain_repost,
    post_comment,
    post_thread,
    follow_user,
    like_post,
    bookmark_post,
    download_images,
)
from content.generator import (
    generate_tweet,
    generate_quote_comment,
    generate_reply_comment,
    generate_project_comment,
    generate_smart_project_comment,
    generate_degen_tweet,
    generate_degen_quote_comment,
    generate_degen_reply_comment,
    generate_thread,
    classify_post_with_llm,
    extract_position,
    check_image_relevance_with_vision,
)
from content.position_memory import record_position, get_relevant_positions
from content.validator import is_too_similar
from content.rules import (
    FORMAT_CATALOG,
    DEGEN_FORMAT_CATALOG,
    DEGEN_TOPIC_KEYWORDS,
    classify_post_type,
)


TOPIC_KEYWORDS = {
    "Database / backend": ["postgres", "sql", "database", "redis", "backend", "migration", "orm", "prisma", "supabase", "mongodb"],
    "Frontend / UI / UX": ["frontend", "react", "css", "tailwind", "ui", "ux", "design system", "component", "nextjs", "next.js", "svelte", "vue"],
    "DevOps / infra": ["deploy", "ci/cd", "docker", "kubernetes", "k8s", "terraform", "aws", "gcp", "azure", "infra", "monitoring"],
    "AI / ML tools": ["gpt", "claude", "llm", "openai", "copilot", "cursor", "ai coding", "model", "fine-tun", "benchmark"],
    "Open source": ["open source", "open-source", "oss", "github", "contributor", "maintainer", "license", "fork"],
    "Startup / founder life": ["startup", "founder", "fundrais", "pivot", "pmf", "product-market", "launch", "yc", "investor", "seed", "series"],
    "Career / growth": ["hiring", "interview", "promotion", "resume", "career", "mentor", "salary", "job"],
    "Developer tools / productivity": ["ide", "vscode", "terminal", "cli", "neovim", "vim", "workflow", "dev tools", "productivity"],
    "Product thinking": ["feature", "roadmap", "user research", "ship", "prioriti", "product"],
    "Hardware / gadgets": ["hardware", "gadget", "device", "peripheral", "monitor", "keyboard", "mouse", "home office"],
    "Remote work / async": ["remote", "async", "timezone", "wfh", "hybrid", "distributed"],
    "Side projects": ["side project", "build in public", "indie", "solo", "weekend project", "burnout", "scope creep"],
    "Security / privacy": ["security", "auth", "encrypt", "vulnerability", "pentest", "oauth", "jwt", "password"],
    "Technical debt / refactoring": ["tech debt", "refactor", "legacy", "rewrite", "code quality", "migration"],
    "Pricing / monetization": ["pricing", "monetiz", "freemium", "subscription", "revenue", "mrr", "arr", "billing"],
    "API design": ["api", "rest", "graphql", "trpc", "endpoint", "webhook", "versioning"],
    "Mobile / cross-platform": ["mobile", "react native", "flutter", "ios", "android", "pwa", "swift", "kotlin"],
    "Data / analytics": ["analytics", "metrics", "dashboard", "data pipeline", "observability", "datadog"],
    "Community / content creation": ["newsletter", "blog", "content", "audience", "writing", "creator", "youtube", "podcast"],
    "Entrepreneurship": ["entrepreneur", "bootstrap", "indie hacker", "saas", "acquisition", "exit", "business"],
    "Economics": ["economy", "market", "inflation", "policy", "macro", "gdp", "trade"],
    "AI / future of AI": ["agi", "ai agent", "artificial intelligence", "automation", "future of", "singularity"],
    "Philosophy of tech": ["ethics", "digital minimalism", "philosophy", "agi risk", "alignment"],
    "AI agents": ["agent", "tool use", "multi-agent", "autonomous", "agentic", "crew", "langchain", "langgraph"],
    "Robotics / physical tech": ["robot", "drone", "embodied", "humanoid", "physical ai", "manufacturing"],
    "Current events / news": ["breaking", "announced", "just launched", "update", "released"],
    "Culture / memes / takes": ["meme", "hot take", "viral", "discourse", "ratio", "timeline"],
}

_IMAGE_STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "to", "of", "and",
    "in", "that", "it", "for", "on", "with", "as", "at", "by", "this", "i",
})


def _images_relevant(source_text: str, generated_text: str) -> bool:
    """Check if generated text shares enough keywords with source to justify reusing images."""
    source_words = set(source_text.lower().split()) - _IMAGE_STOPWORDS
    gen_words = set(generated_text.lower().split()) - _IMAGE_STOPWORDS
    if not source_words:
        return False
    overlap = len(source_words & gen_words) / len(source_words)
    return overlap >= 0.15


def classify_topic(text: str, enabled_topics: list[str], keyword_map: dict | None = None) -> str:
    """Classify a tweet's topic using keyword matching."""
    if keyword_map is None:
        keyword_map = TOPIC_KEYWORDS
    text_lower = text.lower()
    scores = {}
    for topic, keywords in keyword_map.items():
        if topic not in enabled_topics:
            continue
        score = sum(1 for kw in keywords if kw in text_lower)
        if score > 0:
            scores[topic] = score

    if scores:
        return max(scores, key=scores.get)
    return random.choice(enabled_topics) if enabled_topics else "General"


def _is_question_post(text: str) -> bool:
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if not lines:
        return False
    question_lines = sum(1 for l in lines if l.endswith("?"))
    return question_lines >= len(lines) * 0.5


class SequenceEngine:
    def __init__(self, config: Config, log_fn: Callable[[str], None] | None = None):
        self.config = config
        self._profile_dir = config.data_dir()
        self.state = SequenceState.load_for(self._profile_dir)
        self.client: XClient | None = None
        self._cancelled = False
        self._warmed_up = False
        self._log = log_fn or print

    def log(self, msg: str):
        self._log(msg)

    def cancel(self):
        self._cancelled = True

    async def _ensure_browser(self) -> bool:
        if self.client is None:
            self.client = XClient(
                self.config.chrome_profile_path,
                self.config.headless,
                self.config.chrome_profile_directory,
            )
            self.client.set_log_fn(self.log)

        await self.client.start()
        self.log("Browser ready.")

        logged_in = await self.client.is_logged_in()
        if not logged_in:
            if self.config.x_username and self.config.x_password:
                self.log("Not logged in. Attempting auto-login...")
                logged_in = await self.client.login(
                    self.config.x_username,
                    self.config.x_password,
                    self.config.x_totp_secret,
                )
            if not logged_in:
                self.log("ERROR: Not logged into X. Check credentials or Chrome profile.")
                return False
        self.log("Logged into X.")
        return True

    async def _close_browser(self):
        if self.client:
            await self.client.stop()
            self.client = None

    async def _organic_pause(self, short: bool = False):
        """Simulate natural browsing between actions."""
        pause = random.uniform(8, 25) if not short else random.uniform(3, 10)
        self.log(f"  [Pause] Browsing for {pause:.0f}s...")
        await asyncio.sleep(pause)
        if random.random() < 0.3 and self.client and self.client.page:
            await self.client.page.evaluate("window.scrollBy(0, window.innerHeight)")
            await asyncio.sleep(random.uniform(2, 5))

    def _recent_posts(self, n: int = 5) -> list[str]:
        """Return last N posted texts for dedup context."""
        return self.state.recent_posted_texts[-n:] if self.state.recent_posted_texts else []

    async def _like_and_bookmark(self, post_url: str):
        """Like (80% chance) and optionally bookmark (10%) before interacting with a post."""
        if random.random() < 0.8 and self._can_act("likes"):
            liked = await like_post(self.client.page, post_url)
            if liked:
                self.log("  [Like] Liked post.")
                self._record_action("likes")
            await asyncio.sleep(random.uniform(2, 6))
        if random.random() < 0.1:
            bookmarked = await bookmark_post(self.client.page, post_url)
            if bookmarked:
                self.log("  [Bookmark] Bookmarked post.")
            await asyncio.sleep(random.uniform(1, 3))

    def _daily_caps(self) -> dict:
        """Build daily caps dict from config."""
        c = self.config
        return {
            "tweets": c.daily_max_tweets,
            "comments": c.daily_max_comments,
            "likes": c.daily_max_likes,
            "follows": c.daily_max_follows,
            "qrts": c.daily_max_qrts,
        }

    def _can_act(self, action_type: str) -> bool:
        """Check daily cap and log if limit reached."""
        caps = self._daily_caps()
        if self.state.can_perform_action(action_type, caps):
            return True
        cap = caps.get(action_type, "?")
        self.log(f"[Cap] Daily {action_type} limit reached ({cap}/{cap}). Skipping.")
        return False

    def _record_action(self, action_type: str):
        self.state.record_daily_action(action_type)

    def _is_active_hours(self) -> bool:
        """Check if current time is within active hours. Returns True if feature disabled."""
        if not self.config.active_hours_enabled:
            return True
        try:
            tz = ZoneInfo(self.config.active_hours_timezone)
        except Exception:
            tz = timezone.utc
        now = datetime.now(tz)
        hour = now.hour
        start = self.config.active_hours_start
        end = self.config.active_hours_end
        if start <= end:
            return start <= hour < end
        return hour >= start or hour < end

    def _seconds_until_active(self) -> int:
        """Calculate seconds until the next active window opens."""
        if not self.config.active_hours_enabled:
            return 0
        try:
            tz = ZoneInfo(self.config.active_hours_timezone)
        except Exception:
            tz = timezone.utc
        now = datetime.now(tz)
        start = self.config.active_hours_start
        target = now.replace(hour=start, minute=0, second=0, microsecond=0)
        if target <= now:
            from datetime import timedelta
            target += timedelta(days=1)
        return int((target - now).total_seconds())

    async def _wait_for_active_hours(self):
        """Sleep until active hours if currently outside them."""
        if self._is_active_hours():
            return
        wait = self._seconds_until_active()
        self.log(f"[Hours] Outside active hours ({self.config.active_hours_start}:00-{self.config.active_hours_end}:00). Waiting {wait // 3600}h {(wait % 3600) // 60}m...")
        for _ in range(wait):
            if self._cancelled:
                return
            await asyncio.sleep(1)

    async def _session_warmup(self):
        """Simulate natural session opening: scroll timeline, check notifications."""
        self.log("[Warmup] Opening session naturally...")
        if not self.client or not self.client.page:
            return
        for _ in range(random.randint(2, 5)):
            await self.client.page.evaluate("window.scrollBy(0, window.innerHeight)")
            await asyncio.sleep(random.uniform(2, 6))
        if random.random() < 0.5:
            await self.client.navigate("https://x.com/notifications")
            await asyncio.sleep(random.uniform(3, 8))
            for _ in range(random.randint(1, 3)):
                await self.client.page.evaluate("window.scrollBy(0, window.innerHeight)")
                await asyncio.sleep(random.uniform(2, 4))
        await self.client.navigate("https://x.com/home")
        await asyncio.sleep(random.uniform(2, 5))
        self.log("[Warmup] Done.")

    async def _lurk_scroll(self, count: int | None = None):
        """Scroll past posts without interacting, simulating reading."""
        count = count or random.randint(3, 8)
        self.log(f"  [Lurk] Scrolling past {count} posts...")
        if not self.client or not self.client.page:
            return
        for _ in range(count):
            await self.client.page.evaluate("window.scrollBy(0, window.innerHeight)")
            pause = random.uniform(2, 8)
            await asyncio.sleep(pause)
            if random.random() < 0.2:
                await asyncio.sleep(random.uniform(5, 15))

    def _classify_post(self, text: str) -> tuple[str, str, str]:
        """Classify a post using LLM if enabled, falling back to keyword matching.
        Returns (type, strategy, tone)."""
        if self.config.use_llm_classification:
            result = classify_post_with_llm(self.config, text)
            if result:
                return (
                    result.get("type", "general"),
                    result.get("reply_strategy", ""),
                    result.get("tone", ""),
                )
        ptype, pstrategy = classify_post_type(text)
        return ptype, pstrategy, ""

    def _get_positions_for(self, post_text: str) -> list[dict]:
        """Get relevant past positions for prompt injection."""
        if not self.config.position_memory_enabled:
            return []
        return get_relevant_positions(self.state, post_text)

    def _record_position_from(self, posted_text: str):
        """Extract and record position from a posted tweet (async-safe, best-effort)."""
        if not self.config.position_memory_enabled:
            return
        result = extract_position(self.config, posted_text)
        if result:
            record_position(
                self.state,
                result["topic"],
                result["stance"],
                datetime.now(timezone.utc).isoformat(),
            )

    async def _scrape_reply_context(self, post_url: str) -> list[str]:
        """Scrape top replies for context before commenting."""
        try:
            replies = await scrape_top_replies(self.client.page, post_url, max_replies=3)
            if replies:
                self.log(f"  [Context] Got {len(replies)} replies for vibe check.")
            return replies
        except Exception:
            return []

    async def _generate_with_dedup(self, gen_fn, max_retries: int = 3, **kwargs) -> str | None:
        """Call a generator function, rejecting results too similar to recent posts.
        Returns None if all attempts produce duplicates."""
        recent = self._recent_posts()
        kwargs["recent_posts"] = recent
        for attempt in range(max_retries):
            text = gen_fn(**kwargs)
            if not is_too_similar(text, recent):
                return text
            self.log(f"  [Dedup] Attempt {attempt + 1}: too similar to recent post, regenerating...")
        self.log("  [Dedup] WARNING: All attempts were similar. Skipping action.")
        return None

    # ------------------------------------------------------------------ #
    #  Dispatch                                                            #
    # ------------------------------------------------------------------ #

    async def run_sequence(self) -> bool:
        """Run one sequence using the configured farming mode."""
        await self._wait_for_active_hours()
        if self._cancelled:
            return False

        if self.state.all_caps_reached(self._daily_caps()):
            self.log("[Cap] All daily limits reached. Stopping early.")
            return False

        mode = self.config.farming_mode
        if mode == "project":
            return await self._run_project_sequence()
        elif mode == "degen":
            return await self._run_degen_sequence()
        elif mode == "rt_farm":
            return await self._run_rt_farm_sequence()
        elif mode == "sniper":
            return await self._run_sniper_sequence()
        else:
            return await self._run_dev_sequence()

    # ------------------------------------------------------------------ #
    #  Dev Farming                                                         #
    # ------------------------------------------------------------------ #

    async def _run_dev_sequence(self) -> bool:
        self._cancelled = False
        enabled = self.config.enabled_topics()
        if len(enabled) < 3:
            self.log("ERROR: Need at least 3 enabled topics.")
            return False
        if not self.config.active_api_key():
            self.log("ERROR: No API key configured for " + self.config.llm_provider)
            return False
        if not await self._ensure_browser():
            return False

        try:
            if self._cancelled:
                return False

            if not self._warmed_up:
                await self._session_warmup()
                self._warmed_up = True

            format_key = self.state.next_format()
            comment_rotation = self.state.next_comment_rotation()
            seq_num = self.state.sequence_number + 1
            self.log(f"=== DEV SEQUENCE {seq_num} | Format: {format_key} ({FORMAT_CATALOG[format_key]['name']}) ===")

            self.log("Scraping timeline for high-engagement posts...")
            posts = await scrape_timeline(
                self.client.page,
                min_likes=self.config.min_engagement_likes,
                max_posts=30,
                scroll_count=5,
            )
            self.log(f"Found {len(posts)} high-engagement posts.")

            if len(posts) < 8:
                self.log("WARNING: Not enough posts found. Lowering threshold...")
                posts = await scrape_timeline(
                    self.client.page, min_likes=20, max_posts=30, scroll_count=3
                )

            if len(posts) < 3:
                self.log("ERROR: Not enough posts to build a sequence.")
                return False

            for p in posts:
                p._topic = classify_topic(p.text, enabled)

            if self._cancelled:
                return False

            # 1. TWEET
            if self._can_act("tweets"):
                tweet_topic = self.state.next_topic(enabled)
                tweet_post = self._pick_post(posts, tweet_topic, exclude_handles=[])
                if not tweet_post:
                    tweet_post = posts[0]
                    tweet_topic = classify_topic(tweet_post.text, enabled)

                if tweet_post.url in self.state.recent_source_urls:
                    self.log(f"[Tweet] Source already used recently, picking another...")
                    for p in posts:
                        if p.url not in self.state.recent_source_urls and p.handle != tweet_post.handle:
                            tweet_post = p
                            tweet_topic = classify_topic(p.text, enabled)
                            break

                self.log(f"[Tweet] Stealing from @{tweet_post.handle} ({tweet_post.likes} likes)")
                length_tier = random.choice(["SHORT", "MEDIUM", "LONG"])

                tweet_text = await self._generate_with_dedup(
                    generate_tweet,
                    config=self.config,
                    format_key=format_key,
                    original_tweet=tweet_post.text,
                    length_tier=length_tier,
                )

                if tweet_text:
                    self.log(f"[Tweet] Generated ({len(tweet_text)} chars): {tweet_text[:80]}...")

                    tweet_images = []
                    if tweet_post.image_urls:
                        if _images_relevant(tweet_post.text, tweet_text):
                            self.log(f"[Tweet] Downloading {len(tweet_post.image_urls)} image(s)...")
                            tweet_images = await download_images(tweet_post.image_urls)
                            if tweet_images and self.config.use_vision_image_check:
                                if not check_image_relevance_with_vision(self.config, tweet_images[0], tweet_text):
                                    self.log("[Tweet] Vision check: images not relevant. Posting text-only.")
                                    tweet_images = []
                                else:
                                    self.log(f"[Tweet] Vision check: images relevant.")
                            self.log(f"[Tweet] Downloaded {len(tweet_images)} image(s).")
                        else:
                            self.log("[Tweet] Skipping images (low relevance to generated text).")

                    await post_tweet(self.client.page, tweet_text, self.config.action_delay_seconds, tweet_images)
                    self.log("[Tweet] Posted.")
                    self._record_action("tweets")
                    self.state.record_posted_text(tweet_text)
                    self.state.record_source_url(tweet_post.url)
                    self._record_position_from(tweet_text)
                else:
                    self.log("[Tweet] Skipped (too similar to recent content).")
            else:
                tweet_post = posts[0]
                tweet_topic = classify_topic(tweet_post.text, enabled)

            if self._cancelled:
                return False

            await self._organic_pause()
            await self._lurk_scroll()

            # 2. QUOTE RT
            if self._can_act("qrts"):
                qrt_topic = self.state.next_topic(enabled, exclude=[tweet_topic])
                qrt_post = self._pick_post(posts, qrt_topic, exclude_handles=[tweet_post.handle])
                if not qrt_post:
                    remaining = [p for p in posts if p.handle != tweet_post.handle]
                    qrt_post = remaining[0] if remaining else posts[1]
                    qrt_topic = classify_topic(qrt_post.text, enabled)

                self.log(f"[Quote RT] Quoting @{qrt_post.handle} ({qrt_post.likes} likes)")

                await self.client.navigate(qrt_post.url)
                await self._like_and_bookmark(qrt_post.url)

                quote_comment = await self._generate_with_dedup(
                    generate_quote_comment,
                    config=self.config,
                    original_tweet=qrt_post.text,
                )

                if quote_comment:
                    self.log(f"[Quote RT] Comment: {quote_comment[:80]}...")
                    await post_quote_rt(
                        self.client.page, qrt_post.url, quote_comment, self.config.action_delay_seconds
                    )
                    self.log("[Quote RT] Posted.")
                    self._record_action("qrts")
                    self.state.record_posted_text(quote_comment)
                    self._record_position_from(quote_comment)
                else:
                    self.log("[Quote RT] Skipped (too similar to recent content).")
            else:
                qrt_topic = tweet_topic
                qrt_post = tweet_post

            if self._cancelled:
                return False

            await self._organic_pause()

            # 3. PLAIN RT (20% chance to skip for pattern-breaking)
            skip_rt = random.random() < 0.2
            used_handles = {tweet_post.handle, qrt_post.handle}
            used_topics = {tweet_topic, qrt_topic}
            rt_topic = ""

            if skip_rt:
                self.log("[Plain RT] Skipped this round (pattern variation).")
                rt_post_handle = ""
            else:
                rt_post = None
                for p in posts:
                    if p.handle not in used_handles and not _is_question_post(p.text):
                        rt_topic = classify_topic(p.text, enabled)
                        if rt_topic not in used_topics:
                            rt_post = p
                            break
                if not rt_post:
                    for p in posts:
                        if p.handle not in used_handles and not _is_question_post(p.text):
                            rt_post = p
                            break
                if not rt_post:
                    rt_post = posts[2] if len(posts) > 2 else posts[-1]

                rt_topic = classify_topic(rt_post.text, enabled)
                self.log(f"[Plain RT] Reposting @{rt_post.handle} ({rt_post.likes} likes)")
                await plain_repost(self.client.page, rt_post.url, self.config.action_delay_seconds)
                self.log("[Plain RT] Done.")
                rt_post_handle = rt_post.handle

            if self._cancelled:
                return False

            await self._organic_pause()
            await self._lurk_scroll()

            # 4. COMMENTS (3-5, randomized)
            num_comments = random.randint(3, 5)
            comment_posts = []
            comment_topics_used = []
            excluded_topics = {tweet_topic, qrt_topic, rt_topic}
            excluded_handles = {tweet_post.handle, qrt_post.handle}
            if rt_post_handle:
                excluded_handles.add(rt_post_handle)

            for p in posts:
                if len(comment_posts) >= num_comments:
                    break
                if p.handle in excluded_handles:
                    continue
                p_topic = classify_topic(p.text, enabled)
                if p_topic in excluded_topics:
                    continue
                comment_posts.append(p)
                comment_topics_used.append(p_topic)
                excluded_topics.add(p_topic)
                excluded_handles.add(p.handle)

            for p in posts:
                if len(comment_posts) >= num_comments:
                    break
                if p not in comment_posts and p.handle not in {tweet_post.handle, qrt_post.handle}:
                    comment_posts.append(p)
                    comment_topics_used.append(classify_topic(p.text, enabled))

            for i, cp in enumerate(comment_posts):
                if self._cancelled:
                    return False
                if not self._can_act("comments"):
                    break
                length = comment_rotation[i] if i < len(comment_rotation) else "MEDIUM"
                tone = self.state.next_tone(i + self.state.sequence_number)
                ptype, pstrategy, ptone = self._classify_post(cp.text)
                self.log(f"[Comment {i+1}/{num_comments}] @{cp.handle} | {length} | {tone} | type:{ptype}")

                await self.client.navigate(cp.url)
                await self._like_and_bookmark(cp.url)

                existing_replies = await self._scrape_reply_context(cp.url)
                positions = self._get_positions_for(cp.text)

                comment_text = await self._generate_with_dedup(
                    generate_reply_comment,
                    config=self.config,
                    original_tweet=cp.text,
                    length_tier=length,
                    tone=tone,
                    post_type=ptype,
                    reply_strategy=pstrategy,
                    existing_replies=existing_replies,
                    positions=positions,
                )

                if comment_text:
                    self.log(f"  -> {comment_text[:60]}...")
                    await post_comment(
                        self.client.page, cp.url, comment_text, self.config.action_delay_seconds
                    )
                    self.log(f"  -> Posted.")
                    self._record_action("comments")
                    self.state.record_posted_text(comment_text)
                    self._record_position_from(comment_text)
                else:
                    self.log(f"  -> Skipped (too similar).")

                if i < len(comment_posts) - 1:
                    await self._organic_pause(short=True)
                    if random.random() < 0.2:
                        await self._lurk_scroll(random.randint(2, 4))

            if self._cancelled:
                return False

            await self._organic_pause()

            # 4b. THREAD (every N sequences)
            if self.state.should_post_thread(self.config.thread_every_n_sequences) and self._can_act("tweets"):
                self.log("[Thread] This sequence includes a thread.")
                thread_format = self.state.next_thread_format()
                thread_source = posts[0]
                thread_tweets = generate_thread(
                    config=self.config,
                    thread_format_key=thread_format,
                    original_tweet=thread_source.text,
                    recent_posts=self._recent_posts(),
                )
                if thread_tweets:
                    self.log(f"[Thread] Generated {len(thread_tweets)}-tweet thread ({thread_format}).")
                    await post_thread(self.client.page, thread_tweets, self.config.action_delay_seconds)
                    self.log("[Thread] Posted.")
                    self._record_action("tweets")
                    self.state.thread_last_format = thread_format
                    for t in thread_tweets:
                        self.state.record_posted_text(t)
                else:
                    self.log("[Thread] Generation failed, skipping.")

                if self._cancelled:
                    return False
                await self._organic_pause()

            # 5. FOLLOWS (1-3, randomized)
            num_follows = random.randint(1, 3)
            self.log(f"[Follows] Finding {num_follows} accounts to follow...")
            await self.client.navigate("https://x.com/home", 2000)
            who_to_follow = await scrape_who_to_follow(self.client.page)

            followed = []
            for handle in who_to_follow:
                if len(followed) >= num_follows:
                    break
                if not self._can_act("follows"):
                    break
                if handle in self.state.last_follows:
                    continue
                self.log(f"[Follow] Following @{handle}...")
                success = await follow_user(self.client.page, handle, self.config.action_delay_seconds)
                if success:
                    followed.append(handle)
                    self._record_action("follows")
                    self.log(f"[Follow] Followed @{handle}.")

            if len(followed) < num_follows:
                for cp in comment_posts:
                    if len(followed) >= num_follows:
                        break
                    if not self._can_act("follows"):
                        break
                    if cp.handle not in followed and cp.handle not in self.state.last_follows:
                        success = await follow_user(
                            self.client.page, cp.handle, self.config.action_delay_seconds
                        )
                        if success:
                            followed.append(cp.handle)
                            self._record_action("follows")
                            self.log(f"[Follow] Followed @{cp.handle}.")

            # SAVE STATE
            self.state.record_sequence(
                profile_dir=self._profile_dir,
                format_key=format_key,
                topic_tweet=tweet_topic,
                topic_qrt=qrt_topic,
                topic_rt=rt_topic,
                qrt_author=qrt_post.handle,
                comment_topics=comment_topics_used,
                comment_rotation=comment_rotation,
                follows=followed,
            )
            self.log(f"=== DEV SEQUENCE {seq_num} COMPLETE ===")
            return True

        except Exception as e:
            self.log(f"ERROR: {e}")
            return False

    # ------------------------------------------------------------------ #
    #  Project Farming                                                     #
    # ------------------------------------------------------------------ #

    async def _generate_context_comment(
        self,
        post: TimelinePost,
        recent: list[str],
    ) -> str:
        """Generate a context-aware reply by scraping top replies and using the LLM.
        Falls back to templates if no API key is configured or LLM fails."""
        top_replies = []
        try:
            self.log(f"  [Context] Scraping replies on @{post.handle}'s post...")
            top_replies = await scrape_top_replies(
                self.client.page, post.url, max_replies=5
            )
            if top_replies:
                self.log(f"  [Context] Got {len(top_replies)} replies for vibe check.")
        except Exception:
            pass

        name = self.config.project_name or post.handle
        smart = generate_smart_project_comment(
            config=self.config,
            post_text=post.text,
            post_author=post.handle,
            top_replies=top_replies,
            project_name=name,
        )
        if smart:
            return smart

        return generate_project_comment(name, recent_comments=recent)

    async def _run_project_sequence(self) -> bool:
        """Scroll the timeline, find any high-engagement post, read existing
        replies for context, and drop a vibe-matching reply-guy comment."""
        self._cancelled = False

        if not await self._ensure_browser():
            return False

        try:
            if not self._warmed_up:
                await self._session_warmup()
                self._warmed_up = True

            seq_num = self.state.project_sequence_number + 1
            target_comments = self.config.project_timeline_comments
            min_likes = self.config.project_timeline_min_likes
            self.log(f"=== PROJECT SEQUENCE {seq_num} | target {target_comments} comments | >= {min_likes} likes ===")

            self.log("[Timeline] Scrolling for high-engagement posts...")
            timeline_posts = await scrape_timeline(
                self.client.page,
                min_likes=min_likes,
                max_posts=50,
                scroll_count=6,
            )
            self.log(f"[Timeline] Found {len(timeline_posts)} posts with {min_likes}+ likes.")

            if not timeline_posts:
                self.log("[Timeline] No posts above the like threshold. Try lowering it in Settings.")
                self.state.record_project_sequence(self._profile_dir, [], 0)
                return True

            total_comments = 0
            recent_comments: list[str] = []
            commented_handles: list[str] = []

            for post in timeline_posts:
                if total_comments >= target_comments:
                    break
                if self._cancelled:
                    return False

                self.log(f"[Reply] @{post.handle} ({post.likes} likes): \"{post.text[:80]}...\"")

                await self.client.navigate(post.url)
                await self._like_and_bookmark(post.url)

                comment_text = await self._generate_context_comment(post, recent_comments)
                self.log(f"[Reply] -> \"{comment_text}\"")

                await post_comment(
                    self.client.page, post.url, comment_text, self.config.action_delay_seconds
                )
                recent_comments.append(comment_text)
                if len(recent_comments) > 10:
                    recent_comments = recent_comments[-10:]
                total_comments += 1
                commented_handles.append(post.handle)
                self.log(f"[Reply] Comment posted on @{post.handle}.")

                await self._organic_pause(short=True)

            self.state.record_project_sequence(self._profile_dir, commented_handles, total_comments)
            self.log(f"=== PROJECT SEQUENCE {seq_num} COMPLETE | {total_comments} comments ===")
            return True

        except Exception as e:
            self.log(f"ERROR: {e}")
            return False

    # ------------------------------------------------------------------ #
    #  Degen Farming                                                       #
    # ------------------------------------------------------------------ #

    async def _run_degen_sequence(self) -> bool:
        """Run a degen crypto sequence: tweet, quote RT, comments on crypto timeline."""
        self._cancelled = False
        enabled = self.config.enabled_degen_topics()
        if len(enabled) < 2:
            self.log("ERROR: Need at least 2 enabled degen topics.")
            return False
        if not self.config.active_api_key():
            self.log("ERROR: No API key configured for " + self.config.llm_provider)
            return False
        if not await self._ensure_browser():
            return False

        try:
            if self._cancelled:
                return False

            if not self._warmed_up:
                await self._session_warmup()
                self._warmed_up = True

            format_key = self.state.next_degen_format()
            comment_rotation = self.state.next_degen_comment_rotation()
            seq_num = self.state.degen_sequence_number + 1
            self.log(f"=== DEGEN SEQUENCE {seq_num} | Format: {format_key} ({DEGEN_FORMAT_CATALOG[format_key]['name']}) ===")

            self.log("Scraping timeline for crypto posts...")
            posts = await scrape_timeline(
                self.client.page,
                min_likes=self.config.min_engagement_likes,
                max_posts=30,
                scroll_count=5,
            )
            self.log(f"Found {len(posts)} posts.")

            if len(posts) < 5:
                posts = await scrape_timeline(
                    self.client.page, min_likes=20, max_posts=30, scroll_count=3
                )

            if len(posts) < 3:
                self.log("ERROR: Not enough posts for a degen sequence.")
                return False

            for p in posts:
                p._topic = classify_topic(p.text, enabled, DEGEN_TOPIC_KEYWORDS)

            if self._cancelled:
                return False

            # 1. DEGEN TWEET
            if self._can_act("tweets"):
                tweet_post = posts[0]

                if tweet_post.url in self.state.recent_source_urls:
                    for p in posts[1:]:
                        if p.url not in self.state.recent_source_urls:
                            tweet_post = p
                            break

                tweet_topic = classify_topic(tweet_post.text, enabled, DEGEN_TOPIC_KEYWORDS)
                self.log(f"[Degen Tweet] Riffing off @{tweet_post.handle} ({tweet_post.likes} likes)")

                tweet_text = await self._generate_with_dedup(
                    generate_degen_tweet,
                    config=self.config,
                    format_key=format_key,
                    original_tweet=tweet_post.text,
                )

                if tweet_text:
                    self.log(f"[Degen Tweet] Generated: {tweet_text[:80]}...")

                    tweet_images = []
                    if tweet_post.image_urls:
                        if _images_relevant(tweet_post.text, tweet_text):
                            tweet_images = await download_images(tweet_post.image_urls)
                            if tweet_images and self.config.use_vision_image_check:
                                if not check_image_relevance_with_vision(self.config, tweet_images[0], tweet_text):
                                    self.log("[Degen Tweet] Vision check: images not relevant. Text-only.")
                                    tweet_images = []
                        else:
                            self.log("[Degen Tweet] Skipping images (low relevance to generated text).")

                    await post_tweet(self.client.page, tweet_text, self.config.action_delay_seconds, tweet_images)
                    self.log("[Degen Tweet] Posted.")
                    self._record_action("tweets")
                    self.state.record_posted_text(tweet_text)
                    self.state.record_source_url(tweet_post.url)
                    self._record_position_from(tweet_text)
                else:
                    self.log("[Degen Tweet] Skipped (too similar to recent content).")
            else:
                tweet_post = posts[0]
                tweet_topic = classify_topic(tweet_post.text, enabled, DEGEN_TOPIC_KEYWORDS)

            if self._cancelled:
                return False

            await self._organic_pause()
            await self._lurk_scroll()

            # 2. DEGEN QUOTE RT
            if self._can_act("qrts"):
                qrt_post = None
                for p in posts[1:]:
                    if p.handle != tweet_post.handle:
                        qrt_post = p
                        break
                if not qrt_post:
                    qrt_post = posts[1] if len(posts) > 1 else posts[0]

                self.log(f"[Degen QRT] Quoting @{qrt_post.handle}")

                await self.client.navigate(qrt_post.url)
                await self._like_and_bookmark(qrt_post.url)

                quote_text = await self._generate_with_dedup(
                    generate_degen_quote_comment,
                    config=self.config,
                    original_tweet=qrt_post.text,
                )

                if quote_text:
                    self.log(f"[Degen QRT] Comment: {quote_text[:80]}...")
                    await post_quote_rt(
                        self.client.page, qrt_post.url, quote_text, self.config.action_delay_seconds
                    )
                    self.log("[Degen QRT] Posted.")
                    self._record_action("qrts")
                    self.state.record_posted_text(quote_text)
                    self._record_position_from(quote_text)
                else:
                    self.log("[Degen QRT] Skipped (too similar to recent content).")
            else:
                qrt_post = tweet_post

            if self._cancelled:
                return False

            await self._organic_pause()

            # 3. DEGEN COMMENTS (3-5, randomized)
            num_comments = random.randint(3, 5)
            used_handles = {tweet_post.handle, qrt_post.handle}
            comment_posts = [p for p in posts if p.handle not in used_handles][:num_comments]
            if len(comment_posts) < num_comments:
                comment_posts += [p for p in posts if p not in comment_posts][:num_comments - len(comment_posts)]

            for i, cp in enumerate(comment_posts[:num_comments]):
                if self._cancelled:
                    return False
                if not self._can_act("comments"):
                    break
                length = comment_rotation[i] if i < len(comment_rotation) else "MEDIUM"
                tone = self.state.next_tone(i + self.state.degen_sequence_number)
                ptype, pstrategy, ptone = self._classify_post(cp.text)
                self.log(f"[Degen Comment {i+1}/{num_comments}] @{cp.handle} | {length} | {tone} | type:{ptype}")

                await self.client.navigate(cp.url)
                await self._like_and_bookmark(cp.url)

                existing_replies = await self._scrape_reply_context(cp.url)
                positions = self._get_positions_for(cp.text)

                comment_text = await self._generate_with_dedup(
                    generate_degen_reply_comment,
                    config=self.config,
                    original_tweet=cp.text,
                    length_tier=length,
                    tone=tone,
                    post_type=ptype,
                    reply_strategy=pstrategy,
                    existing_replies=existing_replies,
                    positions=positions,
                )

                if comment_text:
                    self.log(f"  -> {comment_text[:60]}...")
                    await post_comment(
                        self.client.page, cp.url, comment_text, self.config.action_delay_seconds
                    )
                    self.log(f"  -> Posted.")
                    self._record_action("comments")
                    self.state.record_posted_text(comment_text)
                    self._record_position_from(comment_text)
                else:
                    self.log(f"  -> Skipped (too similar).")

                if i < len(comment_posts) - 1:
                    await self._organic_pause(short=True)
                    if random.random() < 0.2:
                        await self._lurk_scroll(random.randint(2, 4))

            # SAVE STATE
            self.state.record_degen_sequence(
                profile_dir=self._profile_dir,
                format_key=format_key,
                topic=tweet_topic,
                comment_rotation=comment_rotation,
            )
            self.log(f"=== DEGEN SEQUENCE {seq_num} COMPLETE ===")
            return True

        except Exception as e:
            self.log(f"ERROR: {e}")
            return False

    # ------------------------------------------------------------------ #
    #  RT Farm                                                             #
    # ------------------------------------------------------------------ #

    async def _run_rt_farm_sequence(self) -> bool:
        """Scrape a target profile's retweets and replicate them oldest-first."""
        self._cancelled = False
        target = self.config.rt_farm_target_handle
        if not target:
            self.log("ERROR: No target handle configured for RT Farm.")
            return False

        if not await self._ensure_browser():
            return False

        try:
            self.log(f"=== RT FARM | Cloning retweets from @{target} ===")

            self.log(f"[Scrape] Scrolling @{target}'s profile (up to {self.config.rt_farm_max_scrolls} scrolls)...")
            all_rt_urls = await scrape_profile_retweets(
                self.client.page,
                target,
                max_scrolls=self.config.rt_farm_max_scrolls,
                log_fn=self.log,
            )

            if not all_rt_urls:
                self.log("[RT Farm] No retweets found on target profile.")
                return True

            already_done = set(self.state.rt_farm_completed_urls)
            pending = [u for u in all_rt_urls if u not in already_done]
            self.log(f"[RT Farm] {len(all_rt_urls)} total RTs found, {len(pending)} remaining.")

            if not pending:
                self.log("[RT Farm] All retweets already cloned. Nothing to do.")
                return True

            base_delay = self.config.rt_farm_delay_seconds

            for i, url in enumerate(pending):
                if self._cancelled:
                    self.log(f"[RT Farm] Cancelled at {i}/{len(pending)}.")
                    return False

                # Progressive cooldowns
                rt_number = i + 1
                if rt_number > 1 and rt_number % 30 == 0:
                    cool = random.uniform(120, 300)
                    self.log(f"[RT Farm] Long break after {rt_number} RTs ({cool:.0f}s)...")
                    await asyncio.sleep(cool)
                elif rt_number > 1 and rt_number % 10 == 0:
                    cool = random.uniform(30, 90)
                    self.log(f"[RT Farm] Cooldown after {rt_number} RTs ({cool:.0f}s)...")
                    await asyncio.sleep(cool)

                jittered_delay = int(base_delay * random.uniform(0.6, 1.4))
                self.log(f"[RT {rt_number}/{len(pending)}] Retweeting {url}")
                try:
                    await plain_repost(self.client.page, url, jittered_delay)
                    self.state.record_rt_farm_progress(self._profile_dir, url)
                    self.log(f"[RT {rt_number}/{len(pending)}] Done.")
                except Exception as e:
                    self.log(f"[RT {rt_number}/{len(pending)}] Failed: {e} — skipping.")
                    self.state.record_rt_farm_progress(self._profile_dir, url)

            self.log(f"=== RT FARM COMPLETE | {len(pending)} retweets cloned from @{target} ===")
            return True

        except Exception as e:
            self.log(f"ERROR: {e}")
            return False

    # ------------------------------------------------------------------ #
    #  Viral Sniper                                                        #
    # ------------------------------------------------------------------ #

    async def _run_sniper_sequence(self) -> bool:
        """Continuously scan timeline for rising posts and reply early."""
        self._cancelled = False
        if not self.config.active_api_key():
            self.log("ERROR: No API key configured for " + self.config.llm_provider)
            return False
        if not await self._ensure_browser():
            return False

        try:
            if not self._warmed_up:
                await self._session_warmup()
                self._warmed_up = True

            scan_interval = self.config.sniper_scan_interval_minutes * 60
            replies_per_scan = self.config.sniper_replies_per_scan
            min_velocity = self.config.sniper_min_velocity
            max_replies = self.config.sniper_max_replies
            scan_num = 0

            self.log(f"=== SNIPER MODE | Scanning every {self.config.sniper_scan_interval_minutes}min | vel>{min_velocity} | max replies<{max_replies} ===")

            while not self._cancelled:
                await self._wait_for_active_hours()
                if self._cancelled:
                    break

                if not self._can_act("comments"):
                    self.log("[Sniper] Daily comment cap reached. Stopping sniper.")
                    break

                scan_num += 1
                self.log(f"[Sniper Scan #{scan_num}] Scanning timeline for rising posts...")

                await self._lurk_scroll(random.randint(2, 4))

                posts = await scrape_timeline_with_age(
                    self.client.page,
                    min_likes=20,
                    max_posts=40,
                    scroll_count=6,
                )

                opportunities = [
                    p for p in posts
                    if p.velocity >= min_velocity
                    and p.replies < max_replies
                    and p.url not in self.state.sniper_replied_urls
                ]

                self.log(f"[Sniper Scan #{scan_num}] {len(opportunities)} opportunities (from {len(posts)} posts)")

                for p in opportunities[:replies_per_scan]:
                    if self._cancelled:
                        break
                    if not self._can_act("comments"):
                        break

                    self.log(
                        f"  [Sniper] @{p.handle} | {p.likes} likes | "
                        f"vel={p.velocity:.0f}/h | replies={p.replies} | "
                        f"score={p.virality_score:.1f}"
                    )

                    await self.client.navigate(p.url)
                    await self._like_and_bookmark(p.url)

                    ptype, pstrategy, ptone = self._classify_post(p.text)
                    tone = self.state.next_tone(self.state.sniper_total_replies)
                    length = random.choice(["SHORT", "MEDIUM"])

                    existing_replies = await self._scrape_reply_context(p.url)
                    positions = self._get_positions_for(p.text)

                    comment_text = await self._generate_with_dedup(
                        generate_reply_comment,
                        config=self.config,
                        original_tweet=p.text,
                        length_tier=length,
                        tone=tone,
                        post_type=ptype,
                        reply_strategy=pstrategy,
                        existing_replies=existing_replies,
                        positions=positions,
                    )

                    if comment_text:
                        self.log(f"  [Sniper] -> {comment_text[:60]}...")
                        await post_comment(
                            self.client.page, p.url, comment_text, self.config.action_delay_seconds
                        )
                        self.log(f"  [Sniper] -> Posted.")
                        self._record_action("comments")
                        self.state.record_posted_text(comment_text)
                        self.state.record_sniper_reply(self._profile_dir, p.url)
                        self._record_position_from(comment_text)
                    else:
                        self.log(f"  [Sniper] -> Skipped (too similar).")

                    await self._organic_pause(short=True)

                if self._cancelled:
                    break

                jittered_wait = int(scan_interval * random.uniform(0.8, 1.2))
                self.log(f"[Sniper] Next scan in {jittered_wait // 60}m {jittered_wait % 60}s...")
                for _ in range(jittered_wait):
                    if self._cancelled:
                        break
                    await asyncio.sleep(1)

            self.log(f"=== SNIPER MODE STOPPED | {self.state.sniper_total_replies} total replies ===")
            return True

        except Exception as e:
            self.log(f"ERROR: {e}")
            return False

    # ------------------------------------------------------------------ #
    #  Performance Tracking                                                #
    # ------------------------------------------------------------------ #

    async def _check_performance(self):
        """Check performance of recent posts and log top performers."""
        if not self.client or not self.client.page:
            return
        handle = self.config.x_username
        if not handle:
            return

        try:
            self.log("[Performance] Checking recent post metrics...")
            results = await check_post_performance(self.client.page, handle, max_posts=8)
            if not results:
                self.log("[Performance] No posts found to check.")
                return

            self.state.record_performance(self._profile_dir, results)

            best = max(results, key=lambda r: r.get("likes", 0))
            self.log(
                f"[Performance] Best recent post: {best['likes']} likes, "
                f"{best['replies']} replies, {best['views']} views — "
                f"\"{best['text_preview'][:60]}...\""
            )
        except Exception as e:
            self.log(f"[Performance] Check failed: {e}")

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _pick_post(
        self,
        posts: list[TimelinePost],
        target_topic: str,
        exclude_handles: list[str],
    ) -> TimelinePost | None:
        for p in posts:
            if p.handle in exclude_handles:
                continue
            topic = classify_topic(p.text, [target_topic])
            if topic == target_topic:
                return p
        return None

    async def run_batch(self, count: int):
        """Run multiple sequences with delays between them."""
        self._warmed_up = False
        try:
            for i in range(count):
                if self._cancelled:
                    self.log("Batch cancelled.")
                    return

                await self._wait_for_active_hours()
                if self._cancelled:
                    return

                if self.state.all_caps_reached(self._daily_caps()):
                    self.log("[Cap] All daily limits reached. Stopping batch.")
                    return

                if i > 0 and self.config.x_username:
                    await self._check_performance()

                self.log(f"\n--- Starting sequence {i+1}/{count} ---")
                success = await self.run_sequence()
                if not success:
                    self.log(f"Sequence {i+1} failed. Stopping batch.")
                    return
                if i < count - 1:
                    delay_min = self.config.sequence_delay_minutes
                    self.log(f"Waiting {delay_min} minutes before next sequence...")
                    for sec in range(delay_min * 60):
                        if self._cancelled:
                            self.log("Batch cancelled during wait.")
                            return
                        await asyncio.sleep(1)
            self.log("Batch complete.")
        finally:
            await self._close_browser()
