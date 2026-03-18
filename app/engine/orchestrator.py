"""Sequence orchestrator — port of sequence_engine.py using WebSocket commands."""

import asyncio
import random
from datetime import datetime, timezone
from typing import Callable
from zoneinfo import ZoneInfo

from app.content.generator import (
    generate_tweet, generate_quote_comment, generate_reply_comment,
    generate_project_comment, generate_smart_project_comment,
    generate_degen_tweet, generate_degen_quote_comment,
    generate_degen_reply_comment, generate_thread,
    classify_post_with_llm, extract_position,
    check_image_relevance_with_vision,
)
from app.content.position_memory import record_position, get_relevant_positions
from app.content.validator import is_too_similar
from app.content.rules import (
    FORMAT_CATALOG, FORMAT_ORDER, DEGEN_FORMAT_CATALOG, DEGEN_FORMAT_ORDER,
    DEGEN_TOPIC_KEYWORDS, COMMENT_ROTATIONS, TONE_LIST,
    THREAD_FORMAT_ORDER, classify_post_type,
)
from app.ws.manager import manager


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

_RT_BLOCKLIST = [
    "vote", "voting", "election", "candidate", "democrat", "republican", "trump",
    "biden", "kamala", "governor", "senator", "congress", "political", "ballot",
    "campaign trail", "maga", "liberal", "conservative",
    "launching soon", "pre-order", "use code", "discount code", "promo code",
    "giveaway", "giving away", "drop your wallet", "airdrop claim",
    "link in bio", "sign up now", "limited time", "act fast", "don't miss",
    "sponsored", "ad ", "#ad ", "partnership with", "collab with",
    "onlyfans", "subscribe to my", "join my telegram",
    "retweet to win", "follow and rt", "like and retweet", "tag a friend",
]


def _is_rt_worthy(post: dict, enabled_topics: list[str]) -> bool:
    """Check if a post is worth retweeting — on-topic and not junk/promo/political."""
    text = post.get("text", "").lower()
    for blocked in _RT_BLOCKLIST:
        if blocked in text:
            return False
    topic = post.get("_topic", "")
    if topic and topic in enabled_topics:
        return True
    if post.get("likes", 0) > 500:
        return True
    return False


_IMAGE_STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "to", "of", "and",
    "in", "that", "it", "for", "on", "with", "as", "at", "by", "this", "i",
})


def _images_relevant(source_text: str, generated_text: str) -> bool:
    source_words = set(source_text.lower().split()) - _IMAGE_STOPWORDS
    gen_words = set(generated_text.lower().split()) - _IMAGE_STOPWORDS
    if not source_words:
        return False
    overlap = len(source_words & gen_words) / len(source_words)
    return overlap >= 0.15


def classify_topic(text: str, enabled_topics: list[str], keyword_map: dict | None = None) -> str:
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
    return ""


