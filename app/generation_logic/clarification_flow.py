import json
import logging
from typing import Any, Dict, Optional
from uuid import uuid4

from fastapi import HTTPException

from app.core.config import settings
from app.generation_logic.context_preparation import _load_template_excerpt
from app.models.report_models import ClarificationPayload
from app.services.doc_builder import DocBuilderError
from app.services.extractor import ExtractorError
from app.services.llm import JSONParsingError, LLMError
from app.services.pipeline import ConfigurationError, PipelineError, PipelineService

__all__ = ["build_report_with_clarifications"]

logger = logging.getLogger(__name__)


async def build_report_with_clarifications(
    payload: ClarificationPayload,
    request_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Process user clarifications and run the generation pipeline, returning
    the final merged context *before* DOCX generation.

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
        try:
            template_excerpt = await _load_template_excerpt(
                template_path_str, request_id
            )
        except HTTPException as e:
            logger.error(
                "[%s] Failed to load template excerpt during clarification flow: %s",
                request_id,
                e.detail,
            )
            raise

        # Run the pipeline service directly
        pipeline = PipelineService()
        section_map: Dict[str, Any] | None = None

        async for update_json_str in pipeline.run(
            request_id=request_id,
            template_excerpt=template_excerpt,
            corpus=artifacts.original_corpus,
            imgs=artifacts.image_tokens,
            notes=artifacts.notes,
            extra_styles="",
        ):
            try:
                update_data = json.loads(update_json_str)
                if update_data.get("type") == "data" and "payload" in update_data:
                    section_map = update_data["payload"]
                    logger.info(
                        "[%s] Pipeline completed successfully in clarification flow.",
                        request_id,
                    )
                    break
                elif update_data.get("type") == "error":
                    error_message = update_data.get(
                        "message", "Unknown pipeline error in clarification flow"
                    )
                    logger.error(
                        "[%s] Pipeline error in clarification flow: %s",
                        request_id,
                        error_message,
                    )
                    raise PipelineError(error_message)
            except json.JSONDecodeError:
                logger.warning(
                    "[%s] Non-JSON message from pipeline in clarification flow: %s",
                    request_id,
                    update_json_str,
                )
                raise PipelineError(
                    "Received malformed data from pipeline during clarification flow."
                )

        if section_map is None:
            logger.error(
                "[%s] Pipeline finished without returning section map in clarification flow.",
                request_id,
            )
            raise PipelineError(
                "Pipeline did not return the expected section map during clarification flow."
            )

        final_ctx = {**base_ctx, **section_map}
        logger.debug(
            "[%s] Final context created after clarification: %s",
            request_id,
            json.dumps(final_ctx, ensure_ascii=False)[:500] + "…",
        )

        return final_ctx

    except HTTPException:
        raise
    except (
        ConfigurationError,
        PipelineError,
        ExtractorError,
        DocBuilderError,
        LLMError,
        JSONParsingError,
    ) as domain_exc:
        status_code = 500
        if isinstance(domain_exc, (ConfigurationError, ExtractorError)):
            pass
        elif isinstance(domain_exc, PipelineError) and "Prompt too large" in str(
            domain_exc
        ):
            status_code = 413
        elif isinstance(domain_exc, PipelineError) and "Malformed data" in str(
            domain_exc
        ):
            status_code = 400

        logger.error(
            "[%s] Domain error while building report with clarifications: %s",
            request_id,
            str(domain_exc),
            exc_info=False,
        )
        raise HTTPException(
            status_code=status_code,
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
