import io
from typing import List

import pytest
from fastapi import HTTPException
from pytest import MonkeyPatch
from starlette.datastructures import UploadFile

# Target under test
from app.generation_logic.file_processing import _validate_and_extract_files

# Constants from validation module for dynamic reference
from app.core.validation import (
    ALLOWED_EXTENSIONS,
    MAX_FILE_SIZE,
    MAX_FILES,
    MAX_TOTAL_SIZE,
    MIME_MAPPING,
)


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _make_upload_file(name: str, data: bytes) -> UploadFile:
    """Utility to create an in-memory UploadFile for tests."""
    return UploadFile(file=io.BytesIO(data), filename=name)


aSYNC_FIXTURE = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Happy-path validation
# ---------------------------------------------------------------------------

@aSYNC_FIXTURE
async def test_validate_and_extract_happy_path(monkeypatch: MonkeyPatch) -> None:
    """A single small, valid PDF should pass validation and return a corpus string."""

    dummy_text = "Estratto testo"

    # Patch extractor.extract to return dummy text
    def _fake_extract(filename: str, file_stream: io.BytesIO, request_id: str) -> tuple[str, None]:
        # Simulate the real signature (returns text, token)
        return dummy_text, None

    monkeypatch.setattr(
        "app.generation_logic.file_processing.extract", _fake_extract, raising=True
    )

    # Patch magic.from_buffer to return correct MIME for .pdf
    monkeypatch.setattr(
        "app.generation_logic.file_processing.magic.from_buffer",
        lambda _bytes: MIME_MAPPING[".pdf"],  # type: ignore
        raising=True,
    )

    f = _make_upload_file("file.pdf", b"%PDF-1.4\n...")
    corpus = await _validate_and_extract_files([f], request_id="test-happy")

    assert dummy_text in corpus


# ---------------------------------------------------------------------------
# Too many files
# ---------------------------------------------------------------------------

@aSYNC_FIXTURE
async def test_validate_too_many_files(monkeypatch: MonkeyPatch) -> None:
    """Uploading more than MAX_FILES should raise HTTPException 413."""

    # Minimal mocks – they won't be called, but patch to be safe
    monkeypatch.setattr(
        "app.generation_logic.file_processing.extract",
        lambda *args, **kwargs: ("", None),  # type: ignore
    )
    monkeypatch.setattr(
        "app.generation_logic.file_processing.magic.from_buffer",
        lambda _bytes, mime=True: MIME_MAPPING[".pdf"],  # type: ignore
    )

    files: List[UploadFile] = [
        _make_upload_file(f"f{i}.pdf", b"%PDF-1.4\n...") for i in range(MAX_FILES + 1)
    ]

    with pytest.raises(HTTPException) as exc_info:
        await _validate_and_extract_files(files, request_id="test-too-many")

    assert exc_info.value.status_code == 413
    assert "massimo" in exc_info.value.detail.lower()


# ---------------------------------------------------------------------------
# Individual file too large
# ---------------------------------------------------------------------------

@aSYNC_FIXTURE
async def test_validate_individual_file_too_large(monkeypatch: MonkeyPatch) -> None:
    """A single file exceeding MAX_FILE_SIZE should be rejected with 413."""

    monkeypatch.setattr(
        "app.generation_logic.file_processing.magic.from_buffer",
        lambda _bytes, mime=True: MIME_MAPPING[".pdf"],  # type: ignore
    )

    oversized = b"0" * (MAX_FILE_SIZE + 1)
    f = _make_upload_file("big.pdf", oversized)

    with pytest.raises(HTTPException) as exc_info:
        await _validate_and_extract_files([f], request_id="test-big")

    assert exc_info.value.status_code == 413


# ---------------------------------------------------------------------------
# Total size too large
# ---------------------------------------------------------------------------

@aSYNC_FIXTURE
async def test_validate_total_size_too_large(monkeypatch: MonkeyPatch) -> None:
    """Combined size > MAX_TOTAL_SIZE should be rejected."""

    monkeypatch.setattr(
        "app.generation_logic.file_processing.magic.from_buffer",
        lambda _bytes, mime=True: MIME_MAPPING[".pdf"],  # type: ignore
    )

    small_chunk = b"0" * (MAX_TOTAL_SIZE // MAX_FILES)
    files = [_make_upload_file(f"small{i}.pdf", small_chunk) for i in range(MAX_FILES)]

    # Add one more to push total size over the threshold
    files.append(_make_upload_file("extra.pdf", small_chunk))

    with pytest.raises(HTTPException) as exc_info:
        await _validate_and_extract_files(files, request_id="test-total")

    assert exc_info.value.status_code == 413


# ---------------------------------------------------------------------------
# Invalid extension
# ---------------------------------------------------------------------------

@aSYNC_FIXTURE
async def test_validate_invalid_extension(monkeypatch: MonkeyPatch) -> None:
    """A file with an unsupported extension should raise 400."""

    f = _make_upload_file("invalid.exe", b"dummy")
    with pytest.raises(HTTPException) as exc_info:
        await _validate_and_extract_files([f], request_id="test-ext")

    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# Mismatched MIME type
# ---------------------------------------------------------------------------

@aSYNC_FIXTURE
async def test_validate_mismatched_mime(monkeypatch: MonkeyPatch) -> None:
    """If magic returns a MIME different from expected, should raise 400."""

    # Patch magic to return text/plain instead of application/pdf
    monkeypatch.setattr(
        "app.generation_logic.file_processing.magic.from_buffer",
        lambda _bytes, mime=True: "text/plain",  # type: ignore
    )

    f = _make_upload_file("file.pdf", b"%PDF-1.4\n...")
    with pytest.raises(HTTPException) as exc_info:
        await _validate_and_extract_files([f], request_id="test-mime")

    assert exc_info.value.status_code == 400
    assert "non corrisponde" in exc_info.value.detail.lower()
