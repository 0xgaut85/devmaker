"""Database connection and session management."""

import asyncio
import logging
import os

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://localhost:5432/devmaker",
)
if DATABASE_URL.startswith("postgresql://") and "+asyncpg" not in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    connect_args={"timeout": 30},
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

db_ready = False


class Base(DeclarativeBase):
    pass


async def get_db():
    async with async_session() as session:
        yield session


async def init_db():
    global db_ready
    import app.models  # noqa: F401 — register models with Base.metadata

    for attempt in range(10):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            db_ready = True
            logger.info("Database initialized successfully")
            return
        except Exception as e:
            wait = min(2 ** attempt, 30)
            logger.warning(
                "DB init attempt %d failed: %s [%s] — retrying in %ds",
                attempt + 1, e, type(e).__name__, wait,
            )
            await asyncio.sleep(wait)
    logger.error("Failed to initialize database after 10 attempts")

