"""Handles the final generation and streaming of the DOCX report document."""

import logging

from fastapi.responses import StreamingResponse

from app.core.exceptions import PipelineError
from app.models.report_models import ReportContext  # Import ReportContext
from app.services.doc_builder import DocBuilderError
from app.services.doc_builder import inject

__all__ = [
    "_generate_and_stream_docx",
    "DEFAULT_REPORT_FILENAME",
    "DOCX_MEDIA_TYPE",
]

logger = logging.getLogger(__name__)

# Constants used for the generated DOCX ------------------------------------------------
DEFAULT_REPORT_FILENAME = "report.docx"
DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


async def _generate_and_stream_docx(
    template_path: str,
    final_context: ReportContext,  # Changed type hint to ReportContext
    request_id: str,
) -> StreamingResponse:
    """Inject the *final_context* ReportContext object into the Word template and stream it back to
    the client as an attachment.
    """
    try:
        # Pass the final_context ReportContext object directly to inject
        docx_bytes = await inject(str(template_path), final_context)
        logger.info("[%s] Successfully generated DOCX report", request_id)
        return StreamingResponse(
            iter([docx_bytes]),
            media_type=DOCX_MEDIA_TYPE,
            headers={"Content-Disposition": f"attachment; filename={DEFAULT_REPORT_FILENAME}"},
        )
    except DocBuilderError as e:
        logger.error("[%s] Document builder error: %s", request_id, str(e), exc_info=True)
        raise e
    except Exception as e:
        logger.error(
            "[%s] Failed to generate final document: %s",
            request_id,
            str(e),
            exc_info=True,
        )
        raise PipelineError("An unexpected error occurred while generating the final DOCX document.") from e
