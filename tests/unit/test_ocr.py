import io
from pathlib import Path

import pytesseract

from app.core.ocr import ocr

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_ocr_invokes_pytesseract(monkeypatch):
    # Load real image fixture
    path = FIXTURES / "sample.png"
    content = path.read_bytes()
    buf = io.BytesIO(content)
    buf.seek(0)

    # Monkeypatch pytesseract.image_to_string
    monkeypatch.setattr(
        pytesseract, "image_to_string", lambda img_obj: "dummy OCR text"
    )

    result = ocr(buf)
    assert result == "dummy OCR text"
