import json
import logging
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import HTTPException, UploadFile

from app.core.config import settings
from app.generation_logic.context_preparation import (
    _extract_base_context,
    _load_template_excerpt,
    _retrieve_similar_cases,
)
from app.generation_logic.file_processing import _validate_and_extract_files
from app.services.clarification_service import ClarificationService
from app.services.doc_builder import (  # For completeness in error handling
    DocBuilderError,
)
from app.services.extractor import ExtractorError
from app.services.llm import JSONParsingError, LLMError
from app.services.pipeline import PipelineError, PipelineService
from app.services.rag import RAGError

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
    message: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
    missing_fields: Optional[List[Dict[str, str]]] = None,
    request_artifacts: Optional[Dict[str, Any]] = None,
) -> str:
    """Serialize a Server-Sent Event (SSE)-style dict to an NDJSON line."""
    event: Dict[str, Any] = {"type": event_type}
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
    files: List[UploadFile],
    damage_imgs: Optional[List[UploadFile]],
    notes: str,
    use_rag: bool,
):
    """Orchestrate the end-to-end report generation, yielding NDJSON events that
    clients can consume as a stream.
    """
    request_id = str(uuid4())
    logger.info(
        "[%s] Initiating streaming report generation: %d files, %d damage images, use_rag=%s",
        request_id,
        len(files),
        len(damage_imgs or []),
        use_rag,
    )

    original_notes = notes
    original_use_rag = use_rag
    section_map_from_pipeline: Optional[Dict[str, Any]] = None

    try:
        template_path_str = str(settings.template_path)

        # ------------------------------------------------------------------
        # 1. Validate & extract content
        # ------------------------------------------------------------------
        yield _create_stream_event(
            "status", message="Validating inputs and extracting content…"
        )
        corpus, img_tokens = await _validate_and_extract_files(
            files, damage_imgs, request_id
        )
        yield _create_stream_event(
            "status",
            message=f"Content extracted: {len(corpus)} chars, {len(img_tokens)} images.",
        )

        # ------------------------------------------------------------------
        # 2. Template excerpt
        # ------------------------------------------------------------------
        yield _create_stream_event("status", message="Loading template excerpt…")
        template_excerpt = await _load_template_excerpt(template_path_str, request_id)
        yield _create_stream_event("status", message="Template excerpt loaded.")

        # ------------------------------------------------------------------
        # 3. Retrieve similar cases (optional RAG)
        # ------------------------------------------------------------------
        yield _create_stream_event(
            "status", message="Retrieving similar cases (if enabled)…"
        )
        similar_cases = await _retrieve_similar_cases(corpus, use_rag, request_id)
        yield _create_stream_event(
            "status", message=f"{len(similar_cases)} similar cases retrieved."
        )

        # ------------------------------------------------------------------
        # 4. Base context via LLM
        # ------------------------------------------------------------------
        yield _create_stream_event(
            "status", message="Extracting base document context (LLM)…"
        )
        base_ctx = await _extract_base_context(
            template_excerpt, corpus, img_tokens, notes, similar_cases, request_id
        )
        yield _create_stream_event("status", message="Base document context extracted.")

        # ------------------------------------------------------------------
        # 5. Clarification step
        # ------------------------------------------------------------------
        clarification_service = ClarificationService()
        missing_info_list = clarification_service.identify_missing_fields(
            base_ctx, settings.CRITICAL_FIELDS_FOR_CLARIFICATION
        )

        if missing_info_list:
            logger.info(
                "[%s] Clarification needed for %d fields.",
                request_id,
                len(missing_info_list),
            )
            request_artifacts_data: Dict[str, Any] = {
                "original_corpus": corpus,
                "image_tokens": img_tokens,
                "notes": original_notes,
                "use_rag": original_use_rag,
                "similar_cases_retrieved": similar_cases,
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
        # 6. Streaming pipeline
        # ------------------------------------------------------------------
        pipeline = PipelineService()
        async for pipeline_update_json_str in pipeline.run(
            template_excerpt,
            corpus,
            img_tokens,
            notes,
            similar_cases,
            extra_styles="",
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
        # 7. Final merge
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

    # ----------------------------------------------------------------------
    # Error handling
    # ----------------------------------------------------------------------
    except HTTPException as he:
        logger.warning(
            "[%s] HTTPException during stream: %s - %s",
            request_id,
            he.status_code,
            he.detail,
        )
        yield _create_stream_event("error", message=str(he.detail))
    except PipelineError as pe:
        logger.error(
            "[%s] PipelineError during stream orchestration: %s",
            request_id,
            str(pe),
            exc_info=True,
        )
        yield _create_stream_event(
            "error", message=f"Pipeline processing error: {str(pe)}"
        )
    except (
        DocBuilderError,
        LLMError,
        JSONParsingError,
        RAGError,
        ExtractorError,
    ) as known_exc:
        logger.error(
            "[%s] Known error during stream: %s",
            request_id,
            str(known_exc),
            exc_info=True,
        )
        yield _create_stream_event("error", message=str(known_exc))
    except Exception as e:
        logger.exception(
            "[%s] Unexpected error during report generation stream: %s",
            request_id,
            str(e),
        )
        yield _create_stream_event(
            "error", message=f"An unexpected server error occurred: {str(e)}"
        )
    finally:
        logger.info("[%s] Stream generation logic finished.", request_id)
