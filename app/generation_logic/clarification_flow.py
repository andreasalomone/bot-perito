import json
import logging
from typing import Any, Dict, Optional
from uuid import uuid4

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from app.core.config import settings
from app.generation_logic.context_preparation import _load_template_excerpt
from app.generation_logic.report_finalization import (
    _generate_and_stream_docx,
    _run_processing_pipeline,
)
from app.models.report_models import ClarificationPayload
from app.services.doc_builder import DocBuilderError
from app.services.llm import JSONParsingError, LLMError
from app.services.pipeline import PipelineError

__all__ = ["build_report_with_clarifications"]

logger = logging.getLogger(__name__)


async def build_report_with_clarifications(
    payload: ClarificationPayload,
    request_id: Optional[str] = None,
) -> StreamingResponse:
    """Generate the final DOCX report *after* the user provided clarifications.

    This function encapsulates the business logic previously embedded in the
    `/generate-with-clarifications` endpoint so the router can remain lean.
    """

    request_id = request_id or str(uuid4())
    logger.info("[%s] Starting build_report_with_clarifications()", request_id)

    try:
        # ---------------------------------------------------------------
        # 1. Merge clarifications into the LLM base context
        # ---------------------------------------------------------------
        user_clarifications = payload.clarifications
        artifacts = payload.request_artifacts

        base_ctx: Dict[str, Any] = artifacts.initial_llm_base_fields.model_dump(
            exclude_none=True
        )

        for key, value in user_clarifications.items():
            if value is not None and value.strip() != "":
                base_ctx[key] = value
            elif key in base_ctx and (value is None or value.strip() == ""):
                base_ctx[key] = ""

        # ---------------------------------------------------------------
        # 2. Prepare inputs for the heavy pipeline
        # ---------------------------------------------------------------
        template_path_str = str(settings.template_path)
        template_excerpt = await _load_template_excerpt(template_path_str, request_id)

        section_map = await _run_processing_pipeline(
            template_excerpt=template_excerpt,
            corpus=artifacts.original_corpus,
            imgs=artifacts.image_tokens,
            notes=artifacts.notes,
            request_id=request_id,
        )

        final_ctx = {**base_ctx, **section_map}
        logger.debug(
            "[%s] Final context to inject into DOCX: %s",
            request_id,
            json.dumps(final_ctx, ensure_ascii=False)[:500] + "…",
        )

        # ---------------------------------------------------------------
        # 3. Build & stream the DOCX
        # ---------------------------------------------------------------
        docx_response = await _generate_and_stream_docx(
            template_path=template_path_str,
            final_context=final_ctx,
            request_id=request_id,
        )
        logger.info("[%s] DOCX generation completed successfully", request_id)
        return docx_response

    except HTTPException:
        # Re-raise so FastAPI can handle status codes correctly
        raise
    except (
        PipelineError,
        DocBuilderError,
        LLMError,
        JSONParsingError,
    ) as domain_exc:
        logger.error(
            "[%s] Domain error while building report with clarifications: %s",
            request_id,
            str(domain_exc),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Report generation failed after clarifications: {str(domain_exc)}",
        )
    except Exception as e:
        logger.error(
            "[%s] Unexpected error while building report with clarifications: %s",
            request_id,
            str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=(
                "An unexpected server error occurred while generating the report "
                f"with clarifications (id: {request_id})."
            ),
        )
