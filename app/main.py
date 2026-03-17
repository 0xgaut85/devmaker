"""FastAPI application entry point."""

import asyncio
import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.database import init_db
from app.api.accounts import router as accounts_router
from app.api.config import router as config_router
from app.api.logs import router as logs_router
from app.ws.handler import router as ws_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(init_db())
    yield


app = FastAPI(title="DevMaker", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(accounts_router, prefix="/api/accounts", tags=["accounts"])
app.include_router(config_router, prefix="/api/config", tags=["config"])
app.include_router(logs_router, prefix="/api/logs", tags=["logs"])
app.include_router(ws_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


dashboard_dir = os.path.join(os.path.dirname(__file__), "..", "dashboard", "dist")
if os.path.isdir(dashboard_dir):
    app.mount("/assets", StaticFiles(directory=os.path.join(dashboard_dir, "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        return FileResponse(os.path.join(dashboard_dir, "index.html"))
