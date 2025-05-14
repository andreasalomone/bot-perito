import json
import os
from pathlib import Path

import pytest
from fastapi import FastAPI, status
from fastapi.testclient import TestClient
from unittest.mock import Mock

from app.api import routes as routes_module
from app.core.validation import MIME_MAPPING
from app.generation_logic.file_processing import _validate_and_extract_files

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

THREE_MB = 3 * 1024 * 1024

# Global variable for MIME type tracking in tests
# _current_mime: str = ""

def _make_file_tuple(fname: str, mime: str):
    """Return (filename, bytes, mime) tuple for multipart."""
    return (fname, b"0" * THREE_MB, mime)


async def _patched_stream_logic(files, notes):  # noqa: D401 – test helper
    """Lightweight generator that just confirms we received 10 files and exits."""
    yield json.dumps({"type": "status", "message": f"received {len(files)} files"}) + "\n"
    yield json.dumps({"type": "finished"}) + "\n"


# ---------------------------------------------------------------------------
# E2E Test
# ---------------------------------------------------------------------------

@pytest.fixture()
def fastapi_app(monkeypatch):
    app = FastAPI()
    app.include_router(routes_module.router)
    app.dependency_overrides[routes_module.verify_api_key] = lambda: True

    # Patch heavy internals
    monkeypatch.setattr(routes_module, "_stream_report_generation_logic", _patched_stream_logic)

    # Patch extractor to avoid heavy PDF/DOCX processing
    monkeypatch.setattr(
        "app.generation_logic.file_processing.extract",
        lambda fname, stream, req_id: ("dummy text", None),
    )

    # Remove the old _fake_magic and global _current_mime logic
    # The patch for magic.from_buffer will be set up in the test itself

    return app


@pytest.mark.asyncio
async def test_generate_happy_path(fastapi_app, monkeypatch):
    client = TestClient(fastapi_app)

    # Build 10 files of 3 MiB each with correct MIME
    files = []
    sample_files = [
        ("img1.jpeg", MIME_MAPPING[".jpeg"]),
        ("img2.jpeg", MIME_MAPPING[".jpeg"]),
        ("photo1.jpg", MIME_MAPPING[".jpg"]),
        ("photo2.jpg", MIME_MAPPING[".jpg"]),
        ("diagram.png", MIME_MAPPING[".png"]),
        ("doc1.pdf", MIME_MAPPING[".pdf"]),
        ("doc2.pdf", MIME_MAPPING[".pdf"]),
        ("doc3.pdf", MIME_MAPPING[".pdf"]),
        ("file1.docx", MIME_MAPPING[".docx"]),
        ("file2.docx", MIME_MAPPING[".docx"]),
    ]

    for fname, mime in sample_files:
        files.append(("files", _make_file_tuple(fname, mime)))

    # Patch magic.from_buffer to return the correct MIME for each file in order
    expected_mimes_in_order = [mime for _, mime in sample_files]
    monkeypatch.setattr(
        "app.generation_logic.file_processing.magic.from_buffer",
        Mock(side_effect=expected_mimes_in_order)
    )

    response = client.post("/api/generate", files=files, data={"notes": ""})
    assert response.status_code == status.HTTP_200_OK
    body = response.content.decode()
    # Should contain finished event and status message
    assert "received 10 files" in body
    assert "finished" in body
