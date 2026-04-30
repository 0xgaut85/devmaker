"""Per-action handlers shared by the dev / degen modes.

Each ``do_*`` coroutine runs ONE atomic step (one tweet, one comment, one
follow). They share state through :class:`SequenceContext`, which the mode
runners build once per sequence.

A handler is *responsible* for:
1. Re-checking its own daily cap (the planner already does so once but caps
   can be hit mid-sequence by a thread eating tweet quota).
2. Mutating ``ctx.used_urls``/``ctx.used_handles`` only AFTER a successful
   post is verified by the extension.
3. Calling ``ctx.persist()`` so the scheduler can flush state on the next
   safe boundary.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from app.content.engagement_gate import is_spam_post
from app.content.generator import (
    GenerationResult, ThreadResult,
    check_image_relevance_with_vision, classify_post_with_llm,
    extract_position, generate_quote_comment, generate_reply_comment,
    generate_thread, generate_tweet,
)
from app.content.images import fetch_images_as_base64
from app.content.position_memory import get_relevant_positions
from app.content.rules import LENGTH_FOR_FORMAT, classify_post_type
from app.content.validator import has_repeated_opener, is_duplicate
from app.engine import state as S
from app.engine.constants import MAX_GEN_RETRIES
from app.engine.ext import ExtensionClient
from app.engine.human import HumanSim


# --------------------------------------------------------------------------- #
#  Context                                                                    #
# --------------------------------------------------------------------------- #

@dataclass
class SequenceContext:
    """Everything an action handler needs, packaged once per sequence."""
    account_id: str
    cfg: dict
    state: dict
    log: Callable[[str], None]
    ext: ExtensionClient
    human: HumanSim
    is_cancelled: Callable[[], bool]
    persist: Callable[[], Awaitable[None]]

    enabled_topics: list[str] = field(default_factory=list)
    seq_num: int = 0
    format_key: str = ""
    comment_rotation: list[str] = field(default_factory=list)
    comment_idx: int = 0

    used_urls: set[str] = field(default_factory=set)
    used_handles: set[str] = field(default_factory=set)

    # Cached "Who to follow" handles, populated lazily on first follow action
    # so multiple do_follow_one calls in one sequence don't re-scrape.
    # ``None`` = not fetched yet, ``[]`` = fetched but empty.
    wtf_cache: list[str] | None = None


# --------------------------------------------------------------------------- #
#  Generic helpers used by handlers                                           #
# --------------------------------------------------------------------------- #

async def generate_with_dedup(
    ctx: SequenceContext,
    gen_fn,
    label: str,
    **kwargs,
) -> str | None:
    """Wrap a ``generate_*`` call so we retry on near-duplicate output.

    Two checks per attempt:
    - :func:`is_duplicate` – Jaccard word overlap, catches "same idea, slightly
      reworded" repeats.
    - :func:`has_repeated_opener` – literal first-word fingerprint, catches the
      "4 'Hot take:' tweets in a row" failure mode where the body differs but
      the opener is identical and the LLM has fallen into a stylistic rut.

    All generators return :class:`GenerationResult`, so we get a clean
    rejection ``reason`` without any global mutable state.
    """
    recent = S.recent_posts(ctx.state)
    kwargs["recent_posts"] = recent
    for attempt in range(MAX_GEN_RETRIES):
        if ctx.is_cancelled():
            return None
        result: GenerationResult = await asyncio.to_thread(gen_fn, **kwargs)
        if not result.text:
            ctx.log(f"  [Gen] {label} failed: {result.reason or 'no reason recorded'}")
            return None
        if is_duplicate(result.text, recent):
            ctx.log(f"  [Dedup] Attempt {attempt + 1}: too similar to recent post, regenerating...")
            continue
        if has_repeated_opener(result.text, recent):
            ctx.log(
                f"  [Dedup] Attempt {attempt + 1}: same opener as a recent post "
                "('{}'...), regenerating...".format(result.text[:40].replace("\n", " "))
            )
            continue
        return result.text
    ctx.log("  [Dedup] All attempts rejected. Skipping.")
    return None


async def filter_images_with_vision(ctx: SequenceContext, image_urls: list[str],
                                    generated_text: str) -> list[str]:
    """If vision check is on, drop images the model says are off-topic.

    ``fetch_images_as_base64`` returns ``[(b64, mime), ...]`` pairs; the previous
    naive ``zip`` here unpacked them as ``url, b64`` so ``b64`` was actually the
    mime string. Every image then failed the relevance check and rephrased
    tweets posted text-only. Unpack correctly.
    """
    if not image_urls or not ctx.cfg.get("use_vision_image_check"):
        return image_urls
    try:
        b64_list = await fetch_images_as_base64(image_urls)
    except Exception:
        return []
    kept: list[str] = []
    for url, pair in zip(image_urls, b64_list):
        b64 = pair[0] if pair else ""
        if not b64:
            continue
        try:
            ok = await asyncio.to_thread(
                check_image_relevance_with_vision, ctx.cfg, b64, generated_text,
            )
        except Exception:
            ok = False
        if ok:
            kept.append(url)
    if len(kept) < len(image_urls):
        ctx.log(f"  [Vision] Kept {len(kept)}/{len(image_urls)} images after relevance check.")
    return kept


async def classify_post_async(ctx: SequenceContext, text: str) -> tuple[str, str, str]:
    if ctx.cfg.get("use_llm_classification"):
        result = await asyncio.to_thread(classify_post_with_llm, ctx.cfg, text)
        if result:
            return (
                result.get("type", "general"),
                result.get("reply_strategy", ""),
                result.get("tone", ""),
            )
    ptype, strategy = classify_post_type(text)
    return ptype, strategy, ""


def positions_for(ctx: SequenceContext, post_text: str) -> list[dict]:
    if not ctx.cfg.get("position_memory_enabled"):
        return []
    return get_relevant_positions(ctx.state.get("position_history", []), post_text)


def record_position_from_post(ctx: SequenceContext, posted_text: str) -> None:
    if not ctx.cfg.get("position_memory_enabled"):
        return
    result = extract_position(ctx.cfg, posted_text)
    if result and result.get("topic") and result.get("stance"):
        S.record_position_in_state(ctx.state, result["topic"], result["stance"])


async def scrape_reply_context(ctx: SequenceContext, post_url: str) -> list[str]:
    try:
        resp = await ctx.ext.send("scrape_replies", post_url=post_url, max_replies=6)
        replies = resp.get("data", []) or []
        if replies:
            ctx.log(f"  [Context] Got {len(replies)} replies for vibe check.")
        return replies
    except Exception:
        return []


# --------------------------------------------------------------------------- #
#  Pool helpers                                                               #
# --------------------------------------------------------------------------- #

# Probability of allowing a post by an already-used handle. Kept tiny so the
# bot doesn't spam the same creator.
HANDLE_BYPASS_PROB = 0.10


def available_posts(pool: list[dict], ctx: SequenceContext, *,
                    skip_handles: bool = True) -> list[dict]:
    out: list[dict] = []
    for p in pool:
        if p.get("url") in ctx.used_urls:
            continue
        if skip_handles and p.get("handle") in ctx.used_handles \
                and random.random() > HANDLE_BYPASS_PROB:
            continue
        out.append(p)
    return out


_PICK_TOP_K = 3


def pick_post(pool: list[dict], target_topic: str = "",
              exclude_handles: list[str] | None = None) -> dict | None:
    """Pick a high-engagement on-topic post from ``pool``.

    Pool is already topic-gated by :func:`build_eligible_posts` so we trust
    ``_topic`` and never re-classify. We randomize among the top-K by likes so
    sequential calls in the same sequence don't deterministically grab the
    same post each time.
    """
    exclude_handles = exclude_handles or []
    candidates = [p for p in pool if p.get("handle") not in exclude_handles]
    if target_topic:
        on_topic = [p for p in candidates if p.get("_topic") == target_topic]
        if on_topic:
            candidates = on_topic
    if not candidates:
        return None
    candidates.sort(key=lambda p: max(p.get("likes", 0), 1), reverse=True)
    return random.choice(candidates[:_PICK_TOP_K])


def _select_source(ctx: SequenceContext, pool: list[dict],
                   topic: str = "") -> tuple[dict | None, str]:
    """Pick a source post from ``pool`` for an action.

    Strategy: strict pass first (skip already-used URLs and used handles); if
    that comes up empty, retry without the handle filter. A user with
    ``seq_qrt=1`` would rather see the same creator twice in a sequence than
    have their one QRT skipped because the comments ate every handle first.

    Returns ``(post, reason)`` — when ``post`` is ``None``, ``reason`` is a
    compact diagnostic string for the caller's skip log.
    """
    pool_n = len(pool)
    used_urls_n = len(ctx.used_urls)
    used_handles_n = len(ctx.used_handles)

    strict = available_posts(pool, ctx, skip_handles=True)
    chosen = pick_post(strict, topic, exclude_handles=list(ctx.used_handles))
    if chosen is None and strict:
        chosen = strict[0]
    if chosen is not None:
        return chosen, ""

    relaxed = available_posts(pool, ctx, skip_handles=False)
    chosen = pick_post(relaxed, topic, exclude_handles=[])
    if chosen is None and relaxed:
        chosen = relaxed[0]
    if chosen is not None:
        ctx.log(
            f"  [Pool] Strict pass empty (used_handles={used_handles_n}); "
            "reusing a handle so this slot doesn't go to waste."
        )
        return chosen, ""

    return None, f"pool={pool_n}, used_urls={used_urls_n}, used_handles={used_handles_n}"


def filter_clean(posts: list[dict]) -> list[dict]:
    return [p for p in posts if not is_spam_post(p)]


# --------------------------------------------------------------------------- #
#  Action handlers                                                            #
# --------------------------------------------------------------------------- #

def _truncate(s: str, n: int = 80) -> str:
    return (s[:n] + "...") if len(s) > n else s


async def do_tweet_text(ctx: SequenceContext) -> bool:
    """Original from-scratch tweet. No source post, no media."""
    if not S.can_act(ctx.state, ctx.cfg, "tweets"):
        ctx.log("[TweetText] Skipped — daily tweets cap reached.")
        return False
    topic = S.next_topic(ctx.cfg, ctx.state, ctx.enabled_topics)
    length_tier = LENGTH_FOR_FORMAT.get(ctx.format_key, "MEDIUM")
    structure = S.pick_diverse_structure(
        ctx.state, format_key=ctx.format_key, length_tier=length_tier,
    )
    ctx.log(f"[TweetText] Original post on topic={topic} | structure={structure}")
    text = await generate_with_dedup(
        ctx, generate_tweet, label="generate_tweet",
        cfg=ctx.cfg, format_key=ctx.format_key,
        original_tweet=topic,
        length_tier=length_tier,
        enabled_topics=ctx.enabled_topics,
        structure_name=structure,
    )
    if not text or ctx.is_cancelled():
        return False
    ctx.log(f"[TweetText] Generated ({len(text)} chars): {_truncate(text)}")
    try:
        await ctx.ext.send("post_tweet", text=text, image_urls=[])
    except Exception as e:
        ctx.log(f"[TweetText] Failed: {e}")
        await ctx.ext.safe_dismiss_compose()
        return False
    ctx.log("[TweetText] Posted.")
    S.record_action(ctx.state, "tweets")
    S.remember_posted_text(ctx.state, text)
    record_position_from_post(ctx, text)
    ctx.state["last_topic_tweet"] = topic
    await ctx.persist()
    return True


async def do_tweet_rephrase(ctx: SequenceContext, pool: list[dict]) -> bool:
    if not S.can_act(ctx.state, ctx.cfg, "tweets"):
        ctx.log("[TweetRephrase] Skipped — daily tweets cap reached.")
        return False
    topic = S.next_topic(ctx.cfg, ctx.state, ctx.enabled_topics)
    src, reason = _select_source(ctx, pool, topic)
    if src is None:
        ctx.log(f"[TweetRephrase] Skipped — no usable post ({reason}).")
        return False
    src_url, src_handle = src.get("url", ""), src.get("handle", "")
    actual_topic = src.get("_topic", topic)
    length_tier = LENGTH_FOR_FORMAT.get(ctx.format_key, "MEDIUM")
    structure = S.pick_diverse_structure(
        ctx.state, format_key=ctx.format_key, length_tier=length_tier,
    )
    ctx.log(
        f"[TweetRephrase] From @{src_handle} ({src.get('likes', 0)} likes) "
        f"| topic={actual_topic} | structure={structure}"
    )
    text = await generate_with_dedup(
        ctx, generate_tweet, label="generate_tweet",
        cfg=ctx.cfg, format_key=ctx.format_key,
        original_tweet=src["text"],
        length_tier=length_tier,
        enabled_topics=ctx.enabled_topics,
        structure_name=structure,
    )
    if not text or ctx.is_cancelled():
        return False
    ctx.log(f"[TweetRephrase] Generated ({len(text)} chars): {_truncate(text)}")
    image_urls = await filter_images_with_vision(ctx, src.get("image_urls") or [], text)
    try:
        await ctx.ext.send("post_tweet", text=text, image_urls=image_urls)
    except Exception as e:
        ctx.log(f"[TweetRephrase] Failed: {e}")
        await ctx.ext.safe_dismiss_compose()
        return False
    ctx.log("[TweetRephrase] Posted.")
    ctx.used_urls.add(src_url)
    if src_handle:
        ctx.used_handles.add(src_handle)
    S.record_action(ctx.state, "tweets")
    S.remember_posted_text(ctx.state, text)
    S.remember_source_url(ctx.state, src_url)
    record_position_from_post(ctx, text)
    ctx.state["last_topic_tweet"] = actual_topic
    await ctx.persist()
    return True


async def do_tweet_media(ctx: SequenceContext, pool: list[dict]) -> bool:
    """Original tweet that REQUIRES attaching media from a high-engagement
    source post.

    Distinct from :func:`do_tweet_rephrase`, which uses media when the chosen
    source happens to have it. This handler hard-filters the pool to posts
    with images first; if nothing qualifies it skips with a clear log instead
    of silently posting text-only.

    The vision-relevance check is INTENTIONALLY skipped here. The user opted
    into media tweets via ``seq_media_tweets > 0``; the source is already
    high-engagement (so the image is solid content); and we picked a topic
    match before generating. Adding a strict vision filter on top kept
    rejecting valid images and we'd burn the LLM call only to skip-text-only.
    """
    if not S.can_act(ctx.state, ctx.cfg, "tweets"):
        ctx.log("[TweetMedia] Skipped — daily tweets cap reached.")
        return False
    media_pool = [p for p in pool if (p.get("image_urls") or [])]
    if not media_pool:
        ctx.log(
            f"[TweetMedia] Skipped — no eligible source has media "
            f"(pool={len(pool)}, with_images=0)."
        )
        return False
    topic = S.next_topic(ctx.cfg, ctx.state, ctx.enabled_topics)
    src, reason = _select_source(ctx, media_pool, topic)
    if src is None:
        ctx.log(f"[TweetMedia] Skipped — no usable media post ({reason}).")
        return False
    src_url, src_handle = src.get("url", ""), src.get("handle", "")
    actual_topic = src.get("_topic", topic)
    length_tier = LENGTH_FOR_FORMAT.get(ctx.format_key, "MEDIUM")
    structure = S.pick_diverse_structure(
        ctx.state, format_key=ctx.format_key, length_tier=length_tier,
    )
    ctx.log(
        f"[TweetMedia] From @{src_handle} ({src.get('likes', 0)} likes) "
        f"| topic={actual_topic} | imgs={len(src.get('image_urls') or [])} "
        f"| structure={structure}"
    )
    text = await generate_with_dedup(
        ctx, generate_tweet, label="generate_tweet",
        cfg=ctx.cfg, format_key=ctx.format_key,
        original_tweet=src["text"],
        length_tier=length_tier,
        enabled_topics=ctx.enabled_topics,
        structure_name=structure,
    )
    if not text or ctx.is_cancelled():
        return False
    ctx.log(f"[TweetMedia] Generated ({len(text)} chars): {_truncate(text)}")
    # Skip vision relevance check (see docstring). Use source images as-is.
    image_urls = src.get("image_urls") or []
    try:
        await ctx.ext.send("post_tweet", text=text, image_urls=image_urls)
    except Exception as e:
        ctx.log(f"[TweetMedia] Failed: {e}")
        await ctx.ext.safe_dismiss_compose()
        return False
    ctx.log(f"[TweetMedia] Posted with {len(image_urls)} image(s).")
    ctx.used_urls.add(src_url)
    if src_handle:
        ctx.used_handles.add(src_handle)
    S.record_action(ctx.state, "tweets")
    S.remember_posted_text(ctx.state, text)
    S.remember_source_url(ctx.state, src_url)
    record_position_from_post(ctx, text)
    ctx.state["last_topic_tweet"] = actual_topic
    await ctx.persist()
    return True


async def do_qrt(ctx: SequenceContext, pool: list[dict]) -> bool:
    if not S.can_act(ctx.state, ctx.cfg, "qrts"):
        ctx.log("[QRT] Skipped — daily qrts cap reached.")
        return False
    topic = S.next_topic(ctx.cfg, ctx.state, ctx.enabled_topics)
    src, reason = _select_source(ctx, pool, topic)
    if src is None:
        ctx.log(f"[QRT] Skipped — no usable post ({reason}).")
        return False
    src_url, src_handle = src.get("url", ""), src.get("handle", "")
    # Quote comments are 1-3 sentences, so the picker is bounded to SHORT-tier
    # structures. Still rotates so we don't ship 4 single-line QRTs in a row.
    structure = S.pick_diverse_structure(ctx.state, length_tier="SHORT")
    ctx.log(f"[QRT] Quoting @{src_handle} | structure={structure}")
    await ctx.human.like_and_bookmark(src_url)
    if ctx.is_cancelled():
        return False
    image_b64 = await fetch_images_as_base64(src.get("image_urls") or [])
    text = await generate_with_dedup(
        ctx, generate_quote_comment, label="generate_quote",
        cfg=ctx.cfg, original_tweet=src["text"],
        enabled_topics=ctx.enabled_topics, image_b64_list=image_b64,
        structure_name=structure,
    )
    if not text or ctx.is_cancelled():
        return False
    try:
        await ctx.ext.send("quote_tweet", post_url=src_url, text=text)
    except Exception as e:
        ctx.log(f"[QRT] Failed: {e}")
        await ctx.ext.safe_dismiss_compose()
        return False
    ctx.log(f"[QRT] Posted: {_truncate(text, 60)}")
    ctx.used_urls.add(src_url)
    if src_handle:
        ctx.used_handles.add(src_handle)
    S.record_action(ctx.state, "qrts")
    S.remember_posted_text(ctx.state, text)
    S.remember_source_url(ctx.state, src_url)
    record_position_from_post(ctx, text)
    ctx.state["last_topic_qrt"] = src.get("_topic", "")
    await ctx.persist()
    return True


async def do_rt(ctx: SequenceContext, pool: list[dict]) -> bool:
    if not S.can_act(ctx.state, ctx.cfg, "rts"):
        ctx.log("[RT] Skipped — daily rts cap reached.")
        return False
    topic = S.next_topic(ctx.cfg, ctx.state, ctx.enabled_topics)
    src, reason = _select_source(ctx, pool, topic)
    if src is None:
        ctx.log(f"[RT] Skipped — no usable post ({reason}).")
        return False
    src_url, src_handle = src.get("url", ""), src.get("handle", "")
    ctx.log(f"[RT] Reposting @{src_handle}")
    try:
        resp = await ctx.ext.send("retweet", post_url=src_url)
    except Exception as e:
        ctx.log(f"[RT] Failed: {e}")
        return False
    status = resp.get("status")
    if status not in ("ok", "already"):
        ctx.log(f"[RT] Skipped: {resp.get('error', status or 'unknown')}")
        return False
    ctx.log("[RT] Done." if status == "ok" else "[RT] Already retweeted — marking source used.")
    ctx.used_urls.add(src_url)
    if src_handle:
        ctx.used_handles.add(src_handle)
    if status == "ok":
        S.record_action(ctx.state, "rts")
    S.remember_source_url(ctx.state, src_url)
    ctx.state["last_topic_rt"] = src.get("_topic", "")
    await ctx.persist()
    return True


async def do_comment(ctx: SequenceContext, pool: list[dict],
                     gen_fn=None, log_prefix: str = "[Comment]") -> bool:
    # Resolve at call-time so tests can patch the module attribute, and so a
    # future degen / sniper variant can swap the generator with one line.
    if gen_fn is None:
        gen_fn = generate_reply_comment
    if not S.can_act(ctx.state, ctx.cfg, "comments"):
        ctx.log(f"{log_prefix} Skipped — daily comments cap reached.")
        return False
    src, reason = _select_source(ctx, pool)
    if src is None:
        ctx.log(f"{log_prefix} Skipped — no usable post ({reason}).")
        return False
    src_url, src_handle = src.get("url", ""), src.get("handle", "")
    rotation = ctx.comment_rotation or ["MEDIUM"]
    length = rotation[ctx.comment_idx] if ctx.comment_idx < len(rotation) else "MEDIUM"
    tone = S.tone_for(ctx.comment_idx + ctx.seq_num)
    ptype, strategy, _ = await classify_post_async(ctx, src["text"])
    structure = S.pick_diverse_structure(ctx.state, length_tier=length)
    ctx.log(f"{log_prefix} @{src_handle} | {length} | {tone} | structure={structure}")
    await ctx.human.like_and_bookmark(src_url)
    if ctx.is_cancelled():
        return False
    existing_replies = await scrape_reply_context(ctx, src_url)
    positions = positions_for(ctx, src["text"])
    image_b64 = await fetch_images_as_base64(src.get("image_urls") or [])
    text = await generate_with_dedup(
        ctx, gen_fn, label="generate_reply",
        cfg=ctx.cfg, original_tweet=src["text"],
        length_tier=length, tone=tone,
        post_type=ptype, reply_strategy=strategy,
        existing_replies=existing_replies, positions=positions,
        enabled_topics=ctx.enabled_topics,
        image_b64_list=image_b64,
        structure_name=structure,
    )
    ctx.comment_idx += 1
    if not text or ctx.is_cancelled():
        return False
    try:
        await ctx.ext.send("post_comment", post_url=src_url, text=text)
    except Exception as e:
        ctx.log(f"{log_prefix} Failed: {e}")
        await ctx.ext.safe_dismiss_compose()
        return False
    ctx.log(f"  -> Posted.")
    ctx.used_urls.add(src_url)
    if src_handle:
        ctx.used_handles.add(src_handle)
    S.record_action(ctx.state, "comments")
    S.remember_posted_text(ctx.state, text)
    S.remember_source_url(ctx.state, src_url)
    record_position_from_post(ctx, text)
    await ctx.persist()
    return True


async def do_thread(ctx: SequenceContext, pool: list[dict] | None = None) -> bool:
    if not S.can_act(ctx.state, ctx.cfg, "tweets"):
        ctx.log("[Thread] Skipped — daily tweets cap reached.")
        return False
    # Pre-flight cap check. A thread is at least 2 tweets, so if we don't have
    # room for 2 we must skip BEFORE burning an LLM call we'd just throw away.
    caps = S.daily_caps_for(ctx.cfg)
    counts = S.today_counts(ctx.state)
    remaining = caps["tweets"] - counts.get("tweets", 0)
    if remaining < 2:
        ctx.log(f"[Thread] Skipped — only {remaining} tweet(s) left under cap; thread needs >=2.")
        return False
    src_post: dict | None = None
    if pool is not None:
        src_post, reason = _select_source(ctx, pool)
        if src_post is None:
            ctx.log(f"[Thread] Skipped — no usable post ({reason}).")
            return False
    src_handle = src_post.get("handle", "") if src_post else ""
    src_text = src_post.get("text", "") if src_post else ""
    thread_format = S.next_thread_format(ctx.state)
    ctx.log("[Thread] Generating thread...")
    recent = S.recent_posts(ctx.state)
    result: ThreadResult = await asyncio.to_thread(
        generate_thread,
        cfg=ctx.cfg, thread_format_key=thread_format,
        original_tweet=src_text, recent_posts=recent,
        enabled_topics=ctx.enabled_topics,
    )
    if not result.tweets:
        ctx.log(f"[Thread] Skipped — generation failed: {result.reason}")
        return False
    if is_duplicate(result.tweets[0], recent):
        ctx.log("[Thread] Skipped — hook too similar to recent posts.")
        return False
    if ctx.is_cancelled():
        return False
    # Re-check post-generation: a long thread might still exceed remaining cap.
    if remaining < len(result.tweets):
        ctx.log(
            f"[Thread] Skipped — only {remaining} tweet(s) left under cap, "
            f"thread needs {len(result.tweets)}."
        )
        return False
    try:
        await ctx.ext.send("post_thread", tweets=result.tweets)
    except Exception as e:
        ctx.log(f"[Thread] Failed: {e}")
        await ctx.ext.safe_dismiss_compose()
        return False
    ctx.log(f"[Thread] Posted {len(result.tweets)}-tweet thread.")
    if src_handle:
        ctx.used_handles.add(src_handle)
    for _ in result.tweets:
        S.record_action(ctx.state, "tweets")
    ctx.state["thread_last_format"] = thread_format
    for t in result.tweets:
        S.remember_posted_text(ctx.state, t)
    await ctx.persist()
    return True


async def do_follow_one(ctx: SequenceContext, pool: list[dict]) -> bool:
    """Follow ONE candidate (the planner schedules N follows, one per call)."""
    if not S.can_act(ctx.state, ctx.cfg, "follows"):
        return False
    last_follows = list(ctx.state.get("last_follows") or [])

    if ctx.wtf_cache is None:
        try:
            resp = await ctx.ext.send("scrape_who_to_follow")
            ctx.wtf_cache = resp.get("data") or []
        except Exception:
            ctx.wtf_cache = []
    wtf = ctx.wtf_cache

    timeline_handles = [
        h for h in {p.get("handle") for p in pool}
        if h and h not in last_follows
    ]
    random.shuffle(timeline_handles)

    seen: set[str] = set()
    candidates: list[str] = []
    for h in (*wtf, *timeline_handles):
        if h and h not in last_follows and h not in seen:
            candidates.append(h)
            seen.add(h)

    for handle in candidates:
        if ctx.is_cancelled():
            return False
        try:
            resp = await ctx.ext.send("follow_user", handle=handle)
        except ConnectionError as e:
            ctx.log(f"[Follow] Aborting — extension still disconnected: {e}")
            return False
        except Exception as e:
            ctx.log(f"[Follow] Error following @{handle}: {e}")
            await ctx.human.organic_pause(short=True)
            continue
        if resp.get("status") != "ok":
            ctx.log(f"[Follow] Skipped @{handle}: {resp.get('error', resp.get('status', 'unknown'))}")
            await ctx.human.organic_pause(short=True)
            continue
        S.record_action(ctx.state, "follows")
        S.remember_follow(ctx.state, handle)
        ctx.log(f"[Follow] Followed @{handle}.")
        await ctx.persist()
        return True
    ctx.log("[Follow] No new candidates available.")
    return False
