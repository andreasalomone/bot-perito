import logging
from typing import Any, Dict, List
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from app.core.config import settings
from app.core.security import Depends, verify_api_key
from app.generation_logic.clarification_flow import build_report_with_clarifications
from app.generation_logic.report_finalization import _generate_and_stream_docx

# Generation-logic helpers -------------------------------------------------
from app.generation_logic.stream_orchestrator import _stream_report_generation_logic
from app.models.report_models import ClarificationPayload, ReportContext

# Error classes re-used in endpoint-level exception handling --------------
from app.services.doc_builder import DocBuilderError
from app.services.pipeline import PipelineError

# Configure module logger
logger = logging.getLogger(__name__)

router = APIRouter()

# NOTE: All heavy-lifting helpers were migrated into the `app.generation_logic`
# sub-package.  This file now focuses solely on HTTP endpoint definitions and
# top-level orchestration calls.


@router.post("/generate", dependencies=[Depends(verify_api_key)])
async def generate(
    files: List[UploadFile] = File(...),
    notes: str = Form(""),
):
    return StreamingResponse(
        _stream_report_generation_logic(files, notes),
        media_type="application/x-ndjson",
    )


@router.post("/generate-with-clarifications", dependencies=[Depends(verify_api_key)])
async def generate_with_clarifications(payload: ClarificationPayload) -> Dict[str, Any]:
    """Receives clarifications, runs the pipeline, and returns the final JSON context.
    The client must then call /finalize-report to get the DOCX.
    """
    return await build_report_with_clarifications(payload)


@router.post("/finalize-report", dependencies=[Depends(verify_api_key)])
async def finalize_report(
    final_ctx_payload: ReportContext,
):
    request_id = str(uuid4())
    logger.info("[%s] Initiating report finalization and DOCX generation.", request_id)

    try:
        template_path_str = str(settings.template_path)
        final_context_dict = final_ctx_payload.model_dump(exclude_none=True)

        logger.info("[%s] Generating DOCX from final context...", request_id)
        docx_response = await _generate_and_stream_docx(
            template_path=template_path_str,
            final_context=final_context_dict,
            request_id=request_id,
        )
        logger.info(
            "[%s] DOCX generation successful for finalization. Returning stream.",
            request_id,
        )
        return docx_response

    except DocBuilderError as e:
        logger.error(
            "[%s] DocBuilderError during report finalization: %s",
            request_id,
            str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Report finalization document builder error: {str(e)}",
        )
    except PipelineError as e:
        logger.error(
            "[%s] PipelineError during report finalization: %s",
            request_id,
            str(e),
            exc_info=False,
        )
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(
            "[%s] Unexpected error during report finalization: %s",
            request_id,
            str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"An unexpected server error occurred during report finalization (id: {request_id}).",
        )
