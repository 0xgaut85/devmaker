"""SQLAlchemy models for all persistent data."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text,
)
from sqlalchemy.orm import relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


class Account(Base):
    __tablename__ = "accounts"

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String, nullable=False, unique=True)
    api_key = Column(String, nullable=False, unique=True, default=_uuid)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    config = relationship("Config", back_populates="account", uselist=False, cascade="all, delete-orphan")
    state = relationship("State", back_populates="account", uselist=False, cascade="all, delete-orphan")
    logs = relationship("Log", back_populates="account", cascade="all, delete-orphan")
    performance = relationship("Performance", back_populates="account", cascade="all, delete-orphan")


class Config(Base):
    __tablename__ = "configs"

    id = Column(String, primary_key=True, default=_uuid)
    account_id = Column(String, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, unique=True)

    farming_mode = Column(String, default="dev")  # dev | degen | rt_farm | sniper

    # LLM
    llm_provider = Column(String, default="openai")
    openai_api_key = Column(String, default="")
    anthropic_api_key = Column(String, default="")
    openai_model = Column(String, default="gpt-4o")
    anthropic_model = Column(String, default="claude-sonnet-4-20250514")

    # Voice (dev mode)
    voice_description = Column(Text, default="")
    bad_examples = Column(Text, default="")
    good_examples = Column(Text, default="")
    dev_do = Column(Text, default="")
    dev_dont = Column(Text, default="")

    # Topics
    topics = Column(JSON, default=dict)
    degen_topics = Column(JSON, default=dict)

    # Degen voice
    degen_voice_description = Column(Text, default="")
    degen_do = Column(Text, default="")
    degen_dont = Column(Text, default="")

    # RT Farm
    rt_farm_target_handle = Column(String, default="")
    rt_farm_delay_seconds = Column(Integer, default=5)
    rt_farm_max_scrolls = Column(Integer, default=50)

    # Sniper
    sniper_enabled = Column(Boolean, default=False)
    sniper_scan_interval_minutes = Column(Integer, default=8)
    sniper_min_velocity = Column(Integer, default=100)
    sniper_max_replies = Column(Integer, default=80)
    sniper_replies_per_scan = Column(Integer, default=2)

    # Thread (derived from seq_threads on write)
    thread_every_n_sequences = Column(Integer, default=4)

    # Intelligence toggles
    use_llm_classification = Column(Boolean, default=True)
    use_vision_image_check = Column(Boolean, default=False)
    position_memory_enabled = Column(Boolean, default=True)

    # Sequence composition (per-sequence, exact counts)
    seq_text_tweets = Column(Integer, default=1)
    seq_rephrase_tweets = Column(Integer, default=1)
    # Original tweet that REQUIRES attaching media (image) from a high-engagement
    # source post. Skips with a clear log when no eligible source has media.
    seq_media_tweets = Column(Integer, default=0)
    seq_comments = Column(Integer, default=4)
    seq_qrts = Column(Integer, default=1)
    seq_rts = Column(Integer, default=1)
    seq_follows = Column(Integer, default=2)
    seq_threads = Column(Integer, default=0)

    # Daily caps (derived from seq_* * sequences/day on write; runtime ceiling only)
    daily_max_tweets = Column(Integer, default=8)
    daily_max_comments = Column(Integer, default=25)
    daily_max_likes = Column(Integer, default=50)
    daily_max_follows = Column(Integer, default=10)
    daily_max_qrts = Column(Integer, default=5)
    daily_max_rts = Column(Integer, default=10)

    # Active hours
    active_hours_enabled = Column(Boolean, default=False)
    active_hours_start = Column(Integer, default=8)
    active_hours_end = Column(Integer, default=23)
    active_hours_timezone = Column(String, default="UTC")

    # Personality (0-10 sliders)
    personality_humor = Column(Integer, default=5)
    personality_sarcasm = Column(Integer, default=3)
    personality_confidence = Column(Integer, default=6)
    personality_warmth = Column(Integer, default=5)
    personality_controversy = Column(Integer, default=3)
    personality_intellect = Column(Integer, default=5)
    personality_brevity = Column(Integer, default=5)
    personality_edginess = Column(Integer, default=3)

    # Timeline
    use_following_tab = Column(Boolean, default=True)
    allow_trading_price_posts = Column(Boolean, default=False)
    exclude_political_timeline = Column(Boolean, default=True)

    # Timing
    action_delay_seconds = Column(Integer, default=3)
    sequence_delay_minutes = Column(Integer, default=45)
    min_engagement_likes = Column(Integer, default=100)

    account = relationship("Account", back_populates="config")


class State(Base):
    __tablename__ = "states"

    id = Column(String, primary_key=True, default=_uuid)
    account_id = Column(String, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, unique=True)

    # Dev mode rotation
    sequence_number = Column(Integer, default=0)
    last_format = Column(String, default="")
    # Rolling window of the last few format keys used; the picker excludes
    # this set so the user never sees the same format two sequences in a row.
    # Optional column — old DBs without it gracefully degrade to one-step
    # avoidance via last_format alone.
    recent_formats = Column(JSON, default=list)
    # Same idea for visual structures (single_line / two_paragraphs / etc.)
    # so we don't get "all flowing paragraphs" by chance even when the format
    # rotates. Picker excludes the last few used.
    recent_structures = Column(JSON, default=list)
    last_topic_tweet = Column(String, default="")
    last_topic_qrt = Column(String, default="")
    last_topic_rt = Column(String, default="")
    last_comment_rotation = Column(JSON, default=list)
    last_follows = Column(JSON, default=list)

    # Degen
    degen_sequence_number = Column(Integer, default=0)
    degen_last_format = Column(String, default="")
    degen_last_topic = Column(String, default="")
    degen_last_comment_rotation = Column(JSON, default=list)

    # RT Farm
    rt_farm_completed_urls = Column(JSON, default=list)
    rt_farm_total_retweeted = Column(Integer, default=0)

    # Dedup
    recent_posted_texts = Column(JSON, default=list)
    recent_source_urls = Column(JSON, default=list)

    # Sniper
    sniper_replied_urls = Column(JSON, default=list)
    sniper_total_replies = Column(Integer, default=0)

    # Thread
    thread_last_format = Column(String, default="")

    # Performance
    performance_history = Column(JSON, default=list)

    # Position memory
    position_history = Column(JSON, default=list)

    # Daily action counters (rolling 14-day window keyed by YYYY-MM-DD)
    daily_actions = Column(JSON, default=dict)

    account = relationship("Account", back_populates="state")


class Log(Base):
    __tablename__ = "logs"

    id = Column(String, primary_key=True, default=_uuid)
    account_id = Column(String, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    timestamp = Column(DateTime(timezone=True), default=_utcnow)
    message = Column(Text, nullable=False)
    level = Column(String, default="info")

    account = relationship("Account", back_populates="logs")


class Performance(Base):
    __tablename__ = "performance"

    id = Column(String, primary_key=True, default=_uuid)
    account_id = Column(String, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    post_url = Column(String, nullable=False)
    text_preview = Column(String, default="")
    likes = Column(Integer, default=0)
    replies = Column(Integer, default=0)
    views = Column(Integer, default=0)
    checked_at = Column(DateTime(timezone=True), default=_utcnow)

    account = relationship("Account", back_populates="performance")
