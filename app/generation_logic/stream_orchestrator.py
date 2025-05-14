import json
import logging
from typing import Any
from uuid import uuid4

from fastapi import UploadFile

from app.core.config import settings
from app.core.exceptions import ConfigurationError
from app.core.exceptions import PipelineError
from app.generation_logic.context_preparation import _extract_base_context
from app.generation_logic.context_preparation import _load_template_excerpt
from app.generation_logic.file_processing import _validate_and_extract_files
from app.services.clarification_service import ClarificationService
from app.services.extractor import ExtractorError
from app.services.llm import JSONParsingError
from app.services.llm import LLMError
from app.services.pipeline import PipelineService
from app.services.style_loader import load_style_samples

__all__ = [
    "_create_stream_event",
    "_stream_report_generation_logic",
]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# NDJSON event helper
# ---------------------------------------------------------------------------


def _create_stream_event(
    event_type: str,
    message: str | None = None,
    payload: dict[str, Any] | None = None,
    missing_fields: list[dict[str, str]] | None = None,
    request_artifacts: dict[str, Any] | None = None,
) -> str:
    """Serialize a Server-Sent Event (SSE)-style dict to an NDJSON line."""
    event: dict[str, Any] = {"type": event_type}
    if message is not None:
        event["message"] = message
    if payload is not None:
        event["payload"] = payload
    if missing_fields is not None:
        event["missing_fields"] = missing_fields
    if request_artifacts is not None:
        event["request_artifacts"] = request_artifacts
    return json.dumps(event) + "\n"


# ---------------------------------------------------------------------------
# Main streaming generation orchestrator
# ---------------------------------------------------------------------------


