"""Handles file validation, content extraction, and image processing for uploads.

This module provides the core functionality to:
- Validate uploaded files against size, type, and extension constraints.
- Extract textual content from various file formats (PDF, DOCX).
- Process images to extract text via OCR or generate image tokens (e.g., base64 representations)
  for vision-enabled language models.

It orchestrates these tasks concurrently for multiple files to improve efficiency.
The primary entry point is `_validate_and_extract_files` which is used by the
streaming report generation logic.
"""

import asyncio
import io
import logging
from pathlib import Path
from typing import cast

import magic
from fastapi import HTTPException
from fastapi import UploadFile

from app.core.config import settings
from app.core.exceptions import PipelineError
from app.core.validation import ALLOWED_EXTENSIONS
from app.core.validation import MAX_FILE_SIZE
from app.core.validation import MAX_TOTAL_SIZE
from app.core.validation import MIME_MAPPING
from app.services.extractor import ExtractorError
from app.services.extractor import extract
from app.services.extractor import guard_corpus

__all__ = [
    "_validate_and_extract_files",
]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Low-level helpers – single file / image processing
# ---------------------------------------------------------------------------


async def _extract_single_file(filename: str, request_id: str, file_content_bytes: bytes) -> tuple[str | None, str | None]:
    """Extract plain text and (optionally) an image token from file contents.

    Parameters
    ----------
    filename: str
        The original name of the file.
    request_id: str
        A request-scoped identifier used for structured logging.
    file_content_bytes: bytes
        The actual byte content of the file.

    Returns:
    -------
    Tuple[Optional[str], Optional[str]]
        A 2-tuple where the first element is the extracted text (or ``None``) and the
        second element is an image token (or ``None``).
    """
    try:
        # Use io.BytesIO to treat the byte content as a file-like object
        with io.BytesIO(file_content_bytes) as file_stream:
            txt, tok = extract(filename, file_stream, request_id)

        logger.debug(
            "[%s] Extracted from %s: text=%d chars, has_image=%s",
            request_id,
            filename,
            len(txt) if txt else 0,
            bool(tok),
        )
        return txt, tok
    except ExtractorError as e:
        logger.error(
            "[%s] Extraction error from %s: %s",
            request_id,
            filename,
            str(e),
            exc_info=False,
        )
        raise
    except Exception as e:
        logger.error(
            "[%s] Failed to extract from %s: %s",
            request_id,
            filename,
            str(e),
            exc_info=True,
        )
        raise PipelineError(f"Unexpected error extracting file: {filename}") from e


# ---------------------------------------------------------------------------
# High-level helper – validate, extract, prioritise images
# ---------------------------------------------------------------------------


