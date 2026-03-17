"""API key authentication."""

import os
from fastapi import Header, HTTPException

API_SECRET = os.getenv("SECRET_KEY", "dev-secret")


async def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key != API_SECRET:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key
