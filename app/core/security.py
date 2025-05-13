"""Provides API key-based security for FastAPI endpoints."""

import logging

from fastapi import Depends
from fastapi import HTTPException
from fastapi.security import APIKeyHeader

from app.core.config import settings

# Initialize logger
logger = logging.getLogger(__name__)

api_key_header = APIKeyHeader(name="X-API-Key")


async def verify_api_key(key: str = Depends(api_key_header)) -> bool:
    """Verifies the provided API key against the server's configured API key.

    Used as a FastAPI dependency to protect routes.

    Args:
        key: The API key extracted from the 'X-API-Key' header.

    Returns:
        True if the API key is valid.

    Raises:
        HTTPException: With status code 403 if the API key is invalid or
                       if the server has no API key configured (resulting in a mismatch).
    """
    if not settings.api_key:
        # Log a critical server-side issue if the API key is not configured.
        # Access will still be denied due to the mismatch, which is secure.
        logger.critical(
            "CRITICAL: API key security is enforced, but no API_KEY is configured "
            "on the server. All API requests requiring this key will be denied."
        )
        # The check below will handle returning 403

    if key != settings.api_key:
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return True
