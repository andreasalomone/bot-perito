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
    """Extract data from all sheets of an Excel file and represent each as CSV-formatted text."""
    logger.debug("Attempting to extract text from Excel file (as CSV): %s", filename)
    try:
        f.seek(0)
        file_bytes = f.read()
        excel_buffer = io.BytesIO(file_bytes)

        def _sync_excel_to_csv_text(buffer: io.BytesIO, original_filename: str) -> str:
            # Initialize an ExcelFile object to get sheet names
            # This is generally more robust for handling various Excel quirks.
            try:
                xls = pd.ExcelFile(buffer)
            except Exception as e_file:
                logger.error(
                    "Failed to open Excel file %s with pd.ExcelFile: %s. Attempting direct read.", original_filename, str(e_file)
                )
                # Fallback: try to read directly, assuming single sheet or pandas can handle it
                buffer.seek(0)  # Reset buffer for direct read
                try:
                    # sheet_name=None reads all sheets into a dict of DataFrames
                    df_dict = pd.read_excel(buffer, sheet_name=None, header=None)
                    if not isinstance(df_dict, dict):  # If it's a single DataFrame
                        df_dict = {"Sheet1": df_dict}  # Wrap it in a dict for consistent processing
                except Exception as e_direct_read:
                    logger.error("Direct read_excel also failed for %s: %s", original_filename, str(e_direct_read))
                    raise ExtractorError(f"Could not read Excel file content: {original_filename}") from e_direct_read

                # Create a mock ExcelFile-like structure for sheet names if direct read worked
                class MockExcelFile:
                    def __init__(self, sheets: dict[str, pd.DataFrame]) -> None:
                        self.sheet_names: list[str] = list(sheets.keys())
                        self._sheets: dict[str, pd.DataFrame] = sheets

                    def parse(self, sheet_name: str, _header: int | None = None) -> pd.DataFrame:
                        return self._sheets[sheet_name]

                xls = MockExcelFile(df_dict)

            all_sheets_csv_text = []

            for i, sheet_name in enumerate(xls.sheet_names):
                logger.debug("Processing sheet: '%s' (index %d) from file '%s'", sheet_name, i, original_filename)
                try:
                    # header=None ensures all rows are treated as data.
                    # If your Excel files consistently have headers in the first row,
                    # you might use header=0, but header=None is safer for unknown structures.
                    df = xls.parse(sheet_name, header=None)

                    if not df.empty:
                        # Convert DataFrame to CSV string
                        # index=False: Don't write DataFrame index.
                        # header=False: Don't write a header row from pandas' perspective.
                        # All rows from Excel will be data rows in the CSV string.
                        # na_rep='': Represent missing values (NaN) as empty strings in CSV.
                        csv_string = df.to_csv(index=False, header=False, na_rep="")

                        sheet_csv_representation = (
                            f"--- START EXCEL SHEET (File: {original_filename}, Sheet Index: {i}, Sheet Name: {sheet_name}) ---\n"
                            f"{csv_string.strip()}\n"  # .strip() to remove trailing newlines from to_csv if any
                            f"--- END EXCEL SHEET (Sheet Name: {sheet_name}) ---"
                        )
                        all_sheets_csv_text.append(sheet_csv_representation)
                    else:
                        logger.debug("Sheet: '%s' from file '%s' is empty.", sheet_name, original_filename)
                        # Still useful to indicate an empty sheet was processed
                        all_sheets_csv_text.append(
                            f"--- START EXCEL SHEET (File: {original_filename}, Sheet Index: {i}, Sheet Name: {sheet_name}) ---\n"
                            f"(Sheet is empty)\n"
                            f"--- END EXCEL SHEET (Sheet Name: {sheet_name}) ---"
                        )
                except Exception as e_sheet:
                    logger.error(
                        "Failed to parse sheet '%s' from Excel file '%s': %s", sheet_name, original_filename, str(e_sheet)
                    )
                    all_sheets_csv_text.append(
                        f"--- ERROR PROCESSING SHEET (File: {original_filename}, Sheet Name: {sheet_name}: {str(e_sheet)}) ---"
                    )

            final_text = "\n\n".join(all_sheets_csv_text)  # Separate CSV blocks for different sheets
            logger.debug("Extracted %d chars (as CSVs) from Excel file: '%s'", len(final_text), original_filename)
            return final_text

        return await asyncio.to_thread(_sync_excel_to_csv_text, excel_buffer, filename)
    except Exception as e:  # Catch any exception during file reading or initial buffer creation
        logger.error("Failed to extract CSV text from Excel file '%s': %s", filename, str(e), exc_info=True)
        raise ExtractorError(f"Failed to extract CSV text from Excel file: {filename}") from e


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
