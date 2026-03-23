"""
Single place for timeline post eligibility (dev farming).

Spam → trading policy (optional) → per-post category via LLM (or keyword fallback).
Categories are chosen by the model from the user's enabled topic list, not heuristics.
"""

from __future__ import annotations

import logging
from typing import Any

from app.content.topics import TOPIC_KEYWORDS, classify_topic_scored

logger = logging.getLogger(__name__)

SPAM_SUBSTRINGS = [
    "launching soon", "pre-order", "use code", "discount code", "promo code",
    "giveaway", "giving away", "drop your wallet", "airdrop claim",
    "link in bio", "sign up now", "limited time", "act fast", "don't miss",
    "sponsored", "ad ", "#ad ", "partnership with", "collab with",
    "onlyfans", "subscribe to my", "join my telegram",
    "retweet to win", "follow and rt", "like and retweet", "tag a friend",
]


def is_spam_post(post: dict[str, Any]) -> bool:
    text = (post.get("text") or "").lower()
    return any(s in text for s in SPAM_SUBSTRINGS)


_TRADING_PRICE_HINTS = (
    "$btc", "$eth", "$sol", "$bnb", "bullish", "bearish", "pump", "dump",
    "support level", "resistance", "price target", "chart looks", "candle",
    "rsi ", "macd", "longed", "shorted", "liquidat", "perp", "futures",
    "ath ", "atl ", "breakout", "rekt", "ngmi", "wagmi", "lfg ",
)


def _looks_like_trading_or_price_post(text: str) -> bool:
    if not text:
        return False
    t = text.lower()
    return any(p in t for p in _TRADING_PRICE_HINTS)


def should_exclude_trading_price(text: str, cfg: dict[str, Any]) -> bool:
    """True = drop this post in non-degen modes when user did not opt in to trading CT."""
    if cfg.get("farming_mode") == "degen":
        return False
    if cfg.get("allow_trading_price_posts"):
        return False
    return _looks_like_trading_or_price_post(text)


def build_eligible_posts(
    posts: list[dict[str, Any]],
    enabled: list[str],
    cfg: dict[str, Any],
    *,
    keyword_map: dict[str, list[str]] | None = None,
    min_topic_score: int = 1,
) -> list[dict[str, Any]]:
    """
    Single gate: spam → trading policy → per-post LLM category (or keyword fallback).

    With use_llm_classification (default), the LLM analyzes each candidate post and
    assigns at most one enabled topic, or none. No separate political keyword layer.
    """
    # --- fast pre-filters (promo spam + optional trading CT; category = LLM) ---
    candidates: list[dict[str, Any]] = []
    for p in posts:
        if is_spam_post(p):
            continue
        text = p.get("text") or ""
        if should_exclude_trading_price(text, cfg):
            continue
        candidates.append(p)

    if not candidates:
        return []

    # --- topic classification ---
    use_llm = cfg.get("use_llm_classification", True)
    llm_result: dict[str, str] | None = None

    if use_llm:
        try:
            from app.content.generator import batch_classify_topics
            llm_result = batch_classify_topics(cfg, candidates, enabled)
        except Exception as exc:
            logger.warning("[engagement_gate] LLM batch classify failed, falling back to keywords: %s", exc)
            llm_result = None

    if llm_result is not None and use_llm:
        logger.info("[engagement_gate] LLM classified %d/%d posts as on-topic", len(llm_result), len(candidates))
        out: list[dict[str, Any]] = []
        for p in candidates:
            url = p.get("url", "")
            topic = llm_result.get(url)
            if topic:
                row = dict(p)
                row["_topic"] = topic
                row["_topic_score"] = 1
                out.append(row)
        return out

    # --- keyword fallback ---
    logger.info("[engagement_gate] Using keyword classification (LLM off or unavailable)")
    km = keyword_map or TOPIC_KEYWORDS
    out = []
    for p in candidates:
        text = p.get("text") or ""
        topic, score = classify_topic_scored(text, enabled, km)
        if score < min_topic_score or not topic:
            continue
        row = dict(p)
        row["_topic"] = topic
        row["_topic_score"] = score
        out.append(row)
    return out
