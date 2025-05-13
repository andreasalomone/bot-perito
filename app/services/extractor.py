import base64
import io
import logging
from typing import BinaryIO

import pdfplumber
from docx import Document
from PIL import Image

from app.core.config import settings
from app.core.ocr import ocr

# Configure module logger
logger = logging.getLogger(__name__)


class ExtractorError(Exception):
    """Base exception for extraction-related errors"""


def _pdf_to_text(f: BinaryIO) -> str:
    """Extract text from PDF file."""
    try:
        # Read binary stream into BytesIO for pdfplumber
        f.seek(0)
        buffer = io.BytesIO(f.read())
        with pdfplumber.open(buffer) as pdf:
            text = "\n".join(p.extract_text() or "" for p in pdf.pages)
            logger.debug("Extracted %d chars from PDF", len(text))
            return text
    except Exception as e:
        logger.error("Failed to extract text from PDF: %s", str(e), exc_info=True)
        raise ExtractorError("Failed to extract text from PDF") from e


def _docx_to_text(f: BinaryIO) -> str:
    """Extract text from DOCX file."""
    try:
        # Read binary stream into BytesIO for Document
        f.seek(0)
        buffer = io.BytesIO(f.read())
        doc = Document(buffer)
        text = "\n".join(p.text for p in doc.paragraphs)
        logger.debug("Extracted %d chars from DOCX", len(text))
        return text
    except Exception as e:
        logger.error("Failed to extract text from DOCX: %s", str(e), exc_info=True)
        raise ExtractorError("Failed to extract text from DOCX") from e


def _image_handler(fname: str, f: BinaryIO, request_id: str) -> tuple[str, str]:
    """Return (text, img_token). img_token is base64 if vision enabled."""
    logger.info("[%s] Processing image file: %s", request_id, fname)

    try:
        f.seek(0)
        text = ocr(f)
        logger.debug("[%s] OCR extracted %d chars", request_id, len(text.strip()))

        if len(text.strip()) > 30 or not settings.allow_vision:
            logger.info("[%s] Using OCR text (length > 30 or vision disabled)", request_id)
            return text, ""  # good OCR or vision disabled

        # no text ➜ pass downsized image to LLM
        try:
            f.seek(0)
            img = Image.open(f).convert("RGB")
            img.thumbnail(
                (
                    settings.image_thumbnail_width,
                    settings.image_thumbnail_height,
                )
            )  # Use settings
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=settings.image_jpeg_quality)  # Use settings
            buf.seek(0)
            b64 = base64.b64encode(buf.read()).decode()
            token = f"data:image/jpeg;base64,{b64}"
            logger.debug("[%s] Generated base64 token, length: %d", request_id, len(token))
            return "", token
        except Exception as e:
            logger.error("[%s] Failed to process image: %s", request_id, str(e), exc_info=True)
            raise ExtractorError("Failed to process image file") from e

    except Exception as e:
        logger.exception("[%s] Failed to handle image file: %s", request_id, fname)
        raise ExtractorError(f"Failed to handle image file: {fname}") from e


def extract_damage_image(f: BinaryIO, request_id: str) -> tuple[str, str]:
    """Always return ("", base64_token) so the vision model
    receives every damage photo even if OCR finds text.
    """
    logger.info("[%s] Processing damage image", request_id)

    try:
        f.seek(0)
        img = Image.open(f).convert("RGB")
        img.thumbnail(
            (
                settings.image_thumbnail_width,
                settings.image_thumbnail_height,
            )
        )  # Use settings
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=settings.image_jpeg_quality)  # Use settings
        token = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
        logger.debug(
            "[%s] Generated base64 token for damage image, length: %d",
            request_id,
            len(token),
        )
        return "", token
    except Exception as e:
        logger.error("[%s] Failed to process damage image: %s", request_id, str(e), exc_info=True)
        raise ExtractorError("Failed to process damage image") from e


_HANDLERS = {
    "pdf": _pdf_to_text,
    "docx": _docx_to_text,
    "doc": _docx_to_text,
}


def extract(fname: str, f: BinaryIO, request_id: str) -> tuple[str, str]:
    """Extract text and/or image token from a file based on its extension."""
    ext = fname.lower().split(".")[-1]
    logger.info("[%s] Extracting content from file: %s (type: %s)", request_id, fname, ext)

    try:
        if ext in _HANDLERS:
            text = _HANDLERS[ext](f)
            logger.info(
                "[%s] Successfully extracted text from %s: %d chars",
                request_id,
                ext.upper(),
                len(text),
            )
            return text, ""

        if ext in {"png", "jpg", "jpeg"}:
            text, token = _image_handler(fname, f, request_id)
            logger.info("[%s] Successfully processed image file: %s", request_id, fname)
            return text, token

        # Fallback for unknown types
        logger.warning(
            "[%s] Unknown file type '%s' for file '%s'. This type is not explicitly handled.",
            request_id,
            ext,
            fname,
        )
        raise ExtractorError(f"Unsupported file type: '{ext}' for file '{fname}'")

    except ExtractorError:
        raise
    except Exception as e:
        logger.exception("[%s] Unexpected error processing file: %s", request_id, fname)
        raise ExtractorError(f"Failed to process file: {fname}") from e


def guard_corpus(corpus: str, request_id: str) -> str:
    """Ensure corpus doesn't exceed maximum length."""
    original_len = len(corpus)

    if original_len > settings.max_prompt_chars:
        logger.warning(
            "[%s] Corpus exceeds max length (%d > %d), truncating",
            request_id,
            original_len,
            settings.max_prompt_chars,
        )
        return corpus[: settings.max_prompt_chars] + "\n\n[TESTO TRONCATO PER LIMITE TOKEN]"

    logger.debug("[%s] Corpus length OK: %d chars", request_id, original_len)
    return corpus
