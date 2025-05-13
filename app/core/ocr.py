from typing import BinaryIO

import pytesseract
from PIL import Image

from app.core.config import settings


def ocr(file_obj: BinaryIO) -> str:
    """Performs OCR on an image file object using pytesseract.

    Args:
        file_obj: A binary file-like object representing the image.
                  The file pointer should be at the beginning of the file
                  if it has been read previously.
        lang: The language for OCR processing, typically from settings.

    Returns:
        The extracted text as a string.
    """
    return pytesseract.image_to_string(Image.open(file_obj), lang=settings.ocr_language)
