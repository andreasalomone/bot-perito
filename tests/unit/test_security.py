import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.core.security import verify_api_key


@pytest.mark.asyncio
async def test_verify_api_key_success(monkeypatch):
    # Set expected API key
    monkeypatch.setattr(settings, "api_key", "secret", raising=False)
    result = await verify_api_key("secret")
    assert result is True


@pytest.mark.asyncio
async def test_verify_api_key_failure(monkeypatch):
    # Set expected API key
    monkeypatch.setattr(settings, "api_key", "secret", raising=False)
    with pytest.raises(HTTPException) as exc:
        await verify_api_key("wrong_key")
    assert exc.value.status_code == 403
    assert exc.value.detail == "Invalid API Key"
