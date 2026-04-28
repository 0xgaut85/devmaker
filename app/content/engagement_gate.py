"""
Single place for timeline post eligibility (dev farming).

Pipeline:
  raw posts
    -> drop spam (hard filter, always)
    -> classify topic + trading flag via LLM (or keyword fallback)
    -> drop posts whose topic is null
    -> drop trading/price posts unless allow_trading_price_posts=True

Per-stage drop counts are stamped on the returned list as ``out._drop_stats``
so the caller can surface diagnostics when the gate empties.
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

# Keyword skip used by the keyword fallback path so it mirrors the LLM
# political-content rule. Deliberately short and unambiguous to avoid false
# positives.
_POLITICAL_SKIP_HINTS = (
    "election", "elections", "ballot", "vote ", " votes",
    "president", "presidential", "white house", "congress",
    "senate", "parliament", "prime minister", "chancellor",
    "republican", "democrat", "gop ", "leftist", "rightist",
    "trump", "biden", "harris", "putin", "xi jinping",
    "war ", "ceasefire", "airstrike", "invasion", "occupation",
    "geopolit", "diplomatic", "sanction", "regime",
    "israel", "gaza", "palestin", "ukraine", "russia",
    "iran", "houthi", "hezbollah", "hamas",
)


def _looks_political(text: str) -> bool:
    if not text:
        return False
    t = text.lower()
    return any(h in t for h in _POLITICAL_SKIP_HINTS)


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


def _user_allows_trading(cfg: dict[str, Any]) -> bool:
    """Trading/price posts are first-class in degen mode and opt-in elsewhere."""
    if cfg.get("farming_mode") == "degen":
        return True
    return bool(cfg.get("allow_trading_price_posts"))


class EligiblePosts(list):
    """List subclass that also carries per-stage drop counts for diagnostics."""

    drop_stats: dict[str, int]
    sample_llm_outputs: list[str]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.drop_stats = {}
        self.sample_llm_outputs = []


def build_eligible_posts(
    posts: list[dict[str, Any]],
    enabled: list[str],
    cfg: dict[str, Any],
    *,
    keyword_map: dict[str, list[str]] | None = None,
    min_topic_score: int = 2,
) -> EligiblePosts:
    """Filter the timeline pool down to engageable posts.

    Order matters: spam is dropped first (cheap and never wanted), then the
    LLM (or keyword) classifier picks one of the user's enabled topics, then
    trading/price posts are dropped unless the user opted in. Doing trading
    AFTER classification lets the LLM make the call, so e.g. a thoughtful
    market-structure piece tagged 'Crypto' still passes when 'Crypto' is an
    enabled topic but allow_trading_price_posts is off.
    """
    out = EligiblePosts()
    out.drop_stats = {
        "raw": len(posts),
        "spam": 0,
        "no_topic": 0,
        "trading_blocked": 0,
        "kept": 0,
    }

    after_spam: list[dict[str, Any]] = []
    for p in posts:
        if is_spam_post(p):
            out.drop_stats["spam"] += 1
            continue
        after_spam.append(p)

    if not after_spam:
        return out

    use_llm = cfg.get("use_llm_classification", True)
    classified: dict[str, dict[str, Any]] = {}
    classify_path = "keyword"

    if use_llm:
        try:
            from app.content.generator import batch_classify_topics
            llm_result = batch_classify_topics(cfg, after_spam, enabled)
        except Exception as exc:
            logger.warning("[engagement_gate] LLM batch classify failed, falling back to keywords: %s", exc)
            llm_result = {}
        if llm_result:
            classify_path = "llm"
            classified = {url: dict(meta) for url, meta in llm_result.items()}
            out.sample_llm_outputs = [
                f"@{p.get('handle','?')}: {classified.get(p.get('url','')) or 'null'}"
                for p in after_spam[:5]
            ]
        else:
            logger.info("[engagement_gate] LLM returned 0 matches, falling back to keywords")

    if not classified:
        # Keyword fallback path. Mirrors the LLM political rule so user gets the
        # same exclusion behaviour either way.
        km = keyword_map or TOPIC_KEYWORDS
        skip_political = bool(cfg.get("exclude_political_timeline", True))
        for p in after_spam:
            text = p.get("text") or ""
            if skip_political and _looks_political(text):
                continue
            topic, score = classify_topic_scored(text, enabled, km)
            if score < min_topic_score or not topic:
                continue
            classified[p.get("url", f"_idx_{id(p)}")] = {
                "topic": topic,
                "trading": _looks_like_trading_or_price_post(text),
                "score": score,
            }

    allow_trading = _user_allows_trading(cfg)
    for p in after_spam:
        url = p.get("url", "")
        meta = classified.get(url)
        if not meta or not meta.get("topic"):
            out.drop_stats["no_topic"] += 1
            continue
        if not allow_trading and meta.get("trading"):
            out.drop_stats["trading_blocked"] += 1
            continue
        row = dict(p)
        row["_topic"] = meta["topic"]
        row["_topic_score"] = meta.get("score", 1)
        out.append(row)

    out.drop_stats["kept"] = len(out)
    out.drop_stats["classify_path"] = classify_path  # type: ignore[assignment]
    return out
