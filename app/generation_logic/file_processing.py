"""Handles file validation, content extraction, and image processing for uploads.

This module provides the core functionality to:
- Validate uploaded files against size, type, and extension constraints.
- Extract textual content from various file formats (PDF, DOCX) and images via OCR.

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


async def _extract_single_file(filename: str, request_id: str, file_content_bytes: bytes) -> str | None:
    """Extract plain text from file contents.

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
    Optional[str]
        The extracted text (or ``None``).
    """
    try:
        # Use io.BytesIO to treat the byte content as a file-like object
        with io.BytesIO(file_content_bytes) as file_stream:
            txt = await extract(filename, file_stream, request_id)

        logger.debug(
            "[%s] Extracted from %s: text=%d chars",
            request_id,
            filename,
            len(txt) if txt else 0,
        )
        return txt
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


async def _validate_single_uploaded_file(f_obj: UploadFile, request_id: str) -> tuple[str, bytes]:
    filename = f_obj.filename or "unknown_file"
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
    logger.debug(
        "[%s] Attempting to read %s (type=%s, closed=%s)",
        request_id,
        filename,
        type(f_obj.file),
        getattr(f_obj.file, "closed", "?"),
    )
    try:
        try:
            if hasattr(f_obj.file, "seek") and callable(f_obj.file.seek):
                await asyncio.to_thread(f_obj.file.seek, 0)
            else:
                logger.warning(f"[{request_id}] File object for {f_obj.filename} does not support seek.")
        except Exception as seek_err:
            logger.warning(f"[{request_id}] Error seeking file {f_obj.filename}: {seek_err}")
        contents = await f_obj.read()
    except Exception as async_read_err:
        logger.error(
            f"[{request_id}] Failed to read file content for {filename} during initial async read: {async_read_err}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=400,
            detail=f"Impossibile leggere '{filename}': errore di accesso al contenuto.",
        ) from async_read_err
    size = len(contents)
    if size == 0:
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
            detail=f"File '{filename}' troppo grande ({size // (1024 * 1024)}MB). "
            f"Limite per file: {MAX_FILE_SIZE // (1024 * 1024)}MB",
        )
    try:
        mime = await asyncio.to_thread(magic.from_buffer, contents, mime=True)
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
            detail=f"Il contenuto del file '{filename}' (rilevato: {mime}) "
            f"non corrisponde all'estensione '{ext}' (atteso: {expected_mime}).",
        )
    logger.debug(
        "[%s] File validation successful: %s (%d bytes, MIME: %s)",
        request_id,
        filename,
        size,
        mime,
    )
    return filename, contents


async def _validate_and_extract_files(
    files: list[UploadFile],
    request_id: str,
) -> str:
    """Validate uploads (size, type, total size), then extract text corpus concurrently."""
    total_size = 0
    validated_files_data: list[tuple[str, bytes]] = []  # To store (filename, content_bytes)

    # --- Pre-flight: max file count check ---
    from app.core.validation import MAX_FILES  # Local import to avoid circulars during tests

    if len(files) > MAX_FILES:
        logger.warning("[%s] Upload rejected: too many files (%d > %d)", request_id, len(files), MAX_FILES)
        raise HTTPException(
            status_code=413,
            detail=f"Puoi caricare al massimo {MAX_FILES} file alla volta.",
        )

    # --- Validation Loop ---
    for f_obj in files:
        filename, contents = await _validate_single_uploaded_file(f_obj, request_id)
        size = len(contents)
        total_size += size
        validated_files_data.append((filename, contents))

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

    if not validated_files_data:  # If no files were validated (e.g. empty initial list)
        logger.info("[%s] No files to extract.", request_id)
        return ""

    tasks = [_extract_single_file(fname, request_id, f_content_bytes) for fname, f_content_bytes in validated_files_data]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for result_item in results:
        if isinstance(result_item, Exception):
            # _extract_single_file raises ExtractorError or PipelineError
            logger.error(
                "[%s] Error during concurrent extraction for file: %s",
                request_id,
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
                raise PipelineError(f"Error processing file: {str(result_item)}") from result_item
            else:  # For truly unexpected exceptions from gather or the task itself
                raise PipelineError(f"Unexpected error processing file: {str(result_item)}") from result_item
        else:
            assert not isinstance(result_item, Exception)  # Help Mypy with type narrowing
            txt = cast(str | None, result_item)  # result_item is Optional[str]
            if txt is not None:  # Ensure not None, could also check for non-empty string if needed
                texts_content.append(txt)

    corpus = guard_corpus("\\n\\n".join(texts_content), request_id)

    logger.info(
        "[%s] Validation & Extraction complete. Corpus length: %d.",
        request_id,
        len(corpus),
    )
    return corpus
