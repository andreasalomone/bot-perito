from fastapi.security import APIKeyHeader
from fastapi import Depends, HTTPException

from app.core.config import settings

api_key_header = APIKeyHeader(name="X-API-Key")


async def verify_api_key(key: str = Depends(api_key_header)):
    if key != settings.api_key:
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return True
