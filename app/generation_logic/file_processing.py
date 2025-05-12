import asyncio
import logging
from typing import List, Optional, Tuple

from fastapi import HTTPException, UploadFile

from app.core.config import settings
from app.core.validation import validate_upload
from app.services.extractor import (
    ExtractorError,
    extract,
    extract_damage_image,
    guard_corpus,
)

__all__ = [
    "_extract_single_file",
    "extract_texts",
    "_process_single_image",
    "process_images",
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


async def _process_single_image(damage_img: UploadFile, request_id: str) -> str:
    """Process a single *dedicated* damage image, returning its token."""
    try:
        if not hasattr(damage_img, "file") or not hasattr(damage_img.file, "read"):
            logger.error(
                "[%s] Invalid UploadFile object for damage image: %s",
                request_id,
                damage_img.filename,
            )
            raise HTTPException(
                status_code=400, detail="Invalid damage image file object received."
            )

        # Reset pointer
        if hasattr(damage_img, "seek") and asyncio.iscoroutinefunction(damage_img.seek):
            await damage_img.seek(0)
        elif hasattr(damage_img.file, "seek"):
            damage_img.file.seek(0)
        else:
            logger.warning(
                "[%s] Damage image object for %s does not support seek(0). Proceeding…",
                request_id,
                damage_img.filename,
            )

        _discarded_text, tok = extract_damage_image(damage_img.file)
        if tok is None:
            logger.error(
                "[%s] Damage image token extraction returned None for %s",
                request_id,
                damage_img.filename,
            )
            raise ExtractorError(
                f"Token extraction failed for damage image {damage_img.filename}"
            )

        logger.debug(
            "[%s] Extracted damage image from %s", request_id, damage_img.filename
        )
        return tok
    except ExtractorError as e:
        logger.error(
            "[%s] Extraction error for damage image %s: %s",
            request_id,
            damage_img.filename,
            str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(
            "[%s] Failed to extract damage image from %s: %s",
            request_id,
            damage_img.filename,
            str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred during image processing.",
        )


async def process_images(damage_imgs: List[UploadFile], request_id: str) -> List[str]:
    """Process a list of dedicated damage images in parallel, returning their tokens."""
    if not damage_imgs:
        return []

    tasks = [_process_single_image(img, request_id) for img in damage_imgs]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    img_tokens: List[str] = []
    for result in results:
        if isinstance(result, Exception):
            if isinstance(result, HTTPException):
                raise result
            logger.error(
                "[%s] Unexpected error during image processing part: %s",
                request_id,
                str(result),
                exc_info=True,
            )
            raise result

        img_tokens.append(result)  # type: ignore[arg-type]

    return img_tokens


# ---------------------------------------------------------------------------
# High-level helper – validate, extract, prioritise images
# ---------------------------------------------------------------------------


async def _validate_and_extract_files(
    files: List[UploadFile],
    damage_imgs: Optional[List[UploadFile]],
    request_id: str,
) -> Tuple[str, List[str]]:
    """Validate uploads and extract the main textual *corpus* and image tokens.

    The logic prioritises image tokens found in the regular *files* over those
    coming from *damage_imgs*, enforcing the ``settings.max_images_in_report``
    limit.
    """
    max_images_in_report = getattr(settings, "max_images_in_report", 10)

    # Validate inputs -------------------------------------------------------
    for f_obj in files:
        await validate_upload(f_obj, request_id)
    if damage_imgs:
        for img_file in damage_imgs:
            await validate_upload(img_file, request_id)

    # Extract content -------------------------------------------------------
    texts_content, general_img_tokens = await extract_texts(files, request_id)

    damage_img_tokens: List[str] = []
    if damage_imgs:
        damage_img_tokens = await process_images(damage_imgs, request_id)

    # Prioritise images from the main documents ----------------------------
    final_img_tokens: List[str] = list(general_img_tokens)
    remaining_slots = max_images_in_report - len(final_img_tokens)
    if remaining_slots > 0 and damage_img_tokens:
        final_img_tokens.extend(damage_img_tokens[:remaining_slots])

    if len(final_img_tokens) > max_images_in_report:
        # Truncation warnings ------------------------------------------------
        if len(general_img_tokens) > max_images_in_report:
            logger.warning(
                "[%s] Too many general images (%d) from 'documenti perizia', truncating to %d.",
                request_id,
                len(general_img_tokens),
                max_images_in_report,
            )
        else:
            logger.warning(
                "[%s] Total images exceed limit (%d); truncating to %d including dedicated 'immagini danni'.",
                request_id,
                len(final_img_tokens),
                max_images_in_report,
            )
        final_img_tokens = final_img_tokens[:max_images_in_report]

    corpus = guard_corpus("\n\n".join(texts_content))
    logger.info(
        "[%s] Final image tokens for prompt: %d (prioritised general doc images). Corpus length: %d.",
        request_id,
        len(final_img_tokens),
        len(corpus),
    )
    return corpus, final_img_tokens
