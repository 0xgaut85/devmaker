"""Log retrieval endpoint."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Log
from app.api.auth import verify_api_key

router = APIRouter()


@router.get("/{account_id}")
async def get_logs(
    account_id: str,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_api_key),
):
    result = await db.execute(
        select(Log)
        .where(Log.account_id == account_id)
        .order_by(desc(Log.timestamp))
        .offset(offset)
        .limit(limit)
    )
    logs = result.scalars().all()
    return [
        {
            "id": l.id,
            "message": l.message,
            "level": l.level,
            "timestamp": l.timestamp.isoformat() if l.timestamp else "",
        }
        for l in reversed(logs)
    ]