async def _stream_report_generation_logic(
    files: list[UploadFile],
    notes: str,
):
    """Orchestrate the end-to-end report generation, yielding NDJSON events that
    clients can consume as a stream.
    """
    request_id = str(uuid4())
    logger.info(
        "[%s] Initiating streaming report generation: %d files",
        request_id,
        len(files),
    )

    original_notes = notes
    section_map_from_pipeline: dict[str, Any] | None = None

    try:
        template_path_str = str(settings.template_path)

        # ------------------------------------------------------------------
        # 0. Load styles early (for consistency)
        # ------------------------------------------------------------------
        reference_style_text = load_style_samples()
        yield _create_stream_event("status", message="Stylistic references loaded.")

        # ------------------------------------------------------------------
        # 1. Validate & extract content
        # ------------------------------------------------------------------
        yield _create_stream_event("status", message="Validating inputs and extracting content…")
        corpus = await _validate_and_extract_files(files, request_id)
        img_tokens: list[str] = []  # Vision model no longer used; keep for compatibility
        yield _create_stream_event(
            "status",
            message=f"Content extracted: {len(corpus)} chars.",
        )

        # ------------------------------------------------------------------
        # 2. Template excerpt
        # ------------------------------------------------------------------
        yield _create_stream_event("status", message="Loading template excerpt…")
        template_excerpt = await _load_template_excerpt(template_path_str, request_id)
        yield _create_stream_event("status", message="Template excerpt loaded.")

        # ------------------------------------------------------------------
        # 3. Base context via LLM
        # ------------------------------------------------------------------
        yield _create_stream_event("status", message="Extracting base document context (LLM)…")
        base_ctx = await _extract_base_context(
            template_excerpt,
            corpus,
            img_tokens,
            notes,
            request_id,
            reference_style_text,
        )
        yield _create_stream_event("status", message="Base document context extracted.")

        # ------------------------------------------------------------------
        # 4. Clarification step
        # ------------------------------------------------------------------
        clarification_service = ClarificationService()
        missing_info_list = clarification_service.identify_missing_fields(base_ctx, settings.CRITICAL_FIELDS_FOR_CLARIFICATION)

        if missing_info_list:
            logger.info(
                "[%s] Clarification needed for %d fields.",
                request_id,
                len(missing_info_list),
            )
            request_artifacts_data: dict[str, Any] = {
                "original_corpus": corpus,
                "image_tokens": img_tokens,
                "notes": original_notes,
                "template_excerpt": template_excerpt,
                "reference_style_text": reference_style_text,
                "initial_llm_base_fields": base_ctx,
            }
            yield _create_stream_event(
                "clarification_needed",
                missing_fields=missing_info_list,
                request_artifacts=request_artifacts_data,
            )
            return

        yield _create_stream_event(
            "status",
            message="No immediate clarifications needed. Starting main report generation pipeline…",
        )

        # ------------------------------------------------------------------
        # 5. Streaming pipeline
        # ------------------------------------------------------------------
        pipeline = PipelineService()
        async for pipeline_update_json_str in pipeline.run(
            request_id=request_id,
            template_excerpt=template_excerpt,
            corpus=corpus,
            imgs=img_tokens,
            notes=notes,
            reference_style_text=reference_style_text,
        ):
            try:
                update_data = json.loads(pipeline_update_json_str)
                if update_data.get("type") == "data" and "payload" in update_data:
                    section_map_from_pipeline = update_data.get("payload")
                    yield _create_stream_event(
                        "status",
                        message="Core content generation complete. Finalising report data…",
                    )
                elif update_data.get("type") == "error":
                    logger.error(
                        "[%s] Error from pipeline stream: %s",
                        request_id,
                        update_data.get("message"),
                    )
                    yield _create_stream_event(
                        "error",
                        message=update_data.get("message", "Unknown pipeline error"),
                    )
                    return
                else:
                    yield _create_stream_event(
                        update_data.get("type", "status"),
                        message=update_data.get("message", "Pipeline update"),
                    )
            except json.JSONDecodeError:
                logger.warning(
                    "[%s] Non-JSON message from pipeline: %s",
                    request_id,
                    pipeline_update_json_str,
                )
                yield _create_stream_event(
                    "status",
                    message="Processing report sections (received non-JSON update)…",
                )

        # ------------------------------------------------------------------
        # 6. Final merge
        # ------------------------------------------------------------------
        if section_map_from_pipeline is None:
            logger.error(
                "[%s] Pipeline completed without providing final section map.",
                request_id,
            )
            raise PipelineError("Pipeline did not return section map data.")

        final_ctx = {**base_ctx, **section_map_from_pipeline}
        yield _create_stream_event(
            "data",
            message="Report data processing complete. Document download will be initiated by client.",
            payload=final_ctx,
        )

        # Send a 'finished' event to properly close the stream
        # This helps the frontend know the stream has ended successfully
        yield _create_stream_event("finished", message="Stream completed successfully.")

    # ----------------------------------------------------------------------
    # Error handling
    # ----------------------------------------------------------------------
    except ConfigurationError as ce:  # Catch specific configuration errors
        logger.error(
            "[%s] ConfigurationError during stream: %s",
            request_id,
            str(ce),
            exc_info=False,
        )
        yield _create_stream_event("error", message=f"Configuration error: {str(ce)}")
    except ExtractorError as ee:  # Catch specific extractor errors
        logger.error("[%s] ExtractorError during stream: %s", request_id, str(ee), exc_info=False)
        yield _create_stream_event("error", message=f"File extraction error: {str(ee)}")
    except PipelineError as pe:
        logger.error(
            "[%s] PipelineError during stream orchestration: %s",
            request_id,
            str(pe),
            exc_info=False,  # Usually logged deeper if it's a re-raise
        )
        yield _create_stream_event("error", message=f"Pipeline processing error: {str(pe)}")
    except LLMError as le:  # Specific LLM errors
        logger.error("[%s] LLMError during stream: %s", request_id, str(le), exc_info=False)
        yield _create_stream_event("error", message=f"Language model processing error: {str(le)}")
    except JSONParsingError as jpe:  # Specific JSON parsing errors
        logger.error(
            "[%s] JSONParsingError during stream: %s",
            request_id,
            str(jpe),
            exc_info=False,
        )
        yield _create_stream_event("error", message=f"Data parsing error: {str(jpe)}")
    except Exception as e:  # General catch-all MUST be last
        logger.exception(
            "[%s] Unexpected error during report generation stream: %s",
            request_id,
            str(e),
            exc_info=True,  # Log full trace for truly unexpected errors
        )
        yield _create_stream_event("error", message=f"An unexpected server error occurred: {str(e)}")
    finally:
        logger.info("[%s] Stream generation logic finished.", request_id)
