from pathlib import Path

import pytest
from fastapi import HTTPException

from app.core.validation import MAX_FILE_SIZE, validate_upload

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.mark.asyncio
async def test_invalid_extension(make_dummy_upload):
    # Create dummy file with unsupported extension
    dummy = make_dummy_upload("bad.txt", b"123")

    with pytest.raises(HTTPException) as exc:
        await validate_upload(dummy, "req1")
    assert exc.value.status_code == 400
    assert "Tipo file non supportato" in exc.value.detail


@pytest.mark.asyncio
async def test_file_too_large(make_dummy_upload):
    # Create dummy file exceeding size limit
    large_content = b"0" * (MAX_FILE_SIZE + 1)
    dummy = make_dummy_upload("file.pdf", large_content)

    with pytest.raises(HTTPException) as exc:
        await validate_upload(dummy, "req2")
    assert exc.value.status_code == 400
    assert "File troppo grande" in exc.value.detail


@pytest.mark.asyncio
async def test_mismatched_mime(monkeypatch, make_dummy_upload):
    # Use real PDF fixture for content
    path = FIXTURES / "sample.pdf"
    content = path.read_bytes()
    # Create dummy file with correct name but mismatched mime
    dummy = make_dummy_upload("sample.pdf", content)

    # Monkeypatch magic detection to wrong mime
    monkeypatch.setattr(
        "app.core.validation.magic.from_buffer",
        lambda buf, mime=True: "application/octet-stream",
    )

    with pytest.raises(HTTPException) as exc:
        await validate_upload(dummy, "req3")
    assert exc.value.status_code == 400
    assert "contenuto del file non corrisponde" in exc.value.detail


@pytest.mark.asyncio
async def test_validate_success(monkeypatch, make_dummy_upload):
    # Use real PDF fixture for content
    path = FIXTURES / "sample.pdf"
    content = path.read_bytes()
    # Create dummy file with correct mime
    dummy = make_dummy_upload("sample.pdf", content)

    # Monkeypatch magic to correct mime
    monkeypatch.setattr(
        "app.core.validation.magic.from_buffer",
        lambda buf, mime=True: "application/pdf",
    )

    await validate_upload(dummy, "req4")
    # After validation, file pointer should be reset to 0
    assert dummy.file.tell() == 0
