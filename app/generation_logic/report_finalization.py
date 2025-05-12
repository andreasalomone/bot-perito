import json
import logging
from typing import Any, Dict

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from app.services.doc_builder import DocBuilderError, inject
from app.services.pipeline import PipelineError, PipelineService

__all__ = [
    "_run_processing_pipeline",
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


async def _run_processing_pipeline(
    template_excerpt: str,
    corpus: str,
    imgs: list[str],
    notes: str,
    request_id: str,
) -> Dict[str, Any]:
    """Execute the main content-generation pipeline synchronously, returning the
    section map once complete.
    """
    try:
        pipeline = PipelineService()
        section_map: Dict[str, Any] | None = None

        async for update_json_str in pipeline.run(
            template_excerpt,
            corpus,
            imgs,
            notes,
            extra_styles="",
        ):
            try:
                update_data = json.loads(update_json_str)
                if update_data.get("type") == "data" and "payload" in update_data:
                    section_map = update_data["payload"]
                    break
                elif update_data.get("type") == "error":
                    error_message = update_data.get(
                        "message",
                        "Unknown pipeline error during non-streaming generation",
                    )
                    logger.error(
                        "[%s] Pipeline error during non-streaming generation: %s",
                        request_id,
                        error_message,
                    )
                    raise PipelineError(error_message)
            except json.JSONDecodeError:
                logger.warning(
                    "[%s] Non-JSON message from pipeline during non-streaming generation: %s",
                    request_id,
                    update_json_str,
                )
                raise PipelineError(
                    "Received malformed data from pipeline during non-streaming generation."
                )

        if section_map is None:
            logger.error(
                "[%s] Pipeline finished without returning section map.", request_id
            )
            raise PipelineError("Pipeline did not return the expected section map.")

        logger.info(
            "[%s] Pipeline processing completed successfully (non-streaming).",
            request_id,
        )
        return section_map
    except PipelineError as e:
        logger.error(
            "[%s] PipelineError in _run_processing_pipeline: %s",
            request_id,
            str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail=f"Pipeline processing failed: {str(e)}"
        )
    except Exception as e:
        logger.error(
            "[%s] Unexpected error in _run_processing_pipeline: %s",
            request_id,
            str(e),
            exc_info=True,
        )
        raise PipelineError(
            f"An unexpected error occurred in the report generation pipeline: {e}"
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
        raise HTTPException(status_code=500, detail=f"Document builder error: {str(e)}")
    except Exception as e:
        logger.error(
            "[%s] Failed to generate final document: %s",
            request_id,
            str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while generating the DOCX document.",
        )
