import asyncio
import io
import logging
from typing import BinaryIO

import openpyxl  # For .xlsx files
import pdfplumber

# docx for Word documents
from docx import Document

from app.core.config import settings
from app.core.ocr import ocr

# Configure module logger
logger = logging.getLogger(__name__)


class ExtractorError(Exception):
    """Base exception for extraction-related errors"""


async def _pdf_to_text(f: BinaryIO) -> str:
    """Extract text from PDF file."""

    def _sync_pdf_extraction(file_bytes: bytes) -> str:
        buffer = io.BytesIO(file_bytes)
        with pdfplumber.open(buffer) as pdf:
            text = "\n".join(p.extract_text() or "" for p in pdf.pages)
            logger.debug("Extracted %d chars from PDF", len(text))
            return text

    try:
        f.seek(0)
        file_bytes = f.read()
        return await asyncio.to_thread(_sync_pdf_extraction, file_bytes)
    except Exception as e:
        logger.error("Failed to extract text from PDF: %s", str(e), exc_info=True)
        raise ExtractorError("Failed to extract text from PDF") from e


async def _docx_to_text(f: BinaryIO) -> str:
    """Extract text from DOCX file."""

    def _sync_docx_extraction(file_bytes: bytes) -> str:
        buffer = io.BytesIO(file_bytes)
        doc = Document(buffer)
        text = "\n".join(p.text for p in doc.paragraphs)
        logger.debug("Extracted %d chars from DOCX", len(text))
        return text

    try:
        f.seek(0)
        file_bytes = f.read()
        return await asyncio.to_thread(_sync_docx_extraction, file_bytes)
    except Exception as e:
        logger.error("Failed to extract text from DOCX: %s", str(e), exc_info=True)
        raise ExtractorError("Failed to extract text from DOCX") from e


async def _image_handler(fname: str, f: BinaryIO, request_id: str) -> str:
    """Return text"""
    logger.info("[%s] Processing image file: %s", request_id, fname)

    try:
        f.seek(0)
        # Always await the ocr function since we've confirmed it's asynchronous
        text = await ocr(f)
        logger.debug("[%s] OCR extracted %d chars", request_id, len(text.strip()))

        if len(text.strip()) > 0:
            logger.info("[%s] Using OCR text (length > 0)", request_id)
            return text  # good OCR
        else:
            logger.info("[%s] No OCR text found", request_id)
            return ""  # no OCR text

    except Exception as e:
        logger.exception("[%s] Failed to handle image file: %s", request_id, fname)
        raise ExtractorError(f"Failed to handle image file: {fname}") from e


async def _excel_to_text(f: BinaryIO, filename: str) -> str:
    """
    Asynchronously extracts text from an Excel file by running sync extraction in a thread.
    f: A binary file-like object.
    filename: The original name of the file, used to determine .xlsx vs .xls.
    """
    try:
        f.seek(0)
        file_bytes = f.read()  # Read the whole file into memory for the sync function
        return await asyncio.to_thread(_sync_excel_extraction, file_bytes, filename)
    except Exception as e:
        # Log error from this async wrapper if reading bytes fails or thread call fails
        logger.error("Async wrapper for Excel extraction failed for '%s': %s", filename, str(e), exc_info=True)
        raise ExtractorError(f"Error during async processing of Excel file: {filename}") from e


