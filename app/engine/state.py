"""Pure helpers operating on the orchestrator's state dict.

Kept side-effect-free except for in-place dict mutation so the scheduler can
flush the same dict back to the database with `_save_state`.
"""

from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Any

from app.content.position_memory import record_position
from app.content.rules import (
    COMMENT_ROTATIONS, DEGEN_FORMAT_ORDER, FORMAT_ORDER,
    THREAD_FORMAT_ORDER, TONE_LIST,
)
from app.engine.constants import (
    DAILY_COUNTER_RETENTION, RECENT_FOLLOWS_CAP, RECENT_POSTED_TEXTS_CAP,
    RECENT_SOURCE_URLS_CAP,
)


# --- Daily caps -------------------------------------------------------------

def _today_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def daily_caps_for(cfg: dict) -> dict[str, int]:
    return {
        "tweets": int(cfg.get("daily_max_tweets", 8)),
        "comments": int(cfg.get("daily_max_comments", 25)),
        "likes": int(cfg.get("daily_max_likes", 50)),
        "follows": int(cfg.get("daily_max_follows", 10)),
        "qrts": int(cfg.get("daily_max_qrts", 5)),
        "rts": int(cfg.get("daily_max_rts", 10)),
    }


def today_counts(state: dict) -> dict[str, int]:
    """Return today's mutable counter dict, pruning old days first."""
    daily = state.setdefault("daily_actions", {})
    if not isinstance(daily, dict):
        daily = {}
        state["daily_actions"] = daily
    key = _today_key()
    if key not in daily:
        daily[key] = {}
        if len(daily) > DAILY_COUNTER_RETENTION:
            for old_key in sorted(daily.keys())[:-DAILY_COUNTER_RETENTION]:
                daily.pop(old_key, None)
    return daily[key]


def can_act(state: dict, cfg: dict, action_type: str) -> bool:
    cap = daily_caps_for(cfg).get(action_type)
    if cap is None:
        return True
    return today_counts(state).get(action_type, 0) < cap


def record_action(state: dict, action_type: str) -> None:
    counts = today_counts(state)
    counts[action_type] = counts.get(action_type, 0) + 1


def all_caps_reached(state: dict, cfg: dict) -> bool:
    counts = today_counts(state)
    for k, cap in daily_caps_for(cfg).items():
        if counts.get(k, 0) < cap:
            return False
    return True


# --- Dedup state ------------------------------------------------------------

def recent_posts(state: dict, n: int = 5) -> list[str]:
    texts = state.get("recent_posted_texts") or []
    return texts[-n:]


def remember_posted_text(state: dict, text: str) -> None:
    texts = state.setdefault("recent_posted_texts", [])
    texts.append(text)
    state["recent_posted_texts"] = texts[-RECENT_POSTED_TEXTS_CAP:]


def remember_source_url(state: dict, url: str) -> None:
    if not url:
        return
    urls = state.setdefault("recent_source_urls", [])
    if url not in urls:
        urls.append(url)
    state["recent_source_urls"] = urls[-RECENT_SOURCE_URLS_CAP:]


def remember_follow(state: dict, handle: str) -> None:
    if not handle:
        return
    follows = state.setdefault("last_follows", [])
    if handle not in follows:
        follows.append(handle)
    state["last_follows"] = follows[-RECENT_FOLLOWS_CAP:]


# --- Rotation helpers -------------------------------------------------------

def _next_in(order: list[str], current: str) -> str:
    if not order:
        return ""
    if current in order:
        return order[(order.index(current) + 1) % len(order)]
    return order[0]


def next_format(state: dict) -> str:
    return _next_in(FORMAT_ORDER, state.get("last_format", ""))


def next_degen_format(state: dict) -> str:
    return _next_in(DEGEN_FORMAT_ORDER, state.get("degen_last_format", ""))


def next_thread_format(state: dict) -> str:
    return _next_in(THREAD_FORMAT_ORDER, state.get("thread_last_format", ""))


def next_comment_rotation(state: dict) -> list[str]:
    last = state.get("last_comment_rotation") or []
    if last in COMMENT_ROTATIONS:
        idx = (COMMENT_ROTATIONS.index(last) + 1) % len(COMMENT_ROTATIONS)
    else:
        idx = 0
    return COMMENT_ROTATIONS[idx]


def tone_for(index: int) -> str:
    return TONE_LIST[index % len(TONE_LIST)]


# --- Topic selection --------------------------------------------------------

def topic_weight(cfg: dict, topic: str) -> float:
    topics = cfg.get("topics") or {}
    degen = cfg.get("degen_topics") or {}
    return float(topics.get(topic, 0) or degen.get(topic, 0) or 1)


def next_topic(cfg: dict, state: dict, enabled: list[str], exclude: list[str] | None = None) -> str:
    """Pick a weighted-random enabled topic, avoiding the most recent ones."""
    exclude = exclude or []
    recent = {
        state.get("last_topic_tweet", ""),
        state.get("last_topic_qrt", ""),
        state.get("last_topic_rt", ""),
        *exclude,
    }
    available = [t for t in enabled if t not in recent] \
        or [t for t in enabled if t not in exclude] \
        or list(enabled)
    weights = [topic_weight(cfg, t) for t in available]
    return random.choices(available, weights=weights, k=1)[0]


# --- Position memory --------------------------------------------------------

def record_position_in_state(state: dict, topic: str, stance: str) -> None:
    history = state.setdefault("position_history", [])
    state["position_history"] = record_position(
        history, topic, stance, datetime.now(timezone.utc).isoformat(),
    )


# --- Active hours -----------------------------------------------------------

def is_active_hours(cfg: dict) -> bool:
    if not cfg.get("active_hours_enabled"):
        return True
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(cfg.get("active_hours_timezone", "UTC"))
    except Exception:
        tz = timezone.utc
    now = datetime.now(tz)
    start = int(cfg.get("active_hours_start", 8))
    end = int(cfg.get("active_hours_end", 23))
    if start <= end:
        return start <= now.hour < end
    return now.hour >= start or now.hour < end


# --- Misc -------------------------------------------------------------------

def active_api_key(cfg: dict) -> str:
    if cfg.get("llm_provider") == "anthropic":
        return cfg.get("anthropic_api_key", "")
    return cfg.get("openai_api_key", "")


def enabled_topics(cfg: dict) -> list[str]:
    return [t for t, w in (cfg.get("topics") or {}).items() if w]


def enabled_degen_topics(cfg: dict) -> list[str]:
    return [t for t, w in (cfg.get("degen_topics") or {}).items() if w]


def use_following(cfg: dict) -> bool:
    return bool(cfg.get("use_following_tab", True))


__all__ = [
    "daily_caps_for", "today_counts", "can_act", "record_action", "all_caps_reached",
    "recent_posts", "remember_posted_text", "remember_source_url", "remember_follow",
    "next_format", "next_degen_format", "next_thread_format", "next_comment_rotation",
    "tone_for", "topic_weight", "next_topic", "record_position_in_state",
    "is_active_hours", "active_api_key", "enabled_topics", "enabled_degen_topics",
    "use_following",
]
