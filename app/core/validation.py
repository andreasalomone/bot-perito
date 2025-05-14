"""Defines constants for file upload validation."""

import logging

# Path, magic, and HTTPException are no longer imported here as they are unused
# or imported directly by consumer modules.

logger = logging.getLogger(__name__)

# Allowed file extensions and size limits
ALLOWED_EXTENSIONS: set[str] = {".pdf", ".docx", ".png", ".jpg", ".jpeg"}
MAX_FILE_SIZE: int = 25 * 1024 * 1024  # 25 MB per file

# Maximum number of files allowed in a single request
MAX_FILES: int = 20  # Prevents users from flooding the API with hundreds of tiny files

MAX_TOTAL_SIZE: int = 100 * 1024 * 1024  # 100 MB total upload limit

# MIME type mapping for validation
MIME_MAPPING: dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


# The validate_upload function's logic is now integrated
# into app.generation_logic.file_processing._validate_and_extract_files
