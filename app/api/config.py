"""Config get/set endpoints for per-account settings."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Config
from app.api.auth import verify_api_key

router = APIRouter()

EXPOSED_FIELDS = [
    "farming_mode", "llm_provider", "openai_api_key", "anthropic_api_key",
    "openai_model", "anthropic_model",
    "voice_description", "bad_examples", "good_examples",
    "topics", "degen_topics",
    "project_name", "project_about", "project_do", "project_dont",
    "project_categories", "project_timeline_comments", "project_timeline_min_likes",
    "degen_voice_description", "degen_do", "degen_dont",
    "rt_farm_target_handle", "rt_farm_delay_seconds", "rt_farm_max_scrolls",
    "sniper_enabled", "sniper_scan_interval_minutes", "sniper_min_velocity",
    "sniper_max_replies", "sniper_replies_per_scan",
    "thread_every_n_sequences",
    "use_llm_classification", "use_vision_image_check", "position_memory_enabled",
    "daily_max_tweets", "daily_max_comments", "daily_max_likes",
    "daily_max_follows", "daily_max_qrts",
    "active_hours_enabled", "active_hours_start", "active_hours_end", "active_hours_timezone",
    "personality_humor", "personality_sarcasm", "personality_confidence", "personality_warmth",
    "personality_controversy", "personality_intellect", "personality_brevity", "personality_edginess",
    "use_following_tab",
    "allow_trading_price_posts",
    "action_delay_seconds", "sequence_delay_minutes", "min_engagement_likes",
]


@router.get("/{account_id}")
async def get_config(account_id: str, db: AsyncSession = Depends(get_db), _=Depends(verify_api_key)):
    result = await db.execute(select(Config).where(Config.account_id == account_id))
    cfg = result.scalar_one_or_none()
    if not cfg:
        raise HTTPException(404, "Config not found")
    return {field: getattr(cfg, field) for field in EXPOSED_FIELDS}


@router.put("/{account_id}")
async def update_config(account_id: str, body: dict, db: AsyncSession = Depends(get_db), _=Depends(verify_api_key)):
    result = await db.execute(select(Config).where(Config.account_id == account_id))
    cfg = result.scalar_one_or_none()
    if not cfg:
        raise HTTPException(404, "Config not found")

    updated = []
    for key, value in body.items():
        if key in EXPOSED_FIELDS and hasattr(cfg, key):
            setattr(cfg, key, value)
            updated.append(key)

    await db.commit()
    return {"updated": updated}
