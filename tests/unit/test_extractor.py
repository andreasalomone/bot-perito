from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from app.core.config import settings
from app.services.extractor import (
    ExtractorError,
    _docx_to_text,
    _pdf_to_text,
    extract,
    extract_damage_image,
    guard_corpus,
)

# Add fixture path
FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_docx_to_text_success():
    path = FIXTURES / "sample.docx"
    with open(path, "rb") as f:
        text = _docx_to_text(f)
    assert isinstance(text, str)
    assert len(text) > 0


def test_docx_to_text_error(monkeypatch):
    monkeypatch.setattr(
        "app.services.extractor.Document",
        lambda buf: (_ for _ in ()).throw(Exception("bad docx")),
    )
    path = FIXTURES / "sample.docx"
    with open(path, "rb") as f:
        with pytest.raises(ExtractorError):
            _docx_to_text(f)


def test_extract_docx_via_extract():
    path = FIXTURES / "sample.docx"
    with open(path, "rb") as f:
        text, token = extract("sample.docx", f)
    assert isinstance(text, str)
    assert token == ""


def test_extract_fallback_unknown():
    buf = BytesIO(b"rawdata\xff")
    text, token = extract("file.unknown", buf)
    assert "rawdata" in text
    assert token == ""


@pytest.mark.parametrize(
    "ocr_text, allow_vision, expected_text, expected_token_prefix",
    [
        (
            "This is long OCR text longer than thirty characters...",
            True,
            "This is long OCR text longer than thirty characters...",
            "",
        ),
        ("short text", False, "short text", ""),
        ("short text", True, "", "data:image/jpeg;base64,"),
    ],
)
def test_extract_image_handler(
    monkeypatch, ocr_text, allow_vision, expected_text, expected_token_prefix
):
    buf = BytesIO()
    img = Image.new("RGB", (100, 100), color="white")
    img.save(buf, format="PNG")
    buf.seek(0)

    # Monkeypatch ocr and settings
    monkeypatch.setattr("app.services.extractor.ocr", lambda f: ocr_text)
    monkeypatch.setattr(settings, "allow_vision", allow_vision, raising=False)

    text, token = extract("image.png", buf)
    assert text == expected_text
    if expected_token_prefix:
        assert token.startswith(expected_token_prefix)
    else:
        assert token == ""


def test_extract_damage_image():
    buf = BytesIO()
    img = Image.new("RGB", (50, 50), color="blue")
    img.save(buf, format="JPEG")
    buf.seek(0)
    text, token = extract_damage_image(buf)
    assert text == ""
    assert token.startswith("data:image/jpeg;base64,")


def test_pdf_to_text_success():
    path = FIXTURES / "sample.pdf"
    with open(path, "rb") as f:
        text = _pdf_to_text(f)
    assert isinstance(text, str)
    assert len(text) > 0


def test_pdf_to_text_error(monkeypatch):
    monkeypatch.setattr(
        "app.services.extractor.pdfplumber.open",
        lambda buf: (_ for _ in ()).throw(Exception("bad pdf")),
    )
    path = FIXTURES / "sample.pdf"
    with open(path, "rb") as f:
        with pytest.raises(ExtractorError):
            _pdf_to_text(f)


def test_guard_corpus_truncate(monkeypatch):
    monkeypatch.setattr(settings, "max_prompt_chars", 5, raising=False)
    corpus = "abcdefg"
    result = guard_corpus(corpus)
    assert result.endswith("[TESTO TRONCATO PER LIMITE TOKEN]")
    assert len(result) <= 5 + len("\n\n[TESTO TRONCATO PER LIMITE TOKEN]")


def test_extract_pdf_via_extract():
    path = FIXTURES / "sample.pdf"
    with open(path, "rb") as f:
        text, token = extract("sample.pdf", f)
    assert isinstance(text, str)
    assert token == ""
