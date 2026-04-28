"""High-level sequence runners for each farming mode.

Modes share the same per-action handlers in :mod:`app.engine.actions`. The
mode runner's only job is to scrape the timeline, build the action plan, and
drive the handlers in order. Active-hours + cap gating is the orchestrator's
responsibility (the runner returns ``False`` to stop a batch early).
"""

from __future__ import annotations

import asyncio
import random

from app.content.engagement_gate import build_eligible_posts, is_spam_post
from app.content.generator import (
    generate_degen_quote_comment, generate_degen_reply_comment,
    generate_degen_tweet, generate_reply_comment, GenerationResult,
)
from app.content.images import fetch_images_as_base64
from app.content.rules import (
    DEGEN_FORMAT_CATALOG, DEGEN_TOPIC_KEYWORDS, FORMAT_CATALOG,
)
from app.content.topics import classify_topic
from app.content.validator import is_duplicate
from app.engine import actions as A
from app.engine import state as S
from app.engine.actions import SequenceContext
from app.engine.constants import (
    SNIPER_REPLIED_CAP, TIMELINE_FALLBACK_LIKES_DIVISOR, TIMELINE_MIN_ELIGIBLE,
)
from app.engine.planner import build_dev_action_plan, summarize_plan


# Bail an RT-farm batch after this many consecutive failures (extension issue,
# rate limit, X UI break, etc.) instead of grinding through every URL.
RT_FARM_MAX_CONSECUTIVE_FAILURES = 5


# --------------------------------------------------------------------------- #
#  Timeline scrape (shared)                                                   #
# --------------------------------------------------------------------------- #

def _format_gate_stats(eligible) -> str:
    """Compact one-line summary from EligiblePosts.drop_stats."""
    stats = getattr(eligible, "drop_stats", None) or {}
    if not stats:
        return f"kept={len(eligible)}"
    path = stats.get("classify_path", "?")
    return (
        f"raw={stats.get('raw', 0)} "
        f"spam={stats.get('spam', 0)} "
        f"no_topic={stats.get('no_topic', 0)} "
        f"trading_blocked={stats.get('trading_blocked', 0)} "
        f"kept={stats.get('kept', len(eligible))} "
        f"via={path}"
    )


