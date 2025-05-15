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
from typing import TypeVar
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
from app.services.storage.s3_service import download_bytes

__all__ = [
    "_validate_and_extract_files",
]

logger = logging.getLogger(__name__)

T = TypeVar("T")
S = TypeVar("S")


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
            detail=f"File '{filename}' troppo grande ({size // (1024 * 1024)}MB). Limite per file: {MAX_FILE_SIZE // (1024 * 1024)}MB",
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
            detail=f"Il contenuto del file '{filename}' (rilevato: {mime}) non corrisponde all'estensione '{ext}' (atteso: {expected_mime}).",
        )
    logger.debug(
        "[%s] File validation successful: %s (%d bytes, MIME: %s)",
        request_id,
        filename,
        size,
        mime,
    )
    return filename, contents


# --- Nuovo Helper per scaricare da S3 e validare ---
async def _download_and_validate_s3_file(key: str, request_id: str) -> tuple[str, bytes]:
    """
    Downloads a file from S3, validates its size and MIME type.
    Returns (filename, file_bytes).
    Raises HTTPException on failure.
    """
    logger.info(f"[{request_id}] Downloading and validating S3 key: {key}")

    # download_bytes è una funzione sincrona, la chiamiamo in un thread separato
    file_bytes = await asyncio.to_thread(download_bytes, key)

    if file_bytes is None:
        logger.error(f"[{request_id}] Failed to download S3 key: {key}")
        raise HTTPException(status_code=404, detail=f"File {key} not found or download failed from S3.")

    # A questo punto file_bytes non può essere None, quindi è bytes
    bytes_data: bytes = cast(bytes, file_bytes)

    filename = Path(key).name  # Estrae 'nomefile.ext' da 'uploads/uuid_nomefile.ext'

    # Validazione dimensione
    if len(bytes_data) > MAX_FILE_SIZE:
        logger.warning(f"[{request_id}] S3 file {filename} too large: {len(bytes_data)} bytes")
        raise HTTPException(status_code=413, detail=f"File {filename} from S3 is too large.")

    # Validazione MIME type
    try:
        mime_type_detected = await asyncio.to_thread(magic.from_buffer, bytes_data, mime=True)
    except Exception as e:
        logger.error(f"[{request_id}] MIME detection failed for S3 file {filename}: {e}")
        raise HTTPException(status_code=500, detail=f"MIME type detection failed for S3 file {filename}.") from e

    ext = Path(filename).suffix.lower()
    expected_mime = MIME_MAPPING.get(ext)

    if not expected_mime:  # Estensione non in MIME_MAPPING
        logger.warning(f"[{request_id}] S3 file {filename} has an unmapped extension '{ext}'. Skipping strict MIME check for this file but proceeding with caution.")
    elif mime_type_detected != expected_mime:
        logger.warning(f"[{request_id}] S3 file {filename} MIME mismatch. Expected: {expected_mime}, Got: {mime_type_detected}")
        raise HTTPException(status_code=400, detail=f"S3 file {filename} has incorrect content type. Expected {expected_mime}, got {mime_type_detected}.")

    logger.info(f"[{request_id}] S3 file {filename} downloaded and validated successfully.")
    return filename, bytes_data


