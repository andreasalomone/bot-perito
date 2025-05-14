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


# --- Helper: Style Loading ---
async def _helper_load_styles() -> str:
    return await load_style_samples()


# --- Helper: File Validation & Extraction ---
async def _helper_validate_and_extract(files: list[UploadFile], request_id: str) -> str:
    return await _validate_and_extract_files(files, request_id)


# --- Helper: Template Excerpt Loading ---
async def _helper_load_template_excerpt(template_path_str: str, request_id: str) -> str:
    return await _load_template_excerpt(template_path_str, request_id)


# --- Helper: Base Context LLM ---
async def _helper_extract_base_context(
    template_excerpt: str, corpus: str, notes: str, request_id: str, reference_style_text: str
) -> dict:
    return await _extract_base_context(template_excerpt, corpus, notes, request_id, reference_style_text)


# --- Helper: Clarification Check ---
def _helper_clarification_check(
    base_ctx: dict,
    corpus: str,
    notes: str,
    original_notes: str,
    template_excerpt: str,
    reference_style_text: str,
    request_id: str,
):
    clarification_service = ClarificationService()
    missing_info_list = clarification_service.identify_missing_fields(base_ctx, settings.CRITICAL_FIELDS_FOR_CLARIFICATION)
    if missing_info_list:
        request_artifacts_data: dict[str, Any] = {
            "original_corpus": corpus,
            "notes": original_notes,
            "template_excerpt": template_excerpt,
            "reference_style_text": reference_style_text,
            "initial_llm_base_fields": base_ctx,
        }
        return missing_info_list, request_artifacts_data
    return None, None


# --- Helper: Main Pipeline Execution ---
async def _helper_run_pipeline(request_id: str, template_excerpt: str, corpus: str, notes: str, reference_style_text: str):
    pipeline = PipelineService()
    async for pipeline_update_json_str in pipeline.run(
        request_id=request_id,
        template_excerpt=template_excerpt,
        corpus=corpus,
        notes=notes,
        reference_style_text=reference_style_text,
    ):
        yield pipeline_update_json_str


# --- Helper: Final Context Merge ---
def _helper_merge_final_context(base_ctx: dict, section_map_from_pipeline: dict) -> dict:
    return {**base_ctx, **section_map_from_pipeline}


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
    _final_event_sent = False

    try:
        template_path_str = str(settings.template_path)

        # 0. Load styles early (for consistency)
        reference_style_text = await _helper_load_styles()
        yield _create_stream_event("status", message="Stylistic references loaded.")

        # 1. Validate & extract content
        yield _create_stream_event("status", message="Validating inputs and extracting content…")
        corpus = await _helper_validate_and_extract(files, request_id)
        yield _create_stream_event(
            "status",
            message=f"Content extracted: {len(corpus)} chars.",
        )

        # 2. Template excerpt
        yield _create_stream_event("status", message="Loading template excerpt…")
        template_excerpt = await _helper_load_template_excerpt(template_path_str, request_id)
        yield _create_stream_event("status", message="Template excerpt loaded.")

        # 3. Base context via LLM
        yield _create_stream_event("status", message="Extracting base document context (LLM)…")
        base_ctx = await _helper_extract_base_context(
            template_excerpt,
            corpus,
            notes,
            request_id,
            reference_style_text,
        )
        yield _create_stream_event("status", message="Base document context extracted.")

        # 4. Clarification step
        missing_info_list, request_artifacts_data = _helper_clarification_check(
            base_ctx, corpus, notes, original_notes, template_excerpt, reference_style_text, request_id
        )
        if missing_info_list:
            logger.info(
                "[%s] Clarification needed for %d fields.",
                request_id,
                len(missing_info_list),
            )
            yield _create_stream_event(
                "clarification_needed",
                missing_fields=missing_info_list,
                request_artifacts=request_artifacts_data,
            )
            _final_event_sent = True
            return

        yield _create_stream_event(
            "status",
            message="No immediate clarifications needed. Starting main report generation pipeline…",
        )

        # 5. Streaming pipeline
        section_map_from_pipeline = None
        async for pipeline_update_json_str in _helper_run_pipeline(
            request_id,
            template_excerpt,
            corpus,
            notes,
            reference_style_text,
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
                    _final_event_sent = True
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

        # 6. Final merge
        if section_map_from_pipeline is None:
            logger.error(
                "[%s] Pipeline completed without providing final section map.",
                request_id,
            )
            raise PipelineError("Pipeline did not return section map data.")

        final_ctx = _helper_merge_final_context(base_ctx, section_map_from_pipeline)
        yield _create_stream_event(
            "data",
            message="Report data processing complete. Document download will be initiated by client.",
            payload=final_ctx,
        )

        # Send a 'finished' event to properly close the stream
        yield _create_stream_event("finished", message="Stream completed successfully.")
        _final_event_sent = True

    except ConfigurationError as ce:
        logger.error(
            "[%s] ConfigurationError during stream: %s",
            request_id,
            str(ce),
            exc_info=False,
        )
        yield _create_stream_event("error", message=f"Configuration error: {str(ce)}")
        _final_event_sent = True
    except ExtractorError as ee:
        logger.error("[%s] ExtractorError during stream: %s", request_id, str(ee), exc_info=False)
        yield _create_stream_event("error", message=f"File extraction error: {str(ee)}")
        _final_event_sent = True
    except PipelineError as pe:
        logger.error(
            "[%s] PipelineError during stream orchestration: %s",
            request_id,
            str(pe),
            exc_info=False,
        )
        yield _create_stream_event("error", message=f"Pipeline processing error: {str(pe)}")
        _final_event_sent = True
    except LLMError as le:
        logger.error("[%s] LLMError during stream: %s", request_id, str(le), exc_info=False)
        yield _create_stream_event("error", message=f"Language model processing error: {str(le)}")
        _final_event_sent = True
    except JSONParsingError as jpe:
        logger.error(
            "[%s] JSONParsingError during stream: %s",
            request_id,
            str(jpe),
            exc_info=False,
        )
        yield _create_stream_event("error", message=f"Data parsing error: {str(jpe)}")
        _final_event_sent = True
    except Exception as e:
        logger.exception(
            "[%s] Unexpected error during report generation stream: %s",
            request_id,
            str(e),
            exc_info=True,
        )
        yield _create_stream_event("error", message=f"An unexpected server error occurred: {str(e)}")
        _final_event_sent = True
    finally:
        if not _final_event_sent:
            logger.warning(f"[{request_id}] Stream exiting without a proper final event. Yielding generic error.")
            yield _create_stream_event(
                event_type="error",
                message="The report generation process terminated unexpectedly on the server. Please try again.",
            )
        logger.info(f"[{request_id}] Stream generation logic finished.")