def _sync_excel_extraction(file_bytes: bytes, filename: str) -> str:
    """
    Extracts data from all sheets of an Excel file (.xlsx or .xls)
    and represents each as CSV-formatted text, delimited by markers.
    Uses openpyxl for .xlsx and xlrd3 (if installed) for .xls.
    """
    logger.debug("Attempting to extract text from Excel file (using openpyxl/xlrd): %s", filename)
    file_extension = filename.lower().split(".")[-1]
    excel_buffer = io.BytesIO(file_bytes)
    all_sheets_content: list[str] = []

    try:
        if file_extension == "xlsx":
            workbook = openpyxl.load_workbook(excel_buffer, read_only=True, data_only=True)
            for i, sheet_name in enumerate(workbook.sheetnames):
                sheet = workbook[sheet_name]
                sheet_lines: list[str] = [
                    f"--- START EXCEL SHEET (File: {filename}, Sheet Index: {i}, Sheet Name: {sheet_name}) ---"
                ]
                if sheet.max_row == 0 and sheet.max_column == 0:  # Check if sheet is truly empty
                    sheet_lines.append("(Sheet is empty)")
                else:
                    for row_tuple in sheet.iter_rows():
                        # Ensure all cell values are converted to string, handling None
                        row_values = [str(cell.value) if cell.value is not None else "" for cell in row_tuple]
                        sheet_lines.append(",".join(row_values))

                sheet_lines.append(f"--- END EXCEL SHEET (Sheet Name: {sheet_name}) ---")
                all_sheets_content.append("\n".join(sheet_lines))

        elif file_extension == "xls":
            try:
                # Try xlrd3 first, then fall back to xlrd if needed
                try:
                    from xlrd3 import XLRDError  # type: ignore
                    from xlrd3 import open_workbook  # type: ignore
                except ImportError:
                    try:
                        from xlrd import XLRDError  # type: ignore
                        from xlrd import open_workbook  # type: ignore
                    except ImportError:
                        logger.warning(
                            "Neither xlrd3 nor xlrd library is installed. Cannot process .xls files like '%s'. "
                            "Please install 'xlrd3' to enable .xls support.",
                            filename,
                        )
                        # Return a clear message instead of raising an error immediately
                        return (
                            f"--- ERROR: Processing .xls file '{filename}' requires 'xlrd3' library, which is not installed. ---"
                        )
            except Exception as e_import:
                logger.error("Error importing xlrd modules: %s", str(e_import))
                return f"--- ERROR: Processing .xls file '{filename}' encountered library import error: {e_import} ---"

            try:
                workbook = open_workbook(file_contents=file_bytes)  # xlrd uses file_contents
                for i in range(workbook.nsheets):
                    sheet = workbook.sheet_by_index(i)
                    sheet_name = sheet.name
                    xls_sheet_lines: list[str] = [
                        f"--- START EXCEL SHEET (File: {filename}, Sheet Index: {i}, Sheet Name: {sheet_name}) ---"
                    ]
                    if sheet.nrows == 0 and sheet.ncols == 0:
                        xls_sheet_lines.append("(Sheet is empty)")
                    else:
                        for row_idx in range(sheet.nrows):
                            row_values = []
                            for col_idx in range(sheet.ncols):
                                cell_value = sheet.cell_value(row_idx, col_idx)
                                row_values.append(str(cell_value) if cell_value is not None else "")
                            xls_sheet_lines.append(",".join(row_values))
                    xls_sheet_lines.append(f"--- END EXCEL SHEET (Sheet Name: {sheet_name}) ---")
                    all_sheets_content.append("\n".join(xls_sheet_lines))
            except XLRDError as e_xlrd:  # Catch specific xlrd errors
                logger.error("xlrd failed to parse .xls file '%s': %s", filename, str(e_xlrd))
                raise ExtractorError(f"Failed to parse .xls file '{filename}' with xlrd: {e_xlrd}") from e_xlrd

        else:
            logger.warning("Unsupported Excel extension for file: %s", filename)
            raise ExtractorError(f"Unsupported Excel file type for: {filename}")

        final_text = "\n\n".join(all_sheets_content)
        logger.debug("Extracted %d chars (as CSVs) from Excel file: '%s'", len(final_text), filename)
        return final_text

    except Exception as e:  # Catch any other unexpected errors during processing
        logger.error("Failed to extract text from Excel file '%s': %s", filename, str(e), exc_info=True)
        raise ExtractorError(f"Failed to extract text from Excel file: {filename}") from e


_HANDLERS = {
    "pdf": _pdf_to_text,
    "docx": _docx_to_text,
    "doc": _docx_to_text,
}


async def extract(fname: str, f: BinaryIO, request_id: str) -> str:
    """Extract text from a file based on its extension."""
    ext = fname.lower().split(".")[-1]
    logger.info("[%s] Extracting content from file: %s (type: %s)", request_id, fname, ext)

    try:
        if ext == "pdf":
            text = await _pdf_to_text(f)
            logger.info(
                "[%s] Successfully extracted text from %s: %d chars",
                request_id,
                ext.upper(),
                len(text),
            )
            return text

        if ext in {"docx", "doc"}:
            text = await _docx_to_text(f)
            logger.info(
                "[%s] Successfully extracted text from %s: %d chars",
                request_id,
                ext.upper(),
                len(text),
            )
            return text

        if ext in {"xlsx", "xls"}:
            text = await _excel_to_text(f, fname)
            logger.info(
                "[%s] Successfully extracted text from %s: %d chars",
                request_id,
                ext.upper(),
                len(text),
            )
            return text

        if ext in {"png", "jpg", "jpeg"}:
            # Manually handle image files rather than trying to await _image_handler which is already async
            text = await _image_handler(fname, f, request_id)
            logger.info("[%s] Successfully processed image file: %s", request_id, fname)
            return text

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