async def _validate_and_extract_files(
    files_input: list[UploadFile] | list[str],
    request_id: str,
) -> str:
    """Validate uploads (size, type, total size), then extract text corpus concurrently."""
    total_size = 0
    extracted_texts: list[str] = []

    # --- Pre-flight: max file count check ---
    from app.core.validation import MAX_FILES  # Local import to avoid circulars during tests

    if len(files_input) > MAX_FILES:
        logger.warning(f"[{request_id}] Upload rejected: too many files/keys ({len(files_input)} > {MAX_FILES})")
        raise HTTPException(
            status_code=413,
            detail=f"Puoi processare al massimo {MAX_FILES} file alla volta.",
        )

    # --- Validation and Content Retrieval Loop ---
    processed_file_data: list[tuple[str, bytes]] = []

    if not files_input:
        logger.info(f"[{request_id}] No files or S3 keys provided for processing.")
        return ""

    # CASO 1: Input è una lista di chiavi S3 (stringhe)
    if all(isinstance(f, str) for f in files_input):
        logger.info(f"[{request_id}] Processing S3 keys: {files_input}")
        s3_keys: list[str] = cast(list[str], files_input)
        download_tasks = [_download_and_validate_s3_file(key, request_id) for key in s3_keys]

        # Gather può sollevare eccezioni se una task fallisce e non ha return_exceptions=True
        try:
            results = await asyncio.gather(*download_tasks)  # Se una fallisce, gather fallisce
            for filename, content_bytes in results:
                processed_file_data.append((filename, content_bytes))
                total_size += len(content_bytes)
        except HTTPException as http_exc:  # Rilancia HTTPException da _download_and_validate_s3_file
            raise http_exc
        except Exception as e:
            logger.error(f"[{request_id}] Unexpected error during S3 file download/validation batch: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Error processing one or more S3 files.") from e

    # CASO 2: Input è una lista di UploadFile (logica esistente)
    elif all(isinstance(f, UploadFile) for f in files_input):
        logger.info(f"[{request_id}] Processing UploadFile objects.")
        upload_files: list[UploadFile] = cast(list[UploadFile], files_input)
        validation_tasks = [_validate_single_uploaded_file(f_obj, request_id) for f_obj in upload_files]
        try:
            results = await asyncio.gather(*validation_tasks)
            for filename, content_bytes in results:
                processed_file_data.append((filename, content_bytes))
                total_size += len(content_bytes)
        except HTTPException as http_exc:  # Rilancia HTTPException da _validate_single_uploaded_file
            raise http_exc
        except Exception as e:
            logger.error(f"[{request_id}] Unexpected error during UploadFile validation batch: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Error validating one or more uploaded files.") from e
    else:
        logger.error(f"[{request_id}] Invalid input type for files_input: {type(files_input[0]) if files_input else 'empty list'}")
        raise HTTPException(status_code=400, detail="Invalid file input. Expected list of S3 keys or uploaded files.")

    # --- Total Size Check (dopo aver recuperato tutti i contenuti) ---
    if total_size > MAX_TOTAL_SIZE:
        logger.warning(f"[{request_id}] Total data size exceeds limit: {total_size} bytes > {MAX_TOTAL_SIZE} bytes")
        raise HTTPException(status_code=413, detail=f"La dimensione totale dei file ({total_size // (1024 * 1024)}MB) supera il limite di {MAX_TOTAL_SIZE // (1024 * 1024)}MB.")

    logger.info(f"[{request_id}] All data retrieved and validated. Total size: {total_size} bytes. Processing {len(processed_file_data)} items.")

    # --- Concurrent Extraction (come prima, ma su processed_file_data) ---
    if not processed_file_data:
        logger.info(f"[{request_id}] No files to extract text from.")
        return ""

    extraction_tasks = [_extract_single_file(fname, request_id, f_content_bytes) for fname, f_content_bytes in processed_file_data]
    # Using return_exceptions=True means the result can contain exceptions
    # mypy: asyncio.gather with return_exceptions=True returns a list where each item can be either
    # the expected result type (str | None) or an exception
    extraction_results = await asyncio.gather(*extraction_tasks, return_exceptions=True)

    for result_item in extraction_results:
        if isinstance(result_item, Exception):
            logger.error(f"[{request_id}] Error during concurrent text extraction: {result_item}", exc_info=True)  # exc_info per dettagli
            # Scegli se propagare o loggare e continuare. Per ora propaghiamo.
            # Potrebbe essere un ExtractorError o PipelineError già sollevato da _extract_single_file
            if isinstance(result_item, ExtractorError | PipelineError):
                raise result_item  # Rilancia l'errore specifico
            raise PipelineError(f"Error extracting text from a file: {str(result_item)}") from result_item

        # A questo punto, result_item non è un'eccezione, quindi deve essere str | None
        # Use the cast function to tell mypy that this type is str | None
        text_content = cast(str | None, result_item)
        if text_content:
            extracted_texts.append(text_content)

    corpus = guard_corpus("\\n\\n".join(extracted_texts), request_id)
    logger.info(f"[{request_id}] Text extraction complete. Corpus length: {len(corpus)}.")
    return corpus
