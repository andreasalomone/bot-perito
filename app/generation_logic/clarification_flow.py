import json
import logging
from typing import Any
from uuid import uuid4

from fastapi import HTTPException

from app.core.exceptions import ConfigurationError
from app.core.exceptions import PipelineError
from app.models.report_models import ClarificationPayload
from app.models.report_models import ReportContext
from app.services.doc_builder import DocBuilderError
from app.services.extractor import ExtractorError
from app.services.llm import JSONParsingError
from app.services.llm import LLMError
from app.services.pipeline import PipelineService

__all__ = ["build_report_with_clarifications"]

logger = logging.getLogger(__name__)


async def build_report_with_clarifications(
    payload: ClarificationPayload,
    request_id: str | None = None,
) -> ReportContext:
    """Process user clarifications and run the generation pipeline, returning
    the final merged context as a ReportContext object *before* DOCX generation.

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
        template_excerpt = artifacts.template_excerpt
        reference_style_text = artifacts.reference_style_text

        # Start with the base fields from the initial LLM call (already a ReportContext)
        # Use model_dump to get a dict for manipulation, then reload into a new model instance
        base_ctx_dict: dict[str, Any] = artifacts.initial_llm_base_fields.model_dump()

        for key, value in user_clarifications.items():
            if value is not None and value.strip() != "":
                base_ctx_dict[key] = value
            elif key in base_ctx_dict and (value is None or value.strip() == ""):
                # If user provided an empty clarification for an existing field, keep it empty
                # Note: Pydantic might treat empty strings differently from None depending on field type
                base_ctx_dict[key] = ""  # Or potentially None, depending on desired outcome

        # Reload into a ReportContext to ensure structure before pipeline, though pipeline consumes dict parts
        # This intermediate model isn't strictly necessary if pipeline output merges correctly,
        # but maintains consistency.
        # current_context_model_pre_pipeline = ReportContext(**base_ctx_dict)

        # ---------------------------------------------------------------
        # 2. Prepare inputs for the heavy pipeline
        # ---------------------------------------------------------------
        # template_path_str = str(settings.template_path) # No longer needed directly here
        # try: # No longer needed
        #     template_excerpt = await _load_template_excerpt( # No longer needed
        #         template_path_str, request_id # No longer needed
        #     ) # No longer needed
        # except HTTPException as e: # No longer needed
        #     logger.error( # No longer needed
        #         "[%s] Failed to load template excerpt during clarification flow: %s", # No longer needed
        #         request_id, # No longer needed
        #         e.detail, # No longer needed
        #     ) # No longer needed
        #     raise # No longer needed

        # Run the pipeline service directly
        pipeline = PipelineService()
        section_map: dict[str, Any] | None = None

        # Pipeline expects certain inputs (corpus, imgs, etc.) - get them from artifacts
        async for update_json_str in pipeline.run(
            request_id=request_id,
            template_excerpt=template_excerpt,
            corpus=artifacts.original_corpus,
            notes=artifacts.notes,
            reference_style_text=reference_style_text,
        ):
            try:
                update_data = json.loads(update_json_str)
                if update_data.get("type") == "data" and "payload" in update_data:
                    section_map = update_data["payload"]  # Pipeline returns section dict
                    logger.info(
                        "[%s] Pipeline completed successfully in clarification flow.",
                        request_id,
                    )
                    break
                elif update_data.get("type") == "error":
                    error_message = update_data.get("message", "Unknown pipeline error in clarification flow")
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
                raise PipelineError("Received malformed data from pipeline during clarification flow.") from None

        if section_map is None:
            logger.error(
                "[%s] Pipeline finished without returning section map in clarification flow.",
                request_id,
            )
            raise PipelineError("Pipeline did not return the expected section map during clarification flow.")

        # Merge the results: start with the updated base context dict, add pipeline sections
        final_ctx_dict = {**base_ctx_dict, **section_map}

        # Validate and return as ReportContext object
        try:
            final_report_context = ReportContext(**final_ctx_dict)
            logger.debug(
                "[%s] Final ReportContext created after clarification: %s",
                request_id,
                final_report_context.model_dump_json(indent=2, exclude_none=True)[:500] + "…",
            )
            return final_report_context
        except Exception as validation_error:  # Catch Pydantic validation errors
            logger.error(
                "[%s] Failed to validate final merged context into ReportContext: %s. Data: %s",
                request_id,
                str(validation_error),
                json.dumps(final_ctx_dict)[:500] + "...",  # Log snippet of problematic data
            )
            # Raise a more specific internal error or re-use HTTPException
            raise HTTPException(
                status_code=500,
                detail="Internal error: Failed to structure final report data after pipeline.",
            ) from validation_error

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
        if isinstance(domain_exc, ConfigurationError | ExtractorError):
            pass
        elif isinstance(domain_exc, PipelineError) and "Prompt too large" in str(domain_exc):
            status_code = 413
        elif isinstance(domain_exc, PipelineError) and "Malformed data" in str(domain_exc):
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
        ) from domain_exc
    except Exception as e:
        logger.error(
            "[%s] Unexpected error while building report with clarifications: %s",
            request_id,
            str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=(f"An unexpected server error occurred while generating the report with clarifications (id: {request_id})."),
        ) from e
