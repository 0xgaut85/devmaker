"""Account CRUD endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Account, Config, State
from app.api.auth import verify_api_key
from app.ws.manager import manager
from app.engine.scheduler import start_sequence, stop_sequence, is_running

router = APIRouter()


class AccountCreate(BaseModel):
    name: str


class AccountOut(BaseModel):
    id: str
    name: str
    api_key: str
    connected: bool = False
    running: bool = False

    class Config:
        from_attributes = True


class SequenceRequest(BaseModel):
    count: int = 1


@router.get("", response_model=list[AccountOut])
@router.get("/", response_model=list[AccountOut], include_in_schema=False)
async def list_accounts(db: AsyncSession = Depends(get_db), _=Depends(verify_api_key)):
    result = await db.execute(select(Account).order_by(Account.created_at))
    accounts = result.scalars().all()
    return [
        AccountOut(
            id=a.id, name=a.name, api_key=a.api_key,
            connected=manager.is_connected(a.id),
            running=is_running(a.id),
        )
        for a in accounts
    ]


@router.post("", response_model=AccountOut, status_code=201)
@router.post("/", response_model=AccountOut, status_code=201, include_in_schema=False)
async def create_account(body: AccountCreate, db: AsyncSession = Depends(get_db), _=Depends(verify_api_key)):
    existing = await db.execute(select(Account).where(Account.name == body.name))
    if existing.scalar_one_or_none():
        raise HTTPException(400, "Account name already exists")

    account = Account(name=body.name)
    db.add(account)
    await db.flush()

    cfg = Config(account_id=account.id)
    state = State(account_id=account.id)
    db.add(cfg)
    db.add(state)
    await db.commit()
    await db.refresh(account)

    return AccountOut(id=account.id, name=account.name, api_key=account.api_key, connected=False, running=False)


@router.delete("/{account_id}", status_code=204)
async def delete_account(account_id: str, db: AsyncSession = Depends(get_db), _=Depends(verify_api_key)):
    result = await db.execute(select(Account).where(Account.id == account_id))
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(404, "Account not found")
    await stop_sequence(account_id)
    await db.delete(account)
    await db.commit()


@router.post("/{account_id}/start")
async def start(account_id: str, body: SequenceRequest = SequenceRequest(),
                db: AsyncSession = Depends(get_db), _=Depends(verify_api_key)):
    result = await db.execute(select(Account).where(Account.id == account_id))
    if not result.scalar_one_or_none():
        raise HTTPException(404, "Account not found")
    ok = await start_sequence(account_id, body.count)
    if not ok:
        raise HTTPException(409, "Already running or no extension connected")
    return {"status": "started", "count": body.count}


@router.post("/{account_id}/stop")
async def stop(account_id: str, _=Depends(verify_api_key)):
    ok = await stop_sequence(account_id)
    if not ok:
        raise HTTPException(404, "Not running")
    return {"status": "stopped"}


@router.get("/{account_id}/status")
async def status(account_id: str, _=Depends(verify_api_key)):
    return {
        "connected": manager.is_connected(account_id),
        "running": is_running(account_id),
    }