async def _validate_and_extract_files(
    files: list[UploadFile],
    request_id: str,
) -> tuple[str, list[str]]:
    """Validate uploads (size, type, total size), then extract text corpus and image tokens concurrently."""
    max_images_in_report = getattr(settings, "max_images_in_report", 10)
    total_size = 0
    validated_files_data: list[tuple[str, bytes]] = []  # To store (filename, content_bytes)

    # --- Validation Loop ---
    for f_obj in files:
        filename = f_obj.filename or "unknown_file"

        # 1. Extension Check
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            logger.warning(
                "[%s] Rejected file with invalid extension: %s for file %s",
                request_id,
                ext,
                filename,
            )
            raise HTTPException(
                status_code=400,
                detail=f"Tipo file non supportato ('{filename}'). Estensioni permesse: {', '.join(ALLOWED_EXTENSIONS)}",
            )

        # 2. Read Content ONCE for validation checks
        try:
            # Ensure file pointer is at the beginning before reading
            if hasattr(f_obj, "seek") and asyncio.iscoroutinefunction(f_obj.seek):
                await f_obj.seek(0)
            elif hasattr(f_obj.file, "seek"):
                f_obj.file.seek(0)  # For regular file objects wrapped by UploadFile
            else:
                logger.warning(
                    "[%s] File object %s may not support seek for validation read.",
                    request_id,
                    filename,
                )
            contents = await f_obj.read()
        except Exception as read_err:
            logger.error(
                "[%s] Failed to read file content for validation: %s - %s",
                request_id,
                filename,
                str(read_err),
            )
            raise HTTPException(
                status_code=500,
                detail=f"Errore durante la lettura del file per validazione: {filename}",
            ) from read_err

        size = len(contents)

        # 3. Individual File Size Check
        if size == 0:  # Empty file check
            logger.warning("[%s] Rejected empty file: %s", request_id, filename)
            raise HTTPException(
                status_code=400,
                detail=f"Il file '{filename}' è vuoto e non può essere processato.",
            )
        if size > MAX_FILE_SIZE:
            logger.warning(
                "[%s] Rejected file exceeding size limit: %s (%d bytes)",
                request_id,
                filename,
                size,
            )
            raise HTTPException(
                status_code=413,
                detail=f"File '{filename}' troppo grande ({size // (1024 * 1024)}MB). Limite per file: {MAX_FILE_SIZE // (1024 * 1024)}MB",  # noqa: E501
            )

        # 4. MIME Type Check
        try:
            mime = magic.from_buffer(contents, mime=True)
        except Exception as mime_err:
            logger.error(
                "[%s] Failed to detect MIME type for: %s - %s",
                request_id,
                filename,
                str(mime_err),
            )
            raise HTTPException(
                status_code=500,
                detail=f"Errore durante l'analisi del tipo di file: {filename}",
            ) from mime_err

        expected_mime = MIME_MAPPING.get(ext)
        if mime != expected_mime:
            logger.warning(
                "[%s] Rejected file with mismatched content type: %s. Expected: %s, Got: %s",
                request_id,
                filename,
                expected_mime,
                mime,
            )
            raise HTTPException(
                status_code=400,
                detail=f"Il contenuto del file '{filename}' (rilevato: {mime}) non corrisponde all'estensione '{ext}' (atteso: {expected_mime}).",  # noqa: E501
            )

        # 5. Accumulate Total Size & store valid file data
        total_size += size
        validated_files_data.append((filename, contents))
        logger.debug(
            "[%s] File validation successful: %s (%d bytes, MIME: %s)",
            request_id,
            filename,
            size,
            mime,
        )

    # --- Total Size Check ---
    if not validated_files_data and files:  # No files were validated, but files were provided
        logger.warning(
            "[%s] No valid files found after validation, though files were submitted.",
            request_id,
        )
        # This implies all files failed validation. The specific error would have been raised above.
        # If we reach here, it's an unusual state, possibly if an empty `files` list was passed
        # and not caught by FastAPI, or all files individually failed validation.
        # Raising a generic error if no specific one was already raised.
        raise HTTPException(
            status_code=400,
            detail="Nessun contenuto valido trovato nei file forniti.",
        )

    if total_size > MAX_TOTAL_SIZE:
        logger.warning(
            "[%s] Total upload size exceeds limit: %d bytes > %d bytes",
            request_id,
            total_size,
            MAX_TOTAL_SIZE,
        )
        raise HTTPException(
            status_code=413,
            detail=f"La dimensione totale dei file ({total_size // (1024 * 1024)}MB) supera il limite di {MAX_TOTAL_SIZE // (1024 * 1024)}MB.",  # noqa: E501
        )

    logger.info(
        "[%s] All file validations passed. Total size: %d bytes. Processing %d files.",
        request_id,
        total_size,
        len(validated_files_data),
    )

    # --- Concurrent Extraction ---
    texts_content: list[str] = []
    general_img_tokens: list[str] = []

    if not validated_files_data:  # If no files were validated (e.g. empty initial list)
        logger.info("[%s] No files to extract.", request_id)
        return "", []

    tasks = [_extract_single_file(fname, request_id, f_content_bytes) for fname, f_content_bytes in validated_files_data]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for result_idx, result_item in enumerate(results):
        # Get original filename for context in case of error from validated_files_data
        original_filename = validated_files_data[result_idx][0]

        if isinstance(result_item, Exception):
            # _extract_single_file raises ExtractorError or PipelineError
            logger.error(
                "[%s] Error during concurrent extraction for file %s: %s",
                request_id,
                original_filename,
                str(result_item),
                exc_info=(
                    True
                    if not isinstance(result_item, ExtractorError | PipelineError)
                    else False  # ExtractorError and PipelineError are logged at source
                ),
            )
            # Propagate as PipelineError to be handled by orchestrator
            # Ensure the error message includes which file failed.
            if isinstance(result_item, ExtractorError | PipelineError):
                # If it's already one of our specific errors, re-raise with context
                # The original error message in result_item should be descriptive enough
                raise PipelineError(f"Error processing file '{original_filename}': {str(result_item)}") from result_item
            else:  # For truly unexpected exceptions from gather or the task itself
                raise PipelineError(
                    f"Unexpected error processing file '{original_filename}': {str(result_item)}"
                ) from result_item
        else:
            assert not isinstance(result_item, Exception)  # Help Mypy with type narrowing
            txt, tok = cast(tuple[str | None, str | None], result_item)  # result_item is Tuple[Optional[str], Optional[str]]
            if txt is not None:  # Ensure not None, could also check for non-empty string if needed
                texts_content.append(txt)
            if tok is not None:  # Ensure not None
                general_img_tokens.append(tok)

    final_img_tokens: list[str] = list(general_img_tokens)[:max_images_in_report]
    corpus = guard_corpus("\\n\\n".join(texts_content), request_id)

    logger.info(
        "[%s] Validation & Extraction complete. Corpus length: %d. Image tokens: %d.",
        request_id,
        len(corpus),
        len(final_img_tokens),
    )
    return corpus, final_img_tokens
