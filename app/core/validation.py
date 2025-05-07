import logging
from pathlib import Path

import magic
from fastapi import HTTPException, UploadFile

logger = logging.getLogger(__name__)

# Allowed file extensions and size limits
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".png", ".jpg", ".jpeg"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB

# MIME type mapping for validation
MIME_MAPPING = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


async def validate_upload(file: UploadFile, request_id: str) -> None:
    """
    Validate uploaded file against size and type restrictions.

    Args:
        file: The uploaded file to validate
        request_id: Request ID for logging

    Raises:
        HTTPException: If validation fails
    """
    try:
        # Check file extension
        ext = Path(file.filename or "").suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            logger.warning(
                "[%s] Rejected file with invalid extension: %s", request_id, ext
            )
            raise HTTPException(
                status_code=400,
                detail=(
                    "Tipo file non supportato. Estensioni permesse: "
                    f"{', '.join(ALLOWED_EXTENSIONS)}"
                ),
            )

        # Read file contents
        contents = await file.read()

        # Check file size
        size = len(contents)
        if size > MAX_FILE_SIZE:
            logger.warning(
                "[%s] Rejected file exceeding size limit: %d bytes", request_id, size
            )
            raise HTTPException(
                status_code=400,
                detail=f"File troppo grande. Limite: {MAX_FILE_SIZE // (1024*1024)}MB",
            )

        # Check MIME type
        mime = magic.from_buffer(contents, mime=True)
        expected_mime = MIME_MAPPING.get(ext)

        if not expected_mime or not mime.startswith(expected_mime.split("/")[1]):
            logger.warning(
                "[%s] Rejected file with mismatched content type. "
                "Expected: %s, Got: %s",
                request_id,
                expected_mime,
                mime,
            )
            raise HTTPException(
                status_code=400,
                detail="Il contenuto del file non corrisponde all'estensione",
            )

        # Reset file pointer for downstream processing
        file.file.seek(0)
        logger.debug(
            "[%s] File validation successful: %s (%d bytes)",
            request_id,
            file.filename,
            size,
        )

    except HTTPException:
        raise
    except Exception:
        logger.exception("[%s] Unexpected error during file validation", request_id)
        raise HTTPException(
            status_code=500, detail="Errore durante la validazione del file"
        )
