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
from app.content.images import fetch_images_as_base64
from app.content.position_memory import record_position, get_relevant_positions
from app.content.validator import is_too_similar
from app.content.rules import (
    FORMAT_CATALOG, FORMAT_ORDER, DEGEN_FORMAT_CATALOG, DEGEN_FORMAT_ORDER,
    DEGEN_TOPIC_KEYWORDS, COMMENT_ROTATIONS, TONE_LIST,
    THREAD_FORMAT_ORDER, classify_post_type,
)
from app.content.topics import TOPIC_KEYWORDS, classify_topic
from app.content.engagement_gate import build_eligible_posts, is_spam_post
from app.ws.manager import manager


_IMAGE_STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "to", "of", "and",
    "in", "that", "it", "for", "on", "with", "as", "at", "by", "this", "i",
})


_SELFIE_KEYWORDS = frozenset({
    "selfie", "me today", "fit check", "ootd", "new hair", "got dressed",
    "mirror pic", "no filter", "feeling cute", "just me", "my face",
    "new profile", "headshot", "portrait of me",
})


def _is_likely_personal_photo(post: dict) -> bool:
    imgs = post.get("image_urls", [])
    if len(imgs) != 1:
        return False
    text = post.get("text", "").strip()
    if len(text) < 30:
        return True
    text_lower = text.lower()
    return any(kw in text_lower for kw in _SELFIE_KEYWORDS)


