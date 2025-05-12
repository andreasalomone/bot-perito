import asyncio
import logging
from typing import List, Optional, Tuple

from fastapi import HTTPException, UploadFile

from app.core.config import settings
from app.core.validation import validate_upload
from app.services.extractor import ExtractorError, extract, guard_corpus

__all__ = [
    "_extract_single_file",
    "extract_texts",
    "_validate_and_extract_files",
]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Low-level helpers – single file / image processing
# ---------------------------------------------------------------------------


async def _extract_single_file(
    file: UploadFile, request_id: str
) -> Tuple[Optional[str], Optional[str]]:
    """Extract plain text and (optionally) an image token from a single uploaded
    file.

    Parameters
    ----------
    file: UploadFile
        The uploaded file to process.
    request_id: str
        A request-scoped identifier used for structured logging.

    Returns
    -------
    Tuple[Optional[str], Optional[str]]
        A 2-tuple where the first element is the extracted text (or ``None``) and the
        second element is an image token (or ``None``).
    """
    try:
        if not hasattr(file, "file") or not hasattr(file.file, "read"):
            logger.error(
                "[%s] Invalid UploadFile object received: %s", request_id, file.filename
            )
            raise HTTPException(status_code=400, detail="Invalid file object received.")

        # Reset file pointer position – handle both async and sync cases
        if hasattr(file, "seek") and asyncio.iscoroutinefunction(file.seek):
            await file.seek(0)
        elif hasattr(file.file, "seek"):
            file.file.seek(0)
        else:
            logger.warning(
                "[%s] File object for %s does not support seek(0). Proceeding…",
                request_id,
                file.filename,
            )

        txt, tok = extract(file.filename or "", file.file)
        logger.debug(
            "[%s] Extracted from %s: text=%d chars, has_image=%s",
            request_id,
            file.filename,
            len(txt) if txt else 0,
            bool(tok),
        )
        return txt, tok
    except ExtractorError as e:
        logger.error(
            "[%s] Extraction error from %s: %s",
            request_id,
            file.filename,
            str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(
            "[%s] Failed to extract from %s: %s",
            request_id,
            file.filename,
            str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred during text extraction.",
        )


async def extract_texts(
    files: List[UploadFile], request_id: str
) -> Tuple[List[str], List[str]]:
    """Concurrent extraction of texts and image tokens from a list of files."""
    tasks = [_extract_single_file(f, request_id) for f in files]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    texts: List[str] = []
    imgs: List[str] = []

    for result in results:
        if isinstance(result, Exception):
            if isinstance(result, HTTPException):
                raise result
            logger.error(
                "[%s] Unexpected error during file extraction part: %s",
                request_id,
                str(result),
                exc_info=True,
            )
            raise result

        txt, tok = result  # type: ignore[assignment]
        if txt is not None:
            texts.append(txt)
        if tok is not None:
            imgs.append(tok)

    return texts, imgs


# ---------------------------------------------------------------------------
# High-level helper – validate, extract, prioritise images
# ---------------------------------------------------------------------------


async def _validate_and_extract_files(
    files: List[UploadFile],
    request_id: str,
) -> Tuple[str, List[str]]:
    """Validate uploads and extract the main textual *corpus* and image tokens."""
    max_images_in_report = getattr(settings, "max_images_in_report", 10)

    # Validate inputs -------------------------------------------------------
    for f_obj in files:
        await validate_upload(f_obj, request_id)

    # Extract content -------------------------------------------------------
    texts_content, general_img_tokens = await extract_texts(files, request_id)

    # Truncate images if needed
    final_img_tokens: List[str] = list(general_img_tokens)[:max_images_in_report]

    corpus = guard_corpus("\n\n".join(texts_content))
    logger.info(
        "[%s] Final image tokens for prompt: %d (from general doc images). Corpus length: %d.",
        request_id,
        len(final_img_tokens),
        len(corpus),
    )
    return corpus, final_img_tokens
