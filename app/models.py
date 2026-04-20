"""SQLAlchemy models for all persistent data."""

import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Integer, Boolean, Float, Text, DateTime, ForeignKey, JSON,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


def _utcnow():
    return datetime.now(timezone.utc)


def _uuid():
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

    farming_mode = Column(String, default="dev")

    # LLM
    llm_provider = Column(String, default="openai")
    openai_api_key = Column(String, default="")
    anthropic_api_key = Column(String, default="")
    openai_model = Column(String, default="gpt-4o")
    anthropic_model = Column(String, default="claude-sonnet-4-20250514")

    # Voice
    voice_description = Column(Text, default="")
    bad_examples = Column(Text, default="")
    good_examples = Column(Text, default="")

    # Topics
    topics = Column(JSON, default=dict)
    degen_topics = Column(JSON, default=dict)

    # Project Farming
    project_name = Column(String, default="")
    project_about = Column(Text, default="")
    project_do = Column(Text, default="")
    project_dont = Column(Text, default="")
    project_categories = Column(JSON, default=dict)
    project_timeline_comments = Column(Integer, default=5)
    project_timeline_min_likes = Column(Integer, default=100)

    # Degen
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

    # Thread
    thread_every_n_sequences = Column(Integer, default=4)

    # Intelligence
    use_llm_classification = Column(Boolean, default=True)
    use_vision_image_check = Column(Boolean, default=False)
    position_memory_enabled = Column(Boolean, default=True)

    # Daily caps
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

    sequence_number = Column(Integer, default=0)
    last_format = Column(String, default="")
    last_topic_tweet = Column(String, default="")
    last_topic_qrt = Column(String, default="")
    last_topic_rt = Column(String, default="")
    last_qrt_author = Column(String, default="")
    last_comment_topics = Column(JSON, default=list)
    last_comment_rotation = Column(JSON, default=list)
    last_follows = Column(JSON, default=list)
    history = Column(JSON, default=list)

    # Project
    project_sequence_number = Column(Integer, default=0)
    project_comments_sent = Column(Integer, default=0)
    project_accounts_visited = Column(JSON, default=list)

    # Degen
    degen_sequence_number = Column(Integer, default=0)
    degen_last_format = Column(String, default="")
    degen_last_topic = Column(String, default="")
    degen_last_comment_rotation = Column(JSON, default=list)
    degen_history = Column(JSON, default=list)

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

    # Daily actions
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
