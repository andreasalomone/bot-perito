import asyncio
import io
from typing import BinaryIO

import pytesseract
from PIL import Image

from app.core.config import settings


async def ocr(file_obj: BinaryIO) -> str:
    """Performs OCR on an image file object using pytesseract in a non-blocking way.

    Args:
        file_obj: A binary file-like object representing the image.
                  The file pointer should be at the beginning of the file
                  if it has been read previously.

    Returns:
        The extracted text as a string.
    """

    def _sync_perform_ocr(image_bytes: bytes, lang: str) -> str:
        image = Image.open(io.BytesIO(image_bytes))
        return pytesseract.image_to_string(image, lang=lang)

    file_obj.seek(0)
    image_bytes = file_obj.read()
    return await asyncio.to_thread(_sync_perform_ocr, image_bytes, settings.ocr_language)
