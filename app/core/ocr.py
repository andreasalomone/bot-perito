import asyncio
import io
import logging
from typing import BinaryIO

import pytesseract
from PIL import Image

from app.core.config import settings

logger = logging.getLogger(__name__)


async def ocr(file_obj: BinaryIO) -> str:
    """Performs OCR on an image file object using pytesseract in a non-blocking way."""

    def _sync_perform_ocr_on_image_bytes(image_bytes_content: bytes, lang_setting: str) -> str:
        try:
            image = Image.open(io.BytesIO(image_bytes_content))
            logger.debug(f"OCR_CORE: Image opened: format={image.format}, size={image.size}, mode={image.mode}")

            try:
                version = pytesseract.get_tesseract_version()
                logger.debug(f"OCR_CORE: Tesseract version: {version}")
            except Exception as ver_err:
                logger.warning(f"OCR_CORE: Could not get Tesseract version: {ver_err}")

            result = pytesseract.image_to_string(image, lang=lang_setting)
            return result
        except Exception as e:
            logger.error(f"OCR_CORE: Pytesseract image_to_string error: {type(e).__name__}: {str(e)}", exc_info=True)
            raise

    try:
        file_obj.seek(0)
        image_bytes = await asyncio.to_thread(file_obj.read)
        return await asyncio.to_thread(_sync_perform_ocr_on_image_bytes, image_bytes, settings.ocr_language)
    except Exception as e:
        logger.error(f"OCR_CORE: Error in ocr function (read or thread): {type(e).__name__}: {str(e)}", exc_info=True)
        raise