async def _scrape_eligible_pool(ctx: SequenceContext) -> list[dict]:
    """One canonical timeline scrape used by every text/comment/qrt mode.

    Strategy: scrape at the user's threshold; if too few eligible posts come
    back, do ONE retry at a softer threshold. No more 3-stage waterfall.
    """
    following = S.use_following(ctx.cfg)
    min_likes = int(ctx.cfg.get("min_engagement_likes", 100) or 100)

    ctx.log(f"Scraping timeline ({'Following' if following else 'For You'}, min_likes={min_likes})...")
    resp = await ctx.ext.send(
        "scrape_timeline",
        min_likes=min_likes, max_posts=30, scroll_count=5,
        use_following_tab=following,
    )
    posts = resp.get("data") or []
    ctx.log(f"Found {len(posts)} posts (raw).")

    eligible = build_eligible_posts(posts, ctx.enabled_topics, ctx.cfg)
    ctx.log(f"[topic-gate] {_format_gate_stats(eligible)}")
    if len(eligible) == 0 and getattr(eligible, "sample_llm_outputs", None):
        for line in eligible.sample_llm_outputs:
            ctx.log(f"  [topic-gate sample] {line}")

    if len(eligible) >= TIMELINE_MIN_ELIGIBLE:
        return eligible

    # Single softer retry. Drop the floor by the centralized divisor so the
    # behaviour is predictable instead of three escalating "specific fixes".
    soft_floor = max(10, min_likes // TIMELINE_FALLBACK_LIKES_DIVISOR)
    ctx.log(f"Thin pool — second pass at min_likes={soft_floor}...")
    resp2 = await ctx.ext.send(
        "scrape_timeline",
        min_likes=soft_floor, max_posts=40, scroll_count=6,
        use_following_tab=following,
    )
    extra = resp2.get("data") or []
    extra_eligible = build_eligible_posts(extra, ctx.enabled_topics, ctx.cfg)
    ctx.log(f"[topic-gate retry] {_format_gate_stats(extra_eligible)}")
    seen = {p.get("url") for p in eligible}
    for p in extra_eligible:
        u = p.get("url")
        if u and u not in seen:
            eligible.append(p)
            seen.add(u)
    return eligible


# --------------------------------------------------------------------------- #
#  Dev mode                                                                   #
# --------------------------------------------------------------------------- #

async def run_dev_sequence(ctx: SequenceContext) -> bool:
    if not ctx.enabled_topics:
        ctx.log("ERROR: Enable at least 1 topic in Settings.")
        return False
    if not S.active_api_key(ctx.cfg):
        ctx.log("ERROR: No API key configured.")
        return False

    ctx.format_key = S.next_format(ctx.state)
    ctx.comment_rotation = S.next_comment_rotation(ctx.state)
    ctx.seq_num = int(ctx.state.get("sequence_number", 0)) + 1
    fmt_name = FORMAT_CATALOG.get(ctx.format_key, {}).get("name", ctx.format_key)
    ctx.log(f"=== DEV SEQUENCE {ctx.seq_num} | Format: {ctx.format_key} ({fmt_name}) ===")

    pool = await _scrape_eligible_pool(ctx)
    if len(pool) < TIMELINE_MIN_ELIGIBLE:
        stats = getattr(pool, "drop_stats", None) or {}
        hints: list[str] = []
        if stats.get("trading_blocked", 0) > stats.get("kept", 0):
            hints.append("most posts were trading/price — flip 'allow_trading_price_posts' on")
        if stats.get("no_topic", 0) > stats.get("kept", 0) * 3:
            hints.append("most posts didn't match any enabled topic — broaden the topic list")
        if stats.get("raw", 0) < 5:
            hints.append("timeline scrape returned almost nothing — lower min_engagement_likes")
        hint_str = (" Hint: " + "; ".join(hints) + ".") if hints else ""
        ctx.log(
            f"ERROR: Only {len(pool)} eligible post(s) (need {TIMELINE_MIN_ELIGIBLE}).{hint_str}"
        )
        return False
    if ctx.is_cancelled():
        return False

    random.shuffle(pool)
    actions = build_dev_action_plan(ctx.cfg)
    ctx.log(f"[Plan] {summarize_plan(actions)}")

    for action in actions:
        if ctx.is_cancelled():
            return False
        await _dispatch_dev_action(ctx, action, pool)
        if ctx.is_cancelled():
            return False
        if random.random() < 0.4:
            await ctx.human.lurk_scroll(random.randint(1, 3))
        await ctx.human.organic_pause(short=random.random() < 0.5)

    ctx.state["sequence_number"] = ctx.seq_num
    ctx.state["last_format"] = ctx.format_key
    ctx.state["last_comment_rotation"] = ctx.comment_rotation
    await ctx.persist()
    ctx.log(f"=== DEV SEQUENCE {ctx.seq_num} COMPLETE ===")
    return True


async def _dispatch_dev_action(ctx: SequenceContext, action: str, pool: list[dict]) -> None:
    """Single dispatch table — keep all action wiring in one place."""
    if action == "tweet_text":
        await A.do_tweet_text(ctx)
    elif action == "tweet_rephrase":
        await A.do_tweet_rephrase(ctx, pool)
    elif action == "qrt":
        await A.do_qrt(ctx, pool)
    elif action == "rt":
        await A.do_rt(ctx, pool)
    elif action == "comment":
        await A.do_comment(ctx, pool)
    elif action == "follow":
        await A.do_follow_one(ctx, pool)
    elif action == "thread":
        await A.do_thread(ctx, pool)
    else:
        ctx.log(f"[Plan] Unknown action '{action}', skipping.")


# --------------------------------------------------------------------------- #
#  Degen mode                                                                 #
# --------------------------------------------------------------------------- #

async def run_degen_sequence(ctx: SequenceContext) -> bool:
    enabled = S.enabled_degen_topics(ctx.cfg)
    if len(enabled) < 2:
        ctx.log("ERROR: Need at least 2 degen topics.")
        return False
    if not S.active_api_key(ctx.cfg):
        ctx.log("ERROR: No API key configured.")
        return False
    ctx.enabled_topics = enabled

    format_key = S.next_degen_format(ctx.state)
    ctx.comment_rotation = S.next_comment_rotation(ctx.state)
    ctx.seq_num = int(ctx.state.get("degen_sequence_number", 0)) + 1
    fmt_name = DEGEN_FORMAT_CATALOG.get(format_key, {}).get("name", format_key)
    ctx.log(f"=== DEGEN SEQUENCE {ctx.seq_num} | Format: {format_key} ({fmt_name}) ===")

    resp = await ctx.ext.send(
        "scrape_timeline",
        min_likes=ctx.cfg.get("min_engagement_likes", 100),
        max_posts=30, scroll_count=5,
        use_following_tab=S.use_following(ctx.cfg),
    )
    posts = [p for p in (resp.get("data") or []) if not is_spam_post(p)]
    if len(posts) < TIMELINE_MIN_ELIGIBLE:
        ctx.log("ERROR: Not enough degen-eligible posts.")
        return False

    used_urls: set[str] = set(ctx.state.get("recent_source_urls") or [])
    tweet_topic = ""
    tweet_handle = ""

    # 1. Degen tweet
    if S.can_act(ctx.state, ctx.cfg, "tweets"):
        unused = [p for p in posts if p.get("url") not in used_urls]
        unused.sort(
            key=lambda p: max(p.get("likes", 0), 1) * (2.0 if p.get("image_urls") else 1.0),
            reverse=True,
        )
        tweet_post = (unused or posts)[0]
        tweet_topic = classify_topic(tweet_post["text"], enabled, DEGEN_TOPIC_KEYWORDS)
        tweet_handle = tweet_post.get("handle", "")
        ctx.log(f"[Degen Tweet] From @{tweet_handle}")

        result: GenerationResult = await asyncio.to_thread(
            generate_degen_tweet, ctx.cfg, format_key, tweet_post["text"],
            S.recent_posts(ctx.state),
        )
        if not result.text:
            ctx.log(f"[Degen Tweet] Skipped — {result.reason or 'generation failed'}.")
        elif not is_duplicate(result.text, S.recent_posts(ctx.state)):
            image_urls = await A.filter_images_with_vision(
                ctx, tweet_post.get("image_urls") or [], result.text,
            )
            try:
                await ctx.ext.send("post_tweet", text=result.text, image_urls=image_urls)
                ctx.log("[Degen Tweet] Posted.")
                used_urls.add(tweet_post.get("url", ""))
                S.record_action(ctx.state, "tweets")
                S.remember_posted_text(ctx.state, result.text)
                S.remember_source_url(ctx.state, tweet_post.get("url", ""))
                A.record_position_from_post(ctx, result.text)
                await ctx.persist()
            except Exception as e:
                ctx.log(f"[Degen Tweet] Failed: {e}")
                await ctx.ext.safe_dismiss_compose()
        else:
            ctx.log("[Degen Tweet] Skipped — duplicate.")

    if ctx.is_cancelled():
        return False
    await ctx.human.organic_pause()
    if ctx.is_cancelled():
        return False

    # 2. Degen QRT
    if S.can_act(ctx.state, ctx.cfg, "qrts"):
        qrt_candidates = [
            p for p in posts
            if p.get("url") not in used_urls and p.get("handle") != tweet_handle
        ]
        if qrt_candidates:
            qrt_post = qrt_candidates[0]
            qrt_url = qrt_post.get("url", "")
            ctx.log(f"[Degen QRT] Quoting @{qrt_post.get('handle')}")
            await ctx.human.like_and_bookmark(qrt_url)
            if not ctx.is_cancelled():
                quote: GenerationResult = await asyncio.to_thread(
                    generate_degen_quote_comment, ctx.cfg, qrt_post["text"],
                    S.recent_posts(ctx.state),
                )
                if not quote.text:
                    ctx.log(f"[Degen QRT] Skipped — {quote.reason or 'generation failed'}.")
                elif not is_duplicate(quote.text, S.recent_posts(ctx.state)):
                    try:
                        await ctx.ext.send("quote_tweet", post_url=qrt_url, text=quote.text)
                        ctx.log("[Degen QRT] Posted.")
                        used_urls.add(qrt_url)
                        S.record_action(ctx.state, "qrts")
                        S.remember_posted_text(ctx.state, quote.text)
                        S.remember_source_url(ctx.state, qrt_url)
                        await ctx.persist()
                    except Exception as e:
                        ctx.log(f"[Degen QRT] Failed: {e}")
                        await ctx.ext.safe_dismiss_compose()
                else:
                    ctx.log("[Degen QRT] Skipped — duplicate.")
        else:
            ctx.log("[Degen QRT] Skipped — no unused posts.")

    if ctx.is_cancelled():
        return False
    await ctx.human.organic_pause()
    if ctx.is_cancelled():
        return False

    # 3. Degen comments — reuse generic do_comment with the degen generator.
    comment_targets = [p for p in posts if p.get("url") not in used_urls][:random.randint(3, 5)]
    ctx.comment_idx = 0
    # Synthesize a small in-place "pool" passed to do_comment. Use ctx fields.
    ctx.used_urls = used_urls
    for i, _ in enumerate(comment_targets):
        if ctx.is_cancelled() or not S.can_act(ctx.state, ctx.cfg, "comments"):
            break
        await A.do_comment(ctx, comment_targets, gen_fn=generate_degen_reply_comment,
                           log_prefix="[Degen Comment]")
        if i < len(comment_targets) - 1:
            await ctx.human.organic_pause(short=True)

    # 4. Degen follows — keep batch behaviour; planner is dev-only.
    if not ctx.is_cancelled():
        for _ in range(random.randint(7, 8)):
            if ctx.is_cancelled() or not S.can_act(ctx.state, ctx.cfg, "follows"):
                break
            ok = await A.do_follow_one(ctx, posts)
            if not ok:
                break
            await ctx.human.organic_pause(short=True)

    ctx.state["degen_sequence_number"] = ctx.seq_num
    ctx.state["degen_last_format"] = format_key
    ctx.state["degen_last_topic"] = tweet_topic
    await ctx.persist()
    ctx.log(f"=== DEGEN SEQUENCE {ctx.seq_num} COMPLETE ===")
    return True


# --------------------------------------------------------------------------- #
#  RT farm mode                                                               #
# --------------------------------------------------------------------------- #

async def run_rt_farm_sequence(ctx: SequenceContext) -> bool:
    target = ctx.cfg.get("rt_farm_target_handle", "")
    if not target:
        ctx.log("ERROR: No RT farm target handle.")
        return False

    ctx.log(f"=== RT FARM | Cloning RTs from @{target} ===")
    try:
        resp = await ctx.ext.send(
            "scrape_retweets", handle=target,
            max_scrolls=int(ctx.cfg.get("rt_farm_max_scrolls", 50)),
        )
    except Exception as e:
        ctx.log(f"ERROR: scrape_retweets failed: {e}")
        return False

    all_urls = resp.get("data") or []
    if not all_urls:
        ctx.log("No retweets found.")
        return True

    done = set(ctx.state.get("rt_farm_completed_urls") or [])
    pending = [u for u in all_urls if u not in done]
    ctx.log(f"{len(all_urls)} total, {len(pending)} remaining.")

    base_delay = int(ctx.cfg.get("rt_farm_delay_seconds", 5))
    consecutive_failures = 0
    for i, url in enumerate(pending):
        if ctx.is_cancelled():
            return False
        rt_num = i + 1
        if rt_num > 1 and rt_num % 30 == 0:
            await ctx.human.cancellable_sleep(random.uniform(120, 300))
        elif rt_num > 1 and rt_num % 10 == 0:
            await ctx.human.cancellable_sleep(random.uniform(30, 90))

        ctx.log(f"[RT {rt_num}/{len(pending)}] {url}")
        try:
            resp = await ctx.ext.send("retweet", post_url=url)
            status = resp.get("status")
        except Exception as e:
            ctx.log(f"  Failed: {e}")
            status = None

        if status in ("ok", "already"):
            consecutive_failures = 0
            if status == "already":
                ctx.log("  Already retweeted.")
            completed = ctx.state.setdefault("rt_farm_completed_urls", [])
            if url not in completed:
                completed.append(url)
            ctx.state["rt_farm_total_retweeted"] = len(completed)
            await ctx.persist()
        else:
            consecutive_failures += 1
            if consecutive_failures >= RT_FARM_MAX_CONSECUTIVE_FAILURES:
                ctx.log(
                    f"ERROR: {RT_FARM_MAX_CONSECUTIVE_FAILURES} consecutive failures — "
                    "stopping batch. Check the extension / X session and retry."
                )
                return False
        await ctx.human.cancellable_sleep(base_delay * random.uniform(0.6, 1.4))

    ctx.log("=== RT FARM COMPLETE ===")
    return True


# --------------------------------------------------------------------------- #
#  Sniper mode                                                                #
# --------------------------------------------------------------------------- #

async def run_sniper_sequence(ctx: SequenceContext) -> bool:
    if not ctx.cfg.get("sniper_enabled", False):
        ctx.log("Sniper disabled in config (sniper_enabled=false). Skipping.")
        return False
    if not S.active_api_key(ctx.cfg):
        ctx.log("ERROR: No API key configured.")
        return False

    interval_s = int(ctx.cfg.get("sniper_scan_interval_minutes", 8)) * 60
    per_scan = int(ctx.cfg.get("sniper_replies_per_scan", 2))
    min_vel = float(ctx.cfg.get("sniper_min_velocity", 100))
    max_replies = int(ctx.cfg.get("sniper_max_replies", 80))
    ctx.enabled_topics = ctx.enabled_topics or S.enabled_topics(ctx.cfg)
    scan_num = 0

    ctx.log(f"=== SNIPER MODE | every {interval_s // 60}min ===")

    while not ctx.is_cancelled():
        await ctx.human.wait_for_active_hours()
        if ctx.is_cancelled() or not S.can_act(ctx.state, ctx.cfg, "comments"):
            break

        scan_num += 1
        ctx.log(f"[Sniper #{scan_num}] Scanning...")
        await ctx.human.lurk_scroll(random.randint(2, 4))

        try:
            resp = await ctx.ext.send(
                "scrape_timeline",
                min_likes=20, max_posts=40, scroll_count=6, sort_by="virality",
                use_following_tab=S.use_following(ctx.cfg),
            )
            posts = resp.get("data") or []
        except Exception as e:
            ctx.log(f"[Sniper #{scan_num}] Scrape failed: {e}")
            posts = []

        replied_urls = set(ctx.state.get("sniper_replied_urls") or [])
        opps = [
            p for p in posts
            if p.get("velocity", 0) >= min_vel
            and p.get("replies", 0) < max_replies
            and p.get("url") not in replied_urls
        ]
        ctx.log(f"[Sniper #{scan_num}] {len(opps)} opportunities")

        for p in opps[:per_scan]:
            if ctx.is_cancelled() or not S.can_act(ctx.state, ctx.cfg, "comments"):
                break
            ctx.log(f"  @{p.get('handle')} | vel={p.get('velocity', 0):.0f}")
            try:
                await ctx.ext.send("navigate", url=p["url"])
            except Exception as e:
                ctx.log(f"[Sniper] Navigate failed: {e}")
                continue
            await ctx.human.like_and_bookmark(p["url"])

            ptype, strategy, _ = await A.classify_post_async(ctx, p["text"])
            tone = S.tone_for(int(ctx.state.get("sniper_total_replies", 0)))
            length = random.choice(["SHORT", "MEDIUM"])
            existing_replies = await A.scrape_reply_context(ctx, p["url"])
            positions = A.positions_for(ctx, p["text"])
            image_b64 = await fetch_images_as_base64(p.get("image_urls") or [])

            text = await A.generate_with_dedup(
                ctx, generate_reply_comment, label="generate_reply",
                cfg=ctx.cfg, original_tweet=p["text"],
                length_tier=length, tone=tone,
                post_type=ptype, reply_strategy=strategy,
                existing_replies=existing_replies, positions=positions,
                enabled_topics=ctx.enabled_topics,
                image_b64_list=image_b64,
            )
            if not text:
                ctx.log("[Sniper] Skipped — content generation failed.")
                continue
            try:
                await ctx.ext.send("post_comment", post_url=p["url"], text=text)
            except Exception as e:
                ctx.log(f"[Sniper] Comment failed: {e}")
                await ctx.ext.safe_dismiss_compose()
                continue
            S.record_action(ctx.state, "comments")
            S.remember_posted_text(ctx.state, text)
            replied = ctx.state.setdefault("sniper_replied_urls", [])
            replied.append(p["url"])
            ctx.state["sniper_replied_urls"] = replied[-SNIPER_REPLIED_CAP:]
            ctx.state["sniper_total_replies"] = int(ctx.state.get("sniper_total_replies", 0)) + 1
            await ctx.persist()
            await ctx.human.organic_pause(short=True)

        if ctx.is_cancelled():
            break
        jitter = int(interval_s * random.uniform(0.8, 1.2))
        ctx.log(f"[Sniper] Next scan in {jitter // 60}m...")
        await ctx.human.cancellable_sleep(jitter)

    ctx.log(f"=== SNIPER STOPPED | {ctx.state.get('sniper_total_replies', 0)} total ===")
    return True
