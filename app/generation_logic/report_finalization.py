import json
import logging
from typing import Any, Dict

from fastapi.responses import StreamingResponse

from app.services.doc_builder import DocBuilderError, inject
from app.services.pipeline import PipelineError

__all__ = [
    "_generate_and_stream_docx",
    "DEFAULT_REPORT_FILENAME",
    "DOCX_MEDIA_TYPE",
]

logger = logging.getLogger(__name__)

# Constants used for the generated DOCX ------------------------------------------------
DEFAULT_REPORT_FILENAME = "report.docx"
DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


async def _generate_and_stream_docx(
    template_path: str,
    final_context: Dict[str, Any],
    request_id: str,
) -> StreamingResponse:
    """Inject the *final_context* JSON into the Word template and stream it back to
    the client as an attachment."""
    try:
        json_payload = json.dumps(final_context, ensure_ascii=False)
        docx_bytes = inject(str(template_path), json_payload)
        logger.info("[%s] Successfully generated DOCX report", request_id)
        return StreamingResponse(
            iter([docx_bytes]),
            media_type=DOCX_MEDIA_TYPE,
            headers={
                "Content-Disposition": f"attachment; filename={DEFAULT_REPORT_FILENAME}"
            },
        )
    except DocBuilderError as e:
        logger.error(
            "[%s] Document builder error: %s", request_id, str(e), exc_info=True
        )
        raise e
    except Exception as e:
        logger.error(
            "[%s] Failed to generate final document: %s",
            request_id,
            str(e),
            exc_info=True,
        )
        raise PipelineError(
            "An unexpected error occurred while generating the final DOCX document."
        ) from e
