import logging
from functools import wraps
from uuid import uuid4

from fastapi import APIRouter
from fastapi import File
from fastapi import Form
from fastapi import HTTPException
from fastapi import UploadFile
from fastapi.responses import StreamingResponse

from app.core.config import settings
from app.core.exceptions import PipelineError
from app.core.security import Depends
from app.core.security import verify_api_key
from app.generation_logic.clarification_flow import build_report_with_clarifications
from app.generation_logic.report_finalization import _generate_and_stream_docx

# Generation-logic helpers -------------------------------------------------
from app.generation_logic.stream_orchestrator import _stream_report_generation_logic
from app.models.report_models import ClarificationPayload
from app.models.report_models import ReportContext

# Error classes re-used in endpoint-level exception handling --------------
from app.services.doc_builder import DocBuilderError

# Configure module logger
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


# --- Error Handling Decorator for DOCX Generation ---
def handle_docx_generation_errors(func):
    """Decorator to handle common errors during DOCX generation endpoints."""

    @wraps(func)
    async def wrapper(*args, **kwargs):
        # Extract request_id, assuming it's generated within the decorated function
        # or passed explicitly. If not standard, this might need adjustment.
        # For simplicity, we'll generate one if not obvious from args/kwargs.
        # A better approach might be to pass it explicitly or extract from a request object if available.
        request_id = str(uuid4())
        kwargs["request_id"] = request_id  # Inject into kwargs for the decorated function

        try:
            return await func(*args, **kwargs)
        except DocBuilderError as e:
            logger.error(
                "[%s] DocBuilderError during DOCX generation: %s",
                request_id,
                str(e),
                exc_info=True,
            )
            raise HTTPException(
                status_code=500,
                detail=f"DOCX generation error: {str(e)}",
            ) from e
        except PipelineError as e:
            # Refine status code based on error content
            status_code = 500
            error_msg = str(e)
            if "Prompt too large" in error_msg or "size exceeds limit" in error_msg:
                status_code = 413  # Payload Too Large
            elif "Malformed data" in error_msg or "validation failed" in error_msg:
                status_code = 400  # Bad Request

            logger.error(
                "[%s] PipelineError during DOCX generation (status %d): %s",
                request_id,
                status_code,
                error_msg,
                exc_info=False,  # Details should be logged where the error originated
            )
            raise HTTPException(status_code=status_code, detail=error_msg) from e
        except Exception as e:
            logger.error(
                "[%s] Unexpected error during DOCX generation: %s",
                request_id,
                str(e),
                exc_info=True,
            )
            raise HTTPException(
                status_code=500,
                detail=(
                    f"An unexpected server error occurred during report generation (trace: {request_id})."  # Provide trace ID
                ),
            ) from e

    return wrapper


# NOTE: All heavy-lifting helpers were migrated into the `app.generation_logic`
# sub-package.  This file now focuses solely on HTTP endpoint definitions and
# top-level orchestration calls.


@router.post("/generate", dependencies=[Depends(verify_api_key)])
async def generate(
    files: list[UploadFile] = File(  # noqa: B008
        ..., description="List of source documents (PDF, DOCX, JPG, PNG)."
    ),
    notes: str = Form("", description="Optional free-text notes from the user."),
):
    """Initiates the report generation process.

    Accepts uploaded files and optional notes, then streams back NDJSON events
    representing the generation progress. The stream includes status updates,
    potential requests for clarification, or the final report context data.

    Potential Stream Events:
    - `status`: Progress messages.
    - `clarification_needed`: Request for user input on missing fields.
    - `data`: Final report context (requires a subsequent call to /finalize-report).
    - `error`: Indicates a failure during processing.
    - `finished`: Indicates the stream has successfully completed (when no clarification is needed).

    Requires a valid API key via the 'X-API-Key' header.
    """
    return StreamingResponse(
        _stream_report_generation_logic(files, notes),
        media_type="application/x-ndjson",
    )


@router.post("/generate-with-clarifications", dependencies=[Depends(verify_api_key)])
@handle_docx_generation_errors
async def generate_with_clarifications(
    payload: ClarificationPayload,
    request_id: str,  # Injected by decorator
):
    """Receives user clarifications, runs the full report generation pipeline,
    and returns the final DOCX document directly.

    This endpoint is used after the `/generate` stream yields a
    `clarification_needed` event.

    Args:
        payload (ClarificationPayload): Contains user answers (`clarifications`)
                                        and original request artifacts.
        request_id (str): Automatically injected request ID for logging.

    Returns:
        StreamingResponse: The generated DOCX report file as an attachment.

    Raises:
        HTTPException:
            - 400: Malformed input data or validation failure.
            - 403: Invalid API Key.
            - 413: Input too large (e.g., text content exceeds limits).
            - 500: Internal server error during pipeline execution or DOCX generation.
    """
    logger.info("[%s] Processing clarifications and generating DOCX", request_id)

    # build_report_with_clarifications returns a ReportContext instance directly.
    # The previous comment and dict conversion were outdated.
    final_ctx_model: ReportContext = await build_report_with_clarifications(payload, request_id=request_id)

    # Generate DOCX directly from the final context model
    template_path_str = str(settings.template_path)
    docx_response = await _generate_and_stream_docx(
        template_path=template_path_str,
        final_context=final_ctx_model,  # Pass the ReportContext model instance
        request_id=request_id,
    )
    logger.info(
        "[%s] DOCX generation successful after clarification. Returning document.",
        request_id,
    )
    return docx_response


@router.post("/finalize-report", dependencies=[Depends(verify_api_key)])
@handle_docx_generation_errors
async def finalize_report(
    final_ctx_payload: ReportContext,  # Now expects ReportContext directly
    request_id: str,  # Injected by decorator
):
    """Generates the final DOCX report from the provided context data.

    This endpoint is used after the `/generate` stream successfully yields
    a `data` event containing the complete report context.

    Args:
        final_ctx_payload (ReportContext): The final report context data.
        request_id (str): Automatically injected request ID for logging.

    Returns:
        StreamingResponse: The generated DOCX report file as an attachment.

    Raises:
        HTTPException:
            - 400: Malformed input data.
            - 403: Invalid API Key.
            - 500: Internal server error during DOCX generation.
    """
    logger.info("[%s] Initiating report finalization and DOCX generation.", request_id)

    template_path_str = str(settings.template_path)
    # No longer need to dump to dict, pass the ReportContext model directly
    # final_context_dict = final_ctx_payload.model_dump(exclude_none=True)

    logger.info("[%s] Generating DOCX from final context...", request_id)
    docx_response = await _generate_and_stream_docx(
        template_path=template_path_str,
        final_context=final_ctx_payload,  # Pass the ReportContext object directly
        request_id=request_id,
    )
    logger.info(
        "[%s] DOCX generation successful for finalization. Returning stream.",
        request_id,
    )
    return docx_response
