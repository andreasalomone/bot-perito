import asyncio
import io
import logging
from typing import BinaryIO

import pandas as pd
import pdfplumber
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
    """Extract text from all cells in all sheets of an Excel file."""
    logger.debug("Attempting to extract text from Excel file: %s", filename)
    try:
        f.seek(0)
        file_bytes = f.read()

        # Use BytesIO to allow pandas to read from in-memory bytes
        excel_buffer = io.BytesIO(file_bytes)

        def _sync_excel_extraction(buffer: io.BytesIO) -> str:
            try:
                # Read all sheets into a dictionary of DataFrames
                # sheet_name=None reads all sheets
                xls = pd.ExcelFile(buffer)  # More robust to try ExcelFile first
                all_sheets_text = []
                for sheet_name in xls.sheet_names:
                    df = xls.parse(sheet_name, header=None)  # header=None to treat all rows as data
                    if not df.empty:
                        # Convert all cells to string and join them, then join rows
                        # NaNs (empty cells) will become 'nan' string, filter them or handle as needed
                        # We'll join with spaces between cells and newlines between rows.
                        sheet_text = "\n".join(df.apply(lambda row: " ".join(row.astype(str).replace("nan", "")), axis=1))
                        all_sheets_text.append(f"--- Sheet: {sheet_name} ---\n{sheet_text}")

                final_text = "\n\n".join(all_sheets_text)
                logger.debug("Extracted %d chars from Excel file: %s", len(final_text), filename)
                return final_text
            except Exception as e_parse:
                # Fallback if ExcelFile fails, or for simpler cases, direct read_excel
                # This might be less robust for multi-sheet or complex files.
                logger.warning("ExcelFile parsing failed for %s, attempting direct read_excel: %s", filename, e_parse)
                buffer.seek(0)  # Reset buffer pointer
                df = pd.read_excel(buffer, sheet_name=None, header=None)  # Try to read all sheets
                if isinstance(df, dict):  # Multi-sheet case
                    all_sheets_text = []
                    for sheet_name, sheet_df in df.items():
                        if not sheet_df.empty:
                            sheet_text = "\n".join(
                                sheet_df.apply(lambda row: " ".join(row.astype(str).replace("nan", "")), axis=1)
                            )
                            all_sheets_text.append(f"--- Sheet: {sheet_name} ---\n{sheet_text}")
                    final_text = "\n\n".join(all_sheets_text)
                elif not df.empty:  # Single sheet case
                    final_text = "\n".join(df.apply(lambda row: " ".join(row.astype(str).replace("nan", "")), axis=1))
                else:
                    final_text = ""
                logger.debug("Extracted %d chars via direct read_excel from Excel file: %s", len(final_text), filename)
                return final_text

        return await asyncio.to_thread(_sync_excel_extraction, excel_buffer)
    except Exception as e:
        logger.error("Failed to extract text from Excel file %s: %s", filename, str(e), exc_info=True)
        raise ExtractorError(f"Failed to extract text from Excel file: {filename}") from e


_HANDLERS = {
    "pdf": _pdf_to_text,
    "docx": _docx_to_text,
    "doc": _docx_to_text,
    "xlsx": lambda f: _excel_to_text(f, "excel_file.xlsx"),  # Default filename if not provided
    "xls": lambda f: _excel_to_text(f, "excel_file.xls"),  # Default filename if not provided
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
