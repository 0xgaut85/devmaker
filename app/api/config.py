"""Config get/set endpoints for per-account settings."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Config
from app.api.auth import verify_api_key

router = APIRouter()

# Fields the user can write directly via the dashboard.
WRITABLE_FIELDS = [
    "farming_mode", "llm_provider", "openai_api_key", "anthropic_api_key",
    "openai_model", "anthropic_model",
    "voice_description", "bad_examples", "good_examples",
    "dev_do", "dev_dont",
    "topics", "degen_topics",
    "project_name", "project_about", "project_do", "project_dont",
    "project_categories", "project_timeline_comments", "project_timeline_min_likes",
    "degen_voice_description", "degen_do", "degen_dont",
    "rt_farm_target_handle", "rt_farm_delay_seconds", "rt_farm_max_scrolls",
    "sniper_enabled", "sniper_scan_interval_minutes", "sniper_min_velocity",
    "sniper_max_replies", "sniper_replies_per_scan",
    "use_llm_classification", "use_vision_image_check", "position_memory_enabled",
    # Sequence composition (per-sequence exact counts; daily caps derive from these)
    "seq_text_tweets", "seq_rephrase_tweets", "seq_comments",
    "seq_qrts", "seq_rts", "seq_follows", "seq_threads",
    "active_hours_enabled", "active_hours_start", "active_hours_end", "active_hours_timezone",
    "personality_humor", "personality_sarcasm", "personality_confidence", "personality_warmth",
    "personality_controversy", "personality_intellect", "personality_brevity", "personality_edginess",
    "use_following_tab",
    "allow_trading_price_posts",
    "exclude_political_timeline",
    "action_delay_seconds", "sequence_delay_minutes", "min_engagement_likes",
]

# Read-only fields the dashboard still wants visible (derived ceilings, etc.).
DERIVED_FIELDS = [
    "daily_max_tweets", "daily_max_comments", "daily_max_likes",
    "daily_max_follows", "daily_max_qrts", "daily_max_rts",
    "thread_every_n_sequences",
]

EXPOSED_FIELDS = WRITABLE_FIELDS + DERIVED_FIELDS

# Average tweets per thread used when deriving the daily tweet ceiling.
_THREAD_AVG_LEN = 4


def _sequences_per_day_estimate(cfg: Config) -> int:
    """Generous upper bound on sequences/day given active hours + delay.
    Used only to derive the daily safety ceiling, never to limit the user."""
    start = int(cfg.active_hours_start or 0)
    end = int(cfg.active_hours_end or 24)
    if end <= start:
        end = start + 24
    window_minutes = (end - start) * 60
    delay = max(1, int(cfg.sequence_delay_minutes or 1))
    return max(1, window_minutes // delay)


def _recompute_daily_caps(cfg: Config) -> None:
    """Derive the daily_max_* ceiling from the per-sequence composition.
    These are runtime safety nets, not user-visible knobs."""
    seq_per_day = _sequences_per_day_estimate(cfg)
    text_t = int(cfg.seq_text_tweets or 0)
    reph_t = int(cfg.seq_rephrase_tweets or 0)
    threads = int(cfg.seq_threads or 0)
    comments = int(cfg.seq_comments or 0)
    qrts = int(cfg.seq_qrts or 0)
    rts = int(cfg.seq_rts or 0)
    follows = int(cfg.seq_follows or 0)

    tweets_per_seq = text_t + reph_t + threads * _THREAD_AVG_LEN
    cfg.daily_max_tweets = max(1, tweets_per_seq * seq_per_day)
    cfg.daily_max_comments = max(0, comments * seq_per_day)
    cfg.daily_max_qrts = max(0, qrts * seq_per_day)
    cfg.daily_max_rts = max(0, rts * seq_per_day)
    cfg.daily_max_follows = max(0, follows * seq_per_day)
    # Likes happen organically inside _like_and_bookmark; size the ceiling so
    # comment/QRT-driven likes never trip it.
    cfg.daily_max_likes = max(50, (comments + qrts + rts) * seq_per_day * 2)
    # Threads are scheduled per-sequence now; keep the legacy field at a value
    # that makes _should_post_thread() return True every sequence iff the user
    # asked for >=1 thread.
    cfg.thread_every_n_sequences = 1 if threads > 0 else 9999


@router.get("/{account_id}")
async def get_config(account_id: str, db: AsyncSession = Depends(get_db), _=Depends(verify_api_key)):
    result = await db.execute(select(Config).where(Config.account_id == account_id))
    cfg = result.scalar_one_or_none()
    if not cfg:
        raise HTTPException(404, "Config not found")
    # Make sure derived fields reflect the latest seq_* on every read so the
    # dashboard always shows accurate ceilings even if they were never written.
    _recompute_daily_caps(cfg)
    return {field: getattr(cfg, field) for field in EXPOSED_FIELDS}


@router.put("/{account_id}")
async def update_config(account_id: str, body: dict, db: AsyncSession = Depends(get_db), _=Depends(verify_api_key)):
    result = await db.execute(select(Config).where(Config.account_id == account_id))
    cfg = result.scalar_one_or_none()
    if not cfg:
        raise HTTPException(404, "Config not found")

    updated = []
    for key, value in body.items():
        if key in WRITABLE_FIELDS and hasattr(cfg, key):
            setattr(cfg, key, value)
            updated.append(key)

    _recompute_daily_caps(cfg)

    await db.commit()
    return {"updated": updated}
