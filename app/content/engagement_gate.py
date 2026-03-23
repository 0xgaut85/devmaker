"""
Single place for timeline post eligibility (dev farming).

Topic match + minimal spam + optional trading exclusion — not duplicated in the action loop.
"""

from __future__ import annotations

from typing import Any

from app.content.topics import TOPIC_KEYWORDS, classify_topic_scored

# Obvious promo / scam — not politics keyword lists
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
    Filter scraped posts once: spam, topic match score, trading policy.
    Each returned dict is a shallow copy with _topic and _topic_score set.
    """
    km = keyword_map or TOPIC_KEYWORDS
    out: list[dict[str, Any]] = []
    for p in posts:
        if is_spam_post(p):
            continue
        text = p.get("text") or ""
        if should_exclude_trading_price(text, cfg):
            continue
        topic, score = classify_topic_scored(text, enabled, km)
        if score < min_topic_score or not topic:
            continue
        row = dict(p)
        row["_topic"] = topic
        row["_topic_score"] = score
        out.append(row)
    return out
