"""Fetch images from URLs for vision-based content generation."""

import base64
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_MAX_IMAGES = 2
_TIMEOUT = 10.0


async def fetch_images_as_base64(urls: list[str], max_images: int = _MAX_IMAGES) -> list[tuple[str, str]]:
    """Fetch up to max_images from URLs, return list of (base64_data, mime_type)."""
    if not urls:
        return []
    results = []
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        for url in urls[:max_images]:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                ct = resp.headers.get("content-type", "image/jpeg")
                mime = ct.split(";")[0].strip().lower()
                if mime not in ("image/jpeg", "image/png", "image/gif", "image/webp"):
                    mime = "image/jpeg"
                b64 = base64.standard_b64encode(resp.content).decode("ascii")
                results.append((b64, mime))
            except Exception as e:
                logger.debug("Failed to fetch image %s: %s", url[:50], e)
    return results