class Orchestrator:
    """Runs farming sequences by sending commands to the Chrome extension via WebSocket."""

    def __init__(self, account_id: str, cfg: dict, state: dict, log_fn: Callable[[str], None]):
        self.account_id = account_id
        self.cfg = cfg
        self.state = state
        self.log = log_fn
        self._cancelled = False
        self._warmed_up = False

    def cancel(self):
        self._cancelled = True

    _SLOW_COMMANDS = {"post_tweet", "post_comment", "post_thread", "quote_tweet", "session_warmup", "scrape_timeline"}

    async def _cmd(self, cmd: str, timeout: float = 60.0, **params) -> dict:
        """Send a command to the extension and return the response."""
        if cmd in self._SLOW_COMMANDS and timeout <= 60.0:
            timeout = 180.0
        return await manager.send_command(self.account_id, cmd, timeout=timeout, **params)

    def _use_following(self) -> bool:
        return bool(self.cfg.get("use_following_tab", True))

    def _enabled_topics(self) -> list[str]:
        topics = self.cfg.get("topics", {})
        return [t for t, w in topics.items() if w]

    def _enabled_degen_topics(self) -> list[str]:
        topics = self.cfg.get("degen_topics", {})
        return [t for t, w in topics.items() if w]

    def _active_api_key(self) -> str:
        if self.cfg.get("llm_provider") == "anthropic":
            return self.cfg.get("anthropic_api_key", "")
        return self.cfg.get("openai_api_key", "")

    def _recent_posts(self, n: int = 5) -> list[str]:
        texts = self.state.get("recent_posted_texts", [])
        return texts[-n:] if texts else []

    # -- State rotation helpers (mirror SequenceState methods) --

    def _next_format(self) -> str:
        last = self.state.get("last_format", "")
        idx = 0
        if last in FORMAT_ORDER:
            idx = (FORMAT_ORDER.index(last) + 1) % len(FORMAT_ORDER)
        return FORMAT_ORDER[idx]

    def _next_topic(self, enabled: list[str], exclude: list[str] | None = None) -> str:
        exclude = exclude or []
        recent = {self.state.get("last_topic_tweet", ""), self.state.get("last_topic_qrt", ""), self.state.get("last_topic_rt", "")}
        recent.update(exclude)
        available = [t for t in enabled if t not in recent]
        if not available:
            available = [t for t in enabled if t not in exclude]
        if not available:
            available = enabled
        return random.choice(available)

    def _next_comment_rotation(self) -> list[str]:
        last = self.state.get("last_comment_rotation", [])
        if last in COMMENT_ROTATIONS:
            idx = (COMMENT_ROTATIONS.index(last) + 1) % len(COMMENT_ROTATIONS)
        else:
            idx = 0
        return COMMENT_ROTATIONS[idx]

    def _next_tone(self, index: int) -> str:
        return TONE_LIST[index % len(TONE_LIST)]

    def _next_degen_format(self) -> str:
        last = self.state.get("degen_last_format", "")
        idx = 0
        if last in DEGEN_FORMAT_ORDER:
            idx = (DEGEN_FORMAT_ORDER.index(last) + 1) % len(DEGEN_FORMAT_ORDER)
        return DEGEN_FORMAT_ORDER[idx]

    def _next_thread_format(self) -> str:
        last = self.state.get("thread_last_format", "")
        idx = 0
        if last in THREAD_FORMAT_ORDER:
            idx = (THREAD_FORMAT_ORDER.index(last) + 1) % len(THREAD_FORMAT_ORDER)
        return THREAD_FORMAT_ORDER[idx]

    def _should_post_thread(self) -> bool:
        seq = self.state.get("sequence_number", 0)
        every_n = self.cfg.get("thread_every_n_sequences", 4)
        return seq > 0 and seq % every_n == 0

    # -- Daily caps --

    def _daily_caps(self) -> dict:
        return {
            "tweets": self.cfg.get("daily_max_tweets", 8),
            "comments": self.cfg.get("daily_max_comments", 25),
            "likes": self.cfg.get("daily_max_likes", 50),
            "follows": self.cfg.get("daily_max_follows", 10),
            "qrts": self.cfg.get("daily_max_qrts", 5),
        }

    def _today_key(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _today_counts(self) -> dict:
        daily = self.state.get("daily_actions", {})
        key = self._today_key()
        if key not in daily:
            daily = {key: {}}
            self.state["daily_actions"] = daily
        return daily[key]

    def _can_act(self, action_type: str) -> bool:
        cap = self._daily_caps().get(action_type)
        if cap is None:
            return True
        counts = self._today_counts()
        if counts.get(action_type, 0) < cap:
            return True
        self.log(f"[Cap] Daily {action_type} limit reached ({cap}/{cap}). Skipping.")
        return False

    def _record_action(self, action_type: str):
        counts = self._today_counts()
        counts[action_type] = counts.get(action_type, 0) + 1

    def _all_caps_reached(self) -> bool:
        caps = self._daily_caps()
        for action_type, cap in caps.items():
            counts = self._today_counts()
            if counts.get(action_type, 0) < cap:
                return False
        return True

    def _record_posted_text(self, text: str):
        texts = self.state.setdefault("recent_posted_texts", [])
        texts.append(text)
        self.state["recent_posted_texts"] = texts[-30:]

    def _record_source_url(self, url: str):
        urls = self.state.setdefault("recent_source_urls", [])
        if url not in urls:
            urls.append(url)
        self.state["recent_source_urls"] = urls[-50:]

    # -- Active hours --

    def _is_active_hours(self) -> bool:
        if not self.cfg.get("active_hours_enabled"):
            return True
        try:
            tz = ZoneInfo(self.cfg.get("active_hours_timezone", "UTC"))
        except Exception:
            tz = timezone.utc
        now = datetime.now(tz)
        start = self.cfg.get("active_hours_start", 8)
        end = self.cfg.get("active_hours_end", 23)
        if start <= end:
            return start <= now.hour < end
        return now.hour >= start or now.hour < end

    async def _wait_for_active_hours(self):
        if self._is_active_hours():
            return
        self.log(f"[Hours] Outside active hours. Waiting...")
        while not self._is_active_hours() and not self._cancelled:
            await asyncio.sleep(60)

    # -- Human simulation commands --

    async def _organic_pause(self, short: bool = False):
        pause = random.uniform(8, 25) if not short else random.uniform(3, 10)
        self.log(f"  [Pause] {pause:.0f}s...")
        await asyncio.sleep(pause)
        if random.random() < 0.3:
            await self._cmd("scroll", count=1)
            await asyncio.sleep(random.uniform(2, 5))

    async def _session_warmup(self):
        self.log("[Warmup] Opening session naturally...")
        try:
            await self._cmd("session_warmup", timeout=120)
        except Exception:
            pass
        self.log("[Warmup] Done.")

    async def _lurk_scroll(self, count: int | None = None):
        count = count or random.randint(3, 8)
        self.log(f"  [Lurk] Scrolling past {count} posts...")
        try:
            await self._cmd("lurk_scroll", count=count, timeout=120)
        except Exception:
            pass

    async def _like_and_bookmark(self, post_url: str):
        if random.random() < 0.8 and self._can_act("likes"):
            try:
                resp = await self._cmd("like_post", post_url=post_url)
                if resp.get("status") == "ok":
                    self.log("  [Like] Liked post.")
                    self._record_action("likes")
            except Exception:
                pass
            await asyncio.sleep(random.uniform(2, 6))
        if random.random() < 0.1:
            try:
                await self._cmd("bookmark_post", post_url=post_url)
            except Exception:
                pass
            await asyncio.sleep(random.uniform(1, 3))

    # -- Classification --

    def _classify_post(self, text: str) -> tuple[str, str, str]:
        if self.cfg.get("use_llm_classification"):
            result = classify_post_with_llm(self.cfg, text)
            if result:
                return result.get("type", "general"), result.get("reply_strategy", ""), result.get("tone", "")
        ptype, pstrategy = classify_post_type(text)
        return ptype, pstrategy, ""

    def _get_positions_for(self, post_text: str) -> list[dict]:
        if not self.cfg.get("position_memory_enabled"):
            return []
        return get_relevant_positions(self.state.get("position_history", []), post_text)

    def _record_position_from(self, posted_text: str):
        if not self.cfg.get("position_memory_enabled"):
            return
        result = extract_position(self.cfg, posted_text)
        if result:
            history = self.state.setdefault("position_history", [])
            self.state["position_history"] = record_position(
                history, result["topic"], result["stance"],
                datetime.now(timezone.utc).isoformat(),
            )

    async def _scrape_reply_context(self, post_url: str) -> list[str]:
        try:
            resp = await self._cmd("scrape_replies", post_url=post_url, max_replies=3)
            replies = resp.get("data", [])
            if replies:
                self.log(f"  [Context] Got {len(replies)} replies for vibe check.")
            return replies
        except Exception:
            return []

    async def _generate_with_dedup(self, gen_fn, max_retries: int = 3, **kwargs) -> str | None:
        recent = self._recent_posts()
        kwargs["recent_posts"] = recent
        for attempt in range(max_retries):
            text = gen_fn(**kwargs)
            if not is_too_similar(text, recent):
                return text
            self.log(f"  [Dedup] Attempt {attempt + 1}: too similar, regenerating...")
        self.log("  [Dedup] WARNING: All attempts similar. Skipping.")
        return None

    # ================================================================== #
    #  Sequence dispatch                                                   #
    # ================================================================== #

    async def run_sequence(self) -> bool:
        await self._wait_for_active_hours()
        if self._cancelled:
            return False
        if self._all_caps_reached():
            self.log("[Cap] All daily limits reached. Stopping.")
            return False
        mode = self.cfg.get("farming_mode", "dev")
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

    # ================================================================== #
    #  Dev Farming                                                         #
    # ================================================================== #

    async def _run_dev_sequence(self) -> bool:
        self._cancelled = False
        enabled = self._enabled_topics()
        if len(enabled) < 3:
            self.log("ERROR: Need at least 3 enabled topics.")
            return False
        if not self._active_api_key():
            self.log("ERROR: No API key configured.")
            return False

        try:
            if not self._warmed_up:
                await self._session_warmup()
                self._warmed_up = True

            format_key = self._next_format()
            comment_rotation = self._next_comment_rotation()
            seq_num = self.state.get("sequence_number", 0) + 1
            self.log(f"=== DEV SEQUENCE {seq_num} | Format: {format_key} ({FORMAT_CATALOG[format_key]['name']}) ===")

            following = self._use_following()
            self.log(f"Scraping timeline ({'Following' if following else 'For You'})...")
            resp = await self._cmd("scrape_timeline", min_likes=self.cfg.get("min_engagement_likes", 100), max_posts=30, scroll_count=5, use_following_tab=following)
            posts = resp.get("data", [])
            self.log(f"Found {len(posts)} posts (raw).")

            if len(posts) < 8:
                resp = await self._cmd("scrape_timeline", min_likes=20, max_posts=30, scroll_count=3, use_following_tab=following)
                posts = resp.get("data", [])

            for p in posts:
                p["_topic"] = classify_topic(p.get("text", ""), enabled)

            on_topic = [p for p in posts if p["_topic"] in enabled]
            if on_topic:
                posts = on_topic
                self.log(f"Filtered to {len(posts)} on-topic posts.")
            else:
                self.log(f"No on-topic posts found, using all {len(posts)} posts (LLM will adapt).")

            if len(posts) < 3:
                self.log("ERROR: Not enough posts.")
                return False

            if self._cancelled:
                return False

            # Build a shuffled action plan from available posts
            post_pool = list(posts)
            random.shuffle(post_pool)
            used_urls = set(self.state.get("recent_source_urls", []))

            actions = []
            if self._can_act("tweets"):
                actions.append("tweet")
            if self._can_act("qrts"):
                actions.append("qrt")
            if random.random() > 0.2:
                actions.append("rt")
            num_comments = random.randint(3, 5)
            for _ in range(num_comments):
                if self._can_act("comments"):
                    actions.append("comment")
            if random.random() < 0.5:
                actions.append("follow")
            if self._should_post_thread() and self._can_act("tweets"):
                actions.append("thread")

            random.shuffle(actions)
            comment_idx = 0
            used_handles = set()

            for action in actions:
                if self._cancelled:
                    return False

                # follow doesn't need a post from the pool
                if action == "follow":
                    pass
                else:
                    available = [p for p in post_pool if p.get("url") not in used_urls]
                    if not available:
                        self.log(f"[{action.upper()}] Skipped — no unused posts left.")
                        continue
                    post = available[0]

                if action == "tweet":
                    topic_post = self._pick_post(available, self._next_topic(enabled)) or post
                    used_urls.add(topic_post.get("url", ""))
                    self.log(f"[Tweet] From @{topic_post.get('handle')} ({topic_post.get('likes', 0)} likes)")
                    tweet_text = await self._generate_with_dedup(
                        generate_tweet, cfg=self.cfg,
                        format_key=format_key, original_tweet=topic_post["text"],
                        length_tier=random.choice(["SHORT", "MEDIUM", "LONG"]),
                        enabled_topics=enabled,
                    )
                    if tweet_text:
                        self.log(f"[Tweet] Generated ({len(tweet_text)} chars): {tweet_text[:80]}...")
                        image_urls = topic_post.get("image_urls", [])
                        use_images = bool(image_urls) and _images_relevant(topic_post["text"], tweet_text)
                        await self._cmd("post_tweet", text=tweet_text, image_urls=image_urls if use_images else [])
                        self.log("[Tweet] Posted.")
                        self._record_action("tweets")
                        self._record_posted_text(tweet_text)
                        self._record_source_url(topic_post.get("url", ""))
                        self._record_position_from(tweet_text)

                elif action == "qrt":
                    qrt_candidates = [p for p in available if _is_rt_worthy(p, enabled)]
                    if not qrt_candidates:
                        self.log("[QRT] Skipped — no quality post to quote.")
                        continue
                    post = qrt_candidates[0]
                    used_urls.add(post.get("url", ""))
                    self.log(f"[QRT] Quoting @{post.get('handle')}")
                    await self._cmd("navigate", url=post["url"])
                    await self._like_and_bookmark(post["url"])
                    quote_comment = await self._generate_with_dedup(
                        generate_quote_comment, cfg=self.cfg,
                        original_tweet=post["text"],
                        enabled_topics=enabled,
                    )
                    if quote_comment:
                        try:
                            await self._cmd("quote_tweet", post_url=post["url"], text=quote_comment)
                            self.log(f"[QRT] Posted: {quote_comment[:60]}...")
                            self._record_action("qrts")
                            self._record_posted_text(quote_comment)
                            self._record_position_from(quote_comment)
                        except Exception as e:
                            self.log(f"[QRT] Failed: {e}")

                elif action == "rt":
                    rt_candidates = [p for p in available if _is_rt_worthy(p, enabled)]
                    if not rt_candidates:
                        self.log("[RT] Skipped — no quality post to retweet.")
                        continue
                    post = rt_candidates[0]
                    used_urls.add(post.get("url", ""))
                    self.log(f"[RT] Reposting @{post.get('handle')}")
                    try:
                        await self._cmd("retweet", post_url=post["url"])
                        self.log("[RT] Done.")
                    except Exception as e:
                        self.log(f"[RT] Failed: {e}")

                elif action == "comment":
                    if not self._can_act("comments"):
                        continue
                    used_urls.add(post.get("url", ""))
                    length = comment_rotation[comment_idx] if comment_idx < len(comment_rotation) else "MEDIUM"
                    tone = self._next_tone(comment_idx + seq_num)
                    ptype, pstrategy, _ = self._classify_post(post["text"])
                    self.log(f"[Comment] @{post.get('handle')} | {length} | {tone}")
                    await self._cmd("navigate", url=post["url"])
                    await self._like_and_bookmark(post["url"])
                    existing_replies = await self._scrape_reply_context(post["url"])
                    positions = self._get_positions_for(post["text"])
                    comment_text = await self._generate_with_dedup(
                        generate_reply_comment, cfg=self.cfg,
                        original_tweet=post["text"], length_tier=length, tone=tone,
                        post_type=ptype, reply_strategy=pstrategy,
                        existing_replies=existing_replies, positions=positions,
                        enabled_topics=enabled,
                    )
                    if comment_text:
                        await self._cmd("post_comment", post_url=post["url"], text=comment_text)
                        self.log(f"  -> Posted.")
                        self._record_action("comments")
                        self._record_posted_text(comment_text)
                        self._record_position_from(comment_text)
                    comment_idx += 1

                elif action == "follow":
                    try:
                        resp2 = await self._cmd("scrape_who_to_follow")
                        who_to_follow = resp2.get("data", [])
                    except Exception:
                        who_to_follow = []
                    last_follows = self.state.get("last_follows", [])
                    for handle in who_to_follow[:2]:
                        if not self._can_act("follows"):
                            break
                        if handle in last_follows:
                            continue
                        try:
                            await self._cmd("follow_user", handle=handle)
                            self._record_action("follows")
                            self.log(f"[Follow] Followed @{handle}.")
                            last_follows.append(handle)
                        except Exception:
                            pass
                    self.state["last_follows"] = last_follows

                elif action == "thread":
                    self.log("[Thread] Generating thread...")
                    thread_format = self._next_thread_format()
                    recent = self._recent_posts()
                    thread_tweets = generate_thread(
                        cfg=self.cfg, thread_format_key=thread_format,
                        original_tweet=post["text"], recent_posts=recent,
                        enabled_topics=enabled,
                    )
                    if thread_tweets:
                        # Check the hook tweet (first one) isn't too similar to recent posts
                        if is_too_similar(thread_tweets[0], recent):
                            self.log("[Thread] Skipped — hook too similar to recent posts.")
                        else:
                            await self._cmd("post_thread", tweets=thread_tweets)
                            self.log(f"[Thread] Posted {len(thread_tweets)}-tweet thread.")
                            self._record_action("tweets")
                            self.state["thread_last_format"] = thread_format
                            for t in thread_tweets:
                                self._record_posted_text(t)

                # Organic pause between actions (like a real person browsing)
                if random.random() < 0.4:
                    await self._lurk_scroll(random.randint(1, 3))
                await self._organic_pause(short=random.random() < 0.5)

            # SAVE STATE
            self.state["sequence_number"] = seq_num
            self.state["last_format"] = format_key
            self.state["last_comment_rotation"] = comment_rotation
            self.log(f"=== DEV SEQUENCE {seq_num} COMPLETE ===")
            return True

        except Exception as e:
            self.log(f"ERROR: {e}")
            return False

    # ================================================================== #
    #  Project Farming                                                     #
    # ================================================================== #

    async def _run_project_sequence(self) -> bool:
        self._cancelled = False
        try:
            if not self._warmed_up:
                await self._session_warmup()
                self._warmed_up = True

            seq_num = self.state.get("project_sequence_number", 0) + 1
            target = self.cfg.get("project_timeline_comments", 5)
            min_likes = self.cfg.get("project_timeline_min_likes", 100)
            self.log(f"=== PROJECT SEQUENCE {seq_num} | target {target} comments ===")

            resp = await self._cmd("scrape_timeline", min_likes=min_likes, max_posts=50, scroll_count=6, use_following_tab=self._use_following())
            posts = resp.get("data", [])
            self.log(f"Found {len(posts)} posts.")

            if not posts:
                self.log("No posts found. Try lowering like threshold.")
                return True

            total = 0
            recent: list[str] = []
            for post in posts:
                if total >= target or self._cancelled:
                    break
                self.log(f"[Reply] @{post.get('handle')} ({post.get('likes', 0)} likes)")
                await self._cmd("navigate", url=post["url"])
                await self._like_and_bookmark(post["url"])

                # Try smart comment first
                name = self.cfg.get("project_name") or post.get("handle", "")
                try:
                    resp2 = await self._cmd("scrape_replies", post_url=post["url"], max_replies=5)
                    top_replies = resp2.get("data", [])
                except Exception:
                    top_replies = []

                smart = generate_smart_project_comment(
                    cfg=self.cfg, post_text=post["text"],
                    post_author=post.get("handle", ""),
                    top_replies=top_replies, project_name=name,
                )
                comment_text = smart or generate_project_comment(name, recent_comments=recent)
                self.log(f"[Reply] -> \"{comment_text}\"")
                await self._cmd("post_comment", post_url=post["url"], text=comment_text)
                recent.append(comment_text)
                recent = recent[-10:]
                total += 1
                await self._organic_pause(short=True)

            self.state["project_sequence_number"] = seq_num
            self.state["project_comments_sent"] = self.state.get("project_comments_sent", 0) + total
            self.log(f"=== PROJECT SEQUENCE {seq_num} COMPLETE | {total} comments ===")
            return True

        except Exception as e:
            self.log(f"ERROR: {e}")
            return False

    # ================================================================== #
    #  Degen Farming                                                       #
    # ================================================================== #

    async def _run_degen_sequence(self) -> bool:
        self._cancelled = False
        enabled = self._enabled_degen_topics()
        if len(enabled) < 2:
            self.log("ERROR: Need at least 2 degen topics.")
            return False
        if not self._active_api_key():
            self.log("ERROR: No API key configured.")
            return False

        try:
            if not self._warmed_up:
                await self._session_warmup()
                self._warmed_up = True

            format_key = self._next_degen_format()
            comment_rotation = self._next_comment_rotation()
            seq_num = self.state.get("degen_sequence_number", 0) + 1
            self.log(f"=== DEGEN SEQUENCE {seq_num} | Format: {format_key} ===")

            resp = await self._cmd("scrape_timeline", min_likes=self.cfg.get("min_engagement_likes", 100), max_posts=30, scroll_count=5, use_following_tab=self._use_following())
            posts = resp.get("data", [])
            if len(posts) < 3:
                self.log("ERROR: Not enough posts.")
                return False

            tweet_topic = ""
            tweet_handle = ""
            used_urls = set(self.state.get("recent_source_urls", []))

            # 1. DEGEN TWEET
            if self._can_act("tweets"):
                tweet_post = next((p for p in posts if p.get("url") not in used_urls), posts[0])
                used_urls.add(tweet_post.get("url", ""))

                tweet_topic = classify_topic(tweet_post["text"], enabled, DEGEN_TOPIC_KEYWORDS)
                tweet_handle = tweet_post.get("handle", "")
                self.log(f"[Degen Tweet] From @{tweet_handle}")

                tweet_text = await self._generate_with_dedup(
                    generate_degen_tweet, cfg=self.cfg,
                    format_key=format_key, original_tweet=tweet_post["text"],
                )
                if tweet_text:
                    image_urls = tweet_post.get("image_urls", [])
                    use_images = bool(image_urls) and _images_relevant(tweet_post["text"], tweet_text)
                    await self._cmd("post_tweet", text=tweet_text, image_urls=image_urls if use_images else [])
                    self.log("[Degen Tweet] Posted.")
                    self._record_action("tweets")
                    self._record_posted_text(tweet_text)
                    self._record_source_url(tweet_post.get("url", ""))
                    self._record_position_from(tweet_text)
            else:
                tweet_post = posts[0]
                tweet_handle = tweet_post.get("handle", "")
                used_urls.add(tweet_post.get("url", ""))

            if self._cancelled:
                return False
            await self._organic_pause()

            # 2. DEGEN QRT
            if self._can_act("qrts"):
                qrt_candidates = [p for p in posts if p.get("url") not in used_urls and p.get("handle") != tweet_handle]
                if qrt_candidates:
                    qrt_post = qrt_candidates[0]
                    used_urls.add(qrt_post.get("url", ""))
                    self.log(f"[Degen QRT] Quoting @{qrt_post.get('handle')}")
                    await self._cmd("navigate", url=qrt_post["url"])
                    await self._like_and_bookmark(qrt_post["url"])

                    quote_text = await self._generate_with_dedup(
                        generate_degen_quote_comment, cfg=self.cfg,
                        original_tweet=qrt_post["text"],
                    )
                    if quote_text:
                        await self._cmd("quote_tweet", post_url=qrt_post["url"], text=quote_text)
                        self._record_action("qrts")
                        self._record_posted_text(quote_text)
                else:
                    self.log("[Degen QRT] Skipped — no unused posts.")

            if self._cancelled:
                return False
            await self._organic_pause()

            # 3. DEGEN COMMENTS
            num_comments = random.randint(3, 5)
            comment_posts = [p for p in posts if p.get("url") not in used_urls][:num_comments]

            for i, cp in enumerate(comment_posts):
                if self._cancelled:
                    return False
                if not self._can_act("comments"):
                    break
                used_urls.add(cp.get("url", ""))
                length = comment_rotation[i] if i < len(comment_rotation) else "MEDIUM"
                tone = self._next_tone(i + seq_num)
                ptype, pstrategy, _ = self._classify_post(cp["text"])

                await self._cmd("navigate", url=cp["url"])
                await self._like_and_bookmark(cp["url"])
                existing_replies = await self._scrape_reply_context(cp["url"])
                positions = self._get_positions_for(cp["text"])

                comment_text = await self._generate_with_dedup(
                    generate_degen_reply_comment, cfg=self.cfg,
                    original_tweet=cp["text"], length_tier=length, tone=tone,
                    post_type=ptype, reply_strategy=pstrategy,
                    existing_replies=existing_replies, positions=positions,
                )
                if comment_text:
                    await self._cmd("post_comment", post_url=cp["url"], text=comment_text)
                    self._record_action("comments")
                    self._record_posted_text(comment_text)
                if i < len(comment_posts) - 1:
                    await self._organic_pause(short=True)

            self.state["degen_sequence_number"] = seq_num
            self.state["degen_last_format"] = format_key
            self.state["degen_last_topic"] = tweet_topic
            self.log(f"=== DEGEN SEQUENCE {seq_num} COMPLETE ===")
            return True

        except Exception as e:
            self.log(f"ERROR: {e}")
            return False

    # ================================================================== #
    #  RT Farm                                                             #
    # ================================================================== #

    async def _run_rt_farm_sequence(self) -> bool:
        target = self.cfg.get("rt_farm_target_handle", "")
        if not target:
            self.log("ERROR: No RT farm target handle.")
            return False

        try:
            self.log(f"=== RT FARM | Cloning RTs from @{target} ===")
            resp = await self._cmd("scrape_retweets", handle=target,
                                   max_scrolls=self.cfg.get("rt_farm_max_scrolls", 50), timeout=300)
            all_urls = resp.get("data", [])

            if not all_urls:
                self.log("No retweets found.")
                return True

            done = set(self.state.get("rt_farm_completed_urls", []))
            pending = [u for u in all_urls if u not in done]
            self.log(f"{len(all_urls)} total, {len(pending)} remaining.")

            base_delay = self.cfg.get("rt_farm_delay_seconds", 5)
            for i, url in enumerate(pending):
                if self._cancelled:
                    return False
                rt_num = i + 1
                if rt_num > 1 and rt_num % 30 == 0:
                    await asyncio.sleep(random.uniform(120, 300))
                elif rt_num > 1 and rt_num % 10 == 0:
                    await asyncio.sleep(random.uniform(30, 90))

                self.log(f"[RT {rt_num}/{len(pending)}] {url}")
                try:
                    await self._cmd("retweet", post_url=url)
                except Exception as e:
                    self.log(f"  Failed: {e}")

                completed = self.state.setdefault("rt_farm_completed_urls", [])
                if url not in completed:
                    completed.append(url)
                self.state["rt_farm_total_retweeted"] = len(completed)
                await asyncio.sleep(base_delay * random.uniform(0.6, 1.4))

            self.log(f"=== RT FARM COMPLETE ===")
            return True

        except Exception as e:
            self.log(f"ERROR: {e}")
            return False

    # ================================================================== #
    #  Sniper                                                              #
    # ================================================================== #

    async def _run_sniper_sequence(self) -> bool:
        if not self._active_api_key():
            self.log("ERROR: No API key configured.")
            return False

        try:
            if not self._warmed_up:
                await self._session_warmup()
                self._warmed_up = True

            interval = self.cfg.get("sniper_scan_interval_minutes", 8) * 60
            per_scan = self.cfg.get("sniper_replies_per_scan", 2)
            min_vel = self.cfg.get("sniper_min_velocity", 100)
            max_replies = self.cfg.get("sniper_max_replies", 80)
            scan_num = 0

            self.log(f"=== SNIPER MODE | every {interval // 60}min ===")

            while not self._cancelled:
                await self._wait_for_active_hours()
                if self._cancelled:
                    break
                if not self._can_act("comments"):
                    break

                scan_num += 1
                self.log(f"[Sniper #{scan_num}] Scanning...")
                await self._lurk_scroll(random.randint(2, 4))

                resp = await self._cmd("scrape_timeline", min_likes=20, max_posts=40, scroll_count=6, sort_by="virality", use_following_tab=self._use_following())
                posts = resp.get("data", [])

                replied_urls = self.state.get("sniper_replied_urls", [])
                opps = [p for p in posts
                        if p.get("velocity", 0) >= min_vel
                        and p.get("replies", 0) < max_replies
                        and p.get("url") not in replied_urls]

                self.log(f"[Sniper #{scan_num}] {len(opps)} opportunities")

                for p in opps[:per_scan]:
                    if self._cancelled or not self._can_act("comments"):
                        break
                    self.log(f"  @{p.get('handle')} | vel={p.get('velocity', 0):.0f}")
                    await self._cmd("navigate", url=p["url"])
                    await self._like_and_bookmark(p["url"])

                    ptype, pstrategy, _ = self._classify_post(p["text"])
                    tone = self._next_tone(self.state.get("sniper_total_replies", 0))
                    length = random.choice(["SHORT", "MEDIUM"])
                    existing_replies = await self._scrape_reply_context(p["url"])
                    positions = self._get_positions_for(p["text"])

                    comment_text = await self._generate_with_dedup(
                        generate_reply_comment, cfg=self.cfg,
                        original_tweet=p["text"], length_tier=length, tone=tone,
                        post_type=ptype, reply_strategy=pstrategy,
                        existing_replies=existing_replies, positions=positions,
                        enabled_topics=self._enabled_topics(),
                    )
                    if comment_text:
                        await self._cmd("post_comment", post_url=p["url"], text=comment_text)
                        self._record_action("comments")
                        self._record_posted_text(comment_text)
                        replied = self.state.setdefault("sniper_replied_urls", [])
                        replied.append(p["url"])
                        self.state["sniper_replied_urls"] = replied[-200:]
                        self.state["sniper_total_replies"] = self.state.get("sniper_total_replies", 0) + 1
                    await self._organic_pause(short=True)

                if self._cancelled:
                    break
                jitter = int(interval * random.uniform(0.8, 1.2))
                self.log(f"[Sniper] Next scan in {jitter // 60}m...")
                for _ in range(jitter):
                    if self._cancelled:
                        break
                    await asyncio.sleep(1)

            self.log(f"=== SNIPER STOPPED | {self.state.get('sniper_total_replies', 0)} total ===")
            return True

        except Exception as e:
            self.log(f"ERROR: {e}")
            return False

    # ================================================================== #
    #  Batch runner                                                        #
    # ================================================================== #

    async def run_batch(self, count: int):
        self._warmed_up = False
        for i in range(count):
            if self._cancelled:
                self.log("Batch cancelled.")
                return
            await self._wait_for_active_hours()
            if self._cancelled:
                return
            if self._all_caps_reached():
                self.log("[Cap] All caps reached. Stopping batch.")
                return

            self.log(f"\n--- Sequence {i+1}/{count} ---")
            success = await self.run_sequence()
            if not success:
                self.log(f"Sequence {i+1} failed. Stopping.")
                return
            if i < count - 1:
                delay = self.cfg.get("sequence_delay_minutes", 45)
                self.log(f"Waiting {delay}min...")
                for _ in range(delay * 60):
                    if self._cancelled:
                        return
                    await asyncio.sleep(1)
        self.log("Batch complete.")

    # ================================================================== #
    #  Helpers                                                             #
    # ================================================================== #

    def _pick_post(self, posts: list[dict], target_topic: str,
                   exclude_handles: list[str] | None = None) -> dict | None:
        exclude_handles = exclude_handles or []
        for p in posts:
            if p.get("handle") in exclude_handles:
                continue
            if classify_topic(p.get("text", ""), [target_topic]) == target_topic:
                return p
        return None
