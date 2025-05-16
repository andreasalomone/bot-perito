import asyncio
import io
from typing import BinaryIO

import pytesseract
from PIL import Image

from app.core.config import settings


async def ocr(file_obj: BinaryIO) -> str:
    """Performs OCR on an image file object using pytesseract in a non-blocking way."""

    def _sync_perform_ocr(image_bytes: bytes, lang: str) -> str:
        try:
            # First verify we can open the image
            image = Image.open(io.BytesIO(image_bytes))
            print(f"Image opened: format={image.format}, size={image.size}, mode={image.mode}")

            # Check if tesseract is properly installed
            try:
                version = pytesseract.get_tesseract_version()
                print(f"Tesseract version: {version}")
            except Exception as ver_err:
                print(f"Could not get Tesseract version: {ver_err}")

            # Try OCR
            result = pytesseract.image_to_string(image, lang=lang)
            return result
        except Exception as e:
            print(f"OCR error: {type(e).__name__}: {str(e)}")
            raise

    file_obj.seek(0)
    image_bytes = file_obj.read()
    return await asyncio.to_thread(_sync_perform_ocr, image_bytes, settings.ocr_language)