def _images_relevant(source_text: str, generated_text: str) -> bool:
    source_words = set(source_text.lower().split()) - _IMAGE_STOPWORDS
    gen_words = set(generated_text.lower().split()) - _IMAGE_STOPWORDS
    if not source_words:
        return False
    overlap = len(source_words & gen_words) / len(source_words)
    return overlap >= 0.15


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
        result = await manager.send_command(self.account_id, cmd, timeout=timeout, **params)
        if result.get("status") == "error":
            raise RuntimeError(f"Extension error [{cmd}]: {result.get('error', 'unknown')}")
        return result

    async def _dismiss_compose_safe(self):
        """Best-effort cleanup of any open compose dialog."""
        try:
            await self._cmd("dismiss_compose")
        except Exception:
            pass

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

    def _topic_weight(self, topic: str) -> float:
        topics = self.cfg.get("topics", {})
        degen = self.cfg.get("degen_topics", {})
        return float(topics.get(topic, 0) or degen.get(topic, 0) or 1)

    def _next_topic(self, enabled: list[str], exclude: list[str] | None = None) -> str:
        exclude = exclude or []
        recent = {self.state.get("last_topic_tweet", ""), self.state.get("last_topic_qrt", ""), self.state.get("last_topic_rt", "")}
        recent.update(exclude)
        available = [t for t in enabled if t not in recent]
        if not available:
            available = [t for t in enabled if t not in exclude]
        if not available:
            available = enabled
        weights = [self._topic_weight(t) for t in available]
        return random.choices(available, weights=weights, k=1)[0]

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
            "follows": self.cfg.get("daily_max_follows", 30),
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

    async def _seed_dedup_from_own_profile(self):
        handle = self.cfg.get("account_handle", "")
        if not handle:
            return
        try:
            resp = await self._cmd("scrape_own_profile", handle=handle, max_posts=3)
            own_posts = resp.get("data", [])
            if own_posts:
                texts = self.state.setdefault("recent_posted_texts", [])
                for p in own_posts:
                    t = p.get("text", "").strip()
                    if t and t not in texts:
                        texts.append(t)
                self.state["recent_posted_texts"] = texts[-30:]
                self.log(f"[Dedup] Seeded {len(own_posts)} recent own tweets for redundancy check.")
        except Exception as e:
            self.log(f"[Dedup] Could not scrape own profile: {e}")

    # -- Follow helper --

    async def _do_follows(self, post_pool: list[dict]):
        target_follows = random.randint(7, 8)
        followed = 0
        last_follows = self.state.get("last_follows", [])

        try:
            resp2 = await self._cmd("scrape_who_to_follow")
            who_to_follow = resp2.get("data", [])
        except Exception:
            who_to_follow = []

        timeline_handles = list({
            p.get("handle") for p in post_pool
            if p.get("handle") and p.get("handle") not in last_follows
        })
        random.shuffle(timeline_handles)

        candidates = []
        for h in who_to_follow:
            if h not in last_follows and h not in candidates:
                candidates.append(h)
        for h in timeline_handles:
            if h not in candidates:
                candidates.append(h)

        for handle in candidates:
            if followed >= target_follows or not self._can_act("follows"):
                break
            try:
                await self._cmd("follow_user", handle=handle)
                self._record_action("follows")
                self.log(f"[Follow] Followed @{handle}.")
                last_follows.append(handle)
                followed += 1
                await self._organic_pause(short=True)
            except Exception:
                pass
        self.state["last_follows"] = last_follows[-100:]
        self.log(f"[Follow] Followed {followed}/{target_follows} accounts.")

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
            resp = await self._cmd("scrape_replies", post_url=post_url, max_replies=6)
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
            if not text:
                self.log(f"  [Gen] {gen_fn.__name__} returned None (validator rejected all attempts).")
                return None
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

            await self._seed_dedup_from_own_profile()

            following = self._use_following()
            self.log(f"Scraping timeline ({'Following' if following else 'For You'})...")
            resp = await self._cmd("scrape_timeline", min_likes=self.cfg.get("min_engagement_likes", 100), max_posts=30, scroll_count=5, use_following_tab=following)
            posts = resp.get("data", [])
            self.log(f"Found {len(posts)} posts (raw).")

            if len(posts) < 8:
                resp = await self._cmd("scrape_timeline", min_likes=20, max_posts=30, scroll_count=3, use_following_tab=following)
                posts = resp.get("data", [])

            eligible = build_eligible_posts(posts, enabled, self.cfg, min_topic_score=1)
            if len(eligible) < 3:
                self.log("Dev: need more eligible posts — second scrape with lower bar...")
                resp2 = await self._cmd(
                    "scrape_timeline",
                    min_likes=10, max_posts=40, scroll_count=6, use_following_tab=following,
                )
                extra = resp2.get("data", [])
                seen = {p.get("url") for p in eligible}
                for p in build_eligible_posts(extra, enabled, self.cfg, min_topic_score=1):
                    u = p.get("url")
                    if u and u not in seen:
                        eligible.append(p)
                        seen.add(u)

            if len(eligible) < 3:
                self.log(
                    "ERROR: Not enough posts matching your topics (need at least 3 eligible posts). "
                    "Broaden topics, use Following tab, or enable allow_trading_price_posts for CT-style posts."
                )
                return False

            if self._cancelled:
                return False

            self.log(f"Engagement pool: {len(eligible)} posts (topic gate + spam + trading policy).")
            random.shuffle(eligible)
            post_pool = eligible
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
                    # Pool is already gated (topic + spam + trading policy)
                    post = available[0]

                if action == "tweet":
                    tweet_topic = self._next_topic(enabled)
                    topic_post = self._pick_post(available, tweet_topic) or post
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
                        try:
                            await self._cmd("post_tweet", text=tweet_text, image_urls=image_urls)
                            self.log("[Tweet] Posted.")
                            self._record_action("tweets")
                            self._record_posted_text(tweet_text)
                            self._record_source_url(topic_post.get("url", ""))
                            self._record_position_from(tweet_text)
                            self.state["last_topic_tweet"] = tweet_topic
                        except Exception as e:
                            self.log(f"[Tweet] Failed: {e}")
                            await self._dismiss_compose_safe()
                    else:
                        self.log("[Tweet] Skipped — content generation failed.")

                elif action == "qrt":
                    used_urls.add(post.get("url", ""))
                    self.log(f"[QRT] Quoting @{post.get('handle')}")
                    await self._like_and_bookmark(post["url"])
                    image_b64_list = await fetch_images_as_base64(post.get("image_urls", []))
                    quote_comment = await self._generate_with_dedup(
                        generate_quote_comment, cfg=self.cfg,
                        original_tweet=post["text"],
                        enabled_topics=enabled,
                        image_b64_list=image_b64_list,
                    )
                    if quote_comment:
                        try:
                            await self._cmd("quote_tweet", post_url=post["url"], text=quote_comment)
                            self.log(f"[QRT] Posted: {quote_comment[:60]}...")
                            self._record_action("qrts")
                            self._record_posted_text(quote_comment)
                            self._record_position_from(quote_comment)
                            self.state["last_topic_qrt"] = post.get("_topic", "")
                        except Exception as e:
                            self.log(f"[QRT] Failed: {e}")
                            await self._dismiss_compose_safe()
                    else:
                        self.log("[QRT] Skipped — content generation failed.")

                elif action == "rt":
                    used_urls.add(post.get("url", ""))
                    self.log(f"[RT] Reposting @{post.get('handle')}")
                    try:
                        await self._cmd("retweet", post_url=post["url"])
                        self.log("[RT] Done.")
                        self.state["last_topic_rt"] = post.get("_topic", "")
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
                    await self._like_and_bookmark(post["url"])
                    existing_replies = await self._scrape_reply_context(post["url"])
                    positions = self._get_positions_for(post["text"])
                    image_b64_list = await fetch_images_as_base64(post.get("image_urls", []))
                    comment_text = await self._generate_with_dedup(
                        generate_reply_comment, cfg=self.cfg,
                        original_tweet=post["text"], length_tier=length, tone=tone,
                        post_type=ptype, reply_strategy=pstrategy,
                        existing_replies=existing_replies, positions=positions,
                        enabled_topics=enabled,
                        image_b64_list=image_b64_list,
                    )
                    if comment_text:
                        try:
                            await self._cmd("post_comment", post_url=post["url"], text=comment_text)
                            self.log(f"  -> Posted.")
                            self._record_action("comments")
                            self._record_posted_text(comment_text)
                            self._record_position_from(comment_text)
                        except Exception as e:
                            self.log(f"[Comment] Failed: {e}")
                            await self._dismiss_compose_safe()
                    else:
                        self.log("[Comment] Skipped — content generation failed.")
                    comment_idx += 1

                elif action == "follow":
                    await self._do_follows(post_pool)

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
                        if is_too_similar(thread_tweets[0], recent):
                            self.log("[Thread] Skipped — hook too similar to recent posts.")
                        else:
                            try:
                                await self._cmd("post_thread", tweets=thread_tweets)
                                self.log(f"[Thread] Posted {len(thread_tweets)}-tweet thread.")
                                self._record_action("tweets")
                                self.state["thread_last_format"] = thread_format
                                for t in thread_tweets:
                                    self._record_posted_text(t)
                            except Exception as e:
                                self.log(f"[Thread] Failed: {e}")
                                await self._dismiss_compose_safe()

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
            await self._dismiss_compose_safe()
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
                try:
                    await self._cmd("post_comment", post_url=post["url"], text=comment_text)
                    recent.append(comment_text)
                    recent = recent[-10:]
                    total += 1
                except Exception as e:
                    self.log(f"[Reply] Failed: {e}")
                    await self._dismiss_compose_safe()
                await self._organic_pause(short=True)

            self.state["project_sequence_number"] = seq_num
            self.state["project_comments_sent"] = self.state.get("project_comments_sent", 0) + total
            self.log(f"=== PROJECT SEQUENCE {seq_num} COMPLETE | {total} comments ===")
            return True

        except Exception as e:
            self.log(f"ERROR: {e}")
            await self._dismiss_compose_safe()
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

            await self._seed_dedup_from_own_profile()

            resp = await self._cmd("scrape_timeline", min_likes=self.cfg.get("min_engagement_likes", 100), max_posts=30, scroll_count=5, use_following_tab=self._use_following())
            posts = resp.get("data", [])
            posts = [p for p in posts if not is_spam_post(p)]
            if len(posts) < 3:
                self.log("ERROR: Not enough posts.")
                return False

            tweet_topic = ""
            tweet_handle = ""
            used_urls = set(self.state.get("recent_source_urls", []))

            # 1. DEGEN TWEET
            if self._can_act("tweets"):
                unused = [p for p in posts if p.get("url") not in used_urls]
                if unused:
                    unused.sort(key=lambda p: max(p.get("likes", 0), 1) * (2.0 if p.get("image_urls") and not _is_likely_personal_photo(p) else 1.0), reverse=True)
                    tweet_post = unused[0]
                else:
                    tweet_post = posts[0]
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
                    try:
                        await self._cmd("post_tweet", text=tweet_text, image_urls=image_urls)
                        self.log("[Degen Tweet] Posted.")
                        self._record_action("tweets")
                        self._record_posted_text(tweet_text)
                        self._record_source_url(tweet_post.get("url", ""))
                        self._record_position_from(tweet_text)
                    except Exception as e:
                        self.log(f"[Degen Tweet] Failed: {e}")
                        await self._dismiss_compose_safe()
                else:
                    self.log("[Degen Tweet] Skipped — content generation failed.")
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
                    await self._like_and_bookmark(qrt_post["url"])

                    quote_text = await self._generate_with_dedup(
                        generate_degen_quote_comment, cfg=self.cfg,
                        original_tweet=qrt_post["text"],
                    )
                    if quote_text:
                        try:
                            await self._cmd("quote_tweet", post_url=qrt_post["url"], text=quote_text)
                            self.log("[Degen QRT] Posted.")
                            self._record_action("qrts")
                            self._record_posted_text(quote_text)
                        except Exception as e:
                            self.log(f"[Degen QRT] Failed: {e}")
                            await self._dismiss_compose_safe()
                    else:
                        self.log("[Degen QRT] Skipped — content generation failed.")
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
                    try:
                        await self._cmd("post_comment", post_url=cp["url"], text=comment_text)
                        self.log("[Degen Comment] Posted.")
                        self._record_action("comments")
                        self._record_posted_text(comment_text)
                    except Exception as e:
                        self.log(f"[Degen Comment] Failed: {e}")
                        await self._dismiss_compose_safe()
                else:
                    self.log("[Degen Comment] Skipped — content generation failed.")
                if i < len(comment_posts) - 1:
                    await self._organic_pause(short=True)

            # 4. DEGEN FOLLOWS
            await self._do_follows(posts)

            self.state["degen_sequence_number"] = seq_num
            self.state["degen_last_format"] = format_key
            self.state["degen_last_topic"] = tweet_topic
            self.log(f"=== DEGEN SEQUENCE {seq_num} COMPLETE ===")
            return True

        except Exception as e:
            self.log(f"ERROR: {e}")
            await self._dismiss_compose_safe()
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
            await self._dismiss_compose_safe()
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
                    image_b64_list = await fetch_images_as_base64(p.get("image_urls", []))

                    comment_text = await self._generate_with_dedup(
                        generate_reply_comment, cfg=self.cfg,
                        original_tweet=p["text"], length_tier=length, tone=tone,
                        post_type=ptype, reply_strategy=pstrategy,
                        existing_replies=existing_replies, positions=positions,
                        enabled_topics=self._enabled_topics(),
                        image_b64_list=image_b64_list,
                    )
                    if comment_text:
                        try:
                            await self._cmd("post_comment", post_url=p["url"], text=comment_text)
                            self._record_action("comments")
                            self._record_posted_text(comment_text)
                            replied = self.state.setdefault("sniper_replied_urls", [])
                            replied.append(p["url"])
                            self.state["sniper_replied_urls"] = replied[-200:]
                            self.state["sniper_total_replies"] = self.state.get("sniper_total_replies", 0) + 1
                        except Exception as e:
                            self.log(f"[Sniper] Comment failed: {e}")
                            await self._dismiss_compose_safe()
                    else:
                        self.log("[Sniper] Skipped — content generation failed.")
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
            await self._dismiss_compose_safe()
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
        candidates = []
        for p in posts:
            if p.get("handle") in exclude_handles:
                continue
            if classify_topic(p.get("text", ""), [target_topic]) == target_topic:
                candidates.append(p)

        if not candidates:
            return None

        def _score(p: dict) -> float:
            likes = max(p.get("likes", 0), 1)
            has_images = bool(p.get("image_urls"))
            image_boost = 2.0 if has_images else 1.0
            if has_images and _is_likely_personal_photo(p):
                image_boost = 0.5
            return likes * image_boost

        candidates.sort(key=_score, reverse=True)
        return candidates[0]
