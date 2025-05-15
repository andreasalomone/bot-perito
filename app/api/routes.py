import logging
from collections.abc import Callable
from functools import wraps
from typing import Any
from uuid import uuid4

from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from pydantic import Field as PydanticField

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
from app.services.storage.s3_service import create_presigned_put

# Configure module logger
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


# --- Error Handling Decorator for DOCX Generation ---
def handle_docx_generation_errors(func: Callable) -> Callable:
    """Decorator to handle common errors during DOCX generation endpoints."""

    @wraps(func)
    async def wrapper(request: Request, *args: Any, **kwargs: Any) -> StreamingResponse:
        # Generate request_id and store in request.state
        request_id = str(uuid4())
        request.state.request_id = request_id

        try:
            return await func(request, *args, **kwargs)
        except DocBuilderError as e:
            logger.error(
                "[%s] DocBuilderError during DOCX generation: %s",
                request.state.request_id,
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
                request.state.request_id,
                status_code,
                error_msg,
                exc_info=False,  # Details should be logged where the error originated
            )
            raise HTTPException(status_code=status_code, detail=error_msg) from e
        except Exception as e:
            # Ensure request_id is available even if request.state access fails early
            final_request_id = getattr(request.state, "request_id", "unknown")
            logger.error(
                "[%s] Unexpected error during DOCX generation: %s",
                final_request_id,
                str(e),
                exc_info=True,
            )
            raise HTTPException(
                status_code=500,
                detail=(
                    f"An unexpected server error occurred during report generation (trace: {final_request_id})."  # Provide trace ID
                ),
            ) from e

    return wrapper


# NOTE: All heavy-lifting helpers were migrated into the `app.generation_logic`
# sub-package.  This file now focuses solely on HTTP endpoint definitions and
# top-level orchestration calls.


@router.post(
    "/presign",
    dependencies=[Depends(verify_api_key)],  # MANTIENI LA SICUREZZA!
    summary="Generate Presigned URL for S3 Upload",
    tags=["S3 Upload"],  # Opzionale: per organizzare la documentazione Swagger/OpenAPI
)
def presign_upload_file(filename: str, content_type: str) -> dict[str, str]:
    """
    Generates a presigned URL that the client can use to upload a file directly to S3.
    The client should make a PUT request to the returned URL with the file content
    and the correct Content-Type header.
    """
    request_id = str(uuid4())  # Per logging
    logger.info(f"[{request_id}] Presign request received for filename: {filename}, content_type: {content_type}")

    if not filename or not content_type:
        raise HTTPException(status_code=400, detail="Filename and content_type are required.")

    # Genera una chiave univoca per S3, anteponendo "uploads/" come una cartella
    # Esempio: uploads/qualcosa_di_unico_documento.pdf
    s3_key = f"uploads/{uuid4()}_{filename.replace(' ', '_')}"  # Sostituisci spazi per sicurezza

    presigned_url = create_presigned_put(key=s3_key, content_type=content_type)

    if not presigned_url:
        logger.error(f"[{request_id}] Failed to generate presigned URL for key: {s3_key}")
        raise HTTPException(status_code=500, detail="Could not generate S3 presigned URL. Please check server logs.")

    logger.info(f"[{request_id}] Presigned URL generated for key: {s3_key}")
    return {"key": s3_key, "url": presigned_url}


# Definisci un modello Pydantic per il nuovo payload JSON con S3 keys
class GeneratePayloadS3(BaseModel):
    s3_keys: list[str] = PydanticField(..., description="List of S3 keys for the files to process.")
    notes: str | None = PydanticField(default="", description="Optional free-text notes from the user.")


@router.post("/generate", dependencies=[Depends(verify_api_key)])
async def generate(
    payload: GeneratePayloadS3,  # Expect GeneratePayloadS3 directly from JSON body
) -> StreamingResponse:
    """
    Initiates the report generation process using S3 keys.
    Accepts a list of S3 keys and notes via a JSON payload.
    Streams back NDJSON events representing the generation progress.

    Potential Stream Events:
    - `status`: Progress messages.
    - `clarification_needed`: Request for user input on missing fields.
    - `data`: Final report context (requires a subsequent call to /finalize-report).
    - `error`: Indicates a failure during processing.
    - `finished`: Indicates the stream has successfully completed (when no clarification is needed).

    Requires a valid API key via the 'X-API-Key' header.
    """
    request_id = str(uuid4())  # Generate a unique ID for this request

    logger.info(f"[{request_id}] /generate called with S3 keys. Count: {len(payload.s3_keys)}")

    files_to_process = payload.s3_keys
    notes_to_use = payload.notes or ""

    # _stream_report_generation_logic is already designed to handle List[str] for s3_keys
    return StreamingResponse(
        _stream_report_generation_logic(files_to_process, notes_to_use, request_id_override=request_id),
        media_type="application/x-ndjson",
    )


@router.post("/generate-with-clarifications", dependencies=[Depends(verify_api_key)])
@handle_docx_generation_errors
async def generate_with_clarifications(
    request: Request,
    payload: ClarificationPayload,
) -> StreamingResponse:
    """Receives user clarifications, runs the full report generation pipeline,
    and returns the final DOCX document directly.

    This endpoint is used after the `/generate` stream yields a
    `clarification_needed` event.

    Args:
        request (Request): FastAPI request object containing state.
        payload (ClarificationPayload): Contains user answers (`clarifications`)
                                        and original request artifacts.

    Returns:
        StreamingResponse: The generated DOCX report file as an attachment.

    Raises:
        HTTPException:
            - 400: Malformed input data or validation failure.
            - 403: Invalid API Key.
            - 413: Input too large (e.g., text content exceeds limits).
            - 500: Internal server error during pipeline execution or DOCX generation.
    """
    request_id = request.state.request_id

    logger.info("[%s] Processing clarifications and generating DOCX", request_id)

    # build_report_with_clarifications returns a ReportContext instance directly.
    # The previous comment and dict conversion were outdated.
    final_ctx_model: ReportContext = await build_report_with_clarifications(payload, request_id=request_id)

    # Log the entire context model for debugging
    logger.info("[%s] FINAL CONTEXT BEING SENT TO DOC_BUILDER:\n%s", request_id, final_ctx_model.model_dump_json(indent=2, exclude_none=True))

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
    request: Request,
    final_ctx_payload: ReportContext,  # Now expects ReportContext directly
) -> StreamingResponse:
    """Generates the final DOCX report from the provided context data.

    This endpoint is used after the `/generate` stream successfully yields
    a `data` event containing the complete report context.

    Args:
        request (Request): FastAPI request object containing state.
        final_ctx_payload (ReportContext): The final report context data.

    Returns:
        StreamingResponse: The generated DOCX report file as an attachment.

    Raises:
        HTTPException:
            - 400: Malformed input data.
            - 403: Invalid API Key.
            - 500: Internal server error during DOCX generation.
    """
    request_id = request.state.request_id

    logger.info("[%s] Initiating report finalization and DOCX generation.", request_id)

    template_path_str = str(settings.template_path)
    # No longer need to dump to dict, pass the ReportContext model directly
    # final_context_dict = final_ctx_payload.model_dump(exclude_none=True)

    # Log the entire context model for debugging
    logger.info("[%s] FINAL CONTEXT BEING SENT TO DOC_BUILDER:\n%s", request_id, final_ctx_payload.model_dump_json(indent=2, exclude_none=True))

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
