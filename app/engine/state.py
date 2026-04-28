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
    """Legacy sequential rotation. Kept for back-compat; new code should use
    :func:`pick_diverse_format`."""
    return _next_in(FORMAT_ORDER, state.get("last_format", ""))


# How many of the most recently used dev formats to exclude from the next
# pick. Tunable: too high and we starve interesting formats; too low and the
# user sees the same "Hot take on a tool" three sequences in a row. With 22
# formats, 5 keeps a healthy rotation pool of 17.
_RECENT_FORMATS_AVOID = 5
_RECENT_FORMATS_CAP = 8

# Personality-driven boost factors. Multiplied into the base weight (1.0 for
# every format) when the corresponding slider is in the "high" or "low"
# range. Conservative (1.5x-2x) so we still get diversity, just tilted.
_PERSONALITY_BOOSTS: dict[str, dict[str, float]] = {
    # high controversy -> contrarian / counter-narrative / hot-take formats
    "personality_controversy_high": {"E": 2.0, "K": 1.7, "R": 2.0, "S": 1.3},
    # high humor -> wordplay, setup-punchline, mic drop
    "personality_humor_high": {"U": 2.5, "H": 1.8, "T": 1.3},
    # high brevity -> short formats
    "personality_brevity_high": {"A": 2.0, "H": 1.8, "J": 1.5, "Q": 1.5, "T": 1.5, "U": 1.5},
    # low brevity (verbose) -> long formats
    "personality_brevity_low": {"F": 2.0, "N": 1.5, "V": 1.7, "S": 1.3},
    # high intellect -> long-reflection, metaphor, definition
    "personality_intellect_high": {"F": 1.8, "V": 1.8, "P": 1.5, "L": 1.4, "N": 1.3},
    # high warmth -> question hook, recommendation, confession
    "personality_warmth_high": {"D": 1.5, "T": 1.5, "S": 1.5, "Q": 1.4},
    # high confidence -> contrarian, mic drop, hot take
    "personality_confidence_high": {"E": 1.5, "H": 1.7, "K": 1.4, "R": 1.5},
    # high sarcasm -> wordplay, hot take, counter-narrative
    "personality_sarcasm_high": {"U": 2.0, "K": 1.5, "R": 1.5, "H": 1.4},
}


def _personality_weights(cfg: dict) -> dict[str, float]:
    """Compute a per-format multiplier dict from personality slider values.

    Sliders are 0-10. We treat >= 7 as "high" and <= 3 as "low" for
    boost purposes. Returns ``{format_key: multiplier}`` with default 1.0.
    """
    weights: dict[str, float] = {fk: 1.0 for fk in FORMAT_ORDER}
    if not cfg:
        return weights
    for slider, table in (
        ("personality_controversy", "personality_controversy_high"),
        ("personality_humor", "personality_humor_high"),
        ("personality_intellect", "personality_intellect_high"),
        ("personality_warmth", "personality_warmth_high"),
        ("personality_confidence", "personality_confidence_high"),
        ("personality_sarcasm", "personality_sarcasm_high"),
    ):
        if int(cfg.get(slider, 5) or 0) >= 7:
            for fk, boost in _PERSONALITY_BOOSTS[table].items():
                if fk in weights:
                    weights[fk] *= boost
    brev = int(cfg.get("personality_brevity", 5) or 0)
    if brev >= 7:
        for fk, boost in _PERSONALITY_BOOSTS["personality_brevity_high"].items():
            if fk in weights:
                weights[fk] *= boost
    elif brev <= 3:
        for fk, boost in _PERSONALITY_BOOSTS["personality_brevity_low"].items():
            if fk in weights:
                weights[fk] *= boost
    return weights


def pick_diverse_format(cfg: dict, state: dict) -> str:
    """Pick the next dev tweet format with three layers of diversity:

    1. EXCLUDE the last ``_RECENT_FORMATS_AVOID`` formats from the candidate
       pool so we never repeat the same look in a short window. Falls back to
       the full pool only when every format is in the recent list.
    2. WEIGHT the remaining candidates by personality sliders (high
       controversy -> contrarian formats get boosted, high humor -> wordplay
       boosted, etc.). Defaults to a uniform pick when no personality is set.
    3. UPDATE ``state['recent_formats']`` (capped) and ``state['last_format']``
       so the next call respects this pick. Persistence is handled by the
       caller via :func:`Orchestrator._persist_now`.

    Note: ``state['recent_formats']`` may not exist on accounts created before
    the column was added — we handle that by initialising from
    ``state['last_format']`` when missing.
    """
    recent: list[str] = list(state.get("recent_formats") or [])
    if not recent and state.get("last_format"):
        recent = [state["last_format"]]
    avoid = set(recent[-_RECENT_FORMATS_AVOID:])

    candidates = [fk for fk in FORMAT_ORDER if fk not in avoid] or list(FORMAT_ORDER)
    pweights = _personality_weights(cfg)
    weights = [pweights.get(fk, 1.0) for fk in candidates]
    pick = random.choices(candidates, weights=weights, k=1)[0]

    recent.append(pick)
    state["recent_formats"] = recent[-_RECENT_FORMATS_CAP:]
    state["last_format"] = pick
    return pick


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
    "next_format", "pick_diverse_format",
    "next_degen_format", "next_thread_format", "next_comment_rotation",
    "tone_for", "topic_weight", "next_topic", "record_position_in_state",
    "is_active_hours", "active_api_key", "enabled_topics", "enabled_degen_topics",
    "use_following",
]
